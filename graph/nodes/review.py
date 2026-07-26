"""
ARCH_REVIEW node: Human-in-the-loop architecture review gate.

Presents all PLAN artifacts (spec, plan, tasks, analysis, diagrams) for
the human reviewer to approve or reject with comments.

- Approve → routes to BUILD
- Reject → routes back to PLAN with user_review_comments
- Auto-approve → skips interrupt, auto-approves

Uses LangGraph OOTB interrupt() for the HIL pause.
"""
from config.loader import config as _cfg
from config.bounds_loader import bounds
from langgraph.types import interrupt
from tools.audit_logger import AuditLog


def review_node(state: dict) -> dict:
    """
    ARCH_REVIEW phase: Human architecture review gate between PLAN and BUILD.

    Returns partial update dict (LangGraph reducer merges).
    """
    print("\n=== ARCH_REVIEW PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("ARCH_REVIEW", {
        "has_plan": bool(state.get("artifacts", {}).get("plan")),
        "has_diagrams": bool(state.get("artifacts", {}).get("diagrams")),
        "has_pngs": bool(state.get("artifacts", {}).get("diagram_pngs")),
    })

    # ── Auto-approve mode (headless Docker) ──
    # State override wins (Web UI forces HIL), then config fallback (CLI headless)
    auto_approve = state.get("auto_approve_override", _cfg.workflow.auto_approve)
    if auto_approve:
        print("  → Auto-approve mode — skipping review gate")
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "reason": "auto_approve"})
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True},
        }

    # ── Build interrupt payload ──
    artifacts = state.get("artifacts", {})
    diagrams = artifacts.get("diagrams", {})
    diagram_pngs = artifacts.get("diagram_pngs", {})

    # Build diagram display info
    diagram_display = {}
    for dtype, mmd_path in diagrams.items():
        diagram_display[dtype] = {
            "mermaid": mmd_path,
            "png": diagram_pngs.get(dtype, ""),
            "label": dtype.replace("_", " ").title(),
        }

    # Key metrics
    metrics = state.get("metrics")
    arch_uncertainty = getattr(metrics, "arch_uncertainty", 0.0) if metrics else 0.0
    task_count = getattr(metrics, "task_count", 0) if metrics else 0
    diagram_count = getattr(metrics, "diagram_count", 0) if metrics else 0

    interrupt_payload = {
        "type": "review",
        "phase": "ARCH_REVIEW",
        "label": "Architecture & Plan Review",
        "description": (
            "Review the implementation plan, tasks, analysis, and architecture diagrams.\n"
            "Approve to proceed to BUILD, or reject with feedback to send back to PLAN."
        ),
        # Artifacts for display
        "solution_md": artifacts.get("solution_md", ""),
        "spec_refined": artifacts.get("spec_refined", ""),
        "plan": artifacts.get("plan", ""),
        "tasks": artifacts.get("tasks", ""),
        "analysis": artifacts.get("analysis", ""),
        "doubt_resolution": artifacts.get("doubt_resolution", ""),
        "checklist": artifacts.get("checklist", ""),
        "api_contract": artifacts.get("api_contract", ""),
        "interview_notes": artifacts.get("interview_notes", ""),
        # Diagrams
        "diagrams": diagram_display,
        # Metrics summary
        "metrics": {
            "arch_uncertainty": round(arch_uncertainty, 2),
            "task_count": task_count,
            "diagram_count": diagram_count,
        },
    }

    print(f"  → Review payload: {task_count} tasks, {diagram_count} diagrams, uncertainty={arch_uncertainty:.2f}")
    print("  → Pausing for human review...")

    # ── Interrupt for human review ──
    resume_data = interrupt(interrupt_payload)

    # ── Process resume ──
    if not resume_data:
        resume_data = {}

    approved = resume_data.get("approved", True)
    user_review_comments = resume_data.get("feedback", resume_data.get("user_review_comments", ""))

    if approved:
        print("  ✓ ARCH_REVIEW approved — proceeding to BUILD")
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "comments": ""})
        audit.log_node_transition("ARCH_REVIEW", "BUILD", "plan approved")
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True},
        }
    else:
        print(f"  ✗ ARCH_REVIEW rejected — sending back to PLAN with feedback ({len(user_review_comments)} chars)")
        audit.log_node_output("ARCH_REVIEW", {"approved": False, "comments": user_review_comments[:bounds.feedback.max_review_comments_chars]})
        audit.log_node_transition("ARCH_REVIEW", "PLAN", "plan rejected with feedback")
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "PLAN",
            "diagram_status": "rejected",
            "diagram_feedback": user_review_comments,
            "user_review_comments": user_review_comments,
            "artifacts": {"review_approved": False},
        }