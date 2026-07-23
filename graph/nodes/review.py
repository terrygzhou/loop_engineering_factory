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

    Input (from PLAN):
      - spec_refined, api_contract, plan, tasks, analysis, doubt_resolution, checklist
      - diagrams (Mermaid paths), diagram_pngs (PNG paths)
      - arch_uncertainty, task_count, diagram_count metrics

    Interrupt payload:
      - All plan artifacts for display in CLI/Web UI
      - Diagram PNG paths for visual review
      - Key metrics summary

    On resume:
      - resume_data["approved"] == True  → forward to BUILD
      - resume_data["approved"] == False  → back to PLAN with user_review_comments
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
    auto_approve = _cfg.workflow.auto_approve
    if auto_approve:
        print("  → Auto-approve mode — skipping review gate")
        state["artifacts"]["review_approved"] = True
        state["diagram_status"] = "approved"
        state["phase"] = "ARCH_REVIEW"
        state["next_phase"] = "BUILD"
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "reason": "auto_approve"})
        return state

    # ── Set phase ──
    state["phase"] = "ARCH_REVIEW"

    # ── Build interrupt payload ──
    artifacts = state.get("artifacts", {})
    diagrams = artifacts.get("diagrams", {})
    diagram_pngs = artifacts.get("diagram_pngs", {})

    # Build diagram display info (PNG paths for UI, Mermaid for reference)
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

    state["artifacts"]["review_approved"] = approved

    if approved:
        state["diagram_status"] = "approved"
        state["next_phase"] = "BUILD"
        print("  ✓ ARCH_REVIEW approved — proceeding to BUILD")
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "comments": ""})
        audit.log_node_transition("ARCH_REVIEW", "BUILD", "plan approved")
    else:
        state["diagram_status"] = "rejected"
        state["diagram_feedback"] = user_review_comments
        state["user_review_comments"] = user_review_comments
        state["next_phase"] = "PLAN"
        print(f"  ✗ ARCH_REVIEW rejected — sending back to PLAN with feedback ({len(user_review_comments)} chars)")
        audit.log_node_output("ARCH_REVIEW", {"approved": False, "comments": user_review_comments[:bounds.feedback.max_review_comments_chars]})
        audit.log_node_transition("ARCH_REVIEW", "PLAN", "plan rejected with feedback")

    state["phase"] = "ARCH_REVIEW"
    return state