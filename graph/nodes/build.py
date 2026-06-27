"""
BUILD node: Implement backlog items iteratively — one task at a time, with
per-item test validation. Loops until all backlog items pass their tests
or max retries exhausted.

Skills: incremental-implementation → fastapi-jinja2-feature-build → test-driven-development
        → security-and-hardening → requesting-code-review
"""
import os
import re
import json
import subprocess
from pathlib import Path
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.context_manager import prepare_context_for_llm
from tools.audit_logger import AuditLog


def parse_llm_output(text):
    """
    Parse LLM output for file content and shell commands.
    Returns: (files, commands, parse_info)
    """
    files = []
    commands = []
    total_code_blocks = len(re.findall(r'```', text)) // 2

    # --- Parse structured FILE blocks ---
    for m in re.finditer(
        r'===\s*FILE:\s*(.+?)\s*===\s*\n\s*```(\w+)?\s*\n(.*?)```',
        text, re.DOTALL
    ):
        path = m.group(1).strip()
        code = m.group(3).rstrip()
        if code and path:
            files.append((path, code))

    # --- Parse structured COMMAND blocks ---
    for m in re.finditer(
        r'===\s*COMMAND:\s*(.+?)\s*===\s*\n\s*```(\w+)?\s*\n(.*?)```',
        text, re.DOTALL
    ):
        desc = m.group(1).strip()
        cmd = m.group(3).strip()
        if cmd:
            commands.append((desc, cmd))

    # --- Parse bare code blocks (no FILE/COMMAND header) ---
    bare_blocks = 0
    for m in re.finditer(r'```(\w+)?\s*\n(.*?)```', text, re.DOTALL):
        lang = (m.group(1) or '').strip().lower()
        code = m.group(2).rstrip()
        if m.start() in [fm.start() for fm in re.finditer(r'===\s*(?:FILE|COMMAND):', text)]:
            continue
        bare_blocks += 1
        if lang == 'bash' or lang == 'shell':
            commands.append(('auto-detected', code))
        elif lang in ('python', 'html', 'jinja', 'javascript', 'css', 'sql', 'yaml', 'json', 'dockerfile'):
            first_line = code.split('\n')[0].strip()
            if first_line.startswith('#') and 'path:' in first_line.lower():
                inferred = first_line.split('path:')[1].strip()
                if '/' in inferred or '.' in inferred:
                    files.append((inferred, code))
                    continue

    markers_found = len(files) + len(commands)
    parse_info = {
        "markers_found": markers_found,
        "bare_blocks": bare_blocks,
        "total_code_blocks": total_code_blocks,
        "unstructured": bare_blocks > markers_found,
    }
    return files, commands, parse_info


def write_files_to_project(files, project_path):
    """Write parsed files to disk under project_path. Safety: reject paths escaping project."""
    written = []
    proj = os.path.realpath(project_path)
    for path, content in files:
        target = os.path.realpath(os.path.join(project_path, path))
        if not target.startswith(proj + os.sep) and target != proj:
            print(f"  ⚠ Skipping {path}: path escapes project directory")
            continue
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        with open(target, 'w') as f:
            f.write(content)
        written.append(path)
    return written


def run_command(cmd, timeout=180, workdir=None):
    """Run a shell command via subprocess. Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'Command timed out after {timeout}s: {cmd}'
    except Exception as e:
        return -1, '', f'Execution error: {e}'


def find_docker_project(project_path):
    """Find the directory containing docker-compose.yml."""
    for candidate in [project_path, os.path.join(project_path, 'mvp_output')]:
        for pattern in ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml']:
            if os.path.exists(os.path.join(candidate, pattern)):
                return candidate
    return project_path


def build_node(state: dict) -> dict:
    """
    BUILD phase: Implement each backlog item iteratively — generate code + tests,
    validate with pytest, mark complete, repeat until all items pass.

    Input:
      - tasks: Task breakdown from PLAN phase
      - spec_refined: Specification
      - project_folder: Target directory

    Output:
      - $project_folder/build/backlog.md: Feature implementation tracking
      - Generated code, tests, Docker build artifacts
      - Internal loop until all items pass or max retries exhausted
    """
    print("\n=== BUILD PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("BUILD", {
        "has_tasks": bool(state.get("artifacts", {}).get("tasks")),
        "is_retry": bool(state.get("error")),
    })

    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    project_path = state.get("project_path", "")
    project_folder = state.get("project_folder", project_path)
    tasks_text = state.get("artifacts", {}).get("tasks", "")
    spec_text = state.get("artifacts", {}).get("spec_refined", "")
    docker_proj = find_docker_project(project_path)
    build_status_file = os.path.join(docker_proj, '.build_status')

    # ── Create backlog.md ──
    build_dir = Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = build_dir / "backlog.md"

    # Parse tasks into backlog items
    backlog_items = _parse_tasks_to_backlog(tasks_text)
    if not backlog_items:
        backlog_items = [{"id": 1, "description": tasks_text[:200] if tasks_text else "Implement feature", "status": "pending"}]

    # Initialize backlog.md
    backlog_content = _generate_backlog_md(backlog_items, project_folder)
    backlog_path.write_text(backlog_content)
    audit.log_file_write("BUILD", str(backlog_path), "markdown", len(backlog_content))
    print(f"  → backlog.md created: {backlog_path} ({len(backlog_items)} items)")

    # Detect retry (loop-back from VERIFY or SEED_DATA)
    prev_error = state.get("error")
    is_retry = bool(prev_error) or bool(state.get("artifacts", {}).get("build_status"))

    # Clear stale .build_status marker on retry
    if is_retry and os.path.exists(build_status_file):
        print("  → Clearing stale .build_status marker for retry...")
        os.remove(build_status_file)

    # Skip if a previous BUILD passed validation and this is NOT a retry
    if not is_retry:
        try:
            prev = json.loads(Path(build_status_file).read_text())
            if prev.get("status") == "pass":
                print("  → Previous BUILD validation passed. Skipping regeneration.")
                state["phase"] = "BUILD"
                state["next_phase"] = "SEED_DATA"
                return state
        except Exception:
            pass

    # Stop old container to prevent port conflicts on retry
    if is_retry:
        print("  → Stopping existing container for clean retry...")
        _, _, _ = run_command("docker compose down api", timeout=30, workdir=docker_proj)

    # ── GIT ROLLBACK SAFETY ──
    stash_created = False
    if project_path and os.path.isdir(project_path):
        rc, out, err = run_command("git rev-parse --is-inside-work-tree", timeout=5, workdir=project_path)
        if rc == 0 and out.strip() == "true":
            rc2, out2, err2 = run_command("git status --porcelain", timeout=5, workdir=project_path)
            if rc2 == 0 and out2.strip():
                print("  → Creating git stash for rollback safety...")
                rc3, _, err3 = run_command("git stash push -m 'loop-engine: build rollback'", timeout=10, workdir=project_path)
                if rc3 == 0:
                    stash_created = True
                    print("  ✓ Git stash created")
                else:
                    print(f"  ⚠ Git stash failed: {err3[:100]}")

    # ── INTERNAL LOOP: process each backlog item ──
    # Each iteration: generate code+tests for one item → write files → run pytest → mark complete
    MAX_ITEM_RETRIES = 3
    total_sec_findings = 0
    total_revisions = 0
    item_errors = []

    # Aggregate code from all items for security/review passes at the end
    all_generated_code = []

    for idx, item in enumerate(backlog_items):
        if item["status"] == "completed":
            continue

        print(f"\n  ━━ Backlog item {idx + 1}/{len(backlog_items)}: {item['description'][:80]}")
        item_failed = False

        for attempt in range(1, MAX_ITEM_RETRIES + 1):
            print(f"  → Attempt {attempt}/{MAX_ITEM_RETRIES}")

            # ── Generate code + tests for this specific item ──
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

            # Step 1: Incremental implementation
            impl_skill = skills.get("incremental-implementation", {})
            item_code = ""
            if impl_skill:
                print("    → Running incremental-implementation...")
                impl_context = spec_text + "\n\n" + tasks_text
                if item["id"] > 1:
                    # Include previously generated code as context
                    impl_context += "\n\nPreviously generated code:\n" + "\n".join(all_generated_code[-2:])[:2000]

                result = invoke_skill(
                    impl_skill["content"],
                    item_task if attempt == 1 else f"{item_task}\n\nPrevious attempt failed. Fix and retry.",
                    impl_context,
                    llm=None,
                )
                item_code = result
                all_generated_code.append(result)
                feedback.append({"skill": "incremental-implementation", "item": item["id"], "output": result[:200]})

            # Step 2: Generate tests
            tdd_skill = skills.get("test-driven-development", {})
            test_code = ""
            if tdd_skill:
                print("    → Running test-driven-development...")
                tdd_task = (
                    f"Generate tests for backlog item #{item['id']}: {item['description']}\n"
                    f"Follow DAMP, pyramid, and A3 patterns.\n"
                    f"\n=== OUTPUT FORMAT ===\n"
                    "For each test file, output:\n"
                    "=== FILE: tests/test_XXX.py ===\n"
                    "```python\n...complete test file content...\n```"
                )
                test_code = invoke_skill(
                    tdd_skill["content"],
                    tdd_task,
                    item_code,
                    llm=None,
                )
                feedback.append({"skill": "test-driven-development", "item": item["id"], "output": test_code[:200]})

            # ── Write files to disk ──
            combined = item_code + "\n" + test_code
            files, cmds, parse_info = parse_llm_output(combined)
            print(f"    → Parsed {len(files)} files, {len(cmds)} commands")

            if not files:
                print(f"    ✗ No files generated for item {item['id']}")
                item_errors.append(f"Item {item['id']}: No code generated (attempt {attempt})")
                continue

            written = write_files_to_project(files, docker_proj)
            print(f"    ✓ Wrote {len(written)} files")

            # Run pre-build commands
            for desc, cmd in cmds:
                if 'build' in desc.lower() or 'test' in desc.lower():
                    continue
                rc, _, err = run_command(cmd, workdir=docker_proj)
                if rc != 0:
                    print(f"    ⚠ Command '{desc}' failed: {err[:100]}")

            # ── Docker build + test ──
            print("    → Docker compose build...")
            rc, out, err = run_command(
                "docker compose build --no-cache api", timeout=300, workdir=docker_proj
            )
            if rc != 0:
                print(f"    ✗ Docker build failed: {err[:200]}")
                item_errors.append(f"Item {item['id']}: Docker build failed (attempt {attempt})")
                continue

            # Start container
            rc, _, err = run_command(
                "docker compose up -d api", timeout=120, workdir=docker_proj
            )
            if rc != 0:
                print(f"    ✗ Container start failed: {err[:200]}")
                item_errors.append(f"Item {item['id']}: Container start failed")
                continue

            # Health check
            import time
            time.sleep(5)
            _health_url = os.getenv("PRODUCT_URL", "http://localhost:8010") + "/"
            rc, health_out, _ = run_command(
                f"curl -s -o /dev/null -w '%{{http_code}}' {_health_url}",
                timeout=30
            )
            if health_out.strip() not in ('200', '301', '302'):
                print(f"    ✗ Health check failed: HTTP {health_out.strip()}")
                item_errors.append(f"Item {item['id']}: Health check failed")
                continue

            # Run pytest for this item's tests
            print("    → Running pytest...")
            rc, test_out, test_err = run_command(
                "docker compose exec api python -m pytest tests/ -v --tb=short 2>&1",
                timeout=120, workdir=docker_proj
            )
            passed = len(re.findall(r'passed', test_out))
            failed = len(re.findall(r'failed', test_out))

            if rc == 0 and failed == 0:
                print(f"    ✓ pytest passed ({passed} tests) — item {item['id']} complete")
                item["status"] = "completed"
                item_failed = False
                break  # item passed, move to next
            else:
                print(f"    ✗ pytest: {failed} failed, {passed} passed")
                item_errors.append(f"Item {item['id']}: {failed} test failures (attempt {attempt})")

        if item["status"] != "completed":
            print(f"  ⚠ Item {item['id']} exhausted {MAX_ITEM_RETRIES} attempts — will retry in next BUILD cycle")
            item_failed = True

    # ── Security + review on aggregated code (final pass) ──
    aggregated_code = "\n".join(all_generated_code)
    if aggregated_code:
        # Security gate
        sec_skill = skills.get("security-and-hardening", {})
        if sec_skill:
            print("  → Running security-and-hardening (aggregate)...")
            result = invoke_skill(sec_skill["content"],
                                 "Review code for security vulnerabilities using STRIDE model",
                                 aggregated_code, llm=None)
            state["artifacts"]["security_report"] = result
            total_sec_findings = result.lower().count("critical") + result.lower().count("high severity")
            feedback.append({"skill": "security-and-hardening", "output": result[:300]})

        # Code review
        review_skill = skills.get("requesting-code-review", {})
        if review_skill:
            print("  → Running requesting-code-review (aggregate)...")
            result = invoke_skill(review_skill["content"],
                                 "Review code using 5-axis framework",
                                 aggregated_code, llm=None)
            state["artifacts"]["review_report"] = result
            total_revisions = result.lower().count("fix") + result.lower().count("change") + result.lower().count("improve")
            feedback.append({"skill": "requesting-code-review", "output": result[:300]})

    # ── RESULT ──
    all_completed = all(i["status"] == "completed" for i in backlog_items)
    has_errors = bool(item_errors)

    if has_errors and not all_completed:
        error_summary = "\n".join(item_errors[:10])
        print(f"\n  ✗ BUILD: {sum(1 for i in backlog_items if i['status'] != 'completed')} items incomplete")

        # Stop container
        _, _, _ = run_command("docker compose down api", timeout=30, workdir=docker_proj)

        # Restore git stash
        if stash_created:
            rc, _, err = run_command("git stash pop", timeout=10, workdir=project_path)
            if rc == 0:
                print("  ✓ Git stash restored (rollback)")

        state["error"] = error_summary
        state["phase"] = "BUILD"
        state["metrics"] = state["metrics"].model_copy(update={
            "review_revisions": total_revisions,
            "security_findings": total_sec_findings,
        })
        state["feedback"] = state.get("feedback", []) + feedback
        state["next_phase"] = "BUILD"
        return state

    # Success — drop stash
    if stash_created:
        rc, _, err = run_command("git stash drop", timeout=10, workdir=project_path)
        if rc != 0:
            print(f"  ⚠ Git stash drop failed (non-fatal): {err[:100]}")

    # Write marker file
    marker = {
        "status": "pass",
        "items_completed": sum(1 for i in backlog_items if i["status"] == "completed"),
        "total_items": len(backlog_items),
        "security_findings": total_sec_findings,
        "review_revisions": total_revisions,
        "phase": "BUILD",
    }
    Path(build_status_file).write_text(json.dumps(marker))

    # Update backlog.md — reflect final status
    backlog_content = _generate_backlog_md(backlog_items, project_folder)
    backlog_path.write_text(backlog_content)
    audit.log_file_write("BUILD", str(backlog_path), "markdown", len(backlog_content))

    state["metrics"] = state["metrics"].model_copy(update={
        "review_revisions": total_revisions,
        "security_findings": total_sec_findings,
    })
    state["artifacts"]["build_status"] = "pass"
    state["artifacts"]["implementation"] = aggregated_code
    state["phase"] = "BUILD"
    state["feedback"] = state.get("feedback", []) + feedback
    state["next_phase"] = "SEED_DATA"
    state["error"] = None

    print(f"\n  ✓ BUILD passed: {marker['items_completed']}/{marker['total_items']} items, sec_findings={total_sec_findings}, revisions={total_revisions}")
    return state


def _parse_tasks_to_backlog(tasks_text: str) -> list[dict]:
    """Parse task list into backlog items."""
    items = []
    task_num = 0
    for line in tasks_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- [") or re.match(r'^\d+\.', stripped):
            task_num += 1
            desc = re.sub(r'^-\s*\[\s*\]\s*', '', stripped)
            desc = re.sub(r'^\d+\.\s*', '', desc)
            items.append({
                "id": task_num,
                "description": desc.strip(),
                "status": "pending",
            })
    if not items:
        items.append({"id": 1, "description": "Implement feature", "status": "pending"})
    return items


def _generate_backlog_md(items: list[dict], project_folder: str) -> str:
    """Generate backlog.md markdown."""
    lines = ["# Implementation Backlog", ""]
    lines.append(f"Project: {project_folder}")
    lines.append("")
    lines.append("| ID | Description | Status |")
    lines.append("|----|-------------|--------|")
    for item in items:
        lines.append(f"| {item['id']} | {item['description'][:60]} | {item['status']} |")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by Loop Engineering BUILD phase*")
    return "\n".join(lines)
