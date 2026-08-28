"""
Conditional edge routing for the LangGraph workflow.
Thresholds loaded from guardrails.yaml at runtime so REFLECT can update them.
"""

from langgraph.graph import END
from graph.state import WorkflowState
from config.guardrails import get_threshold

# Export END marker for use in main.py
END_MARKER = END

# Valid phase targets for routing safety (S-005)
VALID_PHASES = {
    "DISCOVER",
    "DEFINE",
    "PLAN",
    "ARCH_REVIEW",
    "BUILD",
    "SEED_DATA",
    "VERIFY",
    "SHIP",
    "REFLECT",
    "ERROR",
}

# Error node for unhandled exceptions — terminal state
ERROR_NODE = "ERROR"

# Per-cycle loop counts stored in state["artifacts"]["loop_counts"] — never global.
# Forward paths for forced progression after max retries (prevents livelock).
_forward_paths = {
    "DISCOVER": "DEFINE",
    "DEFINE": "PLAN",
    "PLAN": "ARCH_REVIEW",
    "ARCH_REVIEW": "BUILD",
    "BUILD": "SEED_DATA",
    "SEED_DATA": "VERIFY",
    # Decision 2: an exhausted VERIFY loop must HALT (ERROR), never SHIP.
    # This is the source of truth for the generic livelock guard at the top
    # of route_phase; the per-phase VERIFY branch below is unreachable when
    # the counter is exhausted because the guard fires first.
    "VERIFY": "ERROR",
}


def _get_loop_count(state: WorkflowState, phase: str) -> int:
    """Read loop counter from state (READ ONLY — edges don't mutate)."""
    counts = state.get("artifacts", {}).get("loop_counts", {})
    return counts.get(phase, 0)


def _maybe_increment_loop(state: dict, phase: str) -> bool:
    """
    Increment loop counter and return True if max retries exceeded.
    MUST be called from NODES (not edges) — LangGraph only persists node return values.
    Usage in nodes:
        loop_exceeded = _maybe_increment_loop(state, "DEFINE")
        if loop_exceeded:
            # force forward, don't loop back
    NOTE: Must REPLACE state["artifacts"] with new dict for LangGraph shallow merge to see it.
    """
    new_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))
    new_counts[phase] = new_counts.get(phase, 0) + 1
    state.setdefault("artifacts", {})["loop_counts"] = new_counts
    return new_counts[phase] >= 2


def route_phase(state: WorkflowState) -> str:
    """
    Route to the next phase based on current phase and metrics.
    Quality gates use loop counters persisted BY NODES (not edges),
    since LangGraph doesn't persist edge-side mutations.
    """
    phase = state["phase"]
    m = state["metrics"]
    error = state.get("error")

    # Load thresholds from guardrails (REFLECT can update between cycles)
    min_spec_conf = get_threshold("min_spec_confidence")
    max_arch_uncert = get_threshold("max_arch_uncertainty")
    max_sec_findings = get_threshold("max_security_findings")
    max_rev_revisions = get_threshold("max_review_revisions")
    min_uat_pass = get_threshold("uat_pass_rate")

    # Loop counters are INCREMENTED BY NODES, not edges.
    # Nodes persist via artifacts.loop_counts which the _dict_merge
    # reducer writes into state. Edges only READ the counter to decide
    # where to route. (Decision 5: the BUILD node now persists its retry
    # counter in artifacts.loop_counts, so no edge-side mutation remains.)
    loop_count = _get_loop_count(state, phase)
    max_loops = 2
    if loop_count >= max_loops:
        return _forward_paths.get(phase, END)

    # If there's an error, route to ERROR terminal for safe landing.
    # Exception: next_phase is an intentional override (e.g., BUILD fail guard → REFLECT).
    if error and not state.get("next_phase"):
        return "ERROR"

    # DISCOVER -> always forward to DEFINE (no quality gate needed)
    if phase == "DISCOVER":
        return "DEFINE"

    # DEFINE -> check spec confidence (node increments counter on failure)
    if phase == "DEFINE":
        if m.spec_confidence < min_spec_conf:
            return "DEFINE"  # Loop back to refine spec
        return "PLAN"

    # PLAN -> check architectural uncertainty
    if phase == "PLAN":
        if m.arch_uncertainty > max_arch_uncert:
            return "PLAN"  # Loop back to resolve doubts
        return "ARCH_REVIEW"

    # ARCH_REVIEW -> human gate: approve → BUILD, reject → back to PLAN
    if phase == "ARCH_REVIEW":
        if state.get("artifacts", {}).get("review_approved"):
            return "BUILD"
        return "PLAN"

    # BUILD -> check security, review, and UAT gates (subgraph handles seed+test+UAT)
    if phase == "BUILD":
        # Respect explicit next_phase override (e.g., REFLECT from build_fail_count guard)
        if state.get("next_phase") and state.get("error"):
            return state["next_phase"] or "REFLECT"
        if m.security_findings > max_sec_findings:
            return "BUILD"  # Fix security issues first
        if m.review_revisions > max_rev_revisions:
            return "BUILD"  # Too many revisions, needs simplification
        if m.uat_pass_rate < min_uat_pass:
            return "BUILD"  # UAT failed, rebuild inside subgraph
        return "SEED_DATA"

    # SEED_DATA -> placeholder, always forward to VERIFY
    if phase == "SEED_DATA":
        return "VERIFY"

    # VERIFY -> real gate (Decision 2). A failing VERIFY must loop back to
    # BUILD or halt — it can never reach SHIP. The deterministic signal is
    # test_errors (real pytest failures) OR critical review findings; LLM
    # review text alone is advisory and never the gate.
    #
    # `verify_status` (not the LLM text) is the source of truth, so the
    # `error` + next_phase==ERROR escape hatch still routes to ERROR terminal.
    if phase == "VERIFY":
        verify_status = state.get("artifacts", {}).get("verify_status")
        test_errors = 0
        test_summary = state.get("artifacts", {}).get("test_results")
        if isinstance(test_summary, str) and test_summary:
            try:
                import json as _json

                test_errors = _json.loads(test_summary).get("pytest_fail", 0) or 0
            except (ValueError, TypeError):
                test_errors = 0
        has_failures = bool(state.get("error")) and state.get("next_phase") is None
        failed = verify_status == "fail" or test_errors > 0 or has_failures
        if failed:
            if loop_count >= max_loops:
                # Exceeded the retry budget — force forward (livelock guard).
                # NOTE: the generic branch above sends a plain terminal error
                # to the ERROR sink; a failed-VERIFY that exhausted its retry
                # budget is the one case where halting beats the ERROR sink,
                # so it returns "ERROR" here explicitly.
                return "ERROR"
            return "BUILD"
        return "SHIP"

    # SHIP -> always reflect
    if phase == "SHIP":
        return "REFLECT"

    # REFLECT -> always END (meta-agent reflection is terminal)
    if phase == "REFLECT":
        return END

    # Safety fallback: unknown phase -> END with warning (S-005)
    import logging

    _log = logging.getLogger(__name__)
    _log.warning(f"Unknown phase '{phase}' in route_phase, falling back to END")
    return END
