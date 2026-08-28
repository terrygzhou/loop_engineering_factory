"""
ACHG context scanner — EYW-171 §8.1 implementation (EYW-184 safety interlocks).

Scans the ArcKit project tree for Architecture Change Requests (ACHG) and
builds the `achg_context` payload that the ARCH_REVIEW node injects into its
interrupt payload, per the approved ACHG ↔ ARCH_REVIEW interaction spec:

    Obsidian Vault/Eywalink/Architecture/EYW-171-ACHG-ARCH_REVIEW-interaction-spec.md

Contract:
- ACHG path:  projects/{NNN}-{slug}/changes/ARC-{NNN}-ACHG-{NUM}-v{MAJOR}.{MINOR}.md
- Parsed sections: §1 Change Request, §2 Rationale (2.4 Change Description),
  §4 Affected Artefacts, §5 ADM Re-Entry Point, §8 Approval Workflow.
- board_status comes from the §8 "Board Review" row. An undetermined
  (placeholder/absent) board decision is PENDING (EYW-171 §7.4).
- Latest version wins per change ID (v1.1 supersedes v1.0).

The scanner is a pure filesystem + parse module (no LLM, no graph state),
so it is trivially unit-testable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.arckit_loader import (
    ARTIFACT_FILENAME_RE,
    PLACEHOLDER_RE,
    _clean_value,
    find_section,
    parse_frontmatter,
    parse_md_table,
    paragraphs,
    split_sections,
)

__all__ = [
    "ACHG_NOTE",
    "scan_achg_context",
    "parse_achg",
    "has_pending_achg",
    "pending_achg_ids",
]

#: Displayed to the ARCH_REVIEW human reviewer (spec §4.2 + EYW-184 interlock).
ACHG_NOTE = (
    "Pending ACHGs are context for your review. They do NOT affect the approval "
    "routing — approve or reject the PLAN on its merits. Safety interlock (EYW-184): "
    "auto-approval is BLOCKED while any ACHG has PENDING board status; an explicit "
    "human decision is required (EYW-171 §7.4)."
)

BOARD_STATUSES = ("APPROVED", "PENDING", "REJECTED", "CONDITIONAL")


# ── Parsing helpers ─────────────────────────────────────────────────────────


def _find_section(
    sections: List[Tuple[int, str, str]], *patterns: str
) -> Optional[str]:
    """find_section with tolerance for dotted numbering without trailing dot.

    `find_section` only strips '2.'/'2.1.' style numbering; ACHG templates use
    '2.4 Change Description' (no trailing dot), which it misses.
    """
    hit = find_section(sections, *patterns)
    if hit:
        return hit
    for _lvl, text, body in sections:
        norm = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", text.lower()).strip()
        for p in patterns:
            if norm == p or norm.startswith(p):
                return body
    return None


def _norm_status(raw: str) -> str:
    """Normalise a §8 Board Review decision cell to a canonical status.

    Placeholder values (e.g. `[Pending/Approved/Rejected/Conditional]`) and
    anything unrecognised map to PENDING — an undetermined board decision is
    a PENDING board decision (EYW-171 §7.4).
    """
    v = (raw or "").strip().strip("`*").strip()
    if not v:
        return "PENDING"
    # Unfilled template placeholder, e.g. [Pending/Approved/Rejected/Conditional]
    if PLACEHOLDER_RE.match(v):
        return "PENDING"
    up = v.upper()
    if "REJECT" in up:
        return "REJECTED"
    if "CONDITIONAL" in up:
        return "CONDITIONAL"
    if "APPROV" in up:
        return "APPROVED"
    return "PENDING"


def _field_table(section_body: str) -> Dict[str, str]:
    """Parse a two-column `Field | Value` table into {label: value}."""
    rows = parse_md_table(section_body)
    out: Dict[str, str] = {}
    for r in rows:
        cells = list(r.values())
        if len(cells) < 2:
            continue
        key = _clean_value(cells[0])
        val = _clean_value(cells[1])
        if key and val:
            out[key.lower()] = val
    return out


def parse_achg(path: Path) -> Optional[Dict[str, Any]]:
    """Parse one ACHG document into the context entry shape.

    Returns None when the file is unreadable or its docType frontmatter
    (when present) is not ACHG.
    """
    try:
        text = path.read_text()
    except OSError:
        return None

    meta, _body = parse_frontmatter(text)
    if meta and str(meta.get("docType", "")).upper() != "ACHG":
        return None

    m = ARTIFACT_FILENAME_RE.match(path.name)
    change_id = f"ACHG-{m.group('seq')}" if m and m.group("seq") else "ACHG-?"
    doc_id = path.name[:-3] if path.name.endswith(".md") else path.name

    sections = split_sections(_body if _body else text)

    # ── §1 Change Request (Field | Value table) ──
    change_req = _field_table(find_section(sections, "change request") or "")
    doc_control = _field_table(find_section(sections, "document control") or "")

    change_type = change_req.get("change type") or doc_control.get("change type") or ""
    priority = change_req.get("priority") or doc_control.get("priority") or ""
    cid = change_req.get("change id") or doc_control.get("change id") or change_id

    # ── §2 Rationale → 2.4 Change Description → summary ──
    desc_body = _find_section(sections, "change description") or _find_section(
        sections, "problem statement"
    )
    summary_source = desc_body or find_section(sections, "rationale")
    summary = ""
    if summary_source:
        paras = paragraphs(summary_source)
        if paras:
            summary = paras[0][:200]

    # ── §4 Affected Artefacts ──
    affected: List[str] = []
    for r in parse_md_table(find_section(sections, "affected artefacts") or ""):
        name = _clean_value(r.get("Artefact") or next(iter(r.values()), ""))
        if name and name not in affected:
            affected.append(name)

    # ── §5 ADM Re-Entry Point ──
    adm_reentry: List[str] = []
    for r in parse_md_table(find_section(sections, "adm re-entry point") or ""):
        phase = (r.get("ADM Phase") or "").strip()
        reentry = (r.get("Re-Entry") or "").strip()
        if phase and "YES" in reentry.upper():
            adm_reentry.append(phase)

    # ── §8 Approval Workflow → board decision ──
    board_status = "PENDING"
    board_date = ""
    for r in parse_md_table(find_section(sections, "approval workflow") or ""):
        stage = (r.get("Stage") or "").strip().lower()
        if stage == "board review":
            board_status = _norm_status(r.get("Decision") or "")
            board_date = _clean_value(r.get("Date") or "") or ""
            break

    return {
        "change_id": cid,
        "doc_id": doc_id,
        "change_type": change_type,
        "priority": priority,
        "board_status": board_status,
        "board_date": board_date,
        "summary": summary,
        "affected_artifacts": affected,
        "adm_reentry": adm_reentry,
    }


# ── Scanner ─────────────────────────────────────────────────────────────────


def _version_key(path: Path) -> Tuple[int, int]:
    m = ARTIFACT_FILENAME_RE.match(path.name)
    if not m:
        return (0, 0)
    return (int(m.group("major")), int(m.group("minor") or 0))


def _candidate_files(root: Path) -> List[Path]:
    # pathlib.glob requires patterns relative to the search root
    rel_patterns = [
        "projects/*/changes/ARC-*-ACHG-*-v*.md",
        "projects/*/ARC-*-ACHG-*-v*.md",
        "changes/ARC-*-ACHG-*-v*.md",
    ]
    found: List[Path] = []
    for pat in rel_patterns:
        for p in root.glob(pat):
            if p not in found:
                found.append(p)
    return found


def scan_achg_context(root: str, project_id: str = "") -> Dict[str, Any]:
    """Scan `root` (ArcKit project tree) for ACHGs and build the context dict.

    Args:
        root: directory that contains `projects/` (the ArcKit project root,
              i.e. the Loop Factory `context_folder`), or a project directory
              that contains `changes/` directly. Empty/missing → empty context.
        project_id: optional 3-digit ArcKit project ID filter ("007").
                    Empty → all projects.

    Returns:
        {
            "pending_achgs": [entry, ...],   # board_status in {APPROVED, PENDING}
            "rejected_achgs": [entry, ...],  # displayed for context only
            "note": str,
        }

    Each entry: change_id, doc_id, change_type, priority, board_status,
    board_date, summary, affected_artifacts, adm_reentry (spec §4.2).
    """
    empty: Dict[str, Any] = {
        "pending_achgs": [],
        "rejected_achgs": [],
        "note": ACHG_NOTE,
    }
    if not root:
        return empty
    root_p = Path(root).expanduser()
    if not root_p.is_dir():
        return empty

    latest: Dict[Tuple[str, str], Tuple[Path, Dict[str, Any]]] = {}
    for path in _candidate_files(root_p):
        m = ARTIFACT_FILENAME_RE.match(path.name)
        if not m or m.group("type") != "ACHG":
            continue
        if project_id and m.group("pid") != str(project_id).zfill(3):
            continue
        entry = parse_achg(path)
        if entry is None:
            continue
        # Latest version wins per (project, change) — change IDs are scoped
        # per ArcKit project, so dedupe on (pid, change_id).
        key = (m.group("pid"), entry["change_id"])
        prev = latest.get(key)
        if prev is None or _version_key(path) > _version_key(prev[0]):
            latest[key] = (path, entry)

    pending: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for _cid, (_path, entry) in sorted(latest.items()):
        if entry["board_status"] == "REJECTED":
            rejected.append(entry)
        else:
            pending.append(entry)

    return {
        "pending_achgs": pending,
        "rejected_achgs": rejected,
        "note": ACHG_NOTE,
    }


def has_pending_achg(context: Optional[Dict[str, Any]]) -> bool:
    """True when any ACHG in the context still has a PENDING board decision.

    This is the EYW-184 safety interlock predicate: while True, ARCH_REVIEW
    must not auto-approve (EYW-171 §7.4 — no auto-approve while pending).
    """
    if not isinstance(context, dict):
        return False
    return any(
        a.get("board_status") == "PENDING" for a in context.get("pending_achgs", [])
    )


def pending_achg_ids(context: Optional[Dict[str, Any]]) -> List[str]:
    """Change IDs with PENDING board status (for log/audit messages)."""
    if not isinstance(context, dict):
        return []
    return [
        a.get("change_id", "?")
        for a in context.get("pending_achgs", [])
        if a.get("board_status") == "PENDING"
    ]
