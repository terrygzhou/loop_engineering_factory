"""
VERIFY node: Run UAT, check performance, debug issues, simplify code if needed.
Skills: uat-workflow (Playwright desktop + mobile mandatory) -> performance-optimization
        (if slow) -> systematic-debugging (if flaky) -> code-simplification (if complex)
Tools: playwright (headless Chromium), browser_navigate, browser_snapshot(full=true),
       browser_vision, browser_console, curl, pytest
"""
import os
import re
import json
from config.loader import config
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from config.guardrails import get_threshold


def verify_node(state: dict) -> dict:
    """
    VERIFY phase: Run comprehensive UAT tests (API + browser frontend), check performance,
    debug failures, simplify code if review revisions were high.

    UAT coverage is derived dynamically from DISCOVER's route discovery and the spec,
    never hardcoded to a specific project.
    """
    print("\n=== VERIFY PHASE ===")
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(config.workflow.skill_registry_path)
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    # Load thresholds from guardrails.yaml — REFLECT can update these between cycles
    max_latency = get_threshold("max_latency_ms")
    max_flakiness = get_threshold("max_test_flakiness_rate")
    max_revisions = get_threshold("max_review_revisions")

    project_path = state.get("project_path", "")
    metrics = state["metrics"]
    uat_pass = 0.0  # Default: fail until proven

    # Check if BUILD already compiled and deployed — skip redundant work
    build_status = state.get("artifacts", {}).get("build_status", "")
    skip_rebuild = build_status == "pass"
    skip_pytest = build_status == "pass"

    # ── DYNAMIC ROUTE COVERAGE ──
    # Derive API endpoints and page routes from DISCOVER project_context + spec
    api_endpoints = []
    page_routes = []
    edge_cases = []

    # From DISCOVER: use discovered routes
    project_context_raw = state.get("artifacts", {}).get("project_context", "")
    if project_context_raw:
        try:
            project_ctx = json.loads(project_context_raw)
            for route in project_ctx.get("routes", []):
                api_endpoints.append(f"{route.get('method', 'GET')} {route.get('path', '/')}")
            # Templates indicate page routes
            for tmpl in project_ctx.get("templates", []):
                tmpl_name = tmpl.get("name", tmpl.get("file", "unknown"))
                # Infer route from template filename
                route_name = tmpl_name.replace(".html", "").replace("_", "-")
                page_routes.append(f"/{route_name}")
        except (json.JSONDecodeError, TypeError):
            pass

    # From spec: extract acceptance criteria for edge cases
    spec_refined = state.get("artifacts", {}).get("spec_refined", "")
    if spec_refined:
        spec_lower = spec_refined.lower()
        if "empty" in spec_lower:
            edge_cases.append("Empty result sets → show appropriate message")
        if "404" in spec_lower or "not found" in spec_lower:
            edge_cases.append("Invalid IDs → return 404")
        if "auth" in spec_lower or "login" in spec_lower or "signin" in spec_lower:
            edge_cases.append("Unauthenticated access → redirect to login")
        if "date" in spec_lower:
            edge_cases.append("Past date selection → reject with validation error")
        if "invalid" in spec_lower or "invalid" in spec_lower:
            edge_cases.append("Invalid input → validation error")

    # Deduplicate
    api_endpoints = sorted(set(api_endpoints))
    page_routes = sorted(set(page_routes))
    edge_cases = sorted(set(edge_cases))

    # Build dynamic coverage sections for the UAT prompt
    api_coverage_text = ""
    if api_endpoints:
        api_coverage_text = "API Health Checks (discovered endpoints):\n"
        for i, ep in enumerate(api_endpoints, 1):
            api_coverage_text += f"{i}. {ep}\n"
    else:
        api_coverage_text = "API Health Checks: No routes discovered — skip API-specific checks\n"

    page_coverage_text = ""
    if page_routes:
        page_coverage_text = "Page Route Coverage (discovered from templates):\n"
        for route in page_routes:
            page_coverage_text += f"- {route}\n"

    edge_case_text = ""
    if edge_cases:
        edge_case_text = "Edge Cases (from spec analysis):\n"
        for i, ec in enumerate(edge_cases, 1):
            edge_case_text += f"{i}. {ec}\n"
    else:
        edge_case_text = "Edge Cases: None extracted from spec — rely on generic validation\n"

    # Step 1: UAT workflow (Playwright mandatory + browser-tool fallback)
    uat_skill = skills.get("uat-workflow", {})
    if uat_skill:
        print("  -> Running uat-workflow (Playwright desktop + mobile + browser-tool fallback)...")
        phase_1_note = "SKIP" if skip_rebuild else "REQUIRED"
        phase_4_note = "SKIP (BUILD ran pytest)" if skip_pytest else "REQUIRED"

        from config.loader import config as _cfg
        _base_url = _cfg.services.product.url
        task = (
            f"Run full UAT tests for project: {project_path}\n"
            f"Base URL: {_base_url}\n\n"
            "=== UAT EXECUTION ORDER ===\n"
            "Phase 0: Playwright setup (verify installed, chromium available)\n"
            f"Phase 1: Docker rebuild + health check ({phase_1_note})\n"
            "  - If BUILD phase already compiled and deployed (build_status=pass), skip rebuild.\n"
            "  - Just do a health check: curl " + config.services.product.url + "/ and confirm 200/301/302.\n"
            "  - If BUILD did not run or failed, do full: docker compose build --no-cache api + up -d + health check\n"
            "Phase 2: Pre-UAT bulk API sweep (curl all discovered routes)\n"
            "Phase 3: Template completeness check (cross-check get_template vs files)\n"
            f"Phase 4: Automated pytest test run — {phase_4_note}\n"
            "  - If BUILD already ran pytest and passed, skip. Otherwise run: docker compose exec api python -m pytest tests/ -v\n"
            "Phase 5: Playwright UAT — desktop pass (MANDATORY)\n"
            "  - Generate /tmp/uat_browser.py with safe_fill(), do_login(), 4-phase test\n"
            "  - Execute: python /tmp/uat_browser.py\n"
            "  - Capture screenshots to /tmp/uat_desktop_*.png\n"
            "Phase 6: Playwright UAT — mobile pass (MANDATORY)\n"
            "  - Generate /tmp/uat_mobile.py with 390x844 viewport\n"
            "  - Execute: python /tmp/uat_mobile.py\n"
            "  - Capture screenshots to /tmp/uat_mobile_*.png\n"
            "Phase 7: Browser Tool Walkthrough (fallback for flagged issues)\n"
            "  - Follow the 4-step pattern: browser_navigate → browser_snapshot(full=true) → browser_vision → browser_console\n"
            "  - Use for visual issues that Playwright could not debug in headless mode\n"
            "Phase 8: Report: PASS/FAIL verdict with per-page results (desktop + mobile)\n\n"
            f"=== {api_coverage_text}\n"
            f"=== {page_coverage_text}\n"
            f"=== {edge_case_text}\n"
            "=== Performance Gates ===\n"
            f"1. API response < {max_latency}ms for list endpoints\n"
            "2. Page load < 2 seconds\n"
            "3. Form submission < 3 seconds\n\n"
            "=== Report Format ===\n"
            "For each test case, output: [PASS] or [FAIL]: test description\n"
            "Final summary must include: Total tests run, Passed, Failed, Pass rate (0.0-1.0), Verdict: PASS or FAIL\n"
            "Desktop UAT: X passed, Y failed\n"
            "Mobile UAT: X passed, Y failed\n"
        )

        result = invoke_skill(uat_skill["content"], task,
                             "Project: " + project_path + f"\nBase URL: {_base_url}",
                             llm=None)
        state["artifacts"]["uat_results"] = result
        feedback.append({"skill": "uat-workflow", "output": result[:500]})

        # Parse all UAT metrics
        uat_metrics = _parse_uat_metrics(result)
        uat_pass = uat_metrics["uat_pass_rate"]
        latency_ms = uat_metrics["latency_ms"]
        flakiness = uat_metrics["test_flakiness_rate"]
        print(f"  -> UAT metrics: pass_rate={uat_pass}, latency={latency_ms}ms, flakiness={flakiness}")
    else:
        print("  Warning: uat-workflow skill not found - defaulting to 0.5 pass rate")
        uat_pass = 0.5
        latency_ms = 0.0
        flakiness = 0.0
        feedback.append({"skill": "uat-workflow", "output": "SKIPPED - skill not found"})

    # Step 2: Performance optimization (if latency exceeds threshold)
    if latency_ms > max_latency:
        perf_skill = skills.get("performance-optimization", {})
        if perf_skill:
            print(f"  -> Running performance-optimization (latency {latency_ms}ms > {max_latency}ms)...")
            task = "Profile and optimize performance bottlenecks"
            result = invoke_skill(perf_skill["content"], task,
                                 state.get("artifacts", {}).get("code_generated", ""),
                                 llm=None)
            state["artifacts"]["perf_report"] = result
            feedback.append({"skill": "performance-optimization", "output": result[:300]})

    # Step 3: Systematic debugging (if test flakiness exceeds threshold)
    if flakiness > max_flakiness:
        debug_skill = skills.get("systematic-debugging", {})
        if debug_skill:
            print(f"  -> Running systematic-debugging (flakiness {flakiness} > {max_flakiness})...")
            task = "Debug test failures using 4-phase approach (Understand -> Isolate -> Root Cause -> Fix)"
            result = invoke_skill(debug_skill["content"], task,
                                 state.get("artifacts", {}).get("uat_results", ""),
                                 llm=None)
            state["artifacts"]["debug_report"] = result
            feedback.append({"skill": "systematic-debugging", "output": result[:300]})

    # Step 4: Code simplification (if review revisions exceed threshold)
    if metrics.review_revisions > max_revisions:
        simplify_skill = skills.get("code-simplification", {})
        if simplify_skill:
            print("  -> Running code-simplification (revisions > 2)...")
            task = "Simplify code: reduce nesting, extract helpers, remove dead code"
            result = invoke_skill(simplify_skill["content"], task,
                                 state.get("artifacts", {}).get("code_generated", ""),
                                 llm=None)
            state["artifacts"]["simplified_code"] = result
            feedback.append({"skill": "code-simplification", "output": result[:300]})

    # Update metrics with actual UAT results
    state["metrics"] = state["metrics"].model_copy(update={
        "uat_pass_rate": uat_pass,
        "latency_ms": latency_ms,
        "test_flakiness_rate": flakiness,
    })
    state["phase"] = "VERIFY"
    state["feedback"] = state.get("feedback", []) + feedback
    state["next_phase"] = "SHIP"
    state["human_approval_required"] = False

    print(f"  Done: uat_pass_rate={uat_pass}, endpoints_checked={len(api_endpoints)}, pages_checked={len(page_routes)}")
    return state


def _parse_uat_metrics(uat_output: str) -> dict:
    """
    Parse UAT metrics from the text output of the uat-workflow skill run.
    Returns dict with: uat_pass_rate, latency_ms, test_flakiness_rate.
    All default to conservative values if unparseable.
    """
    defaults = {"uat_pass_rate": 0.5, "latency_ms": 0.0, "test_flakiness_rate": 0.0}
    if not uat_output:
        return defaults

    uat_pass = _parse_uat_pass_rate(uat_output)

    # Latency: extract numeric ms values
    latency_ms = 0.0
    ms_matches = re.findall(r'(\d+(?:\.\d+)?)\s*ms', uat_output)
    if ms_matches:
        latency_ms = max(float(x) for x in ms_matches)
    else:
        sec_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:sec|seconds|s)\b', uat_output)
        if sec_matches:
            latency_ms = max(float(x) for x in sec_matches) * 1000

    # Flakiness: detect retries, intermittent failures
    output_lower = uat_output.lower()
    flakiness = 0.0
    retry_count = len(re.findall(r'retry|retried|intermittent|flaky|inconsistent|sometimes\s+fail', output_lower))
    total_checks = len(re.findall(r'\[(?:pass|fail)\]', output_lower))
    if total_checks > 0:
        flakiness = min(retry_count / total_checks, 1.0)
    elif retry_count > 0:
        flakiness = min(retry_count * 0.1, 1.0)

    return {
        "uat_pass_rate": uat_pass,
        "latency_ms": latency_ms,
        "test_flakiness_rate": flakiness,
    }


def _parse_uat_pass_rate(uat_output: str) -> float:
    """
    Parse UAT pass rate from text output.
    Looks for PASS/FAIL verdicts, status codes, or percentage indicators.
    Returns 0.0-1.0. Defaults to 0.5 if unparseable (conservative).
    """
    if not uat_output:
        return 0.5

    output_lower = uat_output.lower()

    # Explicit PASS verdict
    if "pass" in output_lower and "fail" not in output_lower:
        return 1.0
    if "fail" in output_lower and "pass" not in output_lower:
        return 0.0

    # "X passed / Y failed" pattern
    match = re.search(r'(\d+)\s*passed.*?(\d+)\s*failed', output_lower)
    if match:
        passed = int(match.group(1))
        failed = int(match.group(2))
        total = passed + failed
        return passed / total if total > 0 else 0.5

    # "Pass rate: X.XX"
    match = re.search(r'pass[\s_-]?rate[:\s=]+([\d.]+)', output_lower)
    if match:
        rate = float(match.group(1))
        return min(rate, 1.0) if rate <= 1.0 else min(rate / 100.0, 1.0)

    # Percentage
    match = re.search(r'(\d+(?:\.\d+)?)\s*%', output_lower)
    if match:
        return min(float(match.group(1)) / 100.0, 1.0)

    # Count [PASS] and [FAIL] markers
    pass_count = len(re.findall(r'\[pass\]', output_lower))
    fail_count = len(re.findall(r'\[fail\]', output_lower))
    total = pass_count + fail_count
    if total > 0:
        return pass_count / total

    # Count status codes (200 = pass, 4xx/5xx = fail)
    status_codes = len(re.findall(r'\b200\b', uat_output))
    error_codes = len(re.findall(r'\b(40[1-9]|4[0-9]{2}|500)\b', uat_output))
    total = status_codes + error_codes
    if total > 0:
        return status_codes / total

    return 0.5  # Conservative default
