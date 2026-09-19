"""SuperApp UAT runners (seam split S10).

Moved here from build_subgraph_legacy.py. These are self-contained helpers
(no interrupt, no owned stream-writer/audit, stateless signature).
`invoke_skill` and `run_command` are resolved lazily through
graph.nodes.build_subgraph_legacy so test monkeypatch targets keep working.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .build_legacy_nodes import BuildSubState


def _run_superApp_agent(
    state: "BuildSubState",
    base_url: str,
    output_dir: Path,
) -> dict:
    """SuperApp agent mode: delegate to OpenHands agent server via OpenHandsAgentSkill.

    Returns parsed agent_report.json dict, or {"status": "not_found"} if
    agent-server unavailable.
    """
    from skill_cache import skill_cache, _load_json_from_git, SKILLS_GIT_REPO

    cache = skill_cache()
    content = cache.get_skill("openhands-agent-runner")
    if content is None:
        # Try git cache
        try:
            content = _load_json_from_git(SKILLS_GIT_REPO)
        except Exception:
            return {"status": "not_found"}

    writer = state.get("_writer") or (
        lambda _d: None
    )  # use caller's writer if available

    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "progress",
            "detail": "     [UAT] Delegating to OpenHands agent-server...",
            "ts": time.time(),
        }
    )

    # Build the task prompt
    project = state.get("project_path", "")
    prompt = f"""You are executing UAT tests against a locally running application.

## Test Target
- URL: {base_url}
- Project path: {project}

## Instructions
1. Read the test plan from {project}/build/test-plan.md if it exists
2. Execute each UAT test case against the running application
3. Record pass/fail status for each test
4. Write results to {output_dir}/agent_report.json in this schema:
   {{
     "verdict": "pass" | "fail",
     "tests_total": <int>,
     "tests_passed": <int>,
     "results": [
       {{"name": "...", "status": "passed"|"failed"|"error", "detail": "..."}},
       ...
     ]
   }}
"""

    from tools.openhands_agent import OpenHandsAgentSkill

    agent_skill = OpenHandsAgentSkill()
    try:
        result_text = agent_skill.run(prompt)
        # Parse agent report
        report_file = output_dir / "agent_report.json"
        if report_file.exists():
            report = json.loads(report_file.read_text())
            writer(
                {
                    "type": "progress",
                    "phase": "BUILD",
                    "step": "success",
                    "detail": "     ✓ Agent report received",
                    "ts": time.time(),
                }
            )
            return report
        else:
            # Parse from result text
            writer(
                {
                    "type": "progress",
                    "phase": "BUILD",
                    "step": "warning",
                    "detail": "     Agent finished but no agent_report.json — parsing from response",
                    "ts": time.time(),
                }
            )
            # Try to extract JSON from the response
            match = __import__("re").search(
                r"\{.*\}", result_text, __import__("re").DOTALL
            )
            if match:
                return json.loads(match.group())
            return {
                "status": "not_found",
                "verdict": "unknown",
                "raw": result_text[:500],
            }
    except Exception as e:
        writer(
            {
                "type": "error",
                "phase": "BUILD",
                "step": "error",
                "detail": f"     ✗ OpenHands agent error: {e}",
                "ts": time.time(),
            }
        )
        return {"status": "not_found", "error": str(e)}


def _run_superApp_scripted(
    state: "BuildSubState",
    base_url: str,
    output_dir: Path,
) -> list[dict]:
    """SuperApp scripted mode: run test-cases.json directly.

    Returns list of test result dicts from test-cases.json.
    Falls back to LLM UAT if no test-cases.json exists.
    """
    writer = state.get("_writer") or (lambda _d: None)

    cases_file = Path(state["project_path"]) / "build" / "test-cases.json"
    if not cases_file.exists():
        # No test-cases — generate from spec
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "progress",
                "detail": "     [UAT] No test-cases.json — generating from spec...",
                "ts": time.time(),
            }
        )
        cases = _generate_uat_cases(state)
        cases_file.parent.mkdir(parents=True, exist_ok=True)
        cases_file.write_text(json.dumps(cases, indent=2))

    # Read cases and run them
    cases = json.loads(cases_file.read_text())
    results = []
    passed = 0

    for case in cases:
        case_name = case.get("name", "unnamed")
        case_type = case.get("type", "endpoint")
        expected = case.get("expected", {})

        if case_type == "endpoint":
            path = case.get("path", "/")
            method = case.get("method", "GET")

            rc, out, err = _run_command_safe(
                f"curl -s -w '%{{http_code}}' -o /dev/null {method} {base_url}{path}",
                timeout=30,
            )
            http_code = out.strip()
            expected_code = expected.get("status_code", 200)
            ok = http_code == str(expected_code)
            detail = f"HTTP {http_code}"

        elif case_type == "api":
            path = case.get("path", "/")
            method = case.get("method", "GET")

            rc, out, err = _run_command_safe(
                f"curl -s -X {method} {base_url}{path}", timeout=30
            )
            ok = len(out) > 0
            detail = f"Response: {out[:100]}"

        else:
            ok = False
            detail = "Unknown test type"

        status = "passed" if ok else "failed"
        if ok:
            passed += 1
        results.append(
            {"name": case_name, "status": status, "detail": detail, "type": case_type}
        )
        writer(
            {
                "type": "progress",
                "phase": "BUILD",
                "step": "progress" if not ok else "success",
                "detail": f"     [{'✓' if ok else '✗'}] {case_name} — {detail}",
                "ts": time.time(),
            }
        )

    total = len(results)
    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "success" if passed == total else "warning",
            "detail": f"     UAT complete: {passed}/{total} passed",
            "ts": time.time(),
        }
    )

    # Write results
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "test_results.json").write_text(json.dumps(results, indent=2))

    return results


def _generate_uat_cases(state: "BuildSubState") -> list[dict]:
    """Generate UAT test cases from spec via LLM."""
    spec = state.get("spec_text", "")
    tasks = state.get("tasks_text", "")
    skills = state.get("skills", {})

    task = (
        "Generate a UAT test plan from the following spec and tasks.\n"
        "Output ONLY valid JSON — a list of test case objects.\n"
        "Each test case: {\"name\": str, \"type\": \"endpoint\"|\"api\", "
        "\"path\": str, \"method\": str, \"expected\": {\"status_code\": int}}\n"
        f"\n=== SPEC ===\n{spec[:2000]}\n\n=== TASKS ===\n{tasks[:2000]}"
    )

    from tools.llm import invoke_skill as _invoke

    skills_content = skills.get("ui-craftsmanship")
    if skills_content:
        task = (
            f"Apply UI craftsmanship guidelines when evaluating frontend test cases.\n"
            f"Skill:\n{skills_content[:2000]}\n\n" + task
        )

    try:
        result = _invoke(task, llm=None)
        if result:
            data = json.loads(result)
            if isinstance(data, list):
                return data
    except json.JSONDecodeError:
        pass
    except Exception:
        pass

    # Fallback: minimal endpoint test
    return [
        {
            "name": "Homepage loads",
            "type": "endpoint",
            "path": "/",
            "method": "GET",
            "expected": {"status_code": 200},
        }
    ]


def _run_command_safe(cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a shell command and return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def _run_llm_uat_fallback(
    state: "BuildSubState", base_url: str
) -> tuple[str, float]:
    """LLM-based UAT fallback: ask LLM to validate the running app.

    Returns (result_text, pass_rate).
    """
    import re

    spec = state["spec_text"]
    tasks = state["tasks_text"]

    task = (
        f"You are a QA engineer validating a running application.\n"
        f"Base URL: {base_url}\n"
        f"\n=== SPEC ===\n{spec[:1500]}\n"
        f"\n=== TASKS ===\n{tasks[:1500]}\n"
        "Validate the application meets the spec requirements.\n"
        "Output: A brief assessment and a pass rate (0.0-1.0).\n"
        "Last line must be: PASS_RATE=<0.0-1.0>\n"
    )

    from tools.llm import invoke_skill as _invoke

    skills = state.get("skills", {})
    content = (
        skills.get("ui-craftsmanship")
        or skills.get("quality-assurance-engineering")
        or ""
    )

    try:
        result = _invoke(content, task, f"Base URL: {base_url}", llm=None)
    except Exception as e:
        return f"UAT validation failed: {e}", 0.0

    match = re.search(r"PASS_RATE=([0-9.]+)", result)
    pass_rate = float(match.group(1)) if match else 0.0
    return result, pass_rate
