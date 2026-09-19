"""
VERIFY node: runs code quality review on the generated project using the
pre-commit-review skill.

Scans source files, invokes multi-axis review (correctness, readability,
architecture, security, performance), writes report to build/code_review.md,
and updates metrics (review_revisions, uat_pass_rate).

Output: code review report + test results + updated metrics, forwards to SHIP.
"""

import json
import time
from pathlib import Path
from typing import Any


from config.loader import config
from graph.nodes.verify_acceptance import _run_acceptance_tests  # noqa: F401
from graph.nodes.verify_review import (
    _build_review_context,
    _collect_source_files,
    _parse_review_result,
    _write_review_report,
)  # noqa: F401
from graph.nodes.verify_tooling import _find_venv_python, _run_test_infrastructure  # noqa: F401
from graph.ui_bridge import SkillTimer
from tools.acceptance import parse_acceptance_block
from tools.audit_logger import AuditLog
from tools.llm import invoke_skill
from tools.loader import build_skill_registry
from tools.stream_writer import safe_stream_writer

# ── Main node ───────────────────────────────────────────────────────


def verify_node(state: dict) -> dict:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """
    VERIFY phase: Run multi-axis code quality review on the generated project.

    Loads the pre-commit-review skill, collects source files from
    state.project_path, sends them through the LLM for review, writes the
    report to build/code_review.md, and updates metrics.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer(
        {
            "type": "progress",
            "phase": "VERIFY",
            "step": "started",
            "detail": "\n=== VERIFY PHASE ===",
            "ts": time.time(),
        }
    )

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    project_path = state.get("project_path", "")
    spec_text = state.get("artifacts", {}).get("spec_refined", "")

    audit.log_node_input(
        "VERIFY",
        {
            "project_path": project_path,
            "has_spec": bool(spec_text),
        },
    )

    # ── Default findings (no project / skip) ──
    # Must include "issues" — downstream code accesses it unconditionally.
    findings: dict[str, Any] = {
        "issues": [],
        "critical": 0,
        "required": 0,
        "optional": 0,
        "nit_count": 0,
        "total": 0,
        "verdict": "approve",
    }
    review_text = ""
    report_path: str = ""
    files_reviewed = 0

    if project_path and Path(project_path).exists():
        # ── Load skill registry ──
        skills = build_skill_registry(config.workflow.skill_registry_path)
        cr_skill = skills.get("pre-commit-review", {})

        if not cr_skill:
            writer(
                {
                    "type": "progress",
                    "phase": "VERIFY",
                    "step": "warning",
                    "detail": "  ⚠ pre-commit-review skill not found — running basic file scan",
                    "ts": time.time(),
                }
            )
            audit.log_node_output(
                "VERIFY", {"status": "no_skill", "note": "skill not in registry"}
            )
            # Still collect and count files as a basic check
            files = _collect_source_files(project_path)
            findings["total"] = 0
            findings["verdict"] = "approve"
            review_text = f"[Basic scan] Reviewed {len(files)} source files. No automated review available."
            files_reviewed = len(files)
        else:
            # ── Collect source files ──
            writer(
                {
                    "type": "progress",
                    "phase": "VERIFY",
                    "step": "progress",
                    "detail": "  → Collecting source files...",
                    "ts": time.time(),
                }
            )
            files = _collect_source_files(project_path)
            files_reviewed = len(files)

            if not files:
                writer(
                    {
                        "type": "progress",
                        "phase": "VERIFY",
                        "step": "warning",
                        "detail": "  ⚠ No source files found in project — nothing to review",
                        "ts": time.time(),
                    }
                )
                audit.log_node_output(
                    "VERIFY", {"status": "no_files", "files_reviewed": 0}
                )
                review_text = "No source files found in the generated project."
            else:
                writer(
                    {
                        "type": "progress",
                        "phase": "VERIFY",
                        "step": "progress",
                        "detail": f"  → Found {files_reviewed} source files",
                        "ts": time.time(),
                    }
                )

                # ── Build review context ──
                context = _build_review_context(files, spec_text)

                # ── Invoke code-review skill ──
                writer(
                    {
                        "type": "progress",
                        "phase": "VERIFY",
                        "step": "progress",
                        "detail": "  → Running pre-commit-review...",
                        "ts": time.time(),
                    }
                )
                cr_timer = SkillTimer("pre-commit-review")
                review_text = invoke_skill(
                    cr_skill["content"],
                    (
                        "Review this generated project for code quality across five axes: "
                        "correctness, readability, architecture, security, and performance. "
                        "Flag issues as Critical, Required, Optional, or Nit. "
                        "Provide a clear verdict (approve or request changes). "
                        "Be specific with file paths and line references."
                    ),
                    context,
                    llm=None,
                    workflow_id=state.get("project_name", ""),
                    phase="VERIFY",
                )
                cr_timer.complete()

                # Decision 3: a None result is a fatal LLM failure, not content.
                # Route to the ERROR terminal instead of parsing a sentinel string.
                if not review_text:
                    audit.log_node_output(
                        "VERIFY",
                        {"status": "llm_error", "note": "code-review LLM call failed"},
                    )
                    writer(
                        {
                            "type": "progress",
                            "phase": "VERIFY",
                            "step": "error",
                            "detail": "  ✗ Code-review LLM call failed — routing to ERROR terminal",
                            "ts": time.time(),
                        }
                    )
                    return {
                        "phase": "VERIFY",
                        "error": "VERIFY: code-review LLM call failed (fatal)",
                        "next_phase": "ERROR",
                    }

                # ── Parse results ──
                findings = _parse_review_result(review_text)

                # ── Write report ──
                report_path = _write_review_report(project_path, review_text, findings)
                writer(
                    {
                        "type": "progress",
                        "phase": "VERIFY",
                        "step": "progress",
                        "detail": f"  → Review report: {report_path}",
                        "ts": time.time(),
                    }
                )
                audit.log_file_write(
                    "VERIFY", report_path, "markdown", len(review_text)
                )

        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "success",
                "detail": f"  ✓ Review complete: {findings['total']} findings, verdict={findings['verdict']}",
                "ts": time.time(),
            }
        )
        audit.log_node_output(
            "VERIFY",
            {
                "status": "complete",
                "files_reviewed": files_reviewed,
                "findings": findings,
            },
        )
    else:
        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "warning",
                "detail": f"  ⚠ Project path not found: {project_path}",
                "ts": time.time(),
            }
        )
        audit.log_node_output(
            "VERIFY", {"status": "no_project", "project_path": project_path}
        )

    # ── Automated test infrastructure ──
    test_results: dict = {"pytest": None, "ruff": None, "mypy": None}
    if project_path and Path(project_path).exists():
        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "progress",
                "detail": "  → Running automated test infrastructure...",
                "ts": time.time(),
            }
        )
        test_results = _run_test_infrastructure(project_path, writer, audit)

    # ── W5: acceptance tests (spec block -> deterministic gate input) ──
    # Parse the acceptance-test block from the spec; when present (and the
    # project exists) run each check and record per-test results. No block
    # -> gate is identical to today (test_errors only).
    acceptance_results: dict = {}
    acceptance_tests = parse_acceptance_block(spec_text)
    if acceptance_tests and project_path and Path(project_path).exists():
        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "progress",
                "detail": f"  → Running {len(acceptance_tests)} acceptance tests...",
                "ts": time.time(),
            }
        )
        acceptance_results = _run_acceptance_tests(
            acceptance_tests, project_path, writer
        )

    # ── Compute metrics from findings + test results ──
    test_errors = sum(
        1 for v in test_results.values() if v and v.get("failures", 0) > 0
    )
    acceptance_failures = sum(
        1 for r in acceptance_results.values() if r.get("passed") is False
    )
    review_revisions = max(findings["critical"], findings["required"])
    uat_pass_rate = (
        0.0 if findings["critical"] > 0 else (0.5 if findings["required"] > 0 else 1.0)
    )

    # NOTE: The VERIFY retry counter is incremented BELOW, in the partial-update
    # construction block. The old _maybe_increment_loop call was removed because
    # it mutated state["artifacts"] in-place (LangGraph doesn't persist that) and
    # would double-increment alongside the new loop_counts logic.

    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(
            update={
                "review_revisions": review_revisions,
                "uat_pass_rate": uat_pass_rate,
                "security_findings": findings["critical"],
                "test_flakiness_rate": 0.0,
                "latency_ms": 0.0,
            }
        )

    # ── Increment the VERIFY retry counter (Decision 5: nodes persist,
    # edges only read) — required so route_phase can see a fresh counter on
    # the next pass through the graph after a BUILD->VERIFY loop.
    loop_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))
    if has_failures := (
        findings["critical"] > 0 or test_errors > 0 or acceptance_failures > 0
    ):
        loop_counts["VERIFY"] = loop_counts.get("VERIFY", 0) + 1

    # ── Build partial update ──
    # Decision 2: verify_status is the deterministic gate signal consumed by
    # route_phase. "fail" means loop back to BUILD or halt; "pass" means SHIP.
    update: dict = {
        "phase": "VERIFY",
        "next_phase": "SHIP" if not has_failures else None,
        "artifacts": {
            "verify_status": "fail" if has_failures else "pass",
            "code_review_report": report_path or "",
            "files_reviewed": files_reviewed,
            "loop_counts": loop_counts,
        },
    }
    if findings["issues"]:
        update["artifacts"]["review_findings_summary"] = json.dumps(
            {
                "critical": findings["critical"],
                "required": findings["required"],
                "optional": findings["optional"],
                "nit_count": findings.get("nit_count", 0),
                "total": findings["total"],
                "verdict": findings["verdict"],
            }
        )
    if test_results.get("pytest") or test_results.get("ruff"):
        update["artifacts"]["test_results"] = json.dumps(
            {
                "pytest_pass": (test_results.get("pytest") or {}).get("passed", 0),
                "pytest_fail": (test_results.get("pytest") or {}).get("failed", 0),
                "ruff_violations": (test_results.get("ruff") or {}).get("violations", 0),
                "mypy_errors": (test_results.get("mypy") or {}).get("errors", 0),
            }
        )
    if acceptance_results:
        update["artifacts"]["acceptance_results"] = json.dumps(acceptance_results)
    if has_failures:
        update["error"] = (
            f"VERIFY failed: {findings['critical']} critical, "
            f"{test_errors} test suite failures, "
            f"{acceptance_failures} acceptance test failures"
        )
    if metrics_update:
        update["metrics"] = metrics_update

    audit.log_node_transition(
        "VERIFY",
        "SHIP",
        f"review complete: {findings['total']} findings, test_errors={test_errors}",
    )
    return update
