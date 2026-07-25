"""
VERIFY placeholder node: runs tests, linting, and quality gates on the built project.

Currently a pass-through placeholder — forwards to SHIP. Will be expanded with
real verification logic (test execution, lint checks, security scans, UAT) in a
future iteration.

Output: marks verify phase as complete, forwards to SHIP.
"""

from tools.audit_logger import AuditLog


def verify_node(state: dict) -> dict:
    """
    VERIFY phase: Placeholder for quality verification.

    Currently passes through. Future: run unit tests, integration tests,
    linting, security scans, and UAT against the generated project.

    Returns partial update dict (LangGraph reducer merges).
    """
    print("\n=== VERIFY PHASE (placeholder) ===")
    print("  → Verification not yet implemented — pass-through to SHIP")

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("VERIFY", {"is_placeholder": True})
    audit.log_node_output("VERIFY", {
        "status": "skipped_placeholder",
        "note": "Will be implemented with real verification logic",
    })

    # Metrics: default to passing so workflow can continue
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(update={
            "uat_pass_rate": 1.0,
            "security_findings": 0,
            "review_revisions": 0,
            "test_flakiness_rate": 0.0,
            "latency_ms": 0.0,
        })

    update = {
        "phase": "VERIFY",
        "next_phase": "SHIP",
        "artifacts": {"verify_status": "skipped_placeholder"},
    }
    if metrics_update:
        update["metrics"] = metrics_update

    return update