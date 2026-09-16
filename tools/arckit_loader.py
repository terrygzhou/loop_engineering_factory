"""
ArcKit Artefact Loader — EYW-171 data contract implementation.

Implements the DISCOVER-side ingestion layer specified in
`Obsidian Vault/Eywalink/Architecture/EYW-171-data-contract-arckit-loopfactory-discover.md`:

- §1  consumption order ADMP → REQ → STKE → OAAL → PRIN (first-found wins per field)
- §2  file discovery: projects/{NNN}-{slug}/ARC-{NNN}-{TYPE}-vN.N.md, highest version
- §3  optional YAML frontmatter + Document Control table + section extraction
- §4  auto-population of project_setup + deterministic interview synthesis
- §5  JSON Schema (draft-07 subset) content model per artefact, validated on the
      parsed (not raw) structure
- §6  error taxonomy: NO_ARTIFACTS, MALFORMED_FILENAME, MALFORMED_ARTIFACT,
      SCHEMA_VALIDATION_FAILED, ARTIFACT_SUPERSEDED, ARTIFACT_CONFLICT

The loader is a pure filesystem + parse module (no LLM calls, no graph state),
so it is trivially unit-testable and reusable by other nodes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("arckit_loader")

# ── Contract constants ────────────────────────────────────────────────────────

#: Doc-type codes DISCOVER consumes, in fixed precedence order (§1.1).
DISCOVER_TYPES: tuple[str, ...] = (
    "ADMP",
    "REQ",
    "STKE",
    "OAAL",
    "PRIN",
    "OAPR",
    "OASTR",
    "TRANS",
    "BPCM",
    "GAPA",
    "DATA",
    "TECH",
    "OASEC",
    "OAA-ADM-lite",
)

#: Canonical filename: ARC-{PID}-{TYPE}[-{SEQ}]-v{MAJOR}[.{MINOR}].md (§2).
ARTIFACT_FILENAME_RE = re.compile(
    r"^ARC-(?P<pid>\d{3})-(?P<type>[A-Z]{2,6})(?:-(?P<seq>\d{2,3}))?-v(?P<major>\d+)(?:\.(?P<minor>\d+))?\.md$"
)

VALID_STATUS = {"DRAFT", "APPROVED", "SUPERSEDED"}
PLACEHOLDER_RE = re.compile(
    r"^\[.*\]$"
)  # unfilled template placeholders, e.g. [PROJECT_NAME]

#: Status values DISCOVER will consume; SUPERSEDED is skipped (§3.3).
CONSUMABLE_STATUS = {"DRAFT", "APPROVED"}

# State truncation limits (§3.4.1 ADMP → 500 chars; §3.4.5 PRIN → 1000 chars).
MAX_DESCRIPTION_CHARS = 500
MAX_PRINCIPLES_CHARS = 1000

# Error codes (§6.1)
NO_ARTIFACTS = "NO_ARTIFACTS"
MALFORMED_FILENAME = "MALFORMED_FILENAME"
MALFORMED_ARTIFACT = "MALFORMED_ARTIFACT"
SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
ARTIFACT_SUPERSEDED = "ARTIFACT_SUPERSEDED"
ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
#: **Label**: value — with optional leading bullet/number and optional continuation.
LABEL_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s+\*\*(?P<label>[^*]+?)\*\*\s*:\s*(?P<value>.*)$"
)
TOPLEVEL_LABEL_RE = re.compile(r"^\*\*(?P<label>[^*]+?)\*\*\s*:\s*(?P<value>.*)$")


def _clean_value(value: str | None) -> str | None:
    """Strip markdown code ticks/bold; return None for unfilled `[placeholder]` values."""
    if value is None:
        return None
    v = value.strip().strip("*").strip()
    if v.startswith("`") and v.endswith("`") and len(v) >= 2:
        v = v[1:-1].strip()
    v = v.strip()
    if not v or PLACEHOLDER_RE.match(v):
        return None
    return v


def _is_placeholder(text: str) -> bool:
    return bool(PLACEHOLDER_RE.match(text.strip()))


# ── Markdown structure helpers ────────────────────────────────────────────────


def _norm_heading(text: str) -> str:
    """Normalize a heading for matching: strip numbering ('2.', '2.1'), lowercase, squash space."""
    t = text.strip()
    t = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", t)  # '2.', '2.1', '2.1.'
    t = re.sub(r"^[IVXLC]+\.?\s+", "", t)  # 'II.', 'I'
    return " ".join(t.lower().split())


def split_sections(md: str) -> list[tuple[int, str, str]]:
    """Split markdown into [(level, heading_text, body)] in document order.

    A section's body extends to the next heading of the SAME or SHALLOWER
    level, so subsections (deeper headings) are included in the parent's body
    while also being listed as their own entries. Re-run on a body to descend.
    """
    lines = md.splitlines()
    heads: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    sections: list[tuple[int, str, str]] = []
    for n, (idx, level, text) in enumerate(heads):
        end = len(lines)
        for idx2, level2, _t2 in heads[n + 1 :]:
            if level2 <= level:
                end = idx2
                break
        sections.append((level, text, "\n".join(lines[idx + 1 : end])))
    return sections


def find_section(sections: list[tuple[int, str, str]], *patterns: str) -> str | None:
    """Return the body of the first section whose normalized heading matches.

    Patterns are matched case-insensitively; an exact match anywhere in the
    section list wins over a prefix match (§3.4: case-insensitive H2/H3 match).
    An exact H1 match (the document title, e.g. ADMP's '# Architecture Vision'
    vs its '## 1. Architecture Vision' section) loses to any exact H2+ match.
    """
    exact: str | None = None  # first exact match at level >= 2
    exact_l1: str | None = None  # exact match at H1 — last resort
    prefix_hit: str | None = None
    for level, text, body in sections:
        norm = _norm_heading(text)
        matched_exact = False
        for p in patterns:
            if norm == p:
                matched_exact = True
                if level >= 2 and exact is None:
                    exact = body
                elif level == 1 and exact_l1 is None:
                    exact_l1 = body
        if matched_exact:
            continue
        if prefix_hit is None:
            for p in patterns:
                if norm.startswith(p):
                    prefix_hit = body
                    break
    if exact is not None:
        return exact
    if exact_l1 is not None:
        return exact_l1
    return prefix_hit


def split_blocks(body: str, min_level: int = 3) -> list[tuple[str, str]]:
    """Split a section body into [(heading_text, block_body)] at headings ≥ min_level."""
    lines = body.splitlines()
    heads: list[tuple[int, str, int]] = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) >= min_level:
            heads.append((i, m.group(2).strip(), len(m.group(1))))
    out: list[tuple[str, str]] = []
    for n, (idx, text, _lvl) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.append((text, "\n".join(lines[idx + 1 : end])))
    return out


def _first_table_body(text: str) -> str | None:
    """Return the raw lines of the first markdown table in text, or None."""
    lines = [line for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1])
        ):
            j = i + 2
            rows = [line, lines[i + 1]]
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(lines[j])
                j += 1
            return "\n".join(rows)
    return None


def parse_md_table(table_text: str) -> list[dict[str, str]]:
    """Parse one markdown table into [{header: cell}] row dicts (first table in text)."""
    raw = _first_table_body(table_text)
    if not raw:
        return []
    lines = [line for line in raw.splitlines() if line.strip()]
    header = [
        c.strip().strip("*").strip() for c in lines[0].strip().strip("|").split("|")
    ]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(
            {h: (cells[k] if k < len(cells) else "") for k, h in enumerate(header)}
        )
    return rows


def table_to_rows(
    section_body: str, key_aliases: dict[str, str] | None = None
) -> list[dict[str, str]]:
    """Parse the first table in a section body, mapping headers via key_aliases (lowercase keys)."""
    rows = parse_md_table(section_body)
    if not rows:
        return []
    out = []
    for r in rows:
        nr: dict[str, str] = {}
        for k, v in r.items():
            # stable lowercase keys, word separators kept as underscores
            nk = (key_aliases or {}).get(
                k.lower().replace(" ", "_"),
                re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_"),
            )
            nv = _clean_value(v)
            if nv is not None:
                nr[nk] = nv
        if nr:
            out.append(nr)
    return out


def bullets(text: str) -> list[str]:
    """Extract bullet/numbered list items from text, dropping unfilled placeholders."""
    items: list[str] = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", line)
        if not m:
            continue
        item = m.group(1).strip()
        if item and not _is_placeholder(item):
            items.append(item)
    return items


def paragraphs(text: str) -> list[str]:
    """Non-empty, non-placeholder, non-table/heading paragraphs, whitespace-squashed."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text or ""):
        p = " ".join(para.split())
        if not p or p.startswith(("#", "|", ">", "---")) or _is_placeholder(p):
            continue
        out.append(p)
    return out


def labeled_fields(block_body: str) -> dict[str, Any]:
    """Parse `**Label**: value` fields from a block (BR/FR/UC/persona/SD/Goal blocks).

    - Top-level labels (no bullet prefix) always start a new field.
    - A bulleted label starts a new field UNLESS the previous non-empty line was
      a label with an EMPTY value (i.e. it is a list item under that field).
    Field values: consecutive bullet lines collapse to a list; otherwise joined text.
    """
    fields: dict[str, Any] = {}
    lines = (block_body or "").splitlines()

    def _flush(key: str | None, buf: list[str]) -> None:
        if key is None:
            return
        stripped = [line for line in buf if line.strip() and line.strip() != "---"]
        if not stripped:
            fields.setdefault(key, "")
            return
        all_bullets = all(re.match(r"^\s*(?:[-*]|\d+\.)\s+", line) for line in stripped)
        if all_bullets:
            fields[key] = [
                re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line).strip() for line in stripped
            ]
        else:
            fields[key] = " ".join(" ".join(line.split()) for line in stripped)

    current: str | None = None
    buf: list[str] = []
    prev_line: str | None = None
    for line in lines:
        label_m = None
        is_bulleted = False
        m = LABEL_RE.match(line)
        if m:
            label_m = m
            is_bulleted = True
        else:
            m2 = TOPLEVEL_LABEL_RE.match(line)
            if m2:
                label_m = m2
        if label_m is not None:
            new_field = True
            if is_bulleted:
                # A bulleted label is a list item under the previous field when
                # that field was opened with an empty value ("**Success Metrics**:"
                # followed by "- **Primary Metric**: ...").
                if prev_line is not None:
                    pm = LABEL_RE.match(prev_line) or TOPLEVEL_LABEL_RE.match(prev_line)
                    if pm is not None and not pm.group("value").strip():
                        new_field = False
            if new_field:
                _flush(current, buf)
                current = _snake_key(label_m.group("label").strip())
                val = label_m.group("value").strip()
                buf = [val] if val else []
            else:
                buf.append(line)
            prev_line = line
        else:
            if current is not None:
                buf.append(line)
            prev_line = line if line.strip() else prev_line
    _flush(current, buf)
    return fields


def _snake_key(text: str) -> str:
    """Normalise a **Label** into a stable lowercase snake_case field key.

    'Priority' → 'priority', 'Integration Type' → 'integration_type'.
    Downstream consumers (interview synthesis, stakeholder merge) reference
    these keys case-insensitively, so the normalisation is part of the
    §3.4 extraction contract.
    """
    parts = [p.lower() for p in re.split(r"[\s\-/&]+", text.strip()) if p]
    return "_".join(parts) or "field"


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split optional YAML frontmatter. Returns (meta_or_None, body).

    meta is None (and the whole text returned) when frontmatter is present but
    unparseable — the caller treats that as MALFORMED_ARTIFACT (§6.3 step 2).
    Absent frontmatter is normal: ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, text
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        return None, text
    return meta, text[m.end() :]


# ── Data model (§6.4 audit record, §4.2 synthesis inputs) ──────────────────


@dataclass
class ArtifactRecord:
    """One consumed (or skipped) artefact — mirrors the §6.4 audit entry."""

    type: str
    path: str
    version: str
    status: str
    frontmatter: bool
    schema_valid: bool
    fields_extracted: list[str] = dc_field(default_factory=list)
    errors: list[str] = dc_field(default_factory=list)
    parsed: dict[str, Any] = dc_field(default_factory=dict)

    def audit_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "path": self.path,
            "version": self.version,
            "status": self.status,
            "frontmatter": self.frontmatter,
            "schemaValid": self.schema_valid,
            "fieldsExtracted": self.fields_extracted,
            "errors": self.errors,
        }


@dataclass
class ArcKitContext:
    """Result of scanning an ArcKit project tree for DISCOVER (§1–§4, §6.4)."""

    scanned_root: str
    project_id: str
    project_name: str = ""
    project_description: str = ""
    context_folder_hint: str = ""
    records: list[ArtifactRecord] = dc_field(default_factory=list)
    #: merged interview seeds (stakeholders, success criteria, constraints, ...)
    seeds: dict[str, Any] = dc_field(default_factory=dict)
    #: PRIN principles text, truncated to MAX_PRINCIPLES_CHARS (§3.4.5)
    principles: str = ""
    #: OAAL sprint map rows (§3.4.4) — handoff to PLAN/BUILD (§7)
    sprint_map: list[dict[str, str]] = dc_field(default_factory=list)
    #: OAPR §3 product backlog rows (Tier-2; empty when no valid OAPR)
    product_backlog: list[dict[str, Any]] = dc_field(default_factory=list)
    #: OAPR D1–D10 TBD coverage → open questions (Tier-2; empty on full coverage)
    open_questions: list[dict[str, str]] = dc_field(default_factory=list)
    #: OASTR §4 / TRANS §1 transformation waves (OASTR wins; [] when neither)
    strategy_waves: list[dict[str, Any]] = dc_field(default_factory=list)
    #: BPCM capability hierarchy / value streams / maturity (empty when none)
    capabilities: dict[str, Any] = dc_field(default_factory=dict)
    #: GAPA capability gap rows (empty when no valid GAPA)
    gaps: list[dict[str, Any]] = dc_field(default_factory=list)
    #: DATA entities/domains/classification (empty when no valid DATA)
    data_model: dict[str, Any] = dc_field(default_factory=dict)
    #: TECH integration standards tables (empty when no valid TECH)
    integration_standards: dict[str, Any] = dc_field(default_factory=dict)
    #: OASEC authN/authZ + threat-response controls (empty when no valid OASEC)
    security_controls: dict[str, Any] = dc_field(default_factory=dict)
    #: OAA-ADM-lite vision NFR fields (empty when no valid OAA-ADM-lite)
    nfr_constraints: dict[str, Any] = dc_field(default_factory=dict)
    #: §6.4 audit record
    audit: dict[str, Any] = dc_field(default_factory=dict)
    #: (error_code, detail) pairs
    errors: list[tuple[str, str]] = dc_field(default_factory=list)

    @property
    def has_valid_artifacts(self) -> bool:
        """True when at least one artefact parsed and passed validation."""
        return any(r.schema_valid for r in self.records)


def _err(ctx: ArcKitContext, code: str, detail: str) -> None:
    ctx.errors.append((code, detail))
    logger.warning("%s: %s", code, detail)


# ── Discovery (§2) ──────────────────────────────────────────────────────────

#: Artefact types with their search patterns relative to the scan root.
#: Primary (§2): projects/{NNN}-{slug}/ARC-{NNN}-{TYPE}-v*.md.
#: Fallback: context_folder pointing directly at a project directory.
_TYPE_GLOBS: dict[str, tuple[str, ...]] = {
    "ADMP": ("projects/*/ARC-*-ADMP-v*.md", "ARC-*-ADMP-v*.md"),
    "REQ": ("projects/*/ARC-*-REQ-v*.md", "ARC-*-REQ-v*.md"),
    "STKE": ("projects/*/ARC-*-STKE-v*.md", "ARC-*-STKE-v*.md"),
    "OAAL": ("projects/*/ARC-*-OAAL-v*.md", "ARC-*-OAAL-v*.md"),
    "PRIN": (
        "projects/000-global/ARC-000-PRIN-v*.md",
        "ARC-000-PRIN-v*.md",
        "ARC-*-PRIN-v*.md",
    ),
    "OAPR": ("projects/*/ARC-*-OAPR-v*.md", "ARC-*-OAPR-v*.md"),
    "OASTR": ("projects/*/ARC-*-OASTR-v*.md", "ARC-*-OASTR-v*.md"),
    "TRANS": ("projects/*/ARC-*-TRANS-v*.md", "ARC-*-TRANS-v*.md"),
    "BPCM": ("projects/*/ARC-*-BPCM-v*.md", "ARC-*-BPCM-v*.md"),
    "GAPA": ("projects/*/ARC-*-GAPA-v*.md", "ARC-*-GAPA-v*.md"),
    "DATA": ("projects/*/ARC-*-DATA-v*.md", "ARC-*-DATA-v*.md"),
    "TECH": ("projects/*/ARC-*-TECH-v*.md", "ARC-*-TECH-v*.md"),
    "OASEC": ("projects/*/ARC-*-OASEC-v*.md", "ARC-*-OASEC-v*.md"),
}

#: OAA-ADM-lite has no canonical filename — it is a content-based type: any
#: .md file (e.g. vision.md / DISC.md) carrying a fenced ```yaml block whose
#: top-level `vision:` scope declares `use_cases` is a candidate. Files
#: matching the canonical ARC-NNN-XXXX pattern are excluded so the fallback
#: can never re-claim a Tier-1/Tier-2 artefact.
_LITE_FALLBACK_GLOBS: tuple[str, ...] = (
    "projects/*/*.md",
    "*/*.md",
    "*.md",
)

VISION_FENCE_RE = re.compile(r"```ya?ml[ \t]*\n(.*?)```", re.S)
VISION_SIGNATURE_RE = re.compile(r"^\s*vision\s*:", re.M)


def discover_artifact_files(root: Path, project_id: str = "") -> dict[str, list[Path]]:
    """Glob all DISCOVER artefact types under `root` (§2 discovery algorithm).

    Returns {TYPE: [paths]} — all versioned instances; the caller picks the
    highest version per (project, type).
    """
    out: dict[str, list[Path]] = {}
    for type_code in DISCOVER_TYPES:
        found: list[Path] = []
        pats = (
            _LITE_FALLBACK_GLOBS
            if type_code == "OAA-ADM-lite"
            else _TYPE_GLOBS[type_code]
        )
        for pat in pats:
            for p in root.glob(pat):
                if not p.is_file() or p in found:
                    continue
                m = ARTIFACT_FILENAME_RE.match(p.name)
                if type_code == "OAA-ADM-lite":
                    # Content-based fallback: never claim canonically named
                    # files (Tier-1/2 types own those); require the vision
                    # signature and an .md extension.
                    if m is not None:
                        continue
                    if p.suffix.lower() != ".md":
                        continue
                    if _has_vision_signature(p):
                        found.append(p)
                    continue
                if not m:
                    continue
                if m.group("type") != type_code:
                    continue
                # PRIN is org-global (projects/000-global/), not scoped to a
                # project ID (§2.5) — never filter it by pid.
                if (
                    project_id
                    and type_code != "PRIN"
                    and m.group("pid") != str(project_id).zfill(3)
                ):
                    continue
                found.append(p)
        out[type_code] = found
    return out


def _pick_highest(paths: list[Path]) -> Path | None:
    """Select the highest semantic version (MAJOR.MINOR); `v1` ≡ `v1.0` (§2)."""
    if not paths:
        return None

    def key(p: Path):
        m = ARTIFACT_FILENAME_RE.match(p.name)
        if not m:
            return (0, 0)
        return (int(m.group("major")), int(m.group("minor") or 0))

    return max(paths, key=key)

def _pick_lite(paths: list[Path]) -> Path | None:
    """Select one OAA-ADM-lite candidate. Vision files carry no version in
    the filename: single candidate wins; ties fall back to mtime with an
    ARTIFACT_CONFLICT error (mirrors the canonical conflict rule)."""
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    return max(paths, key=lambda p: p.stat().st_mtime)


# ── Per-artefact extraction (§3.4) ─────────────────────────────────────────


def _doc_control(sections: list[tuple[int, str, str]]) -> dict[str, str]:
    """Parse the Document Control table into {label: value} (lowercased keys)."""
    body = find_section(sections, "document control") or ""
    rows = parse_md_table(body)
    out: dict[str, str] = {}
    for r in rows:
        cells = list(r.values())
        if len(cells) < 2:
            continue
        key = _clean_value(cells[0])
        val = _clean_value(cells[1])
        if key and val:
            out[key.lower()] = val
    return out


def _h1_project_name(text: str, prefix: str) -> str | None:
    """Extract the project name from an H1 of the form '# {prefix} {NAME}'."""
    m = re.search(
        r"^#\s+" + re.escape(prefix) + r"\s+(?P<name>.+)$", text, re.MULTILINE
    )
    if m:
        name = _clean_value(m.group("name"))
        if name and not _is_placeholder(name):
            return name
    return None


def _first_mermaid(body: str) -> str:
    m = re.search(r"```mermaid\s*(.*?)```", body or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def _oaa_header(
    sections: list[tuple[int, str, str]], body: str
) -> dict[str, str]:
    """OAA-style document header (OAAL/OAPR): 2-column header table near the
    top of the document, with a `**Label:** value` line fallback (OAPR
    blockquote headers). Keys are lowercase."""
    header_body = find_section(sections, "template") or body[:2000]
    out: dict[str, str] = {}
    for r in parse_md_table(header_body):
        cells = list(r.values())
        if len(cells) >= 2:
            key = _clean_value(cells[0])
            val = _clean_value(cells[1])
            if key and val:
                out[key.lower()] = val
    if "document_id" not in out or "status" not in out:
        # OAPR blockquote header: `**Document ID:** X | **Status:** DRAFT | ...`
        head = "\n".join(
            line.lstrip(">").lstrip() for line in body.splitlines()[:40]
        )
        for m in re.finditer(r"\*\*([A-Za-z][A-Za-z /&-]*?):\*\*\s*([^\n|]+)", head):
            key = _clean_value(m.group(1).strip().lower())
            val = _clean_value(m.group(2).strip())
            if key and val and key not in out:
                out[key] = val
    return out


def _extract_admp(body: str) -> dict[str, Any]:
    """§3.4.1 — ADMP → project_setup + interview seed."""
    sections = split_sections(body)
    dc = _doc_control(sections)

    vision_body = find_section(sections, "architecture vision") or ""
    vision_paras = paragraphs(vision_body)

    scope = find_section(sections, "scope") or ""
    in_scope = (
        bullets(find_section(split_sections(scope), "in scope") or "") if scope else []
    )
    out_scope = (
        bullets(find_section(split_sections(scope), "out of scope") or "")
        if scope
        else []
    )

    success_rows = table_to_rows(find_section(sections, "success criteria") or "")
    stakeholder_rows = table_to_rows(find_section(sections, "stakeholder map") or "")
    landscape = _first_mermaid(find_section(sections, "architecture landscape") or "")

    def _sub_bullets(parent: str, *subs: str) -> list[str]:
        parent_body = find_section(sections, parent) or ""
        items: list[str] = []
        for sub in subs:
            items.extend(bullets(find_section(split_sections(parent_body), sub) or ""))
        return items

    return {
        "document_id": dc.get("document id", ""),
        "project": dc.get("project", ""),
        "status": dc.get("status", ""),
        "owner": dc.get("owner", ""),
        "architecture_vision": vision_paras[0][:MAX_DESCRIPTION_CHARS]
        if vision_paras
        else "",
        "scope_in": in_scope,
        "scope_out": out_scope,
        "drivers": _sub_bullets(
            "drivers", "strategic", "operational", "compliance", "technology"
        ),
        "constraints": _sub_bullets(
            "constraints", "budget", "timeline", "regulatory", "technical"
        ),
        "resources": _sub_bullets("resources", "team", "budget", "tools"),
        "success_criteria": success_rows,
        "stakeholders": stakeholder_rows,
        "mermaid": landscape,
    }


def _blocks_by_heading(
    body: str, pattern: str, min_level: int = 3
) -> list[dict[str, Any]]:
    """Extract `### {pattern}` blocks and parse their **Label**: value fields.

    Blocks without any parseable fields are dropped so a near-empty parent
    heading cannot shadow its child blocks (e.g. 'Data Entities' wrapping
    'Entity: X' blocks).
    """
    out: list[dict[str, Any]] = []
    for heading, block_body in split_blocks(body, min_level=min_level):
        if re.search(pattern, heading, re.IGNORECASE):
            fields = labeled_fields(block_body)
            if fields:
                # The requirement id lives in the heading ('BR-001: …'), not in
                # the block body — capture it as a first-class field.
                m = re.match(r"\s*([A-Z]{2,}(?:-[A-Z]+)*-\d+)", heading)
                if m:
                    fields["id"] = m.group(1)
                else:
                    fields["id"] = re.sub(r"^[A-Za-z]+:\s*", "", heading).strip()
                out.append(fields)
    return out


def _extract_req(body: str) -> dict[str, Any]:
    """§3.4.2 — REQ → authoritative interview content."""
    sections = split_sections(body)
    dc = _doc_control(sections)

    h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    h1_name = _clean_value(h1.group(1)) if h1 else None
    project_from_h1 = _h1_project_name(body, r"Project Requirements:")

    exec_body = find_section(sections, "executive summary") or ""
    exec_sub = split_sections(exec_body)
    business_context = find_section(exec_sub, "business context") or ""
    bc_paras = paragraphs(business_context)
    objectives = bullets(find_section(exec_sub, "objectives") or "")
    outcomes = bullets(find_section(exec_sub, "expected outcomes") or "")

    scope_body = find_section(exec_sub, "project scope") or ""
    scope_in = bullets(find_section(split_sections(scope_body), "in scope") or "")
    scope_out = bullets(find_section(split_sections(scope_body), "out of scope") or "")

    stakeholders = table_to_rows(find_section(sections, "stakeholders") or "")
    brs = _blocks_by_heading(
        find_section(sections, "business requirements") or "", r"BR-\d+"
    )
    fr_section = find_section(sections, "functional requirements") or ""
    personas = _blocks_by_heading(fr_section, r"persona")
    use_cases = _blocks_by_heading(fr_section, r"UC-\d+")
    frs = _blocks_by_heading(fr_section, r"FR-\d+")

    nfr_section = find_section(sections, "non-functional requirements") or ""
    nfrs: dict[str, list[str]] = {}
    for heading, block_body in split_blocks(nfr_section, min_level=3):
        items = bullets(block_body)
        if items:
            nfrs[heading] = items

    integrations = _blocks_by_heading(
        find_section(sections, "integration requirements") or "", r"INT-\d+"
    )
    data_section = find_section(sections, "data requirements") or ""
    entities = _blocks_by_heading(
        data_section, r"data entities?"
    ) or _blocks_by_heading(data_section, r"entity")

    constraint_body = (
        find_section(sections, "constraints and assumptions")
        or find_section(sections, "constraints")
        or ""
    )
    constraints = bullets(constraint_body)
    assumptions = bullets(
        find_section(split_sections(constraint_body), "assumptions") or ""
    )

    kpi_body = (
        find_section(sections, "success criteria and kpis")
        or find_section(sections, "success criteria")
        or ""
    )
    kpis = bullets(kpi_body)

    risks = bullets(
        find_section(sections, "dependencies and risks")
        or find_section(sections, "risks")
        or ""
    )

    return {
        "document_id": dc.get("document id", ""),
        "project": dc.get("project", "") or (project_from_h1 or ""),
        "status": dc.get("status", ""),
        "h1_name": h1_name or "",
        "business_context": bc_paras[0] if bc_paras else "",
        "objectives": objectives,
        "outcomes": outcomes,
        "scope_in": scope_in,
        "scope_out": scope_out,
        "stakeholders": stakeholders,
        "brs": brs,
        "personas": personas,
        "use_cases": use_cases,
        "frs": frs,
        "nfrs": nfrs,
        "integrations": integrations,
        "data_entities": entities,
        "constraints": constraints,
        "assumptions": assumptions,
        "kpis": kpis,
        "risks": risks,
    }


def _extract_stke(body: str) -> dict[str, Any]:
    """§3.4.3 — STKE → stakeholder / driver / goal enrichment."""
    sections = split_sections(body)
    dc = _doc_control(sections)

    idn_body = find_section(sections, "stakeholder identification") or ""
    internal = table_to_rows(
        find_section(split_sections(idn_body), "internal stakeholders") or ""
    )
    external = table_to_rows(
        find_section(split_sections(idn_body), "external stakeholders") or ""
    )

    drivers = _blocks_by_heading(
        find_section(sections, "stakeholder drivers analysis")
        or find_section(sections, "stakeholder drivers")
        or "",
        r"SD-\d+",
    )
    goals = _blocks_by_heading(
        find_section(sections, "driver-to-goal mapping")
        or find_section(sections, "driver to goal mapping")
        or "",
        r"Goal\s*G-?\d*",
    )
    outcomes = _blocks_by_heading(
        find_section(sections, "goal-to-outcome mapping")
        or find_section(sections, "goal to outcome mapping")
        or "",
        r"Outcome\s*O-?\d*",
    )
    conflicts = bullets(find_section(sections, "conflict analysis") or "")

    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "internal_stakeholders": internal,
        "external_stakeholders": external,
        "drivers": drivers,
        "goals": goals,
        "outcomes": outcomes,
        "conflicts": conflicts,
    }


def _extract_oaal(body: str) -> dict[str, Any]:
    """§3.4.4 — OAAL → template header block + sprint map."""
    sections = split_sections(body)
    # O-AA templates have no Document Control — use the 2-col header table.
    header = _oaa_header(sections, body)
    sprint_rows = table_to_rows(find_section(sections, "sprint map") or "")
    return {"header": header, "sprint_map": sprint_rows}


def _extract_prin(body: str) -> dict[str, Any]:
    """§3.4.5 — PRIN → principles context (≤ MAX_PRINCIPLES_CHARS)."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    org = _clean_value(h1.group(1)) if h1 else ""

    _SKIP = {
        "executive summary",
        "document control",
        "references",
        "appendix",
        "strategic principles",
        "tactical principles",
        "operational principles",
        "complete traceability matrix",
        "communication plan",
        "governance",
    }
    principles: list[str] = []
    for _lvl, text, _body_ in sections:
        # Principles sit at H2/H3; H1 is the org name, H1-level noise is skipped.
        if not (2 <= _lvl <= 3):
            continue
        # Strip numbering prefixes: '1. Name', '2.1 Name', 'I. Name'
        name = re.sub(r"^(?:\d+(?:\.\d+)*|[IVXLC]+)\.?\s+", "", text.strip()).strip()
        if not name or _is_placeholder(name):
            continue
        # match category/known section headings case-insensitively
        if len(name) >= 120 or name.lower() in _SKIP:
            continue
        principles.append(name)
    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "organization": org or "",
        "principles": principles,
    }


def _strip_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


def _oapr_mission(section_body: str) -> str:
    """First substantive content under "Product Mission Statement":
    fenced ```text block, blockquote, or plain paragraph (OAA variants)."""
    if not section_body:
        return ""
    m = re.search(r"```text\s*(.*?)```", section_body, re.DOTALL)
    if m:
        text = " ".join(m.group(1).split())
        if text:
            return text
    quote_lines = [
        line for line in section_body.splitlines() if line.lstrip().startswith(">")
    ]
    if quote_lines:
        text = " ".join(re.sub(r"^\s*>\s?", "", ln).strip() for ln in quote_lines).strip()
        if text:
            return text
    ps = paragraphs(section_body)
    return ps[0] if ps else ""


def _oapr_yaml_backlog(full_body: str) -> list[dict[str, Any]]:
    """YAML-fenced architecture/functional items anywhere in the document.

    Scans the whole body (not just the §3 section body) because fence
    content such as ``# backlog.yaml`` comments would be read as H1
    headings by :func:`split_sections`, truncating the section body.
    Only documents carrying ``architecture_items`` / ``functional_items``
    keys contribute (roadmap / value-stream / compliance fences are
    ignored)."""
    items: list[dict[str, Any]] = []
    for fence in re.findall(r"```ya?ml\s*(.*?)```", full_body, re.DOTALL):
        try:
            doc = yaml.safe_load(fence)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        for key in ("architecture_items", "functional_items"):
            for item in doc.get(key) or []:
                if isinstance(item, dict):
                    entry = {
                        k: item[k]
                        for k in ("id", "title", "type", "priority", "sprint")
                        if k in item
                    }
                    if entry:
                        items.append(entry)
    return items


def _oapr_backlog(section_body: str, full_body: str) -> list[dict[str, Any]]:
    """§3 Product Backlog rows: markdown item tables win, else YAML-fenced
    architecture/functional items (OAA-lite variant)."""
    rows = parse_md_table(section_body)
    yaml_items = _oapr_yaml_backlog(full_body)
    item_keys = {h.lower() for h in (rows[0] if rows else {})}
    if rows and item_keys & {"epic", "architecture item", "backlog item", "item", "id"}:
        return rows
    return yaml_items


def _extract_oapr(body: str) -> dict[str, Any]:
    """Tier-2 — OAPR (OAA Product Architecture): mission / outcome / backlog
    + D1–D10 discovery-dimension coverage (TBD rows → open questions)."""
    sections = split_sections(body)
    header = _oaa_header(sections, body)

    mission = _strip_bold(
        _oapr_mission(find_section(sections, "product mission statement") or "")
    )
    outcome = parse_md_table(find_section(sections, "product outcome") or "")
    backlog = _oapr_backlog(
        find_section(sections, "product backlog") or "", body
    )

    # D1–D10 Discovery Dimensions coverage table when present; OAA-lite
    # documents carry §7 guardrail constraints instead (kept as dimensions).
    d_table = parse_md_table(find_section(sections, "discovery dimensions") or "")
    if not d_table:
        d_table = parse_md_table(
            find_section(sections, "non-negotiable constraints")
            or find_section(sections, "architecture guardrails")
            or ""
        )

    open_questions: list[dict[str, str]] = []
    for r in d_table:
        status = _clean_value(r.get("Status", "")) or ""
        if not status.upper().startswith("TBD"):
            continue
        quoted = re.search(r'"([^"]+)"', status)
        question = (
            quoted.group(1)
            if quoted
            else re.sub(r"^`?TBD\b[\s—-]*`?", "", status).strip()
        )
        if question:
            open_questions.append(
                {"dimension": r.get("#", "").strip(), "question": question}
            )

    return {
        "document_id": header.get("document_id", ""),
        "project": header.get("project", ""),
        "status": header.get("status", ""),
        "owner": header.get("owner", ""),
        "mission": mission,
        "outcome": outcome,
        "backlog": backlog,
        "d_dimensions": d_table,
        "open_questions": open_questions,
    }



def _oastr_waves(body: str) -> list[dict[str, Any]]:
    """OASTR §4 — split '### Wave N: <title>' subsections; per-wave
    defend/attack/outcome bullets."""
    parts = re.split(r"^###\s*Wave\s*(\d+)", body, flags=re.M)
    out: list[dict[str, Any]] = []
    for i in range(1, len(parts) - 1, 2):
        wbody = parts[i + 1]
        h = re.search(r"^##\s", wbody, re.M)
        if h:
            wbody = wbody[: h.start()]
        title = ""
        for line in wbody.splitlines():
            t = line.strip()
            if t:
                title = t.lstrip(":- ").strip()
                break
        wave: dict[str, Any] = {
            "wave": parts[i],
            "title": title,
            "defend": "",
            "attack": "",
            "outcome": "",
        }
        for m in re.finditer(
            r"^\s*[-*]\s*\*\*(?P<k>defend|attack|outcome)\*\*:?\s*(?P<v>.+)$",
            wbody,
            re.I | re.M,
        ):
            wave[m.group("k").lower()] = m.group("v").strip()
        out.append(wave)
    return out


def _trans_waves(body: str) -> list[dict[str, Any]]:
    """TRANS §1 — '**Wave N — Name**' blocks under 'Transition Waves'."""
    matches = list(
        re.finditer(
            r"^\*\*Wave\s*(\d+)\s*(?:[\u2013\u2014-]\s*(.+?))?\*\*",
            body,
            re.M,
        )
    )
    out: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        block = body[m.end() : end]
        h = re.search(r"^#{1,4}\s", block, re.M)
        if h:
            block = block[: h.start()]
        wave: dict[str, Any] = {
            "wave": m.group(1),
            "name": (m.group(2) or "").strip(),
            "objective": "",
            "duration": "",
            "governance_gate": "",
            "key_deliverables": [],
        }
        for line in block.splitlines():
            lm = re.match(
                r"^\s{0,1}-\s+\*\*(?P<k>[^*]+?)\*\*:?\s*(?P<v>.*)$", line
            )
            if lm:
                key = lm.group("k").strip().lower()
                val = lm.group("v").strip()
                if key == "objective":
                    wave["objective"] = val
                elif key == "duration":
                    wave["duration"] = val
                elif key == "governance gate":
                    wave["governance_gate"] = val
            else:
                sm = re.match(r"^\s{2,}-\s+(.+)$", line)
                if sm:
                    wave["key_deliverables"].append(sm.group(1).strip())
        out.append(wave)
    return out


def _kv_table_rows(text: str) -> list[tuple[str, str]]:
    """(key, value) pairs from a 2-column table whose FIRST row is a data row
    (followed by a separator line) — OASTR-style header tables. parse_md_table
    would misread that first row as column headers, so parse it directly."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(
            r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]
        ):
            out: list[tuple[str, str]] = []
            for r in [line] + [
                lines[j]
                for j in range(i + 2, len(lines))
                if lines[j].strip().startswith("|")
            ]:
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                if len(cells) >= 2:
                    k = _clean_value(cells[0])
                    if k:
                        out.append((k.lower(), _clean_value(cells[1]) or ""))
            return out
    return []


def _extract_oastr(body: str) -> dict[str, Any]:
    """Tier-2 P1 — OASTR: strategy canvas dimensions, defend/attack tracks,
    §4 waves (+ outcomes)."""
    sections = split_sections(body)
    header = _oaa_header(sections, body)
    waves = _oastr_waves(body)
    if "document_id" not in header:
        # OASTR header tables open with a key/value row, which parse_md_table
        # drops as a fake header — recover the pairs directly (labels are
        # lowercased, spaces kept).
        for k, v in _kv_table_rows(body[:2000]):
            header.setdefault(k, v)
    return {
        "document_id": header.get("document id", header.get("document_id", "")),
        "project": header.get("project", ""),
        "status": header.get("status", ""),
        "dimensions": table_to_rows(find_section(sections, "strategy canvas") or ""),
        "defend": table_to_rows(find_section(sections, "defend track") or ""),
        "attack": table_to_rows(find_section(sections, "attack track") or ""),
        "waves": waves,
        "outcomes": [w["outcome"] for w in waves if w.get("outcome")],
    }


def _extract_trans(body: str) -> dict[str, Any]:
    """Tier-2 P1 — TRANS: §1 overview + transition waves (fallback
    source for strategy_waves when OASTR is absent)."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    waves = _trans_waves(body)
    return {
        "document_id": dc.get("document id", ""),
        "project": dc.get("project", ""),
        "status": dc.get("status", ""),
        "overview": table_to_rows(find_section(sections, "transition overview") or ""),
        "waves": waves,
        "outcomes": [w["name"] for w in waves if w.get("name")],
    }


def _extract_bpcm(body: str) -> dict[str, Any]:
    """Tier-2 P1 — BPCM: capability hierarchy (L1/L2/L3), value stream
    matrix, maturity table."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    return {
        "document_id": dc.get("document id", ""),
        "project": dc.get("project", ""),
        "status": dc.get("status", ""),
        "hierarchy": {
            "l1": table_to_rows(find_section(sections, "level 1") or ""),
            "l2": table_to_rows(find_section(sections, "level 2") or ""),
            "l3": table_to_rows(find_section(sections, "level 3") or ""),
        },
        "value_stream": table_to_rows(
            find_section(sections, "value stream matrix") or ""
        ),
        "maturity": table_to_rows(find_section(sections, "maturity table") or ""),
    }


def _extract_gapa(body: str) -> dict[str, Any]:
    """Tier-2 P1 — GAPA: capability gap matrix, gap-to-risk mappings,
    constraints bullets."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    return {
        "document_id": dc.get("document id", ""),
        "project": dc.get("project", ""),
        "status": dc.get("status", ""),
        "gaps": table_to_rows(
            find_section(sections, "capability gap matrix") or ""
        ),
        "risk_mappings": table_to_rows(find_section(sections, "gap-to-risk") or ""),
        "constraints": bullets(find_section(sections, "constraints") or ""),
    }


def _entity_rows(section_body: str) -> list[dict[str, Any]]:
    """All entity tables under a 'data entities' section, in template §2.2
    shape: per-domain ``#### Domain N: <name>`` groups. Rows are flattened
    (lowercase keys) and tagged with the enclosing domain heading when the
    row itself has no domain column value."""
    rows: list[dict[str, Any]] = []
    lines = (section_body or "").splitlines()
    cur_domain = ""
    i = 0
    while i < len(lines):
        m = HEADING_RE.match(lines[i])
        if m:
            h = m.group(2).strip()
            dm = re.match(
                r"^(?:\d+\.)?\s*Domain\s*(\d+)?\s*:?\s*(.*)$", h, re.I
            )
            cur_domain = (
                ((dm.group(2) or dm.group(1) or "").strip() if dm else "")
            )
            i += 1
            continue
        if lines[i].lstrip().startswith("|"):
            tbl: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            for r in parse_md_table("\n".join(tbl)):
                nr = {k.lower(): v for k, v in r.items() if v}
                name = _clean_value(
                    nr.get("entity_name") or nr.get("entity") or ""
                )
                if not name:
                    continue
                nr = {
                    k: _clean_value(v) or v for k, v in nr.items()
                }
                nr = {k: v for k, v in nr.items() if v and not _is_placeholder(v)}
                if cur_domain and not nr.get("domain"):
                    nr["domain"] = cur_domain
                rows.append(nr)
            continue
        i += 1
    return rows


def _extract_data(body: str) -> dict[str, Any]:
    """W3 — DATA (TOGAF ADM C.2): domains, entities, classification scheme,
    relationship narrative. Handles both the §2.2 by-domain template shape
    and the compact catalog table shape seen in generated artefacts."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    entities = _entity_rows(find_section(sections, "data entities") or "")
    domains = table_to_rows(find_section(sections, "data domains") or "")
    if not domains:
        seen: list[str] = []
        for r in entities:
            d = r.get("domain", "")
            if d and d not in seen:
                seen.append(d)
        domains = [{"domain": d} for d in seen]
    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "owner": dc.get("owner", ""),
        "domains": domains,
        "entities": entities,
        "classification": table_to_rows(
            find_section(sections, "classification scheme") or ""
        ),
        "relationships": " ".join(
            paragraphs(find_section(sections, "data entity relationships") or "")
        ),
    }


def _extract_tech(body: str) -> dict[str, Any]:
    """W3 — TECH (TOGAF ADM D): API standards, messaging patterns and
    integration-security tables (§4) + observability narrative (§3.4)."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "owner": dc.get("owner", ""),
        "api_standards": table_to_rows(
            find_section(sections, "api standards") or ""
        ),
        "messaging_patterns": table_to_rows(
            find_section(sections, "messaging patterns") or ""
        ),
        "integration_security": table_to_rows(
            find_section(sections, "integration security") or ""
        ),
        "observability": " ".join(
            paragraphs(find_section(sections, "observability") or "")
        ),
    }


def _extract_oasec(body: str) -> dict[str, Any]:
    """W3 — OASEC (O-AA agile security): four-pillar table, per-sprint
    threat modelling, security guardrails, risk assessment."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "pillars": table_to_rows(find_section(sections, "four pillars") or ""),
        "threats": table_to_rows(
            find_section(sections, "threat modeling")
            or find_section(sections, "threat modelling")
            or ""
        ),
        "guardrails": table_to_rows(
            find_section(
                sections,
                "guardrails",
                "security architecture guardrails",
            )
            or ""
        ),
        "risks": table_to_rows(
            find_section(sections, "risk assessment") or ""
        ),
    }


def _vision_yaml_blocks(text: str) -> list[str]:
    """Fenced ```yaml blocks whose top-level key is ``vision:`` (the
    OAA-ADM-lite signature)."""
    return [
        m.group(1)
        for m in VISION_FENCE_RE.finditer(text or "")
        if VISION_SIGNATURE_RE.search(m.group(1))
    ]


def _has_vision_signature(path: Path) -> bool:
    """Cheap pre-filter for OAA-ADM-lite candidates (content, not name)."""
    try:
        text = path.read_text()
    except OSError:
        return False
    return bool(VISION_FENCE_RE.search(text) and VISION_SIGNATURE_RE.search(text))


def _extract_oaalite(body: str) -> dict[str, Any]:
    """W3 — OAA-ADM-lite: fenced vision.yaml block → scope NFR fields.
    Malformed YAML yields ``vision_yaml_error`` so §6.3 can audit-skip it."""
    sections = split_sections(body)
    dc = _doc_control(sections)
    vision: Any = None
    yaml_error = ""
    for block in _vision_yaml_blocks(body):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            yaml_error = f"unparseable vision.yaml block ({e})"
            continue
        if isinstance(data, dict) and "vision" in data:
            vision = data["vision"]
            break
    if yaml_error and vision is None:
        return {
            "document_id": dc.get("document id", ""),
            "status": dc.get("status", ""),
            "version": dc.get("version", ""),
            "vision_yaml_error": yaml_error,
            "use_cases": [],
        }

    def _g(*keys: str, default=None):
        cur: Any = vision
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur

    use_cases = _g("scope", "use_cases", default=[])
    return {
        "document_id": dc.get("document id", ""),
        "status": dc.get("status", ""),
        "version": dc.get("version", ""),
        "vision_yaml_error": "",
        "use_cases": list(use_cases) if isinstance(use_cases, list) else [],
        "user_count": _g("scope", "user_count"),
        "latency_requirement_ms": _g("scope", "latency_requirement_ms"),
        "data_classification": _g("scope", "data_classification"),
        "ai_workload_type": _g("scope", "ai_workload_type"),
        "budget_aud": _g("constraints", "budget_aud"),
        "timeline_weeks": _g("constraints", "timeline_weeks"),
        "infrastructure": _g("constraints", "infrastructure"),
        "jurisdiction": _g("constraints", "jurisdiction"),
    }


_EXTRACTORS = {
    "ADMP": _extract_admp,
    "REQ": _extract_req,
    "STKE": _extract_stke,
    "OAAL": _extract_oaal,
    "PRIN": _extract_prin,
    "OAPR": _extract_oapr,
    "OASTR": _extract_oastr,
    "TRANS": _extract_trans,
    "BPCM": _extract_bpcm,
    "GAPA": _extract_gapa,
    "DATA": _extract_data,
    "TECH": _extract_tech,
    "OASEC": _extract_oasec,
    "OAA-ADM-lite": _extract_oaalite,
}


# ── Validation (§5 required-field subset, §6.3 pipeline) ───────────────────


def _validate_parsed(
    type_code: str, parsed: dict[str, Any], record: ArtifactRecord, filename_doc_id: str
) -> None:
    """Check the §5 required-field subset for one artefact; append errors."""
    problems: list[str] = []

    # Document ID cross-check (§6.3 step 4)
    doc_id = parsed.get("document_id", "")
    if doc_id and doc_id != filename_doc_id:
        problems.append(
            f"Document ID '{doc_id}' does not match filename '{filename_doc_id}'"
        )

    if type_code in ("ADMP", "REQ", "STKE", "PRIN"):
        status = (parsed.get("status") or "").upper()
        if status and status not in VALID_STATUS:
            problems.append(f"Status '{status}' not in {sorted(VALID_STATUS)}")

    if type_code == "ADMP":
        if not parsed.get("architecture_vision"):
            problems.append("missing Architecture Vision narrative (§1 required)")
        if not parsed.get("scope_in"):
            problems.append("missing Scope → In Scope bullets (§2.1 required)")
        if not parsed.get("success_criteria"):
            problems.append("missing Success Criteria rows (§6 required)")
    elif type_code == "REQ":
        if not parsed.get("business_context"):
            problems.append("missing Executive Summary → Business Context")
        if not (parsed.get("brs") or parsed.get("frs")):
            problems.append("no Business or Functional Requirements found")
    elif type_code == "STKE":
        if not (
            parsed.get("internal_stakeholders") or parsed.get("external_stakeholders")
        ):
            problems.append("no stakeholder tables found")
        if not parsed.get("drivers"):
            problems.append("no stakeholder drivers (SD-N) found")
    elif type_code == "OAAL":
        if not parsed.get("header", {}).get("template"):
            problems.append("missing template header block")
        if not parsed.get("sprint_map"):
            problems.append("no Sprint Map rows found")
    elif type_code == "PRIN":
        if not parsed.get("principles"):
            problems.append("no principles found")
    elif type_code == "OAPR":
        if not parsed.get("mission"):
            problems.append("missing Product Mission Statement (§1.1 required)")
        if not parsed.get("backlog"):
            problems.append("missing Product Backlog items (§3 required)")

    elif type_code == "OASTR":
        if not parsed.get("dimensions"):
            problems.append(
                "missing Strategy Canvas dimensions (OASTR required)"
            )
    elif type_code == "TRANS":
        if not parsed.get("waves"):
            problems.append("no transition waves found (TRANS required)")
    elif type_code == "BPCM":
        if not any((parsed.get("hierarchy") or {}).values()):
            problems.append(
                "no capability hierarchy tables found (BPCM required)"
            )
    elif type_code == "GAPA":
        if not (
            parsed.get("gaps")
            or parsed.get("risk_mappings")
            or parsed.get("constraints")
        ):
            problems.append(
                "no gap content found (gap matrix, risk mappings, or constraints)"
            )
    elif type_code == "DATA":
        if not (parsed.get("entities") or parsed.get("domains")):
            problems.append("no data entities found (DATA required)")
    elif type_code == "TECH":
        if not (
            parsed.get("api_standards")
            or parsed.get("messaging_patterns")
            or parsed.get("integration_security")
        ):
            problems.append("no integration tables found (TECH required)")
    elif type_code == "OASEC":
        if not (
            parsed.get("pillars")
            or parsed.get("threats")
            or parsed.get("guardrails")
            or parsed.get("risks")
        ):
            problems.append("no security controls found (OASEC required)")
    elif type_code == "OAA-ADM-lite":
        if parsed.get("vision_yaml_error"):
            problems.append(f"vision.yaml block: {parsed['vision_yaml_error']}")
        elif not parsed.get("use_cases"):
            problems.append(
                "vision.scope.use_cases must be a non-empty list "
                "(OAA-ADM-lite signature)"
            )
    for p in problems:
        record.errors.append(f"SCHEMA_VALIDATION_FAILED: {p}")
    record.schema_valid = not problems


def _process_lite_artifact(ctx: ArcKitContext, path: Path) -> ArtifactRecord:
    """§6.3 pipeline for OAA-ADM-lite (content-based; no canonical
    filename, no H1 requirement). Document ID / version come from the
    Document Control header; version defaults to v1.0."""
    record = ArtifactRecord(
        type="OAA-ADM-lite",
        path=str(path),
        version="v1.0",
        status="",
        frontmatter=False,
        schema_valid=False,
    )
    try:
        text = path.read_text()
    except OSError as e:
        record.errors.append(f"MALFORMED_ARTIFACT: unreadable ({e})")
        ctx.records.append(record)
        _err(ctx, MALFORMED_ARTIFACT, f"{path.name}: unreadable")
        return record

    meta, body = parse_frontmatter(text)
    record.frontmatter = bool(meta)
    parsed = _EXTRACTORS["OAA-ADM-lite"](text if meta is None else body)

    version = parsed.get("version", "")
    if version and version.replace(".", "").isdigit():
        record.version = f"v{version}"
    record.parsed = parsed
    _validate_parsed("OAA-ADM-lite", parsed, record, parsed.get("document_id", ""))
    if record.schema_valid:
        record.fields_extracted = sorted(
            k for k, v in parsed.items() if v not in ("", [], {}, None)
        )
    status = (parsed.get("status") or "").upper()
    record.status = status or "UNKNOWN"
    ctx.records.append(record)
    if record.errors:
        for err in record.errors:
            _err(ctx, err.split(":")[0], f"{path.name}: {err}")
    return record


def _process_artifact(
    ctx: ArcKitContext, type_code: str, path: Path
) -> ArtifactRecord | None:
    """§6.3 validation pipeline for one artefact file."""
    if type_code == "OAA-ADM-lite":
        return _process_lite_artifact(ctx, path)
    m = ARTIFACT_FILENAME_RE.match(path.name)
    if m is None:
        return None
    filename_doc_id = path.name[:-3]
    version = f"v{m.group('major')}.{m.group('minor') or '0'}"
    record = ArtifactRecord(
        type=type_code,
        path=str(path),
        version=version,
        status="",
        frontmatter=False,
        schema_valid=False,
    )

    try:
        text = path.read_text()
    except OSError as e:
        record.errors.append(f"MALFORMED_ARTIFACT: unreadable ({e})")
        ctx.records.append(record)
        _err(ctx, MALFORMED_ARTIFACT, f"{path.name}: unreadable")
        return record

    # Step 1: filename already checked by the caller (§2 step 4 — pid match).
    # Step 2: frontmatter (optional; must parse; docType must match filename)
    meta, body = parse_frontmatter(text)
    if meta is None:
        record.errors.append("MALFORMED_ARTIFACT: unparseable YAML frontmatter")
        ctx.records.append(record)
        _err(ctx, MALFORMED_ARTIFACT, f"{path.name}: unparseable frontmatter")
        return record
    record.frontmatter = bool(meta)
    if meta:
        fm_type = str(meta.get("docType", "")).upper()
        if fm_type and fm_type != type_code:
            record.errors.append(
                f"MALFORMED_ARTIFACT: frontmatter docType '{fm_type}' ≠ filename '{type_code}'"
            )
            ctx.records.append(record)
            _err(ctx, MALFORMED_ARTIFACT, f"{path.name}: frontmatter docType mismatch")
            return record

    # Step 3: H1 title line must be present
    if not re.search(r"^#\s+\S", body, re.MULTILINE):
        record.errors.append("MALFORMED_ARTIFACT: missing H1 title line")
        ctx.records.append(record)
        _err(ctx, MALFORMED_ARTIFACT, f"{path.name}: missing H1")
        return record

    parsed = _EXTRACTORS[type_code](body)

    # Step 4: SUPERSEDED artefacts are skipped (§3.3)
    status = (parsed.get("status") or "").upper()
    record.status = status or "UNKNOWN"
    if status == "SUPERSEDED":
        record.parsed = parsed
        ctx.records.append(record)
        ctx.errors.append((ARTIFACT_SUPERSEDED, f"{path.name} is SUPERSEDED — skipped"))
        return record

    # Step 5: §5 required-field validation
    _validate_parsed(type_code, parsed, record, filename_doc_id)
    record.parsed = parsed
    if record.schema_valid:
        record.fields_extracted = sorted(
            k for k, v in parsed.items() if v not in ("", [], {}, None)
        )
    ctx.records.append(record)
    if record.errors:
        for err in record.errors:
            _err(ctx, err.split(":")[0], f"{path.name}: {err}")
    return record


# ── Public API (§1, §4, §6.4) ──────────────────────────────────────────────


def _warn_lite_conflict(ctx: ArcKitContext, paths: list[Path]) -> None:
    """OAA-ADM-lite carries no filename version: >1 candidate → mtime wins
    with an ARTIFACT_CONFLICT audit error (mirrors the canonical rule)."""
    if len(paths) > 1:
        newest = _pick_lite(paths)
        _err(
            ctx,
            ARTIFACT_CONFLICT,
            f"OAA-ADM-lite: {len(paths)} vision files — using {newest.name} (mtime)",
        )


def load_arckit_artifacts(
    root: str,
    project_id: str = "",
    files: list[str] | None = None,
) -> ArcKitContext:
    """Scan `root` (ArcKit project tree, or a project directory) and build the
    DISCOVER context per the EYW-171 data contract.

    - §2 discovery: projects/{NNN}-{slug}/ARC-{NNN}-{TYPE}-vN.N.md, highest
      version wins; PRIN from projects/000-global/.
    - §1.1 precedence: ADMP → REQ → STKE → OAAL → PRIN; later artefacts add,
      never replace, fields filled by earlier ones.
    - §6.4 audit record is always populated (even when nothing is found).

    `files`: optional explicit list of artefact paths. When non-empty, glob
    discovery is skipped and each file is parsed directly (type/pid/version
    from the filename); the root may be absent. Malformed filenames are
    recorded as MALFORMED_FILENAME and skipped; a non-DISCOVER type is
    ignored; a missing file is recorded as MALFORMED_ARTIFACT. Highest
    version per type and same-version conflict detection still apply.
    """
    ctx = ArcKitContext(
        scanned_root=str(root or ""),
        project_id=str(project_id).zfill(3) if project_id else "",
    )
    explicit: dict[str, list[Path]] = {}
    artifact_files = [Path(str(entry)).expanduser() for entry in (files or [])]
    if artifact_files:
        # Explicit artefact list: operator-supplied paths are authoritative —
        # no glob scan, root need not exist.
        for p in artifact_files:
            if not p.is_file():
                _err(ctx, MALFORMED_ARTIFACT, f"{p.name}: file not found")
                continue
            m = ARTIFACT_FILENAME_RE.match(p.name)
            if m is None:
                # OAA-ADM-lite bypass: a non-canonical name with the fenced
                # vision.yaml signature is a valid lite artefact (e.g.
                # vision.md supplied via the HIL artefact folder).
                if p.suffix.lower() == ".md" and _has_vision_signature(p):
                    explicit.setdefault("OAA-ADM-lite", []).append(p)
                    continue
                _err(
                    ctx,
                    MALFORMED_FILENAME,
                    f"{p.name}: does not match ARC-{{PID}}-{{TYPE}}-vN.N.md",
                )
                continue
            if m.group("type") not in DISCOVER_TYPES:
                continue  # not consumed by DISCOVER
            explicit.setdefault(m.group("type"), []).append(p)
        if not ctx.project_id:
            pids: set[str] = set()
            for ps in explicit.values():
                for p in ps:
                    m2 = ARTIFACT_FILENAME_RE.match(p.name)
                    if m2:
                        pids.add(m2.group("pid"))
            pids.discard("000")
            if len(pids) == 1:
                ctx.project_id = pids.pop()
        chosen: dict[str, Path | None] = {
            t: _pick_highest(explicit.get(t, [])) for t in DISCOVER_TYPES
        }
        chosen["OAA-ADM-lite"] = _pick_lite(explicit.get("OAA-ADM-lite", []))
        _warn_lite_conflict(ctx, explicit.get("OAA-ADM-lite", []))
        conflict_map = explicit
    else:
        root_p = Path(root).expanduser() if root else Path("/dev/null")
        if not root_p.is_dir():
            _err(ctx, NO_ARTIFACTS, f"context folder '{root}' does not exist")
            ctx.audit = _build_audit(ctx)
            return ctx

        discovered = discover_artifact_files(root_p, project_id)

        # Resolve the project ID when not given: prefer a single non-global
        # project dir that holds DISCOVER artefacts.
        if not ctx.project_id:
            pids = set()
            for type_code in ("ADMP", "REQ", "STKE", "OAAL"):
                for p in discovered.get(type_code, []):
                    m = ARTIFACT_FILENAME_RE.match(p.name)
                    if m:
                        pids.add(m.group("pid"))
            pids.discard("000")
            if len(pids) == 1:
                ctx.project_id = pids.pop()

        chosen: dict[str, Path | None] = {}
        for type_code in DISCOVER_TYPES:
            candidates = [
                p
                for p in discovered.get(type_code, [])
                if type_code == "PRIN"
                or not (
                    ctx.project_id
                    and (m := ARTIFACT_FILENAME_RE.match(p.name))
                    and m.group("pid") != ctx.project_id
                )
            ]
            chosen[type_code] = _pick_highest(candidates)
        conflict_map = discovered

    # Conflict detection: two different files for the same (type, version)
    for type_code in DISCOVER_TYPES:
        cand = conflict_map.get(type_code, [])
        if len(cand) > 1:
            by_version: dict[tuple[int, int], list[Path]] = {}
            for p in cand:
                m = ARTIFACT_FILENAME_RE.match(p.name)
                if m is None:
                    continue
                by_version.setdefault(
                    (int(m.group("major")), int(m.group("minor") or 0)), []
                ).append(p)
            for _v, group in by_version.items():
                if len(group) > 1:
                    newest = max(group, key=lambda p: p.stat().st_mtime)
                    _err(
                        ctx,
                        ARTIFACT_CONFLICT,
                        f"{type_code}: {len(group)} files at same version — using {newest.name} (mtime)",
                    )

    _warn_lite_conflict(ctx, conflict_map.get("OAA-ADM-lite", []))
    chosen["OAA-ADM-lite"] = _pick_lite(conflict_map.get("OAA-ADM-lite", []))

    for type_code in DISCOVER_TYPES:
        path = chosen.get(type_code)
        if path:
            _process_artifact(ctx, type_code, path)

    valid = [r for r in ctx.records if r.schema_valid]
    if not valid:
        found_any = any(conflict_map.get(t) for t in DISCOVER_TYPES)
        if not found_any:
            if artifact_files:
                _err(ctx, NO_ARTIFACTS, "no valid ArcKit artefacts in explicit list")
            else:
                _err(ctx, NO_ARTIFACTS, f"no ArcKit artefacts found under '{root_p}'")

    # ── §1.1 precedence merge ──
    def parsed_of(type_code: str) -> dict[str, Any]:
        for r in ctx.records:
            if r.type == type_code and r.schema_valid:
                return r.parsed
        return {}

    parsed_by_type = {t: parsed_of(t) for t in DISCOVER_TYPES}
    (
        admp,
        req,
        stke,
        oaal,
        prin,
        oapr,
        oastr,
        trans,
        bpcm,
        gapa,
        data,
        tech,
        oasec,
        oaalite,
    ) = (parsed_by_type[t] for t in DISCOVER_TYPES)

    # project_name: ADMP Document Control → REQ (DC or H1) → directory slug
    ctx.project_name = admp.get("project") or req.get("project") or ""
    if not ctx.project_name:
        for cand_path in (chosen.get("ADMP"), chosen.get("REQ")):
            if cand_path:
                parent = cand_path.parent.name
                m = re.match(r"^\d{3}-(.+)$", parent)
                if m and m.group(1).lower() not in ("global", ""):
                    ctx.project_name = m.group(1).replace("-", " ").title()
                    break

    # project_description precedence (§1.1, Tier-2 extension):
    # ADMP §1 vision → REQ project + business context → OAPR mission (≤500 chars)
    if admp.get("architecture_vision"):
        ctx.project_description = admp["architecture_vision"]
    elif req.get("project") or req.get("business_context"):
        req_name = req.get("project") or req.get("h1_name", "")
        req_desc = req.get("business_context", "")
        ctx.project_description = (
            f"{req_name}: {req_desc}" if req_name and req_desc else (req_name or req_desc)
        )
    else:
        ctx.project_description = oapr.get("mission", "")
    ctx.project_description = ctx.project_description[:MAX_DESCRIPTION_CHARS]

    # context_folder hint: OAAL Prerequisites referencing an existing repo/path
    prereq = oaal.get("header", {}).get("prerequisites", "")
    if re.match(
        r"^(~?/|\./|\.\./|[A-Za-z]:\\|[a-z][a-z0-9+.-]*://)", prereq
    ) or prereq.startswith("projects/"):
        ctx.context_folder_hint = prereq

    # Stakeholders: merge ADMP + REQ + STKE, de-duped by name (case-insensitive)
    seen: set = set()
    stakeholders: list[dict[str, str]] = []
    for row in (
        list(admp.get("stakeholders", []))
        + list(req.get("stakeholders", []))
        + list(stke.get("internal_stakeholders", []))
        + list(stke.get("external_stakeholders", []))
    ):
        name = (row.get("name") or row.get("stakeholder") or "").lower().strip()
        if not name or name in seen:
            continue
        seen.add(name)
        stakeholders.append(row)

    success = list(admp.get("success_criteria", []))
    kpis = req.get("kpis", [])

    ctx.seeds = {
        "scope_in": admp.get("scope_in") or req.get("scope_in", []),
        "scope_out": admp.get("scope_out") or req.get("scope_out", []),
        "drivers": admp.get("drivers", []),
        "resources": admp.get("resources", []),
        "constraints": admp.get("constraints", []) + req.get("constraints", []),
        "assumptions": req.get("assumptions", []),
        "success_criteria": success,
        "kpis": kpis,
        "stakeholders": stakeholders,
        "objectives": req.get("objectives", []),
        "outcomes": req.get("outcomes", []) + stke.get("outcomes", []),
        "brs": req.get("brs", []),
        "frs": req.get("frs", []),
        "use_cases": req.get("use_cases", []),
        "personas": req.get("personas", []),
        "nfrs": req.get("nfrs", {}),
        "integrations": req.get("integrations", []),
        "data_entities": req.get("data_entities", []),
        "risks": req.get("risks", []),
        "drivers_stke": stke.get("drivers", []),
        "goals": stke.get("goals", []),
        "conflicts": stke.get("conflicts", []),
        "mermaid": admp.get("mermaid", ""),
    }
    ctx.sprint_map = oaal.get("sprint_map", [])
    ctx.principles = "\n".join(prin.get("principles", []))[:MAX_PRINCIPLES_CHARS]

    # Tier-2 OAPR handoff keys (arckit-tier2-ingestion)
    if oapr.get("backlog"):
        ctx.product_backlog = list(oapr["backlog"])
    if oapr.get("open_questions"):
        ctx.open_questions = list(oapr["open_questions"])

    # Tier-2 P1 handoff keys (arckit-tier2-ingestion tasks 5-7):
    # strategy waves (OASTR §4 wins, TRANS §1 fallback), BPCM capability
    # model, GAPA gaps → constraint/risk seeds.
    if oastr.get("dimensions"):
        ctx.seeds["objectives"] += [
            f"{d.get('dimension', '')}: {d.get('description', '')}".strip()
            for d in oastr["dimensions"]
            if d.get("dimension")
        ]
    ctx.seeds["outcomes"] += oastr.get("outcomes", [])
    if oastr.get("waves"):
        ctx.strategy_waves = list(oastr["waves"])
    elif trans.get("waves"):
        ctx.strategy_waves = list(trans["waves"])
    bpcm_hierarchy = bpcm.get("hierarchy") or {}
    if bpcm and (
        any(bpcm_hierarchy.values())
        or bpcm.get("maturity")
        or bpcm.get("value_stream")
    ):
        ctx.capabilities = {
            "hierarchy": bpcm_hierarchy,
            "value_stream": bpcm.get("value_stream", []),
            "maturity": bpcm.get("maturity", []),
        }
    if gapa and (
        gapa.get("gaps")
        or gapa.get("risk_mappings")
        or gapa.get("constraints")
    ):
        ctx.gaps = list(gapa.get("gaps", []))
        ctx.seeds["constraints"] += [
            f"Gap {g.get('capability', '')}: {g.get('current', '')} → {g.get('target', '')}"
            for g in gapa.get("gaps", [])
            if g.get("capability")
        ] + list(gapa.get("constraints", []))
        ctx.seeds["risks"] += [
            f"{r.get('gap', '')} → {r.get('associated_risk', '')} ({r.get('mitigation', '')})"
            for r in gapa.get("risk_mappings", [])
            if r.get("gap")
        ]

    # W3 arckit-build-context handoff keys (empty when the type is absent —
    # never sentinel values).
    dm = {
        "domains": data.get("domains", []),
        "entities": data.get("entities", []),
        "classification": data.get("classification", []),
        "relationships": data.get("relationships", ""),
    }
    if data and any(dm.values()):
        ctx.data_model = {k: v for k, v in dm.items() if v}
    istd = {
        "api_standards": tech.get("api_standards", []),
        "messaging_patterns": tech.get("messaging_patterns", []),
        "integration_security": tech.get("integration_security", []),
        "observability": tech.get("observability", ""),
    }
    if tech and any(istd.values()):
        ctx.integration_standards = {k: v for k, v in istd.items() if v}
    sc = {
        "pillars": oasec.get("pillars", []),
        "threats": oasec.get("threats", []),
        "guardrails": oasec.get("guardrails", []),
        "risks": oasec.get("risks", []),
    }
    if oasec and any(sc.values()):
        ctx.security_controls = {k: v for k, v in sc.items() if v}
    if oaalite.get("use_cases"):
        nfr = {
            k: oaalite[k]
            for k in (
                "use_cases",
                "user_count",
                "latency_requirement_ms",
                "data_classification",
                "ai_workload_type",
                "budget_aud",
                "timeline_weeks",
                "infrastructure",
                "jurisdiction",
            )
            if oaalite.get(k) not in (None, "", [])
        }
        ctx.nfr_constraints = nfr

    ctx.audit = _build_audit(ctx)
    return ctx


#: ArcKit types that are valuable (advisory) build inputs. Their absence is
#: surfaced as "valuable but absent" advisories (ARCH_REVIEW
#: missing_build_inputs channel) — advisory only, never routing.
VALUABLE_ARTIFACT_TYPES = (
    "OAPR",
    "OASTR",
    "BPCM",
    "GAPA",
    "TRANS",  # Tier-2 (arckit-tier2-ingestion)
    "DATA",
    "TECH",
    "OASEC",
    "OAA-ADM-lite",  # W3 build-context (arckit-build-context)
)


def _build_audit(ctx: ArcKitContext) -> dict[str, Any]:
    """§6.4 — discover_artifact_audit record."""
    records = [r.audit_dict() for r in ctx.records]
    valid = sum(1 for r in ctx.records if r.schema_valid)
    superseded = sum(1 for r in ctx.records if r.status == "SUPERSEDED")
    summary = {
        "discovered": len(records),
        "valid": valid,
        "malformed": sum(
            1 for r in ctx.records if r.errors and r.status != "SUPERSEDED"
        ),
        "superseded": superseded,
        "autoPopulated": bool(ctx.has_valid_artifacts and ctx.project_description),
        "fallbackToInterview": not (
            ctx.has_valid_artifacts and ctx.project_description
        ),
    }
    valid_types = {r.type for r in ctx.records if r.schema_valid}
    return {
        "scanned_root": ctx.scanned_root,
        "project_id": ctx.project_id,
        "artefacts": records,
        "errors": [f"{code}: {detail}" for code, detail in ctx.errors],
        "summary": summary,
        # W3: advisory "valuable but absent" list (drives the ARCH_REVIEW
        # missing_build_inputs channel); empty when every valuable type has a
        # valid record.
        "valuable_absent": [
            t for t in VALUABLE_ARTIFACT_TYPES if t not in valid_types
        ],
    }


def synthesize_interview_notes(ctx: ArcKitContext) -> str:
    """§4.2 — deterministic auto-interview document (no LLM call).

    Produces the same heading set the generic interview yields, so downstream
    nodes (DEFINE `_generate_requirement_via_fabric`, `_refine_idea`,
    `_build_context`) treat it identically to a human-interview transcript.
    """
    s = ctx.seeds
    name = ctx.project_name or "Untitled"
    lines: list[str] = [
        f"# Auto-Interview: {name}",
        "",
        "_Synthesised from ArcKit artefacts (EYW-171 data contract)._",
    ]

    def section(title: str, body: str):
        lines.append(f"\n## {title}\n")
        lines.append(body.strip() or "(none provided)")

    def bullets_block(items: Any) -> str:
        if isinstance(items, list):
            return "\n".join(f"- {i}" for i in items if i)
        return ""

    def rows_block(rows: Any) -> str:
        if not rows:
            return ""
        out = []
        for r in rows:
            parts = []
            for k, v in r.items():
                if v:
                    parts.append(f"{k}: {v}")
            out.append("- " + " | ".join(parts) if parts else "")
        return "\n".join(x for x in out if x)

    section("Project Overview", ctx.project_description)
    overview = []
    if s["objectives"]:
        overview.append("**Objectives:**\n" + bullets_block(s["objectives"]))
    if s["scope_in"]:
        overview.append("**In scope:**\n" + bullets_block(s["scope_in"]))
    if s["scope_out"]:
        overview.append("**Out of scope:**\n" + bullets_block(s["scope_out"]))
    if overview:
        lines.append("")
        lines.append("\n".join(overview))

    core = []
    if s["use_cases"]:
        core.append(
            "**Use cases:**\n"
            + bullets_block(
                [
                    f"{uc.get('name', uc.get('id', '?'))}: {uc.get('description', '')}"
                    for uc in s["use_cases"]
                ]
            )
        )
    if s["frs"]:
        core.append(
            "**Functional requirements:**\n"
            + bullets_block(
                [
                    f"{fr.get('id', fr.get('name', '?'))}: {fr.get('description', '')}"
                    for fr in s["frs"]
                ]
            )
        )
    if s["brs"]:
        core.append(
            "**Business requirements:**\n"
            + bullets_block(
                [
                    f"{br.get('id', '?')} [{br.get('priority', '?')}]: {br.get('description', br.get('name', ''))}"
                    for br in s["brs"]
                ]
            )
        )
    section("Core Behavior", "\n".join(core))

    section(
        "Data Model",
        rows_block(s["data_entities"])
        or bullets_block(
            s["data_entities"] if isinstance(s["data_entities"], list) else []
        ),
    )

    api = bullets_block(
        [
            f"{i.get('id', i.get('name', '?'))}: {i.get('purpose', i.get('description', ''))}"
            for i in s["integrations"]
        ]
    )
    section("API Surface", api)

    section("Stakeholders", rows_block(s["stakeholders"]))

    succ = rows_block(s["success_criteria"])
    if s["kpis"]:
        k = bullets_block(s["kpis"])
        succ = (succ + "\n" + k).strip() if succ else k
    section("Success Criteria", succ)

    constr = bullets_block(s["constraints"])
    if s["assumptions"]:
        a = bullets_block(s["assumptions"])
        constr = (
            (constr + "\n\n**Assumptions:**\n" + a).strip()
            if constr
            else "**Assumptions:**\n" + a
        )
    section("Constraints", constr)

    nfr_lines = []
    for cat, items in (s["nfrs"] or {}).items():
        nfr_lines.append(f"**{cat}:**\n" + bullets_block(items))
    section("Non-Functional Requirements", "\n".join(nfr_lines))

    edge = []
    if s["conflicts"]:
        edge.append("**Stakeholder conflicts:**\n" + bullets_block(s["conflicts"]))
    if s["risks"]:
        edge.append("**Risks:**\n" + bullets_block(s["risks"]))
    section("Edge Cases", "\n".join(edge))

    section("Architecture Principles", ctx.principles)

    section("Delivery Shape (Sprint Map)", rows_block(ctx.sprint_map))

    if ctx.strategy_waves:
        section("Strategy Waves", rows_block(ctx.strategy_waves))

    if ctx.capabilities:
        cap = ctx.capabilities
        cap_parts: list[str] = []
        for lvl in ("l1", "l2", "l3"):
            rows = (cap.get("hierarchy") or {}).get(lvl) or []
            if rows:
                cap_parts.append(f"**{lvl.upper()} hierarchy:**\n{rows_block(rows)}")
        if cap.get("maturity"):
            cap_parts.append(
                "**Maturity (current -> target):**\n"
                + rows_block(cap["maturity"])
            )
        if cap.get("value_stream"):
            cap_parts.append(
                "**Value streams:**\n" + rows_block(cap["value_stream"])
            )
        section("Capabilities", "\n".join(cap_parts))

    if ctx.open_questions:
        section(
            "Open questions (OAPR D1–D10)",
            "\n".join(
                f"- **{q.get('dimension') or '?'}**: {q.get('question', '')}"
                for q in ctx.open_questions
            ),
        )

    return "\n".join(lines).rstrip() + "\n"
