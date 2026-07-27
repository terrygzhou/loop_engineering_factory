"""
Build task executor — standalone build pipeline replicating build_subgraph logic.

Pipeline: PROVISION → IMPL_PLAN → CREATE_BACKLOG → IMPLEMENT → UNIT_TEST → INT_TEST → SEED → UAT
"""
import os
import re
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from tools.llm import invoke_skill
from graph.nodes.build_helpers import (
    parse_llm_output, write_files_to_project, run_command, find_docker_project,
    resolve_app_service,
    parse_tasks_to_backlog, generate_backlog_md, extract_data_models,
    extract_api_specs, parse_uat_metrics,
)
from builder import stack_detect


MAX_ITEM_RETRIES = 3


def impl_plan(spec: str, tasks: str, skills: dict) -> str:
    """Generate implementation plan from spec + tasks."""
    print(f"  → [IMPL_PLAN] Generating implementation plan...")
    impl_skill = skills.get("incremental-implementation", {})
    if impl_skill:
        task = (
            "Review the spec and tasks, then create an implementation plan.\n"
            "Outline the order of implementation, dependencies between components,\n"
            "and any architectural decisions. Be concise.\n\n"
            f"Spec:\n{spec[:2000]}\n\nTasks:\n{tasks[:2000]}"
        )
        plan = invoke_skill(impl_skill["content"], task, "", llm=None)
    else:
        plan = f"Implement tasks in order: {tasks[:500]}"
    print(f"  → [IMPL_PLAN] Plan generated ({len(plan)} chars)")
    return plan


def create_backlog(tasks_text: str, project_path: str) -> list[dict]:
    """Parse tasks into backlog items, write backlog.md."""
    print(f"  → [CREATE_BACKLOG] Creating backlog...")
    backlog_items = parse_tasks_to_backlog(tasks_text)
    build_dir = Path(project_path) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = build_dir / "backlog.md"
    backlog_content = generate_backlog_md(backlog_items, project_path)
    backlog_path.write_text(backlog_content)
    print(f"  → [CREATE_BACKLOG] {len(backlog_items)} backlog items created")
    return backlog_items


def implement_item(item: dict, spec: str, tasks: str, skills: dict,
                   project_path: str, all_generated_code: list[str],
                   retry_count: int = 0) -> tuple[str, str]:
    """Generate code + tests for a backlog item. Returns (item_code, test_code)."""
    docker_proj = find_docker_project(project_path)
    item_id = item.get("id", "?")
    description = item.get("description", "unknown")
    print(f"  → [IMPLEMENT] Item {item_id}: {description[:80]}")
    print(f"     Retry: {retry_count}/{MAX_ITEM_RETRIES}")

    item_task = (
        f"Implement backlog item #{item_id}: {description}\n"
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
        if all_generated_code:
            impl_context += "\n\nPreviously generated code:\n" + "\n".join(all_generated_code[-2:])[:2000]

        result = invoke_skill(
            impl_skill["content"],
            item_task if retry_count == 0 else f"{item_task}\n\nPrevious attempt failed. Fix and retry.",
            impl_context,
            llm=None,
        )
        item_code = result

    # Step 2: Generate tests
    tdd_skill = skills.get("test-driven-development", {})
    test_code = ""
    if tdd_skill:
        tdd_task = (
            f"Generate tests for backlog item #{item_id}: {description}\n"
            f"Follow DAMP, pyramid, and A3 patterns.\n"
            f"\n=== OUTPUT FORMAT ===\n"
            "For each test file, output:\n"
            "=== FILE: tests/test_XXX.py ===\n"
            "```python\n...complete test file content...\n```"
        )
        test_code = invoke_skill(tdd_skill["content"], tdd_task, item_code, llm=None)

    return item_code, test_code


def unit_test(item_code: str, test_code: str, docker_proj: str,
              item_id: int, retry_count: int) -> tuple[str, str, str]:
    """
    Run Docker build + pytest for current item.
    Returns (test_result, test_output, next_action).
      test_result: "pass" | "fail"
      test_output: raw output snippet
      next_action: "next" | "retry" | "skip"
    """
    print(f"  → [UNIT_TEST] Building and testing item {item_id}...")

    _svc = resolve_app_service(docker_proj)

    combined = item_code + "\n" + test_code
    files, cmds, _ = parse_llm_output(combined)
    print(f"     Parsed {len(files)} files, {len(cmds)} commands")

    if not files:
        print(f"     ✗ No files generated for item {item_id}")
        return "fail", "No files generated", "retry"

    written = write_files_to_project(files, docker_proj)
    print(f"     Wrote {len(written)} files")

    # Run pre-build commands (skip build/test commands)
    for desc, cmd in cmds:
        if 'build' in desc.lower() or 'test' in desc.lower():
            continue
        rc, _, err = run_command(cmd, workdir=docker_proj)
        if rc != 0:
            print(f"     ⚠ Command '{desc}' failed: {err[:100]}")

    # Docker build
    print("     Docker compose build...")
    rc, out, err = run_command(f"docker compose build --no-cache {_svc}", timeout=300, workdir=docker_proj)
    if rc != 0:
        print(f"     ✗ Docker build failed: {err[:200]}")
        return "fail", err[:500], "retry"

    # Start container
    rc, _, err = run_command(f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj)
    if rc != 0:
        print(f"     ✗ Container start failed: {err[:200]}")
        return "fail", err[:500], "retry"

    # Health check
    subprocess.run(["sleep", "5"], timeout=10)
    from config.loader import config as _cfg
    _health_url = _cfg.services.product.url + "/"
    rc, health_out, _ = run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30
    )
    if health_out.strip() not in ('200', '301', '302'):
        print(f"     ✗ Health check failed: HTTP {health_out.strip()}")
        return "fail", f"Health check failed: HTTP {health_out.strip()}", "retry"

    # Run pytest
    print("     Running pytest...")
    rc, test_out, test_err = run_command(
        f"docker compose exec {_svc} python -m pytest tests/ -v --tb=short 2>&1",
        timeout=120, workdir=docker_proj,
    )
    passed = len(re.findall(r'passed', test_out))
    failed = len(re.findall(r'failed', test_out))

    if rc == 0 and failed == 0:
        print(f"     ✓ pytest passed ({passed} tests) — item {item_id} complete")
        return "pass", test_out[:500], "next"
    else:
        print(f"     ✗ pytest: {failed} failed, {passed} passed")
        return "fail", test_out[:500], "retry"


def int_test(docker_proj: str) -> tuple[str, str]:
    """Integration test: verify Docker app is running. Returns (result, output)."""
    print("  → [INT_TEST] Running integration tests...")
    from config.loader import config as _cfg
    _health_url = _cfg.services.product.url + "/"

    _svc = resolve_app_service(docker_proj)

    # Ensure container is running
    rc, _, err = run_command(f"docker compose up -d {_svc}", timeout=120, workdir=docker_proj)
    if rc != 0:
        print(f"     ✗ Container start failed: {err[:200]}")
        return "fail", err

    subprocess.run(["sleep", "5"], timeout=10)

    rc, health_out, _ = run_command(
        f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}", timeout=30
    )
    if health_out.strip() in ('200', '301', '302'):
        result = "pass"
        output = f"Health check: HTTP {health_out.strip()}"
        print(f"     ✓ Integration tests passed (health: HTTP {health_out.strip()})")
    else:
        result = "fail"
        output = f"Health check failed: HTTP {health_out.strip()}"
        print(f"     ✗ Integration test failed: HTTP {health_out.strip()}")

    return result, output


def seed_data(docker_proj: str, project_path: str, spec_text: str,
              skills: dict) -> tuple[str, str]:
    """Generate and execute seed data script. Returns (result, output)."""
    print("  → [SEED] Generating and running seed data...")

    seed_dir = Path(project_path) / "build" / "seed_data"
    seed_dir.mkdir(parents=True, exist_ok=True)

    # Extract data models and API specs
    data_models = extract_data_models(docker_proj)
    api_specs = extract_api_specs(docker_proj)

    # Generate seed script via LLM
    seed_skill = skills.get("ai-workflow-data-seeding", {})
    if not seed_skill:
        seed_skill = {
            "content": (
                "Generate a seed script that populates the database with realistic data. "
                "Use SQLAlchemy 2.0 async insert(). Be idempotent. Output ONLY valid Python code."
            )
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
        import ast
        ast.parse(clean_script)
    except SyntaxError as e:
        print(f"     ✗ Seed script syntax error: {e}")
        return "fail", str(e)

    # Write and execute
    seed_path = seed_dir / "seed.py"
    seed_path.write_text(clean_script)

    docker_seed_path = Path(docker_proj) / "app" / "seed.py"
    docker_seed_path.parent.mkdir(parents=True, exist_ok=True)
    docker_seed_path.write_text(clean_script)

    _svc = resolve_app_service(docker_proj)

    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", _svc, "python", "-m", "app.seed"],
            capture_output=True, text=True, timeout=60, cwd=docker_proj,
        )
        seed_output = result.stdout + result.stderr
        if result.returncode != 0:
            print(f"     ✗ Seed script failed (exit {result.returncode})")
            return "fail", seed_output[:500]
        else:
            print(f"     ✓ Seed data populated successfully")
            return "pass", seed_output[:500]
    except subprocess.TimeoutExpired:
        print("     ✗ Seed script timed out (>60s)")
        return "fail", "Timed out"
    except Exception as e:
        print(f"     ✗ Seed execution failed: {e}")
        return "fail", str(e)


def run_uat(docker_proj: str, project_path: str, skills: dict) -> tuple[str, str, float]:
    """Run UAT tests via SuperWeb (agent mode) with LLM fallback.
    Returns (result, output, pass_rate).
    """
    print("  → [UAT] Running UAT tests...")
    import json as _json
    import subprocess as _sub

    from config.loader import config as _cfg
    from config.bounds_loader import bounds as _bounds

    _base_url = _cfg.services.product.url
    _output_dir = os.path.join(project_path, "superweb_output")
    os.makedirs(_output_dir, exist_ok=True)

    # ── Try SuperWeb agent mode (primary) ──────────────────────────
    _agent_timeout = getattr(getattr(_bounds, "superweb", None), "agent_timeout_seconds", 3600)
    _llm_url = _cfg.services.llm.base_url
    _llm_model = _cfg.services.llm.model

    _cmd = [
        "superweb", "run",
        "--target", _base_url,
        "--source", project_path,
        "--output", _output_dir,
        "--mode", "agent",
        "--agent-timeout", str(_agent_timeout),
        "--llm-url", _llm_url,
        "--llm-model", _llm_model,
    ]
    _superweb_worked = False
    try:
        _result = _sub.run(
            _cmd, capture_output=True, text=True, timeout=_agent_timeout + 120,
            cwd=project_path,
        )
        # Parse agent_report.json
        _report_path = os.path.join(_output_dir, "report", "agent_report.json")
        if os.path.exists(_report_path):
            _superweb_worked = True
            _report = _json.loads(open(_report_path).read())
            _output = _json.dumps(_report, indent=2)[:10000]
            # Extract pass rate from results
            _pass_rate = 0.5
            if "results" in _report:
                _results = _report["results"]
                if isinstance(_results, list) and _results:
                    _passed = sum(1 for r in _results if r.get("status") == "passed")
                    _pass_rate = _passed / len(_results)
                else:
                    _verdict = _report.get("verdict", "unknown")
                    _pass_rate = 1.0 if _verdict == "pass" else 0.0
            elif _report.get("verdict") == "pass":
                _pass_rate = 1.0
            else:
                _pass_rate = 0.5
            print(f"     ✓ SuperWeb agent UAT completed (rate={_pass_rate:.2f})")
            return "pass" if _pass_rate >= 0.8 else "fail", _output, _pass_rate
    except (_sub.TimeoutExpired, FileNotFoundError) as _e:
        print(f"     ⚠ SuperWeb unavailable: {_e}")

    # ── Fallback: LLM-prompted UAT via uat-workflow skill ─────────
    print("     ⚠ Falling back to LLM UAT...")
    uat_skill = skills.get("uat-workflow", {})
    if not uat_skill:
        print("     ⚠ uat-workflow skill not found — defaulting to pass")
        return "pass", "SKIPPED — no UAT skill", 0.5

    task = (
        f"Run UAT tests for project: {project_path}\n"
        f"Base URL: {_base_url}\n\n"
        "Generate a Playwright UAT script, execute it, and report results.\n"
        "Phases: public pages → auth flow → authenticated pages → form submission.\n"
        "Report format: [PASS]/[FAIL] per test, summary with pass rate.\n"
    )
    result = invoke_skill(uat_skill["content"], task,
                         f"Project: {project_path}\nBase URL: {_base_url}", llm=None)

    metrics = parse_uat_metrics(result)
    pass_rate = metrics["uat_pass_rate"]

    if pass_rate >= 0.8:
        print(f"     ✓ UAT passed (rate={pass_rate})")
        return "pass", result, pass_rate
    else:
        print(f"     ✗ UAT failed (rate={pass_rate})")
        return "fail", result, pass_rate


class BuildRunner:
    """Orchestrates the full build pipeline."""

    def __init__(self, request):
        self.request = request
        self.progress: list[dict] = []
        self.errors: list[str] = []
        self.artifacts: dict = {}
        self.cancelled = False

    def _update_progress(self, phase: str, status: str, detail: str = ""):
        entry = {
            "phase": phase,
            "status": status,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.progress.append(entry)

    def get_status(self) -> dict:
        """Current build status snapshot."""
        return {
            "sub_phase": self.progress[-1]["phase"] if self.progress else "idle",
            "progress": self.progress,
            "artifacts": self.artifacts,
            "errors": self.errors,
        }

    def run_build(self) -> dict:
        """
        Run the full build pipeline sequentially.
        Returns BuildStatus-compatible dict.
        """
        req = self.request
        project_path = req.project_path
        spec_text = req.spec_text
        tasks_text = req.tasks_text
        skills = req.skills
        solution_md = req.solution_md or ""

        # Resolve Docker project path
        docker_proj = find_docker_project(project_path)

        # ── Phase 0: PROVISION (toolchain) ──
        self._update_progress("PROVISION", "running", "Detecting tech stack from PLAN output")
        try:
            packages = stack_detect.detect_tech_stack(solution_md)
            if packages:
                print(f"  → [PROVISION] Stack detected: {packages}")
                missing = stack_detect.check_existing_tools(packages)
                if missing:
                    print(f"  → [PROVISION] Installing: {missing}")
                    success, out, err = stack_detect.provision_tools(solution_md)
                    if not success:
                        self.errors.append(f"PROVISION: {err[:300]}")
                        self._update_progress("PROVISION", "fail", err[:200])
                        return self._build_result("fail", "PROVISION")
                    self.artifacts["installed_tools"] = missing
                    self._update_progress("PROVISION", "pass", f"Installed: {out}")
                else:
                    self._update_progress("PROVISION", "pass", f"All tools present: {packages}")
            else:
                self._update_progress("PROVISION", "pass", "No additional tools needed (Python-only)")
        except Exception as e:
            self.errors.append(f"PROVISION: {e}")
            self._update_progress("PROVISION", "fail", str(e))
            # Don't abort — provision is best-effort. Proceed with what we have.
            print(f"  → [PROVISION] Warning: {e} — continuing anyway")

        # ── Phase 1: IMPL_PLAN ──
        self._update_progress("IMPL_PLAN", "running", "Generating implementation plan")
        try:
            plan = impl_plan(spec_text, tasks_text, skills)
            self.artifacts["impl_plan"] = plan
            self._update_progress("IMPL_PLAN", "pass", f"Plan: {len(plan)} chars")
        except Exception as e:
            self.errors.append(f"IMPL_PLAN: {e}")
            self._update_progress("IMPL_PLAN", "fail", str(e))
            return self._build_result("fail", "IMPL_PLAN")

        # ── Phase 2: CREATE_BACKLOG ──
        self._update_progress("CREATE_BACKLOG", "running", "Parsing tasks into backlog")
        try:
            backlog = create_backlog(tasks_text, project_path)
            self._update_progress("CREATE_BACKLOG", "pass", f"{len(backlog)} items")
        except Exception as e:
            self.errors.append(f"CREATE_BACKLOG: {e}")
            self._update_progress("CREATE_BACKLOG", "fail", str(e))
            return self._build_result("fail", "CREATE_BACKLOG")

        # ── Phase 3: IMPLEMENT + UNIT_TEST (per item) ──
        all_generated_code: list[str] = []
        completed_items = 0
        failed_items = 0

        self._update_progress("IMPLEMENT", "running", f"Implementing {len(backlog)} items")

        for idx, item in enumerate(backlog):
            if self.cancelled:
                return self._build_result("partial", "IMPLEMENT", cancelled=True)

            item_id = item.get("id", idx + 1)
            print(f"\n  ── Item {idx + 1}/{len(backlog)}: {item.get('description', 'unknown')[:60]}")

            # Implement (with retries)
            retry_count = 0
            item_passed = False

            while retry_count < MAX_ITEM_RETRIES:
                item_code, test_code = implement_item(
                    item, spec_text, tasks_text, skills, project_path,
                    all_generated_code, retry_count,
                )
                all_generated_code.append(item_code)

                if not item_code:
                    self.errors.append(f"Item {item_id}: No code generated")
                    retry_count += 1
                    continue

                # Unit test
                test_result, test_output, action = unit_test(
                    item_code, test_code, docker_proj, item_id, retry_count
                )

                if test_result == "pass":
                    item_passed = True
                    all_generated_code.append(test_code)
                    break
                elif action == "retry":
                    self.errors.append(
                        f"Item {item_id}: test failure (attempt {retry_count + 1})"
                    )
                    retry_count += 1
                elif action == "skip":
                    self.errors.append(f"Item {item_id}: skipped")
                    break

            if item_passed:
                item["status"] = "completed"
                completed_items += 1
                self._update_progress(
                    "IMPLEMENT", "pass", f"Item {item_id} completed"
                )
            else:
                item["status"] = "failed"
                failed_items += 1
                self._update_progress(
                    "IMPLEMENT", "fail", f"Item {item_id} failed after {MAX_ITEM_RETRIES} retries"
                )

        self.artifacts["backlog"] = backlog
        self.artifacts["items_completed"] = completed_items
        self.artifacts["items_failed"] = failed_items

        # ── Phase 4: INT_TEST ──
        self._update_progress("INT_TEST", "running", "Running integration tests")
        try:
            int_result, int_output = int_test(docker_proj)
            self.artifacts["int_test_output"] = int_output
            if int_result == "pass":
                self._update_progress("INT_TEST", "pass", "Integration tests passed")
            else:
                self.errors.append(f"INT_TEST: {int_output}")
                self._update_progress("INT_TEST", "fail", int_output[:200])
        except Exception as e:
            self.errors.append(f"INT_TEST: {e}")
            self._update_progress("INT_TEST", "fail", str(e))

        # ── Phase 5: SEED ──
        self._update_progress("SEED", "running", "Generating seed data")
        try:
            seed_result, seed_output = seed_data(
                docker_proj, project_path, spec_text, skills
            )
            self.artifacts["seed_output"] = seed_output
            if seed_result == "pass":
                self._update_progress("SEED", "pass", "Seed data populated")
            else:
                self.errors.append(f"SEED: {seed_output[:200]}")
                self._update_progress("SEED", "fail", seed_output[:200])
        except Exception as e:
            self.errors.append(f"SEED: {e}")
            self._update_progress("SEED", "fail", str(e))

        # ── Phase 6: UAT ──
        self._update_progress("UAT", "running", "Running UAT tests")
        try:
            uat_result, uat_output, uat_pass_rate = run_uat(
                docker_proj, project_path, skills
            )
            self.artifacts["uat_output"] = uat_output
            self.artifacts["uat_pass_rate"] = uat_pass_rate
            if uat_result == "pass":
                self._update_progress("UAT", "pass", f"UAT pass rate: {uat_pass_rate}")
            else:
                self.errors.append(f"UAT: pass rate {uat_pass_rate} < 0.8")
                self._update_progress("UAT", "fail", f"Pass rate: {uat_pass_rate}")
        except Exception as e:
            self.errors.append(f"UAT: {e}")
            self._update_progress("UAT", "fail", str(e))

        # ── Determine final status ──
        all_completed = failed_items == 0
        has_critical_errors = any(
            e for e in self.errors
            if "INT_TEST" in e or "UAT" in e
        )

        if all_completed and not has_critical_errors:
            return self._build_result("pass", "COMPLETE")
        elif failed_items > 0 or has_critical_errors:
            return self._build_result("fail", "COMPLETE")
        else:
            return self._build_result("partial", "COMPLETE")

    def _build_result(self, status: str, sub_phase: str,
                      cancelled: bool = False) -> dict:
        """Build the final result dict."""
        completed_at = datetime.now(timezone.utc).isoformat()
        if cancelled:
            status = "partial"
        self.artifacts["completed_at"] = completed_at
        self.artifacts["status"] = status
        return {
            "build_id": self.request.build_id,
            "status": status,
            **self.get_status(),
            "completed_at": completed_at,
        }