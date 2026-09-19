"""Pure confidence-estimation helper for the DEFINE node (seam split, node-module-seams spec)."""

from tools.acceptance import parse_acceptance_block


def _estimate_spec_confidence(artifacts: dict) -> float:
    """Derive spec confidence from actual artifact content."""
    score = 0.0
    spec_text = artifacts.get("spec_refined", "")
    api_text = artifacts.get("api_contract", "")
    interview_text = artifacts.get("interview_notes", "")
    if spec_text and len(spec_text) > 100:
        score += 0.3
    if api_text and len(api_text) > 50:
        score += 0.2
    if interview_text and len(interview_text) > 50:
        score += 0.15
    spec_lower = spec_text.lower()
    if any(
        kw in spec_lower
        for kw in ["given", "when", "then", "acceptance", "criteria", "scenario"]
    ):
        score += 0.15
    if any(
        kw in spec_lower
        for kw in ["edge case", "edge-case", "corner case", "empty", "invalid", "error"]
    ):
        score += 0.1
    if any(
        kw in spec_lower
        for kw in ["error handling", "exception", "failure", "rollback", "fallback"]
    ):
        score += 0.1
    # W5: a well-formed machine-checkable acceptance-test block is a strong
    # completeness signal. Absent or invalid block -> no bonus (backward-
    # compatible scoring).
    if parse_acceptance_block(spec_text):
        score += 0.1
    return min(score, 1.0)
