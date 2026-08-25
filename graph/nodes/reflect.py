"""
REFLECT node: Meta-agent reflection — analyze cycle, propose config updates,
request human approval, archive feedback.
Skills: meta-agent-reflection (internal) → git-workflow (commit approved diffs)
"""

import json
import time
import yaml
from config.loader import config
from tools.loader import build_skill_registry
from tools.llm import get_llm, invoke_skill
from feedback.aggregator import FeedbackAggregator
from feedback.diff_engine import generate_config_diffs, dry_run_validation
from feedback.chroma_client import get_chroma_client, store_pattern, query_patterns
from tools.stream_writer import safe_stream_writer


def reflect_node(state: dict) -> dict:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """
    REFLECT phase: Analyze the completed cycle, compare against historical patterns,
    generate proposed skill config updates, request human approval, and archive.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer({"type": "progress", "phase": "REFLECT", "step": "started", "detail": "\n=== REFLECT PHASE ===", "ts": time.time()})
    skills = build_skill_registry(config.workflow.skill_registry_path)

    # Step 1: Record cycle data
    writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "  → Recording cycle data...", "ts": time.time()})
    aggregator = FeedbackAggregator(storage_dir=config.paths.storage_dir)
    aggregator.record_cycle(
        cycle_id=state["cycle_id"],
        phase="COMPLETE",
        metrics=state["metrics"].model_dump(),
        artifacts=state.get("artifacts", {}),
        feedback=state.get("feedback", []),
    )
    feedback_entries: list[dict] = [{"action": "cycle_recorded", "cycle_id": state["cycle_id"]}]

    # Step 2: Load guardrails
    writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "  → Loading guardrails...", "ts": time.time()})
    guardrails_path = config.paths.guardrails_path
    try:
        with open(guardrails_path, 'r') as f:
            guardrails = yaml.safe_load(f)
    except Exception as e:
        writer({"type": "progress", "phase": "REFLECT", "step": "warning", "detail": f"  ⚠ Could not load guardrails: {e}", "ts": time.time()})
        guardrails = {}

    # Step 3: Get historical patterns (ChromaDB first, file fallback)
    writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "  → Querying historical patterns...", "ts": time.time()})
    chroma_client = get_chroma_client()
    if chroma_client and state["metrics"].model_dump():
        chroma_results = query_patterns(
            chroma_client,
            query_metrics=state["metrics"].model_dump(),
            top_k=3,
        )
        if chroma_results:
            historical = [{"document": r["document"], "metadata": r["metadata"]} for r in chroma_results]
            writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"     ChromaDB: found {len(historical)} matching patterns", "ts": time.time()})
        else:
            historical = aggregator.get_historical_patterns("review_revisions", 0)
            writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"     Fallback (file): found {len(historical)} historical cycles", "ts": time.time()})
    else:
        historical = aggregator.get_historical_patterns("review_revisions", 0)
        writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"     ChromaDB unavailable — fallback (file): found {len(historical)} historical cycles", "ts": time.time()})

    # Store current cycle pattern in ChromaDB for future reflection
    if chroma_client:
        store_pattern(
            chroma_client,
            pattern_id=state["cycle_id"],
            metrics=state["metrics"].model_dump(),
            feedback=state.get("feedback", []),
            tags=["complete"],
        )

    # Step 4: Generate config diffs via meta-agent
    writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "  → Running meta-agent reflection...", "ts": time.time()})
    cycle_records = aggregator.get_cycle(state["cycle_id"])
    llm = get_llm()

    diffs = generate_config_diffs(cycle_records, guardrails, llm=llm)
    artifacts_delta: dict[str, str] = {"proposed_diffs": json.dumps(diffs, indent=2)}

    changes = diffs.get("changes", [])
    if changes:
        writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"     Proposed {len(changes)} config changes:", "ts": time.time()})
        for c in changes:
            writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"       • {c.get('skill', '?')}: {c.get('change', '?')} [{c.get('risk_level', '?')}]", "ts": time.time()})
    else:
        writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "     No config changes proposed", "ts": time.time()})

    feedback_entries.append({"action": "diff_generated", "change_count": len(changes),
                             "details": diffs.get("overall_assessment", "")})

    # Step 5: Dry-run validation
    if changes and not dry_run_validation(diffs):
        writer({"type": "progress", "phase": "REFLECT", "step": "warning", "detail": "  ⚠ Dry-run validation failed — changes blocked", "ts": time.time()})
        feedback_entries.append({"action": "dry_run_failed", "changes": len(changes)})
        return {
            "phase": "REFLECT",
            "feedback": feedback_entries,
            "next_phase": "END",
            "artifacts": artifacts_delta,
            "error": None,
        }

    # Step 6: Human approval gate — auto-approve or CLI interrupt
    if changes:
        writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "\n  🔍 HUMAN APPROVAL REQUIRED", "ts": time.time()})
        writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"  Proposed {len(changes)} skill config change(s):", "ts": time.time()})
        for i, c in enumerate(changes, 1):
            writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"  {i}. [{c.get('risk_level', 'high')}] {c.get('skill', '?')}: {c.get('change', '?')}", "ts": time.time()})
            writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": f"     Rationale: {c.get('rationale', 'N/A')}", "ts": time.time()})

        # Auto-approve: check config flag to avoid hanging in headless mode
        auto_approve = state.get("auto_approve_override")
        if auto_approve is None:
            try:
                auto_approve = getattr(config.workflow, "auto_approve", False)
            except Exception:
                auto_approve = False

        approved = False
        if auto_approve:
            approved = True
            writer({"type": "progress", "phase": "REFLECT", "step": "auto_approve", "detail": "  → Auto-approving reflect changes", "ts": time.time()})
        else:
            from langgraph.types import interrupt as _interrupt
            try:
                resp = _interrupt({"type": "reflect_approval", "changes": changes})
                approved = isinstance(resp, dict) and resp.get("approved", False)
            except Exception:
                approved = False  # Non-HIL mode: auto-reject

        if approved:
            writer({"type": "progress", "phase": "REFLECT", "step": "success", "detail": "  ✓ Changes approved — applying config diffs...", "ts": time.time()})
            from feedback.diff_engine import apply_yaml_diff
            apply_yaml_diff(guardrails_path, diffs)

            # Commit via git-workflow
            git_skill = skills.get("git-workflow", {})
            if git_skill:
                writer({"type": "progress", "phase": "REFLECT", "step": "progress", "detail": "  → Running git-workflow...", "ts": time.time()})
                result = invoke_skill(git_skill["content"],
                    f"Commit approved config changes for cycle {state['cycle_id']}. "
                    f"Changes: {json.dumps(diffs, indent=2, default=str)}",
                    "", llm=get_llm())
                artifacts_delta["git_commit"] = result
                feedback_entries.append({"action": "git_committed", "details": result[:200]})
            else:
                writer({"type": "progress", "phase": "REFLECT", "step": "warning", "detail": "  ⚠ git-workflow skill not available — manual commit required", "ts": time.time()})
                feedback_entries.append({"action": "git_skipped", "reason": "skill not found"})
            feedback_entries.append({"action": "changes_applied", "count": len(changes)})
        else:
            writer({"type": "error", "phase": "REFLECT", "step": "error", "detail": "  ✗ Changes rejected by human", "ts": time.time()})
            feedback_entries.append({"action": "changes_rejected", "count": len(changes)})

    # Build partial update
    update: dict = {
        "phase": "REFLECT",
        "feedback": feedback_entries,
        "next_phase": "END",
        "config_version": f"{state['cycle_id']}-reflected",
        "artifacts": artifacts_delta,
        "error": None,
    }

    writer({"type": "progress", "phase": "REFLECT", "step": "success", "detail": f"\n  ✓ Reflection complete — cycle {state['cycle_id']} archived", "ts": time.time()})
    return update