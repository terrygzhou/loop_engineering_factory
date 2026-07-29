"""
ARCH_REVIEW node: Human-in-the-loop architecture review gate.

Presents all PLAN artifacts (spec, plan, tasks, analysis, diagrams) for
the human reviewer to approve or reject with comments.

- Approve → routes to BUILD
- Reject → routes back to PLAN with user_review_comments
- Auto-approve → skips interrupt, auto-approves

Uses LangGraph OOTB interrupt() for the HIL pause.
"""
from langgraph.config import get_stream_writer

import time
from config.loader import config as _cfg
from config.bounds_loader import bounds
from langgraph.types import interrupt
from tools.audit_logger import AuditLog

import re


def _extract_task_breakdown(plan_text: str) -> list:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """Extract structured task items from plan text.

    Matches:
      - Checklist items: lines starting with '- [' or '- ["'
      - Numbered lists: lines starting with '1.', '2.', etc.
      - Lines containing 'task' or 'milestone' (case-insensitive)
    """
    if not plan_text:
        return []
    tasks: list[str] = []
    seen: set[str] = set()
    for line in plan_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = False
        # Checklist items: - [ ], - [x], - [task], etc.
        if re.match(r"^\s*-\s*\[", stripped):
            match = True
        # Numbered lists: 1. something, 10. something
        elif re.match(r"^\s*\d+\.\s", stripped):
            match = True
        # Lines containing task/milestone keywords
        elif re.search(r"\b(task|milestone)\b", stripped, re.IGNORECASE):
            match = True
        if match:
            # Clean up leading markdown artifacts
            clean = re.sub(r"^\s*[-*]\s*\[[ xX?\]]\s*", "", stripped)
            clean = re.sub(r"^\s*\d+\.\s+", "", clean)
            clean = clean.strip()
            if clean and clean not in seen:
                seen.add(clean)
                tasks.append(clean)
    return tasks


def _spec_summary(spec_text: str, max_chars: int = 500) -> str:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """Return a concise summary of the spec (first N characters)."""
    if not spec_text:
        return ""
    truncated = spec_text[:max_chars].strip()
    if len(spec_text) > max_chars:
        truncated += " ..."
    return truncated


def review_node(state: dict) -> dict:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """
    ARCH_REVIEW phase: Human architecture review gate between PLAN and BUILD.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "started", "detail": "\n=== ARCH_REVIEW PHASE ===", "ts": time.time()})

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
        writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "progress", "detail": "  → Auto-approve mode — skipping review gate", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "reason": "auto_approve"})
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True},
        }

    # ── Build interrupt payload ──
    artifacts = state.get("artifacts", {})

    # ── Extract task breakdown and spec summary ──
    plan_text = artifacts.get("plan", "")
    spec_refined_text = artifacts.get("spec_refined", "")
    task_breakdown = _extract_task_breakdown(plan_text)
    spec_summary = _spec_summary(spec_refined_text)

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
    spec_confidence = getattr(metrics, "spec_confidence", 0.0) if metrics else 0.0
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
        "spec_summary": spec_summary,
        "plan": artifacts.get("plan", ""),
        "tasks": artifacts.get("tasks", ""),
        "task_breakdown": task_breakdown,
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
            "spec_confidence": round(spec_confidence, 2),
            "task_count": task_count,
            "diagram_count": diagram_count,
        },
    }

    writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "progress", "detail": f"  → Review payload: {task_count} tasks, {diagram_count} diagrams, uncertainty={arch_uncertainty:.2f}", "ts": time.time()})
    writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "progress", "detail": "  → Pausing for human review...", "ts": time.time()})

    # ── Interrupt for human review ──
    resume_data = interrupt(interrupt_payload)

    # ── Process resume ──
    if not resume_data:
        resume_data = {}

    approved = resume_data.get("approved", True)
    user_review_comments = resume_data.get("feedback", resume_data.get("user_review_comments", ""))

    if approved:
        writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "success", "detail": "  ✓ ARCH_REVIEW approved — proceeding to BUILD", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "comments": ""})
        audit.log_node_transition("ARCH_REVIEW", "BUILD", "plan approved")
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True},
        }
    else:
        writer({"type": "error", "phase": "ARCH_REVIEW", "step": "error", "detail": f"  ✗ ARCH_REVIEW rejected — sending back to PLAN with feedback ({len(user_review_comments)} chars)", "ts": time.time()})
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