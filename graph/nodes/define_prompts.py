"""Pure prompt/context helpers for the DEFINE node (seam split, node-module-seams spec)."""

from config.bounds_loader import bounds
from tools.arckit_context import arckit_advisory_block


def _arckit_advisory_context(state: dict) -> str:
    """W3 arckit-build-context — advisory build-context blocks for the
    parallel source-driven + api-design prompts.

    Delegates to the shared :func:`tools.arckit_context.arckit_advisory_block`
    helper (W3: scoped to the two build-context keys this node consumed);
    returns "" when neither key is set (prompts byte-identical to a
    non-ArcKit run). Advisory only — never a routing input.
    """
    arts = state.get("artifacts") or {}
    cap = bounds.context.arckit_advisory_max_chars
    blocks = []
    for key, header in (
        ("arckit_integration_standards", "INTEGRATION STANDARDS"),
        ("arckit_nfr_constraints", "NFR CONSTRAINTS"),
    ):
        block = arckit_advisory_block({key: arts.get(key)}, max_chars=cap)
        if block:
            blocks.append(
                f"## ArcKit {header} (advisory context — conform to these "
                f"standards where feasible)\n{block}"
            )
    # Feature 2: prior REFLECT skill recommendations (advisory; "" when absent
    # so the helper stays byte-identical to the pre-feature behavior).
    from tools.skill_recommendations import skill_recommendations_block

    rec_block = skill_recommendations_block()
    if rec_block:
        blocks.append(f"## Skill Recommendations (advisory)\n{rec_block}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _build_spec_context(
    state: dict,
    interview_notes: str,
    feedback_context: str,
    user_review_comments: str,
) -> str:
    """Assemble the spec-generation LLM context.

    W5 verify-acceptance-criteria: appends an ``NFR constraints`` block
    carrying the raw ``arckit_nfr_constraints`` value ONLY when that
    artifact is set - non-ArcKit runs build a context identical to
    before the change.
    """
    arts = state.get("artifacts") or {}
    project_context = arts.get("project_context", "")
    context = f"Spec path: {state.get('spec_path', '')}\n"
    if project_context:
        context += f"Existing project context:\n{project_context}\n"
    context += f"Interview notes:\n{interview_notes}\n"
    if feedback_context:
        context += f"\n\n{feedback_context}\n"
    if user_review_comments:
        context += (
            f"\n\n## User Review Comments (from ARCH_REVIEW rejection)\n"
            f"{user_review_comments}\n"
        )
    nfr = arts.get("arckit_nfr_constraints")
    if nfr:
        context += f"\n\n## NFR constraints (ArcKit - advisory)\n{nfr}\n"
    return context
