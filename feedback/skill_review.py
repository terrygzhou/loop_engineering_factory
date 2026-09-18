"""
Skill performance review for the REFLECT phase.

Pure helpers -- no graph, no LLM client construction. The REFLECT node calls
``run_skill_review``; the helpers here are unit-testable without LangGraph.

Persistent artifact: ``storage/skill_recommendations.json``. The NEXT
DISCOVER/DEFINE cycle reads it via ``load_skill_recommendations`` and
injects it as advisory prompt context.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


def _recommendations_path(storage_dir: str) -> Path:
    return Path(storage_dir).expanduser() / "skill_recommendations.json"


def build_skill_review_context(state: dict) -> Dict[str, Any]:
    """Collect the performance signals REFLECT's skill review needs.

    Reads:
    - ``state["feedback"]`` -- ``skill_progress`` entries (per-skill
      completed/failed counts, as emitted by ``graph/ui_bridge.py``)
    - ``state["artifacts"]["loop_counts"]`` -- BUILD/VERIFY retry counts
    - ``state["artifacts"]["test_errors"]``, ``verify_status``, ``acceptance_results``
    - ``state["artifacts"]["proposed_diffs"]`` -- the config diffs already generated
    """
    feedback = state.get("feedback", [])
    usage: Dict[str, Dict[str, int]] = {}
    for entry in feedback:
        if not isinstance(entry, dict) or entry.get("type") != "skill_progress":
            continue
        name = entry.get("skill", "?")
        slot = usage.setdefault(name, {"completed": 0, "failed": 0})
        event = entry.get("event")
        if event == "completed":
            slot["completed"] += 1
        elif event == "failed":
            slot["failed"] += 1

    artifacts = state.get("artifacts", {})
    metrics = state.get("metrics", {}) if isinstance(state.get("metrics"), dict) \
        else getattr(state.get("metrics"), "model_dump", lambda: {})()

    return {
        "cycle_id": state.get("cycle_id", ""),
        "metrics": metrics,
        "skill_usage": usage,
        "loop_counts": artifacts.get("loop_counts", {}),
        "test_errors": artifacts.get("test_errors", 0),
        "verify_status": artifacts.get("verify_status"),
        "acceptance_results": artifacts.get("acceptance_results"),
        "proposed_diffs": artifacts.get("proposed_diffs"),
    }


def render_skill_review_prompt(context: Dict[str, Any]) -> str:
    """Render the LLM prompt for the skill review.

    The prompt asks the LLM to judge each skill (keep / improve / retire)
    using the collected signals and to emit concrete recommendations for the
    next iteration. Output is JSON (parsed by run_skill_review).
    """
    m = context.get("metrics", {})
    return f"""You are the REFLECT meta-agent reviewing the skills used in development cycle {context.get('cycle_id', '?')}.

SIGNALS:
- Metrics: {json.dumps(m, default=str)}
- Skill usage (per-skill completed/failed counts from skill_progress feedback): {json.dumps(context.get('skill_usage', {}))}
- Loop counters (retries per phase): {json.dumps(context.get('loop_counts', {}))}
- Test errors: {context.get('test_errors', 0)}
- VERIFY status: {context.get('verify_status')}
- Acceptance results: {str(context.get('acceptance_results'))[:800]}
- Proposed config diffs (from this cycle's REFLECT): {str(context.get('proposed_diffs'))[:800]}

TASK:
For EACH skill in the usage map, emit a verdict:
- verdict: "keep" | "improve" | "retire"
- signal: the specific metric(s) driving the verdict
- rationale: one sentence

Then emit 1-3 concrete recommendations for the next iteration. Each:
- skill: which skill
- action: "keep" | "rewrite_section" | "add_substep" | "retire" | "promote" | "demote"
- target: which section/substep (null for keep/retire)
- suggestion: concrete, executable text
- priority: "high" | "medium" | "low"

Return ONLY this JSON shape (no prose):
{{
  "verdicts": [{{"skill": "...", "verdict": "...", "signal": "...", "rationale": "..."}}],
  "recommendations": [{{"skill": "...", "action": "...", "target": "...", "suggestion": "...", "priority": "..."}}]
}}
"""


def store_skill_review(review: dict, storage_dir: str) -> Path:
    """Persist the review to storage/skill_recommendations.json. Overwrites any prior file."""
    p = _recommendations_path(storage_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(review, indent=2, default=str))
    return p


def load_skill_recommendations(storage_dir: str) -> Dict[str, Any]:
    """Read the persistent review. Returns {} when the file is absent or unreadable.

    The returned value is the top-level dict (NOT just the recommendations)
    so callers can also read ``verdicts``.
    """
    p = _recommendations_path(storage_dir)
    if not p.exists():
        return {}
    try:
        loaded = json.loads(p.read_text())
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def run_skill_review(state: dict, llm, storage_dir: str) -> dict:
    """Run the LLM skill review and persist the result.

    Decision 3: if ``llm`` is None or the LLM call fails, returns
    ``{"status": "unavailable", "reason": str, ...}`` and still persists it
    (so the next cycle sees a stable shape). Never raises.
    """
    ctx = build_skill_review_context(state)
    prompt = render_skill_review_prompt(ctx)
    review: Dict[str, Any] = {
        "cycle_id": ctx.get("cycle_id", ""),
        "ts": int(time.time()),
        "verdicts": [],
        "recommendations": [],
        "status": "ok",
    }

    if llm is None:
        review["status"] = "unavailable"
        review["reason"] = "LLM not configured (dry-run)"
        try:
            store_skill_review(review, storage_dir)
        except Exception:
            pass
        return review

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = llm.invoke([
            SystemMessage(content="You are a meta-agent reviewing AI development skills. Output JSON only."),
            HumanMessage(content=prompt),
        ])
        parsed = json.loads(resp.content)
        review["verdicts"] = parsed.get("verdicts", [])
        review["recommendations"] = parsed.get("recommendations", [])
    except Exception as e:
        review["status"] = "unavailable"
        review["reason"] = f"LLM review failed: {e}"

    try:
        store_skill_review(review, storage_dir)
    except Exception:
        pass
    return review
