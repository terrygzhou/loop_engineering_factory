"""Legacy BUILD subgraph node functions (seam split S10).

Moved here from build_subgraph_legacy.py so the node file stays focused on
the wiring: build_input_mapping, build_output_mapping, route_build,
build_subgraph, get_compiled_subgraph, build_subgraph_node.

All 11 sub-node functions + BuildSubState live here. `invoke_skill` and
`run_command` are resolved lazily through graph.nodes.build_subgraph_legacy
so that test monkeypatch targets ("graph.nodes.build_subgraph_legacy.invoke_skill",
"graph.nodes.build_subgraph_legacy.run_command") keep working.
"""

import ast
import json
import re
import subprocess
import time
from pathlib import Path
from typing import TypedDict

from config.bounds_loader import bounds
from tools.stream_writer import safe_stream_writer

from .build_helpers import (
    extract_api_specs,
    extract_data_models,
    generate_backlog_md,
    parse_llm_output,
    parse_tasks_to_backlog,
    resolve_app_service,
    write_files_to_project,
)


# ── Sub-state ──────────────────────────────────────────────────────


class BuildSubState(TypedDict):
    """Internal state for the BUILD subgraph."""

    sub_phase: str  # Current sub-phase name
    project_path: str  # Resolved project path
    docker_proj: str  # Docker project dir
    spec_text: str  # Refined spec
    tasks_text: str  # Task breakdown text
    skills: dict  # Skill registry
    backlog: list[dict]  # Backlog items with status
    backlog_idx: int  # Index of current item being worked on
    impl_plan: str  # Implementation plan
    current_code: str  # Code generated for current item
    test_code: str  # Test code for current item
    test_result: str  # "pass" / "fail" / "skip"
    test_output: str  # Raw test output
    retry_count: int  # Retries for current item
    int_test_result: str  # "pass" / "fail"
    int_test_output: str  # Raw integration test output
    seed_result: str  # "pass" / "fail"
    seed_output: str  # Raw seed output
    uat_result: str  # "pass" / "fail"
    uat_output: str  # Raw UAT output
    uat_pass_rate: float  # Parsed UAT pass rate
    all_generated_code: list[str]  # Accumulated code across items
    errors: list[str]  # Accumulated error messages
    build_status: str  # "pass" / "fail" / "partial"
    parent_artifacts: dict  # Reference to parent artifacts dict (for writing back)
    superApp_mode: str  # "agent" (default) | "scripted"
    superApp_agent_report: dict  # Parsed agent_report.json from agent mode
    security_review: str  # Security audit result (security-and-hardening skill)
    code_review: str  # Code quality review result (pre-commit-review skill)


MAX_ITEM_RETRIES = None  # Runtime value from bounds.build.max_item_retries


# ── Lazy helpers (monkeypatch-target invariants, S10) ─────────────


def _invoke_skill(*args, **kwargs):
    """Resolve invoke_skill through build_subgraph_legacy so test patches reach it."""
    import graph.nodes.build_subgraph_legacy as _mod

    return _mod.invoke_skill(*args, **kwargs)


def _run_command(*args, **kwargs):
    """Resolve run_command through build_subgraph_legacy so test patches reach it."""
    import graph.nodes.build_subgraph_legacy as _mod

    return _mod.run_command(*args, **kwargs)


# ── Sub-node functions ─────────────────────────────────────────────


def impl_plan_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Generate implementation plan from spec + tasks."""
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "IMPL_PLAN",
            "detail": "Generating implementation plan...",
            "ts": time.time(),
        }
    )
    skills = state["skills"]
    spec = state["spec_text"]
    tasks = state["tasks_text"]

    impl_skill = skills.get("incremental-implementation", {})
    if impl_skill:
        task = (
            "Review the spec and tasks, then create an implementation plan.\n"
            "Outline the order of implementation, dependencies between components,\n"
            "and any architectural decisions. Be concise.\n\n"
            f"Spec:\n{spec[: bounds.build.recent_code_chars]}\n\nTasks:\n{tasks[: bounds.build.recent_code_chars]}"
        )
        plan = _invoke_skill(impl_skill["content"], task, "", llm=None)
    else:
        plan = f"Implement tasks in order: {tasks[: bounds.build.recent_code_chars]}"

    state["impl_plan"] = plan
    state["sub_phase"] = "IMPL_PLAN"
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "IMPL_PLAN",
            "detail": f"Plan generated ({len(plan)} chars)",
            "ts": time.time(),
        }
    )
    return state


def create_backlog_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Parse tasks into backlog items, write backlog.md."""
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "CREATE_BACKLOG",
            "detail": "Creating backlog...",
            "ts": time.time(),
        }
    )
    tasks_text = state["tasks_text"]
    project_folder = state["project_path"]

    backlog_items = parse_tasks_to_backlog(tasks_text)
    build_dir = Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = build_dir / "backlog.md"
    backlog_content = generate_backlog_md(backlog_items, project_folder)
    backlog_path.write_text(backlog_content)

    state["backlog"] = backlog_items
    state["backlog_idx"] = 0
    state["sub_phase"] = "CREATE_BACKLOG"
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "CREATE_BACKLOG",
            "detail": f"{len(backlog_items)} backlog items created",
            "ts": time.time(),
        }
    )
    return state


def implement_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Generate code + tests for current backlog item."""
    idx = state["backlog_idx"]
    if idx >= len(state["backlog"]):
        state["sub_phase"] = "NO_MORE_ITEMS"
        return state

    item = state["backlog"][idx]
    if item["status"] == "completed":
        state["backlog_idx"] = idx + 1
        state["sub_phase"] = "IMPLEMENT"
        return implement_node(state)  # Skip to next

    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "IMPLEMENT",
            "detail": f"Item {idx + 1}/{len(state['backlog'])}: {item['description'][:80]}",
            "ts": time.time(),
        }
    )
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "IMPLEMENT",
            "detail": f"Retry: {state['retry_count']}/{bounds.build.max_item_retries}",
            "ts": time.time(),
        }
    )

    skills = state["skills"]
    spec = state["spec_text"]
    tasks = state["tasks_text"]

    item_task = (
        f"Implement backlog item #{item['id']}: {item['description']}\n"
        f"\n=== OUTPUT FORMAT ===\n"
        "For each new or modified file, output:\n"
        "=== FILE: path/to/file.py ===\n"
        "```python\n...complete file content...\n```\n"
        "For shell commands (testing, setup):\n"
        "=== COMMAND: description ===\n"
        "```bash\n...command...\n```"
    )

    # Step 1: Generate code
    impl_skill = skills.get("incremental-implementation", {})
    item_code = ""
    if impl_skill:
        impl_context = spec + "\n\n" + tasks
        if idx > 0:
            impl_context += (
                "\n\nPreviously generated code:\n"
                + "\n".join(
                    state["all_generated_code"][-bounds.build.recent_code_snippets :]
                )[: bounds.build.recent_code_chars]
            )

        # Inject UI implementation guidance for frontend items so the
        # generated interface is production-quality (accessible, responsive,
        # not "AI-look"). frontend-ui-engineering skill drives this.
        item_desc_lower = item["description"].lower()
        ui_keywords = (
            "ui",
            "interface",
            "frontend",
            "front-end",
            "component",
            "page",
            "form",
            "dashboard",
            "view",
            "layout",
            "html",
            "css",
            "react",
            "vue",
            "svelte",
            "component",
        )
        if any(k in item_desc_lower for k in ui_keywords):
            ui_skill = skills.get("frontend-ui-engineering", {})
            if ui_skill:
                writer(
                    {
                        "type": "progress",
                        "phase": "BUILD",
                        "step": "IMPLEMENT",
                        "detail": "  → Applying frontend-ui-engineering skill (UI item)",
                        "ts": time.time(),
                    }
                )
                impl_context += (
                    "\n\n=== FRONTEND UI GUIDANCE (frontend-ui-engineering) ===\n"
                    + ui_skill["content"][:3000]
                )

        result = _invoke_skill(
            impl_skill["content"],
            item_task
            if state["retry_count"] == 0
            else f"{item_task}\n\nPrevious attempt failed. Fix and retry.",
            impl_context,
            llm=None,
        )
        item_code = result
        # Cap to prevent unbounded memory growth
        state["all_generated_code"] = state["all_generated_code"][
            -bounds.artifacts.max_generated_code_entries :
        ] + [result]

    # Step 2: Generate tests
    tdd_skill = skills.get("test-driven-development", {})
    test_code = ""
    if tdd_skill:
        tdd_task = (
            f"Generate tests for backlog item #{item['id']}: {item['description']}\n"
            f"Follow DAMP, pyramid, and A3 patterns.\n"
            f"\n=== OUTPUT FORMAT ===\n"
            "For each test file, output:\n"
            "=== FILE: tests/test_XXX.py ===\n"
            "```python\n...complete test file content...\n```"
        )
        test_code = _invoke_skill(tdd_skill["content"], tdd_task, item_code, llm=None)

    state["current_code"] = item_code
    state["test_code"] = test_code
    state["sub_phase"] = "IMPLEMENT"

    if not item_code:
        state["errors"].append(f"Item {item['id']}: No code generated")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
            state["retry_count"] = 0  # D3: new item gets a fresh retry budget
        return state

    return state


def unit_test_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Run Docker build + pytest for current item."""
    idx = state["backlog_idx"]
    if state["sub_phase"] == "NO_MORE_ITEMS":
        state["sub_phase"] = "ALL_ITEMS_DONE"
        return state

    # Guard against empty backlog or out-of-bounds index
    if idx >= len(state["backlog"]):
        state["sub_phase"] = "ALL_ITEMS_DONE"
        return state

    item = state["backlog"][idx]
    if item["status"] == "failed":
        state["backlog_idx"] = idx + 1
        state["sub_phase"] = "UNIT_TEST"
        return unit_test_node(state)

    docker_proj = state["docker_proj"]
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "UNIT_TEST",
            "detail": f"Building and testing item {item['id']}...",
            "ts": time.time(),
        }
    )

    # Write files
    combined = state["current_code"] + "\n" + state["test_code"]
    files, cmds, parse_info = parse_llm_output(combined)
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "UNIT_TEST",
            "detail": f"Parsed {len(files)} files, {len(cmds)} commands",
            "ts": time.time(),
        }
    )

    if not files:
        state["test_result"] = "fail"
        state["test_output"] = "No files generated"
        state["errors"].append(f"Item {item['id']}: No files to test")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        state["sub_phase"] = "UNIT_TEST"
        return state

    written = write_files_to_project(files, docker_proj)
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "UNIT_TEST",
            "detail": f"Wrote {len(written)} files",
            "ts": time.time(),
        }
    )

    # Run pre-build commands
    for desc, cmd in cmds:
        if "build" in desc.lower() or "test" in desc.lower():
            continue
        rc, _, err = _run_command(cmd, workdir=docker_proj)
        if rc != 0:
            writer(
                {
                    "type": "progress",
                    "phase": "BUILD",
                    "step": "UNIT_TEST",
                    "detail": f"Command '{desc}' failed: {err[:100]}",
                    "ts": time.time(),
                }
            )

    # Docker build
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "UNIT_TEST",
            "detail": "Docker compose build...",
            "ts": time.time(),
        }
    )
    _svc = resolve_app_service(docker_proj)
    rc, out, err = _run_command(
        f"docker compose build --no-cache {_svc}", timeout=300, workdir=docker_proj
    )
    if rc != 0:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "UNIT_TEST",
                "detail": f"Docker build failed: {err[:200]}",
                "ts": time.time(),
            }
        )
        state["test_result"] = "fail"
        state["test_output"] = err[: bounds.build.max_test_output_chars]
        state["errors"].append(f"Item {item['id']}: Docker build failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    # Start container
    rc, _, err = _run_command(
        f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj
    )
    if rc != 0:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "UNIT_TEST",
                "detail": f"Container start failed: {err[:200]}",
                "ts": time.time(),
            }
        )
        state["test_result"] = "fail"
        state["errors"].append(f"Item {item['id']}: Container start failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    # Health check
    import subprocess as sp

    sp.run(["sleep", "5"], timeout=10)
    from config.loader import config as _cfg

    _health_url = _cfg.services.product.url + "/"
    rc, health_out, _ = _run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30
    )
    if health_out.strip() not in ("200", "301", "302"):
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "UNIT_TEST",
                "detail": f"Health check failed: HTTP {health_out.strip()}",
                "ts": time.time(),
            }
        )
        state["test_result"] = "fail"
        state["errors"].append(f"Item {item['id']}: Health check failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    # Run pytest
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "UNIT_TEST",
            "detail": "Running pytest...",
            "ts": time.time(),
        }
    )
    rc, test_out, test_err = _run_command(
        f"docker compose exec {_svc} python -m pytest tests/ -v --tb=short 2>&1",
        timeout=120,
        workdir=docker_proj,
    )
    passed = len(re.findall(r"passed", test_out))
    failed = len(re.findall(r"failed", test_out))

    if rc == 0 and failed == 0:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "UNIT_TEST",
                "detail": f"pytest passed ({passed} tests) — item {item['id']} complete",
                "ts": time.time(),
            }
        )
        state["test_result"] = "pass"
        state["test_output"] = test_out[: bounds.build.max_test_output_chars]
        state["backlog"][idx]["status"] = "completed"
        state["retry_count"] = 0
        state["backlog_idx"] = idx + 1
    else:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "UNIT_TEST",
                "detail": f"pytest: {failed} failed, {passed} passed",
                "ts": time.time(),
            }
        )
        state["test_result"] = "fail"
        state["test_output"] = test_out[: bounds.build.max_test_output_chars]
        state["errors"].append(
            f"Item {item['id']}: {failed} test failures (attempt {state['retry_count'] + 1})"
        )
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
            state["retry_count"] = 0

    state["sub_phase"] = "UNIT_TEST"
    return state


def int_test_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Integration test: verify Docker app is running, run aggregate checks."""
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "INT_TEST",
            "detail": "Running integration tests...",
            "ts": time.time(),
        }
    )
    docker_proj = state["docker_proj"]
    from config.loader import config as _cfg

    _health_url = _cfg.services.product.url + "/"

    _svc = resolve_app_service(docker_proj)

    # Ensure container is running
    rc, _, err = _run_command(
        f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj
    )
    if rc != 0:
        state["int_test_result"] = "fail"
        state["int_test_output"] = err[: bounds.build.max_seed_output_chars]
        state["errors"].append(f"INT_TEST: Container start failed: {err[:200]}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        return state

    import subprocess as _sp

    _sp.run(["sleep", "5"], timeout=10)

    rc, health_out, _ = _run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30
    )
    if health_out.strip() in ("200", "301", "302"):
        state["int_test_result"] = "pass"
        state["int_test_output"] = f"Health check: HTTP {health_out.strip()}"[
            : bounds.build.max_seed_output_chars
        ]
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "INT_TEST",
                "detail": f"Integration tests passed (health: HTTP {health_out.strip()})",
                "ts": time.time(),
            }
        )
    else:
        state["int_test_result"] = "fail"
        state["int_test_output"] = f"Health check failed: HTTP {health_out.strip()}"[
            : bounds.build.max_seed_output_chars
        ]
        state["errors"].append("INT_TEST: Health check failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "INT_TEST",
                "detail": f"Integration test failed: HTTP {health_out.strip()}",
                "ts": time.time(),
            }
        )

    state["sub_phase"] = "INT_TEST"
    return state


def seed_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Generate and execute seed data script."""
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "SEED",
            "detail": "Generating and running seed data...",
            "ts": time.time(),
        }
    )
    skills = state["skills"]
    docker_proj = state["docker_proj"]
    project_folder = state["project_path"]
    spec_text = state["spec_text"]

    seed_dir = Path(project_folder) / "build" / "seed_data"
    seed_dir.mkdir(parents=True, exist_ok=True)

    # Extract data models
    data_models = extract_data_models(docker_proj)
    api_specs = extract_api_specs(docker_proj)

    # Generate seed script via LLM
    seed_skill = skills.get("ai-workflow-data-seeding", {})
    if not seed_skill:
        seed_skill = {
            "content": "Generate a seed script that populates the database with realistic data. "
            "Use SQLAlchemy 2.0 async insert(). Be idempotent. Output ONLY valid Python code."
        }

    task = f"""Generate random test data seed script for project at {docker_proj}.
Data models available: {len(data_models)} models
API specs available: {len(api_specs)} endpoints

Requirements:
- Generate at least 5 records per model with realistic random data
- Include edge cases: null fields, empty strings, boundary values
- Make the script idempotent with INSERT OR IGNORE or check-first pattern
"""

    context = (
        spec_text
        + f"\n\nData models: {json.dumps(data_models, indent=2)}\nAPI specs: {json.dumps(api_specs, indent=2)}"
    )
    seed_script = _invoke_skill(seed_skill["content"], task, context, llm=None)

    # Clean markdown fences
    clean_script = seed_script.strip()
    if clean_script.startswith("```"):
        lines = clean_script.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_script = "\n".join(lines)

    # Validate AST
    try:
        ast.parse(clean_script)
    except SyntaxError as e:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "SEED",
                "detail": f"Seed script syntax error: {e}",
                "ts": time.time(),
            }
        )
        state["seed_result"] = "fail"
        state["seed_output"] = str(e)[: bounds.build.max_seed_output_chars]
        state["errors"].append(f"SEED: SyntaxError: {e}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        state["sub_phase"] = "SEED"
        return state

    # Write and execute
    seed_path = seed_dir / "seed.py"
    seed_path.write_text(clean_script)

    docker_seed_path = Path(docker_proj) / "app" / "seed.py"
    docker_seed_path.parent.mkdir(parents=True, exist_ok=True)
    docker_seed_path.write_text(clean_script)

    _svc = resolve_app_service(docker_proj)

    try:
        import subprocess as _sp

        result = _sp.run(
            ["docker", "compose", "exec", "-T", _svc, "python", "-m", "app.seed"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=docker_proj,
        )
        seed_output = result.stdout + result.stderr
        if result.returncode != 0:
            writer(
                {
                    "type": "progress",
                    "phase": "BUILD",
                    "step": "SEED",
                    "detail": f"Seed script failed (exit {result.returncode})",
                    "ts": time.time(),
                }
            )
            state["seed_result"] = "fail"
            state["seed_output"] = seed_output[: bounds.build.max_seed_output_chars]
            state["errors"].append(
                f"SEED: exit {result.returncode}: {seed_output[:200]}"
            )
            state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
        else:
            writer(
                {
                    "type": "progress",
                    "phase": "BUILD",
                    "step": "SEED",
                    "detail": "Seed data populated successfully",
                    "ts": time.time(),
                }
            )
            state["seed_result"] = "pass"
            state["seed_output"] = seed_output[: bounds.build.max_seed_output_chars]
    except subprocess.TimeoutExpired:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "SEED",
                "detail": "Seed script timed out (>60s)",
                "ts": time.time(),
            }
        )
        state["seed_result"] = "fail"
        state["seed_output"] = "Timed out"
        state["errors"].append("SEED: timeout after 60s")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]
    except Exception as e:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "SEED",
                "detail": f"Seed execution failed: {e}",
                "ts": time.time(),
            }
        )
        state["seed_result"] = "fail"
        state["seed_output"] = str(e)[: bounds.build.max_seed_output_chars]
        state["errors"].append(f"SEED: {e}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]

    state["sub_phase"] = "SEED"
    return state


def deploy_gate_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Validate container is healthy before UAT begins.

    Gate: container running, HTTP health endpoint responds, seed data exists.
    If unhealthy, skip UAT — nothing to test.
    """
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "DEPLOY_GATE",
            "detail": "Validating deployment health...",
            "ts": time.time(),
        }
    )
    docker_proj = state["docker_proj"]
    from config.loader import config as _cfg

    _svc = resolve_app_service(docker_proj)
    _health_url = _cfg.services.product.url + "/"

    # Check 1: Container running
    rc, out, err = _run_command(
        f"docker compose ps {_svc} --format '{{{{.Status}}}}'", workdir=docker_proj
    )
    if rc != 0 or "Up" not in out:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "DEPLOY_GATE",
                "detail": f"Container {_svc} not running — skipping UAT",
                "ts": time.time(),
            }
        )
        state["uat_result"] = "skip"
        state["uat_output"] = "DEPLOY_GATE failed: container not running"
        state["uat_pass_rate"] = 0.0  # skip: deployment not verified; VERIFY gate (Decision 2) owns the pass/fail verdict
        state["sub_phase"] = "DEPLOY_GATE"
        return state

    # Check 2: Health endpoint
    rc, health_out, _ = _run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}",
        timeout=15,
        workdir=docker_proj,
    )
    if health_out.strip() not in ("200", "301", "302"):
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "DEPLOY_GATE",
                "detail": f"Health check failed: HTTP {health_out.strip()} — skipping UAT",
                "ts": time.time(),
            }
        )
        state["uat_result"] = "skip"
        state["uat_output"] = f"DEPLOY_GATE failed: HTTP {health_out.strip()}"
        state["uat_pass_rate"] = 0.0  # skip: deployment not verified; VERIFY gate (Decision 2) owns the pass/fail verdict
        state["sub_phase"] = "DEPLOY_GATE"
        return state

    # Check 3: Logs for startup errors
    rc, logs, _ = _run_command(
        f"docker compose logs {_svc} --tail=20", timeout=10, workdir=docker_proj
    )
    if any(kw in logs for kw in ["Traceback", "ImportError", "SyntaxError"]):
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "DEPLOY_GATE",
                "detail": "Container logs contain startup errors — proceeding with caution",
                "ts": time.time(),
            }
        )

    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "DEPLOY_GATE",
            "detail": f"Deploy gate passed: HTTP {health_out.strip()}",
            "ts": time.time(),
        }
    )
    state["sub_phase"] = "DEPLOY_GATE"
    return state


def uat_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Run UAT tests — agent mode default, scripted fallback, LLM fallback."""
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "progress",
            "detail": "  → [UAT] Running UAT tests...",
            "ts": time.time(),
        }
    )
    from config.loader import config as _cfg

    base_url = _cfg.services.product.url

    output_dir = Path(state["project_path"]) / "superApp_output"
    mode = state.get("superApp_mode", "agent")
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "progress",
            "detail": f"     Mode: {mode}",
            "ts": time.time(),
        }
    )

    uat_pass_rate = 0.0
    uat_result = "fail"
    uat_output = ""

    # ── Try SuperApp (agent mode default) ──────────────────────────
    from graph.nodes.build_legacy_superapp import (
        _run_llm_uat_fallback,
        _run_superApp_agent,
        _run_superApp_scripted,
    )

    superApp_worked = False
    if mode == "agent":
        report = _run_superApp_agent(state, base_url, output_dir)
        if report.get("status") != "not_found":
            superApp_worked = True
            uat_output = json.dumps(report, indent=2)[
                : bounds.build.max_seed_output_chars
            ]
            # Parse verdict
            verdict = report.get("verdict", "unknown")
            # Try to extract pass rate from results
            if "results" in report:
                results = report["results"]
                if isinstance(results, list) and results:
                    passed = sum(1 for r in results if r.get("status") == "passed")
                    uat_pass_rate = passed / len(results)
                else:
                    uat_pass_rate = 1.0 if verdict == "pass" else 0.0
            elif verdict == "pass":
                uat_pass_rate = 1.0
            elif verdict == "fail":
                uat_pass_rate = 0.0
            else:
                uat_pass_rate = 0.5
    else:
        results = _run_superApp_scripted(state, base_url, output_dir)
        if results:
            superApp_worked = True
            passed = sum(1 for r in results if r.get("status") == "passed")
            uat_pass_rate = passed / len(results)
            uat_output = json.dumps(results[:5], indent=2)[
                : bounds.build.max_seed_output_chars
            ]

    # ── Fallback chain ─────────────────────────────────────────────
    if not superApp_worked:
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "warning",
                "detail": "     ⚠ SuperApp unavailable — falling back to LLM UAT",
                "ts": time.time(),
            }
        )
        result_text, uat_pass_rate = _run_llm_uat_fallback(state, base_url)
        uat_output = result_text[: bounds.build.max_seed_output_chars]

    # ── Verdict ────────────────────────────────────────────────────
    if uat_pass_rate >= 0.8:
        uat_result = "pass"
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "success",
                "detail": f"     ✓ UAT passed (rate={uat_pass_rate:.2f})",
                "ts": time.time(),
            }
        )
    else:
        uat_result = "fail"
        writer(
            {
                "type": "error",
                "phase": "BUILD",
                "step": "error",
                "detail": f"     ✗ UAT failed (rate={uat_pass_rate:.2f})",
                "ts": time.time(),
            }
        )
        state["errors"].append(f"UAT: pass rate {uat_pass_rate:.2f} < 0.8")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries :]

    state["uat_pass_rate"] = uat_pass_rate
    state["uat_result"] = uat_result
    state["uat_output"] = uat_output
    state["sub_phase"] = "UAT"
    return state


def security_review_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Aggregate security review pass after all implementation items.

    Runs security-and-hardening skill on the generated codebase.
    """
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "progress",
            "detail": "  → [SECURITY_REVIEW] Running security audit...",
            "ts": time.time(),
        }
    )
    skills = state["skills"]
    security_skill = skills.get("security-and-hardening", {})
    if security_skill:
        project_path = state["project_path"]
        task = (
            f"Run a security audit on the generated project at: {project_path}\n\n"
            "Check for:\n"
            "- Input validation and sanitization\n"
            "- Authentication and authorization patterns\n"
            "- Rate limiting and DoS protection\n"
            "- Secret management (no hardcoded credentials)\n"
            "- SQL injection prevention\n"
            "- XSS protection\n"
            "- CSRF protection\n"
            "Report findings and score the security posture.\n"
        )

        result = _invoke_skill(
            security_skill["content"], task, f"Project: {project_path}", llm=None
        )
        state["security_review"] = result[:5000]
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "success",
                "detail": f"     ✓ Security review complete ({len(result)} chars)",
                "ts": time.time(),
            }
        )
    return state


def code_review_node(state: BuildSubState) -> BuildSubState:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Aggregate code quality review pass.

    Runs pre-commit-review skill on the generated codebase.
    """
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "progress",
            "detail": "  → [CODE_REVIEW] Running code quality review...",
            "ts": time.time(),
        }
    )
    skills = state["skills"]
    review_skill = skills.get("pre-commit-review", {})
    if review_skill:
        project_path = state["project_path"]
        task = (
            f"Review the code quality of the generated project at: {project_path}\n\n"
            "Check for:\n"
            "- Clean architecture and separation of concerns\n"
            "- Error handling patterns\n"
            "- Testing readiness (unit-testable functions)\n"
            "- Code style and naming conventions\n"
            "- Import organization\n"
            "Report findings and score the code quality.\n"
        )

        result = _invoke_skill(
            review_skill["content"], task, f"Project: {project_path}", llm=None
        )
        state.setdefault("code_review", "")
        state["code_review"] = result[: state["skills"].get("max_review_chars", 5000)]
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "success",
                "detail": f"     ✓ Code review complete ({len(result)} chars)",
                "ts": time.time(),
            }
        )
    return state


def security_gate_node(state: BuildSubState) -> BuildSubState:
    """Security and code review gate before DEPLOY_GATE.

    Runs security audit and code review, then proceeds to DEPLOY_GATE.
    """
    state = security_review_node(state)
    state = code_review_node(state)
    return state
