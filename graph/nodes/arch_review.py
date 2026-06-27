"""
ARCH_REVIEW node: Pause for user review of all Plan outputs.
Presents specification, solution plan, tasks, and architecture diagrams
for approval/rejection before BUILD phase.
"""
from langgraph.errors import GraphInterrupt


def arch_review_node(state: dict) -> dict:
    """
    Pause for user review of all Plan outputs:
    - Specification (spec_refined)
    - Implementation Plan (plan)
    - Task Breakdown (tasks)
    - Architecture Diagrams (diagrams)

    If approved → BUILD
    If rejected → PLAN (with feedback for revision)
    """
    print("\n=== ARCHITECTURE REVIEW PHASE ===")
    print("  → Pausing for architecture review...")

    state["phase"] = "ARCH_REVIEW"
    state["human_approval_required"] = True

    # Always raise GraphInterrupt so executor's _astream_with_hil catches it and
    # calls on_hil() → _cli_arch_review() to collect real approval/rejection.
    # Auto-approve is handled by the executor, not by short-circuiting here.
    raise GraphInterrupt(
        interrupts=[
            {
                "type": "arch_review",
                "phase": "ARCH_REVIEW",
                "message": "Review specification, plan, tasks, and diagrams before BUILD",
            }
        ]
    )