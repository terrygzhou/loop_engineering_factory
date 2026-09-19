"""Diagram concern for the PLAN node (seam split S8).

Pure helpers + diagram-skill resolution moved here so `plan.py` keeps
only the LLM-orchestration core (`_generate_diagram`, `_generate_all_diagrams`,
the `asyncio.gather` LLM-call site, and `_generate_solution_md` assembly).

Re-exported from `graph/nodes/plan.py` so existing test imports
(`from graph.nodes.plan import _extract_use_cases`) keep resolving.
"""

import json
import re
from pathlib import Path

from config.bounds_loader import bounds

# ── Inline skill instructions for diagram generation (fallback) ──
_DIAGRAM_SKILL_INSTRUCTIONS = """You are an architecture diagram generator. Your job is to produce valid Mermaid syntax diagrams.

Rules:
- Output ONLY a Mermaid code block, nothing else.
- Use the appropriate Mermaid diagram type for the request.
- Include all components, relationships, and data flows mentioned in the context.
- Mark assumed components with a note.

Diagram type mappings:
- "component" → use `graph TD` with subgraphs for modules/boundaries
- "sequence" → use `sequenceDiagram` with participant interactions
- "data flow" → use `graph LR` or `graph TD` showing entity relationships and data movement
- "deployment" → use `graph TD` with infrastructure nodes (servers, containers, networks)"""


def _load_local_diagram_skill() -> str | None:
    """Load architecture-diagram-generator skill from local project skills dir."""
    local_path = (
        Path(__file__).resolve().parent.parent.parent
        / "skills"
        / "architecture-diagram-generator"
        / "SKILL.md"
    )
    if local_path.exists():
        return local_path.read_text().split("---", 2)[-1].strip()
    return None


def _get_diagram_skill(skills: dict) -> str:
    """Resolve diagram skill content: registry → local → inline fallback."""
    arch_skill = skills.get("architecture-diagram-generator", {})
    skill_content = arch_skill.get("content", "") if arch_skill else ""
    if not skill_content:
        local = _load_local_diagram_skill()
        if local:
            skill_content = local
    if not skill_content:
        skill_content = _DIAGRAM_SKILL_INSTRUCTIONS
    return skill_content


def _build_diagram_context(state: dict) -> str:
    """Build truncated context string for diagram generation."""
    spec = state.get("artifacts", {}).get("spec_refined", "")
    plan = state.get("artifacts", {}).get("plan", "")
    tasks = state.get("artifacts", {}).get("tasks", "")
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")
    return (
        f"Spec:\n{spec[: bounds.context.diagram_spec_chars]}\n\n"
        f"Plan:\n{plan[: bounds.context.diagram_plan_chars]}\n\n"
        f"Tasks:\n{tasks[: bounds.context.diagram_tasks_chars]}\n\n"
        f"Doubt Resolution:\n{doubt[: bounds.context.diagram_doubt_chars]}"
    )


# ── W4 plan-sequence-view: use-case-driven sequence views ─────────────
_UC_PREFIX_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:user\s+(?:story|flow|journey)|scenario)\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_UC_AS_A_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?as\s+(?:a|an|the)\s+[^.;]{0,80}?\s+I\s+(?:want|need|can)\s+.+?\s*$",
    re.IGNORECASE,
)


def _extract_use_cases(artifacts: dict) -> list[str]:
    """Extract use cases: NFR key first, else user-flow lines, else []."""
    raw = artifacts.get("arckit_nfr_constraints")
    if raw:
        try:
            nfr = json.loads(raw)
        except (TypeError, ValueError):
            nfr = None
        if isinstance(nfr, dict):
            ucs = nfr.get("use_cases")
            if isinstance(ucs, list):
                names = [str(u).strip() for u in ucs if str(u).strip()]
                if names:
                    return names
    text = "\n".join(
        part
        for part in (
            artifacts.get("interview_notes", "") or "",
            artifacts.get("spec_refined", "") or "",
        )
        if part
    )
    found: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = _UC_PREFIX_RE.match(line)
        cand = m.group(1).strip() if m else None
        if cand is None:
            m2 = _UC_AS_A_RE.match(line)
            cand = m2.group(0).strip() if m2 else None
        if cand and cand.lower() not in seen:
            seen.add(cand.lower())
            found.append(cand)
    return found


def _slugify(text: str, limit: int = 40) -> str:
    """URL/identifier-safe slug for diagram keys (sequence_<slug>)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:limit].rstrip("-")
    return slug or "uc"
