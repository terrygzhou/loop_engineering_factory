"""
BUILD subgraph — structured sub-workflow for the BUILD phase.

Sub-nodes:
  IMPL_PLAN → CREATE_BACKLOG → IMPLEMENT → UNIT_TEST → INT_TEST → SEED → UAT → END

Internal routing:
  UNIT_TEST pass → next backlog item (IMPLEMENT) or INT_TEST (if all done)
  UNIT_TEST fail → retry IMPLEMENT (max 3) or skip
  INT_TEST bugs → append to backlog → IMPLEMENT
  UAT fail → route back to BUILD parent (outer graph handles retry)
"""
import re
import json
import ast
import subprocess
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from config.bounds_loader import bounds
from graph.state import CycleMetrics
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from .build_helpers import (
    parse_llm_output, write_files_to_project, run_command, find_docker_project,
    resolve_app_service,
    parse_tasks_to_backlog, generate_backlog_md, extract_data_models, extract_api_specs,
    parse_uat_metrics,
)

# ── Sub-state ──────────────────────────────────────────────────────

class BuildSubState(TypedDict):
    """Internal state for the BUILD subgraph."""
    sub_phase: str                  # Current sub-phase name
    project_path: str               # Resolved project path
    docker_proj: str                # Docker project dir
    spec_text: str                  # Refined spec
    tasks_text: str                 # Task breakdown text
    skills: dict                    # Skill registry
    backlog: list[dict]            # Backlog items with status
    backlog_idx: int               # Index of current item being worked on
    impl_plan: str                 # Implementation plan
    current_code: str              # Code generated for current item
    test_code: str                 # Test code for current item
    test_result: str               # "pass" / "fail" / "skip"
    test_output: str               # Raw test output
    retry_count: int               # Retries for current item
    int_test_result: str           # "pass" / "fail"
    int_test_output: str           # Raw integration test output
    seed_result: str               # "pass" / "fail"
    seed_output: str               # Raw seed output
    uat_result: str                # "pass" / "fail"
    uat_output: str                # Raw UAT output
    uat_pass_rate: float           # Parsed UAT pass rate
    all_generated_code: list[str]  # Accumulated code across items
    errors: list[str]              # Accumulated error messages
    build_status: str              # "pass" / "fail" / "partial"
    parent_artifacts: dict         # Reference to parent artifacts dict (for writing back)
    superweb_mode: str             # "agent" (default) | "scripted"
    superweb_agent_report: dict    # Parsed agent_report.json from agent mode

MAX_ITEM_RETRIES = None  # Runtime value from bounds.build.max_item_retries

# ── Sub-node functions ─────────────────────────────────────────────

def impl_plan_node(state: BuildSubState) -> BuildSubState:
    """Generate implementation plan from spec + tasks."""
    print("  → [IMPL_PLAN] Generating implementation plan...")
    skills = state["skills"]
    spec = state["spec_text"]
    tasks = state["tasks_text"]

    impl_skill = skills.get("incremental-implementation", {})
    if impl_skill:
        task = (
            "Review the spec and tasks, then create an implementation plan.\n"
            "Outline the order of implementation, dependencies between components,\n"
            "and any architectural decisions. Be concise.\n\n"
            f"Spec:\n{spec[:bounds.build.recent_code_chars]}\n\nTasks:\n{tasks[:bounds.build.recent_code_chars]}"
        )
        plan = invoke_skill(impl_skill["content"], task, "", llm=None)
    else:
        plan = f"Implement tasks in order: {tasks[:bounds.build.recent_code_chars]}"

    state["impl_plan"] = plan
    state["sub_phase"] = "IMPL_PLAN"
    print(f"  → [IMPL_PLAN] Plan generated ({len(plan)} chars)")
    return state

def create_backlog_node(state: BuildSubState) -> BuildSubState:
    """Parse tasks into backlog items, write backlog.md."""
    print("  → [CREATE_BACKLOG] Creating backlog...")
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
    print(f"  → [CREATE_BACKLOG] {len(backlog_items)} backlog items created")
    return state

def implement_node(state: BuildSubState) -> BuildSubState:
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

    print(f"  → [IMPLEMENT] Item {idx + 1}/{len(state['backlog'])}: {item['description'][:80]}")
    print(f"     Retry: {state['retry_count']}/{bounds.build.max_item_retries}")

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
            impl_context += "\n\nPreviously generated code:\n" + "\n".join(state["all_generated_code"][-bounds.build.recent_code_snippets:])[:bounds.build.recent_code_chars]

        result = invoke_skill(
            impl_skill["content"],
            item_task if state["retry_count"] == 0 else f"{item_task}\n\nPrevious attempt failed. Fix and retry.",
            impl_context,
            llm=None,
        )
        item_code = result
        # Cap to prevent unbounded memory growth
        state["all_generated_code"] = state["all_generated_code"][-bounds.artifacts.max_generated_code_entries:] + [result]

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
        test_code = invoke_skill(tdd_skill["content"], tdd_task, item_code, llm=None)

    state["current_code"] = item_code
    state["test_code"] = test_code
    state["sub_phase"] = "IMPLEMENT"

    if not item_code:
        state["errors"].append(f"Item {item['id']}: No code generated")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    return state

def unit_test_node(state: BuildSubState) -> BuildSubState:
    """Run Docker build + pytest for current item."""
    idx = state["backlog_idx"]
    if state["sub_phase"] == "NO_MORE_ITEMS":
        state["sub_phase"] = "ALL_ITEMS_DONE"
        return state

    item = state["backlog"][idx]
    if item["status"] == "failed":
        state["backlog_idx"] = idx + 1
        state["sub_phase"] = "UNIT_TEST"
        return unit_test_node(state)

    docker_proj = state["docker_proj"]
    print(f"  → [UNIT_TEST] Building and testing item {item['id']}...")

    # Write files
    combined = state["current_code"] + "\n" + state["test_code"]
    files, cmds, parse_info = parse_llm_output(combined)
    print(f"     Parsed {len(files)} files, {len(cmds)} commands")

    if not files:
        state["test_result"] = "fail"
        state["test_output"] = "No files generated"
        state["errors"].append(f"Item {item['id']}: No files to test")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        state["sub_phase"] = "UNIT_TEST"
        return state

    written = write_files_to_project(files, docker_proj)
    print(f"     Wrote {len(written)} files")

    # Run pre-build commands
    for desc, cmd in cmds:
        if 'build' in desc.lower() or 'test' in desc.lower():
            continue
        rc, _, err = run_command(cmd, workdir=docker_proj)
        if rc != 0:
            print(f"     ⚠ Command '{desc}' failed: {err[:100]}")

    # Docker build
    print("     Docker compose build...")
    _svc = resolve_app_service(docker_proj)
    rc, out, err = run_command(f"docker compose build --no-cache {_svc}", timeout=300, workdir=docker_proj)
    if rc != 0:
        print(f"     ✗ Docker build failed: {err[:200]}")
        state["test_result"] = "fail"
        state["test_output"] = err[:bounds.build.max_test_output_chars]
        state["errors"].append(f"Item {item['id']}: Docker build failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    # Start container
    rc, _, err = run_command(f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj)
    if rc != 0:
        print(f"     ✗ Container start failed: {err[:200]}")
        state["test_result"] = "fail"
        state["errors"].append(f"Item {item['id']}: Container start failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
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
    rc, health_out, _ = run_command(f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30)
    if health_out.strip() not in ('200', '301', '302'):
        print(f"     ✗ Health check failed: HTTP {health_out.strip()}")
        state["test_result"] = "fail"
        state["errors"].append(f"Item {item['id']}: Health check failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
        return state

    # Run pytest
    print("     Running pytest...")
    rc, test_out, test_err = run_command(
        f"docker compose exec {_svc} python -m pytest tests/ -v --tb=short 2>&1",
        timeout=120, workdir=docker_proj,
    )
    passed = len(re.findall(r'passed', test_out))
    failed = len(re.findall(r'failed', test_out))

    if rc == 0 and failed == 0:
        print(f"     ✓ pytest passed ({passed} tests) — item {item['id']} complete")
        state["test_result"] = "pass"
        state["test_output"] = test_out[:bounds.build.max_test_output_chars]
        state["backlog"][idx]["status"] = "completed"
        state["retry_count"] = 0
        state["backlog_idx"] = idx + 1
    else:
        print(f"     ✗ pytest: {failed} failed, {passed} passed")
        state["test_result"] = "fail"
        state["test_output"] = test_out[:bounds.build.max_test_output_chars]
        state["errors"].append(f"Item {item['id']}: {failed} test failures (attempt {state['retry_count'] + 1})")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        state["retry_count"] += 1
        if state["retry_count"] >= bounds.build.max_item_retries:
            state["backlog"][idx]["status"] = "failed"
            state["backlog_idx"] = idx + 1
            state["retry_count"] = 0

    state["sub_phase"] = "UNIT_TEST"
    return state

def int_test_node(state: BuildSubState) -> BuildSubState:
    """Integration test: verify Docker app is running, run aggregate checks."""
    print("  → [INT_TEST] Running integration tests...")
    docker_proj = state["docker_proj"]
    from config.loader import config as _cfg
    _health_url = _cfg.services.product.url + "/"

    _svc = resolve_app_service(docker_proj)

    # Ensure container is running
    rc, _, err = run_command(f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj)
    if rc != 0:
        state["int_test_result"] = "fail"
        state["int_test_output"] = err[:bounds.build.max_seed_output_chars]
        state["errors"].append(f"INT_TEST: Container start failed: {err[:200]}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        return state

    import subprocess as _sp
    _sp.run(["sleep", "5"], timeout=10)

    rc, health_out, _ = run_command(f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30)
    if health_out.strip() in ('200', '301', '302'):
        state["int_test_result"] = "pass"
        state["int_test_output"] = f"Health check: HTTP {health_out.strip()}"[:bounds.build.max_seed_output_chars]
        print(f"     ✓ Integration tests passed (health: HTTP {health_out.strip()})")
    else:
        state["int_test_result"] = "fail"
        state["int_test_output"] = f"Health check failed: HTTP {health_out.strip()}"[:bounds.build.max_seed_output_chars]
        state["errors"].append(f"INT_TEST: Health check failed")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        print(f"     ✗ Integration test failed: HTTP {health_out.strip()}")

    state["sub_phase"] = "INT_TEST"
    return state

def seed_node(state: BuildSubState) -> BuildSubState:
    """Generate and execute seed data script."""
    print("  → [SEED] Generating and running seed data...")
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

    context = spec_text + f"\n\nData models: {json.dumps(data_models, indent=2)}\nAPI specs: {json.dumps(api_specs, indent=2)}"
    seed_script = invoke_skill(seed_skill["content"], task, context, llm=None)

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
        print(f"     ✗ Seed script syntax error: {e}")
        state["seed_result"] = "fail"
        state["seed_output"] = str(e)[:bounds.build.max_seed_output_chars]
        state["errors"].append(f"SEED: SyntaxError: {e}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
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
            capture_output=True, text=True, timeout=60, cwd=docker_proj,
        )
        seed_output = result.stdout + result.stderr
        if result.returncode != 0:
            print(f"     ✗ Seed script failed (exit {result.returncode})")
            state["seed_result"] = "fail"
            state["seed_output"] = seed_output[:bounds.build.max_seed_output_chars]
            state["errors"].append(f"SEED: exit {result.returncode}: {seed_output[:200]}")
            state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
        else:
            print(f"     ✓ Seed data populated successfully")
            state["seed_result"] = "pass"
            state["seed_output"] = seed_output[:bounds.build.max_seed_output_chars]
    except subprocess.TimeoutExpired:
        print("     ✗ Seed script timed out (>60s)")
        state["seed_result"] = "fail"
        state["seed_output"] = "Timed out"
        state["errors"].append("SEED: timeout after 60s")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]
    except Exception as e:
        print(f"     ✗ Seed execution failed: {e}")
        state["seed_result"] = "fail"
        state["seed_output"] = str(e)[:bounds.build.max_seed_output_chars]
        state["errors"].append(f"SEED: {e}")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]

    state["sub_phase"] = "SEED"
    return state

def _run_superweb_agent(state: BuildSubState, base_url: str, output_dir: Path) -> dict:
    """Run SuperWeb in agent mode — OpenHands agent explores and tests."""
    agent_timeout = getattr(getattr(bounds, "superweb", None), "agent_timeout_seconds", 3600)
    # LLM config is in config.yaml, not bounds.yaml — use config loader
    from config.loader import config as _cfg
    llm_url = _cfg.services.llm.base_url
    llm_model = _cfg.services.llm.model
    # SuperWeb root from config (default: pip-installed CLI runs from project dir)
    superweb_config = getattr(_cfg, "superweb", None)
    if superweb_config:
        superweb_root = getattr(superweb_config, "root", state["project_path"])
    else:
        superweb_root = state["project_path"]
    cmd = [
        "superweb", "run",
        "--target", base_url,
        "--source", state["project_path"],
        "--output", str(output_dir),
        "--mode", "agent",
        "--agent-timeout", str(agent_timeout),
        "--llm-url", llm_url,
        "--llm-model", llm_model,
    ]
    try:
        subprocess.run(
            cmd, capture_output=True, text=True, timeout=agent_timeout + 120,
            cwd=superweb_root,
        )
        # Parse agent_report.json (agent mode writes to report/)
        report_path = output_dir / "report" / "agent_report.json"
        if report_path.exists():
            return json.loads(report_path.read_text())
        # Fallback: check data/test_results.json
        results_path = output_dir / "data" / "test_results.json"
        if results_path.exists():
            return {"results": json.loads(results_path.read_text())}
        return {"status": "completed", "verdict": "unknown"}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "verdict": "fail"}
    except FileNotFoundError:
        return {"status": "not_found", "verdict": "fail"}


def _run_superweb_scripted(state: BuildSubState, base_url: str, output_dir: Path) -> dict:
    """Run SuperWeb in scripted mode — deterministic Playwright pipeline."""
    timeout = getattr(getattr(bounds, "superweb", None), "timeout_seconds", 600)
    variations = getattr(getattr(bounds, "superweb", None), "variations", 3)
    from config.loader import config as _cfg
    llm_url = _cfg.services.llm.base_url
    llm_model = _cfg.services.llm.model
    superweb_config = getattr(_cfg, "superweb", None)
    superweb_root = (getattr(superweb_config, "root", state["project_path"])
                     if superweb_config else state["project_path"])
    cmd = [
        "superweb", "run",
        "--target", base_url,
        "--source", state["project_path"],
        "--output", str(output_dir),
        "--mode", "scripted",
        "--variations", str(variations),
        "--llm-url", llm_url,
        "--llm-model", llm_model,
    ]
    try:
        subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=superweb_root,
        )
        results_path = output_dir / "data" / "test_results.json"
        if results_path.exists():
            return {"scripted_results": json.loads(results_path.read_text())}
        return {"scripted_results": []}
    except subprocess.TimeoutExpired:
        return {"scripted_results": []}
    except FileNotFoundError:
        return {"scripted_results": []}


def _run_llm_uat_fallback(state: BuildSubState, base_url: str) -> tuple[str, float]:
    """Fallback to LLM-prompt UAT (original behavior)."""
    skills = state["skills"]
    uat_skill = skills.get("uat-workflow", {})
    if not uat_skill:
        return "SKIPPED — skill not found", 0.5

    task = (
        f"Run full UAT tests for project: {state['project_path']}\n"
        f"Base URL: {base_url}\n\n"
        "=== UAT EXECUTION ORDER ===\n"
        "Phase 0: Playwright setup (verify installed, chromium available)\n"
        "Phase 2: Pre-UAT bulk API sweep (curl all discovered routes)\n"
        "Phase 3: Template completeness check\n"
        "Phase 5: Playwright UAT — desktop pass (MANDATORY)\n"
        "Phase 6: Playwright UAT — mobile pass (MANDATORY)\n"
        "Phase 7: Browser Tool Walkthrough (fallback)\n"
        "Phase 8: Report: PASS/FAIL verdict with per-page results\n\n"
        "=== Report Format ===\n"
        "For each test case, output: [PASS] or [FAIL]: test description\n"
        "Final summary must include: Total tests run, Passed, Failed, Pass rate (0.0-1.0), Verdict: PASS or FAIL\n"
    )
    result = invoke_skill(uat_skill["content"], task, f"Project: {state['project_path']}\nBase URL: {base_url}", llm=None)
    state["uat_output"] = result[:bounds.build.max_seed_output_chars]
    uat_metrics = parse_uat_metrics(result)
    return result, uat_metrics["uat_pass_rate"]


def deploy_gate_node(state: BuildSubState) -> BuildSubState:
    """Validate container is healthy before UAT begins.

    Gate: container running, HTTP health endpoint responds, seed data exists.
    If unhealthy, skip UAT — nothing to test.
    """
    print("  → [DEPLOY_GATE] Validating deployment health...")
    docker_proj = state["docker_proj"]
    from config.loader import config as _cfg
    _svc = resolve_app_service(docker_proj)
    _health_url = _cfg.services.product.url + "/"

    # Check 1: Container running
    rc, out, err = run_command(f"docker compose ps {_svc} --format '{{{{.Status}}}}'", workdir=docker_proj)
    if rc != 0 or "Up" not in out:
        print(f"     ✗ Container {_svc} not running — skipping UAT")
        state["uat_result"] = "skip"
        state["uat_output"] = f"DEPLOY_GATE failed: container not running"
        state["uat_pass_rate"] = 1.0  # skip counts as pass
        state["sub_phase"] = "DEPLOY_GATE"
        return state

    # Check 2: Health endpoint
    rc, health_out, _ = run_command(f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=15, workdir=docker_proj)
    if health_out.strip() not in ('200', '301', '302'):
        print(f"     ✗ Health check failed: HTTP {health_out.strip()} — skipping UAT")
        state["uat_result"] = "skip"
        state["uat_output"] = f"DEPLOY_GATE failed: HTTP {health_out.strip()}"
        state["uat_pass_rate"] = 1.0
        state["sub_phase"] = "DEPLOY_GATE"
        return state

    # Check 3: Logs for startup errors
    rc, logs, _ = run_command(f"docker compose logs {_svc} --tail=20", timeout=10, workdir=docker_proj)
    if any(kw in logs for kw in ["Traceback", "ImportError", "SyntaxError"]):
        print("     ⚠ Container logs contain startup errors — proceeding with caution")

    print(f"     ✓ Deploy gate passed: HTTP {health_out.strip()}")
    state["sub_phase"] = "DEPLOY_GATE"
    return state


def uat_node(state: BuildSubState) -> BuildSubState:
    """Run UAT tests — agent mode default, scripted fallback, LLM fallback."""
    print("  → [UAT] Running UAT tests...")
    from config.loader import config as _cfg
    base_url = _cfg.services.product.url

    output_dir = Path(state["project_path"]) / "superweb_output"
    mode = state.get("superweb_mode", "agent")
    print(f"     Mode: {mode}")

    uat_pass_rate = 0.0
    uat_result = "fail"
    uat_output = ""

    # ── Try SuperWeb (agent mode default) ──────────────────────────
    superweb_worked = False
    if mode == "agent":
        report = _run_superweb_agent(state, base_url, output_dir)
        if report.get("status") != "not_found":
            superweb_worked = True
            uat_output = json.dumps(report, indent=2)[:bounds.build.max_seed_output_chars]
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
        results = _run_superweb_scripted(state, base_url, output_dir)
        if results:
            superweb_worked = True
            passed = sum(1 for r in results if r.get("status") == "passed")
            uat_pass_rate = passed / len(results)
            uat_output = json.dumps(results[:5], indent=2)[:bounds.build.max_seed_output_chars]

    # ── Fallback chain ─────────────────────────────────────────────
    if not superweb_worked:
        print("     ⚠ SuperWeb unavailable — falling back to LLM UAT")
        result_text, uat_pass_rate = _run_llm_uat_fallback(state, base_url)
        uat_output = result_text[:bounds.build.max_seed_output_chars]

    # ── Verdict ────────────────────────────────────────────────────
    if uat_pass_rate >= 0.8:
        uat_result = "pass"
        print(f"     ✓ UAT passed (rate={uat_pass_rate:.2f})")
    else:
        uat_result = "fail"
        print(f"     ✗ UAT failed (rate={uat_pass_rate:.2f})")
        state["errors"].append(f"UAT: pass rate {uat_pass_rate:.2f} < 0.8")
        state["errors"] = state["errors"][-bounds.feedback.max_error_entries:]

    state["uat_pass_rate"] = uat_pass_rate
    state["uat_result"] = uat_result
    state["uat_output"] = uat_output
    state["sub_phase"] = "UAT"
    return state

# ── Conditional routing ────────────────────────────────────────────

def route_build(state: BuildSubState) -> str:
    """Route within the BUILD subgraph."""
    sub_phase = state["sub_phase"]

    if sub_phase == "ALL_ITEMS_DONE":
        return "INT_TEST"

    if sub_phase == "NO_MORE_ITEMS":
        return "INT_TEST"

    if sub_phase == "IMPL_PLAN":
        return "CREATE_BACKLOG"

    if sub_phase == "CREATE_BACKLOG":
        return "IMPLEMENT"

    if sub_phase == "IMPLEMENT":
        return "UNIT_TEST"

    if sub_phase == "UNIT_TEST":
        # unit_test_node already advanced backlog_idx on completion/failure.
        # If backlog_idx >= len(backlog), all items processed → INT_TEST.
        # Otherwise, loop back to IMPLEMENT for the next item.
        if state["backlog_idx"] >= len(state["backlog"]):
            return "INT_TEST"
        return "IMPLEMENT"

    if sub_phase == "INT_TEST":
        return "SEED"

    if sub_phase == "SEED":
        return "DEPLOY_GATE"

    if sub_phase == "DEPLOY_GATE":
        return "UAT"

    if sub_phase == "UAT":
        return END

    return END

# ── State mapping functions (parent ↔ child) ──────────────────────

def build_input_mapping(parent: dict) -> BuildSubState:
    """Map parent WorkflowState → BuildSubState for native subgraph entry.

    Called by LangGraph automatically when entering the BUILD subgraph.
    Replaces the manual BuildSubState construction in build.py.
    """
    import os as _os
    from .build_helpers import find_docker_project

    project_path = parent.get("project_path", "")
    project_folder = parent.get("project_folder", project_path)
    docker_proj = find_docker_project(project_path)

    from config import loader as config_loader

    skills = parent.get("artifacts", {}).get("skill_registry")
    if skills is None:
        from tools.loader import build_skill_registry
        skills = build_skill_registry(config_loader.config.workflow.skill_registry_path)

    return BuildSubState({
        "sub_phase": "IMPL_PLAN",
        "project_path": project_path,
        "docker_proj": docker_proj,
        "spec_text": parent.get("artifacts", {}).get("spec_refined", "")[:bounds.artifacts.max_spec_subgraph_chars],
        "tasks_text": parent.get("artifacts", {}).get("tasks", "")[:bounds.artifacts.max_tasks_subgraph_chars],
        "skills": skills,
        "backlog": [],
        "backlog_idx": 0,
        "impl_plan": "",
        "current_code": "",
        "test_code": "",
        "test_result": "",
        "test_output": "",
        "retry_count": 0,
        "int_test_result": "",
        "int_test_output": "",
        "seed_result": "",
        "seed_output": "",
        "uat_result": "",
        "uat_output": "",
        "uat_pass_rate": 0.5,
        "all_generated_code": [],
        "errors": [],
        "build_status": "pending",
        "parent_artifacts": parent.get("artifacts", {}),
        "superweb_mode": "agent",  # Default: agent mode
        "superweb_agent_report": {},
    })

def build_output_mapping(child: BuildSubState) -> dict:
    """Map BuildSubState → parent WorkflowState update for native subgraph exit.

    Called by LangGraph automatically when the BUILD subgraph completes.
    Returns a dict that gets shallow-merged into the parent WorkflowState.
    Replaces the manual merge logic in build.py (lines 139-206).
    """
    from pathlib import Path as _Path

    # ── Extract subgraph results ──
    backlog = child.get("backlog", [])
    errors = child.get("errors", [])
    uat_pass_rate = child.get("uat_pass_rate", 0.5)
    uat_result = child.get("uat_result", "pass")
    all_code = child.get("all_generated_code", [])
    uat_output = child.get("uat_output", "")
    project_folder = child.get("project_path", "")

    # ── Write backlog.md ──
    build_dir = _Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = build_dir / "backlog.md"
    backlog_path.write_text(generate_backlog_md(backlog, project_folder))

    # ── Determine pass/fail ──
    all_completed = all(i["status"] == "completed" for i in backlog) if backlog else False
    has_errors = bool(errors) or uat_result == "fail"

    # ── Build updated artifacts dict ──
    artifacts = dict(child.get("parent_artifacts", {}))
    if has_errors and not all_completed:
        # ── FAILURE ──
        error_summary = "\n".join(errors[:10])
        incomplete = sum(1 for i in backlog if i["status"] != "completed")
        print(f"\n  ✗ BUILD: {incomplete} items incomplete, UAT={uat_result}")
        artifacts["build_status"] = "fail"

        from graph.state import CycleMetrics
        metrics = CycleMetrics(
            uat_pass_rate=uat_pass_rate,
        )

        return {
            "phase": "BUILD",
            "error": error_summary,
            "next_phase": "BUILD",  # Loop back
            "artifacts": artifacts,
            "metrics": metrics,
        }

    # ── SUCCESS ──
    items_completed = sum(1 for i in backlog if i["status"] == "completed")
    artifacts["build_status"] = "pass"
    artifacts["implementation"] = "\n".join(all_code)
    artifacts["uat_results"] = uat_output
    artifacts["uat_pass_rate"] = uat_pass_rate

    from graph.state import CycleMetrics
    metrics = CycleMetrics(
        uat_pass_rate=uat_pass_rate,
        test_flakiness_rate=0.0,
        latency_ms=0.0,
    )

    print(f"\n  ✓ BUILD passed: {items_completed}/{len(backlog)} items, UAT rate={uat_pass_rate}")

    return {
        "phase": "BUILD",
        "error": None,
        "next_phase": "SHIP",
        "artifacts": artifacts,
        "metrics": metrics,
    }

# ── Build subgraph ─────────────────────────────────────────────────

def build_subgraph() -> StateGraph:
    """Build the BUILD subgraph (returns the StateGraph, not compiled)."""
    sub = StateGraph(BuildSubState)

    sub.add_node("IMPL_PLAN", impl_plan_node)
    sub.add_node("CREATE_BACKLOG", create_backlog_node)
    sub.add_node("IMPLEMENT", implement_node)
    sub.add_node("UNIT_TEST", unit_test_node)
    sub.add_node("INT_TEST", int_test_node)
    sub.add_node("SEED", seed_node)
    sub.add_node("DEPLOY_GATE", deploy_gate_node)
    sub.add_node("UAT", uat_node)

    sub.add_edge(START, "IMPL_PLAN")
    sub.add_edge("IMPL_PLAN", "CREATE_BACKLOG")
    sub.add_edge("CREATE_BACKLOG", "IMPLEMENT")
    sub.add_edge("IMPLEMENT", "UNIT_TEST")
    sub.add_conditional_edges("UNIT_TEST", route_build)
    sub.add_edge("INT_TEST", "SEED")
    sub.add_edge("SEED", "DEPLOY_GATE")
    sub.add_edge("DEPLOY_GATE", "UAT")
    sub.add_edge("UAT", END)

    return sub

def get_compiled_subgraph():
    """Return the compiled BUILD subgraph for native parent integration."""
    return build_subgraph().compile()

def build_subgraph_node(state: dict) -> dict:
    """Wrapper node that bridges WorkflowState ↔ BuildSubState.

    Maps parent state to subgraph input, invokes the subgraph,
    then maps the result back to a parent state update.
    """
    child_state = build_input_mapping(state)
    compiled = get_compiled_subgraph()
    result = compiled.invoke(child_state)
    return build_output_mapping(result)
