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
from config.guardrails import get_arch_review_gate
from langgraph.types import interrupt
from tools.audit_logger import AuditLog
from graph.achg_scanner import scan_achg_context, pending_achg_ids
from service.px_gate import PxGate

import re


def _resolve_achg_context(state: dict) -> dict:
    """ACHG context for this review (EYW-171 §8, EYW-184 interlock).

    Prefers a context already persisted in state (e.g. set by an earlier
    run of this node on replay), otherwise scans the ArcKit tree rooted at
    the workflow's context folder.
    """
    artifacts = state.get("artifacts") or {}
    ctx = artifacts.get("achg_context")
    if isinstance(ctx, dict) and (
        ctx.get("pending_achgs") or ctx.get("rejected_achgs")
    ):
        return ctx
    root = state.get("context_folder") or state.get("project_path") or ""
    return scan_achg_context(root)


def _extract_task_breakdown(plan_text: str) -> list:
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
    """Return a concise summary of the spec (first N characters)."""
    if not spec_text:
        return ""
    truncated = spec_text[:max_chars].strip()
    if len(spec_text) > max_chars:
        truncated += " ..."
    return truncated


def review_node(state: dict) -> dict:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        writer = lambda *a, **kw: None
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

    # ── ACHG context + safety interlock inputs (EYW-171 §8 / EYW-184) ──
    achg_context = _resolve_achg_context(state)
    pending_ids = pending_achg_ids(achg_context)

    # ── Auto-approve mode (headless Docker) ──
    # State override wins (Web UI forces HIL), then config fallback (CLI headless)
    auto_approve = state.get("auto_approve_override", _cfg.workflow.auto_approve)
    if auto_approve and pending_ids:
        # EYW-184 interlock (EYW-171 §7.4): never auto-approve while an ACHG
        # has PENDING board status — force an explicit human decision instead.
        writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "progress", "detail": f"  → Auto-approve BLOCKED — pending ACHG(s): {', '.join(pending_ids)}. Explicit human decision required (EYW-171 §7.4).", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": None, "reason": "auto_approve_blocked_pending_achg", "pending_achgs": pending_ids})
        auto_approve = False
    if auto_approve:
        writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "progress", "detail": "  → Auto-approve mode — skipping review gate", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "reason": "auto_approve"})
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True, "achg_context": achg_context},
        }

    # ── Build interrupt payload ──
    artifacts = state.get("artifacts", {})

    # ── Extract task breakdown and spec summary ──
    plan_text = artifacts.get("plan", "")
    spec_refined_text = artifacts.get("spec_refined", "")
    task_breakdown = _extract_task_breakdown(plan_text)
    spec_summary = _spec_summary(spec_refined_text)

    # ── px_evaluator gate (EYW-184; config-flagged, default off) ──
    gate_cfg = get_arch_review_gate()
    px_gate = PxGate(
        enabled=bool(gate_cfg.get("enabled")),
        min_spec_quality=gate_cfg.get("min_spec_quality", 0.8),
        min_plan_score=gate_cfg.get("min_plan_score", 0.8),
        fail_closed=bool(gate_cfg.get("fail_closed", True)),
    )
    gate_result = px_gate.evaluate_review_gate(spec_refined_text, plan_text)

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

    # ── Reviewer warnings (EYW-171 §4.2 / EYW-184) ──
    warning_lines = []
    if pending_ids:
        warning_lines.append(
            "⚠ PENDING ACHG(S) IN FLIGHT: "
            + ", ".join(pending_ids)
            + " — see the ACHG panel below. These are advisory context;"
            + " they do NOT change the approval routing (EYW-171 §7.3)."
        )
    if px_gate.enabled and not gate_result.passed:
        warning_lines.append(
            "⚠ px_evaluator GATE FAILED: "
            + "; ".join(gate_result.failures)
            + ". Approval requires an explicit override=true in the resume payload."
        )

    interrupt_payload = {
        "type": "review",
        "phase": "ARCH_REVIEW",
        "label": "Architecture & Plan Review",
        "description": (
            ("\n".join(warning_lines) + "\n\n") if warning_lines else ""
        ) + (
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
        # ACHG context (EYW-171 §4.2) — advisory panel, rendered by the HIL UI
        "achg_context": achg_context,
        # px gate result (EYW-184) — shown when the gate is enabled
        "px_gate": gate_result.to_artifact() if px_gate.enabled else None,
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
    # LangGraph wraps resume payload in a list when resumed via Command(resume=[...])
    if isinstance(resume_data, list):
        resume_data = resume_data[0] if resume_data else {}
    if not resume_data:
        resume_data = {}

    approved = resume_data.get("approved", True)
    override = bool(resume_data.get("override", False))
    user_review_comments = resume_data.get("feedback", resume_data.get("user_review_comments", ""))

    # ── EYW-184 px-gate interlock: plain approve below threshold → reject ──
    if approved and px_gate.enabled and not gate_result.passed and not override:
        approved = False
        user_review_comments = (
            "[px-gate] ARCH_REVIEW approval blocked: "
            + "; ".join(gate_result.failures)
            + ". Address these findings in the regenerated PLAN, or re-submit "
            "with override=true and a documented rationale."
        )
        writer({"type": "error", "phase": "ARCH_REVIEW", "step": "error", "detail": f"  ✗ px gate blocked approval ({'; '.join(gate_result.failures)}) — converting to reject", "ts": time.time()})

    if approved:
        writer({"type": "progress", "phase": "ARCH_REVIEW", "step": "success", "detail": "  ✓ ARCH_REVIEW approved — proceeding to BUILD", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": True, "comments": "", "px_gate_override": override, "pending_achgs_at_review": pending_ids})
        audit.log_node_transition("ARCH_REVIEW", "BUILD", "plan approved")
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "BUILD",
            "diagram_status": "approved",
            "artifacts": {"review_approved": True, "achg_context": achg_context, "px_gate_result": gate_result.to_artifact()},
        }
    else:
        # Persist the ARCH_REVIEW loop count so the route_phase livelock guard
        # (loop_count >= 2 → force forward to BUILD) is actually armed —
        # LangGraph only persists node return values (EYW-184 reject-loop).
        loop_counts = dict(artifacts.get("loop_counts", {}))
        loop_counts["ARCH_REVIEW"] = int(loop_counts.get("ARCH_REVIEW", 0)) + 1
        writer({"type": "error", "phase": "ARCH_REVIEW", "step": "error", "detail": f"  ✗ ARCH_REVIEW rejected (loop {loop_counts['ARCH_REVIEW']}/2) — sending back to PLAN with feedback ({len(user_review_comments)} chars)", "ts": time.time()})
        audit.log_node_output("ARCH_REVIEW", {"approved": False, "comments": user_review_comments[:bounds.feedback.max_review_comments_chars], "px_gate_blocked": not gate_result.passed, "pending_achgs_at_review": pending_ids})
        audit.log_node_transition("ARCH_REVIEW", "PLAN", "plan rejected with feedback")
        return {
            "phase": "ARCH_REVIEW",
            "next_phase": "PLAN",
            "diagram_status": "rejected",
            "diagram_feedback": user_review_comments,
            "user_review_comments": user_review_comments,
            "artifacts": {"review_approved": False, "loop_counts": loop_counts, "achg_context": achg_context, "px_gate_result": gate_result.to_artifact()},
        }