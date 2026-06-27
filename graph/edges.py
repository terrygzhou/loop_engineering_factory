"""
Conditional edge routing for the LangGraph workflow.
Thresholds loaded from guardrails.yaml at runtime so REFLECT can update them.
"""
from langgraph.graph import END
from graph.state import WorkflowState
from config.guardrails import get_threshold

# Export END marker for use in main.py
END_MARKER = END

# Per-cycle loop counts stored in state["artifacts"]["loop_counts"] — never global.
# Forward paths for forced progression after max retries (prevents livelock).
_forward_paths = {
    "DISCOVER": "DEFINE",
    "DEFINE": "PLAN",
    "PLAN": "ARCH_REVIEW",
    "ARCH_REVIEW": "BUILD",
    "BUILD": "SEED_DATA",
    "SEED_DATA": "VERIFY",
    "VERIFY": "SHIP",
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

    # ARCH_REVIEW: explicit HIL gate — review all Plan outputs before BUILD
    if phase == "ARCH_REVIEW":
        if state.get("arch_review_approved"):
            return "BUILD"
        # Rejected — loop back to DEFINE with feedback
        loop_count = _get_loop_count(state, phase)
        if loop_count >= 2:
            return "BUILD"  # Force forward after max retries
        return "DEFINE"

    # Load thresholds from guardrails (REFLECT can update between cycles)
    min_spec_conf = get_threshold("min_spec_confidence")
    max_arch_uncert = get_threshold("max_arch_uncertainty")
    max_sec_findings = get_threshold("max_security_findings")
    max_rev_revisions = get_threshold("max_review_revisions")
    min_uat_pass = get_threshold("uat_pass_rate")

    # Loop counters are INCREMENTED BY NODES, not edges.
    # Nodes persist via model_copy(update={}) which survives LangGraph state updates.
    # Edges only READ the counter to decide where to route.
    loop_count = _get_loop_count(state, phase)
    max_loops = 2
    if loop_count >= max_loops:
        return _forward_paths.get(phase, END)

    # If there's an error AND no more retries available, end the workflow
    if error and loop_count >= max_loops:
        return END

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

    # BUILD -> check security and review gates
    if phase == "BUILD":
        if m.security_findings > max_sec_findings:
            return "BUILD"  # Fix security issues first
        if m.review_revisions > max_rev_revisions:
            return "BUILD"  # Too many revisions, needs simplification
        return "SEED_DATA"

    # SEED_DATA -> check if seed executed successfully
    if phase == "SEED_DATA":
        if state.get("artifacts", {}).get("seed_errors"):
            return "BUILD"  # Seed failed, rebuild
        return "VERIFY"

    # VERIFY -> check UAT pass rate
    if phase == "VERIFY":
        if m.uat_pass_rate < min_uat_pass:
            return "BUILD"  # UAT failed, rebuild
        return "SHIP"

    # SHIP -> always reflect
    if phase == "SHIP":
        return "REFLECT"

    # Default: END
    return END
