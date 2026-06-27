"""
REFLECT node: Meta-agent reflection — analyze cycle, propose config updates,
request human approval, archive feedback.
Skills: meta-agent-reflection (internal) → git-workflow (commit approved diffs)
"""
import os
import json
import yaml
from tools.loader import build_skill_registry
from tools.llm import get_llm, invoke_skill
from tools.context_manager import prepare_context_for_llm
from tools.audit_logger import AuditLog
from feedback.aggregator import FeedbackAggregator
from feedback.diff_engine import generate_config_diffs, dry_run_validation
from feedback.chroma_client import get_chroma_client, store_pattern, query_patterns


def reflect_node(state: dict) -> dict:
    """
    REFLECT phase: Analyze the completed cycle, compare against historical patterns,
    generate proposed skill config updates, request human approval, and archive.
    This is the self-improvement loop closure point.
    """
    print("\n=== REFLECT PHASE ===")
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    # Step 1: Record cycle data
    print("  → Recording cycle data...")
    aggregator = FeedbackAggregator(storage_dir=os.getenv("STORAGE_DIR", "./storage"))
    aggregator.record_cycle(
        cycle_id=state["cycle_id"],
        phase="COMPLETE",
        metrics=state["metrics"].model_dump(),
        artifacts=state.get("artifacts", {}),
        feedback=state.get("feedback", []),
    )
    feedback.append({"action": "cycle_recorded", "cycle_id": state["cycle_id"]})

    # Step 2: Load guardrails
    print("  → Loading guardrails...")
    guardrails_path = os.getenv("GUARDRAILS_PATH", "./config/guardrails.yaml")
    try:
        with open(guardrails_path, 'r') as f:
            guardrails = yaml.safe_load(f)
    except Exception as e:
        print(f"  ⚠ Could not load guardrails: {e}")
        guardrails = {}

    # Step 3: Get historical patterns (ChromaDB first, file fallback)
    print("  → Querying historical patterns...")
    chroma_client = get_chroma_client()
    if chroma_client and state["metrics"].model_dump():
        chroma_results = query_patterns(
            chroma_client,
            query_metrics=state["metrics"].model_dump(),
            top_k=3,
        )
        if chroma_results:
            historical = [{"document": r["document"], "metadata": r["metadata"]} for r in chroma_results]
            print(f"     ChromaDB: found {len(historical)} matching patterns")
        else:
            historical = aggregator.get_historical_patterns("review_revisions", 0)
            print(f"     Fallback (file): found {len(historical)} historical cycles")
    else:
        historical = aggregator.get_historical_patterns("review_revisions", 0)
        print(f"     ChromaDB unavailable — fallback (file): found {len(historical)} historical cycles")

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
    print("  → Running meta-agent reflection...")
    cycle_records = aggregator.get_cycle(state["cycle_id"])
    llm = get_llm()

    diffs = generate_config_diffs(cycle_records, guardrails, llm=llm)
    state["artifacts"]["proposed_diffs"] = json.dumps(diffs, indent=2)

    changes = diffs.get("changes", [])
    if changes:
        print(f"     Proposed {len(changes)} config changes:")
        for c in changes:
            print(f"       • {c.get('skill', '?')}: {c.get('change', '?')} [{c.get('risk_level', '?')}]")
    else:
        print("     No config changes proposed")

    feedback.append({"action": "diff_generated", "change_count": len(changes),
                     "details": diffs.get("overall_assessment", "")})

    # Step 5: Dry-run validation
    if changes and not dry_run_validation(diffs):
        print("  ⚠ Dry-run validation failed — changes blocked")
        feedback.append({"action": "dry_run_failed", "changes": len(changes)})
        state["next_phase"] = "END"
        return state

    # Step 6: Human approval gate (CLI)
    if changes:
        print("\n  🔍 HUMAN APPROVAL REQUIRED")
        print(f"  Proposed {len(changes)} skill config change(s):")
        for i, c in enumerate(changes, 1):
            print(f"  {i}. [{c.get('risk_level', 'high')}] {c.get('skill', '?')}: {c.get('change', '?')}")
            print(f"     Rationale: {c.get('rationale', 'N/A')}")

        from api.input_manager import InputManager
        im = InputManager()
        request_id = im.request_input(
            label="Apply config changes?",
            prompt=f"Proposed {len(changes)} change(s). Apply? [y/N]",
            timeout=300
        )
        response = im.wait_for_response(request_id)
        approved = (response and response.strip().lower() in ('y', 'yes'))

        if approved:
            print("  ✓ Changes approved — applying config diffs...")
            from feedback.diff_engine import apply_yaml_diff
            apply_yaml_diff(guardrails_path, diffs)

            # Commit via git-workflow
            git_skill = skills.get("git-workflow", {})
            if git_skill:
                print("  → Running git-workflow...")
                result = invoke_skill(git_skill["content"],
                    f"Commit approved config changes for cycle {state['cycle_id']}. "
                    f"Changes: {json.dumps(diffs, indent=2, default=str)}",
                    "", llm=get_llm())
                state["artifacts"]["git_commit"] = result
                feedback.append({"action": "git_committed", "details": result[:200]})
            else:
                print("  ⚠ git-workflow skill not available — manual commit required")
                feedback.append({"action": "git_skipped", "reason": "skill not found"})
            feedback.append({"action": "changes_applied", "count": len(changes)})
        else:
            print("  ✗ Changes rejected by human")
            feedback.append({"action": "changes_rejected", "count": len(changes)})

    # Step 7: Update config version
    state["config_version"] = f"{state['cycle_id']}-reflected"

    state["phase"] = "REFLECT"
    state["feedback"] = state.get("feedback", []) + feedback
    state["next_phase"] = "END"

    print(f"\n  ✓ Reflection complete — cycle {state['cycle_id']} archived")
    return state
