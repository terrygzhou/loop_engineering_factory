"""
ARCH_REVIEW node: Pause for user review of all Plan outputs.

Uses LangGraph OOTB: interrupt_after=["ARCH_REVIEW"] suspends after this node.
This node calls interrupt() to yield approval data back to the bridge.
"""
from langgraph.types import interrupt


def arch_review_node(state: dict) -> dict:
    """Pause for architecture review. User approves or provides feedback."""
    state["phase"] = "ARCH_REVIEW"
    state["human_approval_required"] = True

    # Call interrupt() — LangGraph yields this via __interrupt__ in the stream.
    # The bridge (workflow_bridge.py) catches the interrupt, shows diagrams to the user,
    # and resumes with arch_review_approved=True/False + feedback.
    user_decision = interrupt({
        "type": "arch_review",
        "phase": "ARCH_REVIEW",
    })

    # Process user's approval decision
    approved = user_decision.get("approved", True) if user_decision else True
    state["arch_review_approved"] = approved
    state["human_approval_required"] = False

    return state
