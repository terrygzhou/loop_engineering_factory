"""Pure helpers for the ARCH_REVIEW node (seam split, node-module-seams spec)."""

import json
import re

from graph.achg_scanner import scan_achg_context
from tools.arckit_loader import VALUABLE_ARTIFACT_TYPES


def _parse_json_artifact(raw):
    """Best-effort JSON parse of an artifacts value; None when unusable."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _missing_build_inputs(artifacts: dict) -> list[str]:
    """Advisory missing-build-inputs channel (arckit-tier2-ingestion P0.5).

    Derived from two optional upstream DISCOVER artifacts:

    - ``arckit_open_questions`` -- JSON list of ``{dimension, question}``
      (OAPR D1-D10 TBD rows); each becomes a question line.
    - ``discover_artifact_audit`` -- JSON audit (S6.4); Tier-2 types with no
      *valid* record are listed as "valuable but absent" advisories.

    Returns ``[]`` when nothing is derivable, in which case the caller omits
    the field entirely (byte-identical payload for non-ArcKit runs).
    """
    items: list[str] = []
    oq = _parse_json_artifact(artifacts.get("arckit_open_questions"))
    if isinstance(oq, list):
        for q in oq:
            if isinstance(q, dict) and q.get("question"):
                dim = q.get("dimension") or ""
                prefix = f"[{dim}] " if dim else ""
                items.append(f"OAPR {prefix}{q['question']}")
    audit = _parse_json_artifact(artifacts.get("discover_artifact_audit"))
    if isinstance(audit, dict):
        # W3 arckit-build-context: prefer the DISCOVER-computed
        # 'valuable but absent' list (covers Tier-2 + DATA/TECH/OASEC/
        # OAA-ADM-lite); fall back to recomputing from the record set for
        # pre-W3 audit payloads (or hand-built test audits).
        valuable_absent = audit.get("valuable_absent")
        if not isinstance(valuable_absent, list):
            valid_types = {
                r.get("type")
                for r in audit.get("artefacts", [])
                if isinstance(r, dict) and r.get("schemaValid")
            }
            valuable_absent = [
                t for t in VALUABLE_ARTIFACT_TYPES if t not in valid_types
            ]
        for t in valuable_absent:
            items.append(f"Missing valuable ArcKit artefact: {t}")
    return items


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
