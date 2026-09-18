"""
Shared advisory block for skill-review recommendations (Feature 2).

Reads the persistent ``storage/skill_recommendations.json`` written by the
REFLECT skill review and renders it as an advisory prompt block. Returns ""
when the file is absent or has no recommendations — this is what keeps
DISCOVER/DEFINE prompts byte-identical to the pre-feature behavior.
"""

from __future__ import annotations

from config.loader import config
from feedback.skill_review import load_skill_recommendations


def skill_recommendations_block(max_chars: int = 1500) -> str:
    """Render the advisory block, capped at ``max_chars``.

    Returns "" when there is nothing to render (no file, no recommendations,
    or the review was unavailable). The caller appends the result to a prompt.
    """
    rec = load_skill_recommendations(config.paths.storage_dir)
    if not isinstance(rec, dict) or not rec.get("recommendations"):
        return ""
    lines = [
        f"  - {r.get('skill', '?')}: [{r.get('priority', 'medium')}] {r.get('suggestion', '')}"
        for r in rec["recommendations"]
    ]
    block = (
        "SKILL RECOMMENDATIONS FROM PREVIOUS REFLECT "
        "(advisory - apply where sensible):\n" + "\n".join(lines)
    )
    return block[:max_chars]
