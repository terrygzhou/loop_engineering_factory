"""
Unit tests for tools.arckit_loader — EYW-171 data contract (EYW-181 / EYW-178 P1-3).

Fixture scenarios (per contract §8 implementation note):
- tree A "happy":   valid ADMP + REQ + OAAL + PRIN, STKE deliberately missing
- tree B "malformed": happy tree + REQ v2.0 missing a required section
- tree C "multi":    two projects, project_id filter must scope selection
- empty / pid-mismatch / superseded / version-selection edge cases
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.arckit_loader import (  # noqa: E402
    ArcKitContext,
    load_arckit_artifacts,
    synthesize_interview_notes,
    NO_ARTIFACTS,
    ARTIFACT_SUPERSEDED,
    MALFORMED_ARTIFACT,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

ADMP_V1 = """---
title: "Architecture Vision — Preliminary ADM"
docType: ADMP
templateVersion: "1.0"
---

# Architecture Vision

## Document Control

| Field | Value |
|-------|-------|
| Document ID | ARC-001-ADMP-v1.0 |
| Project | Underwriting Platform |
| Owner | Chief Architect |
| Classification | Internal |
| Status | APPROVED |
| Created | 2026-08-01 |

## 1. Architecture Vision

The Underwriting Platform replaces the legacy rules engine with a modern,
explainable decisioning service that shortens quote turnaround from days to
minutes while satisfying regulatory explainability requirements.

## 2. Scope

### 2.1 In Scope

- Quote decisioning for motor lines
- Policy administration hooks
- Decision explainability reports

### 2.2 Out of Scope

- Claims processing
- Pricing model training

## 3. Drivers

### 3.1 Strategic

- Time-to-market

### 3.2 Operational

- Reduce manual underwriting

## 4. Constraints

### 4.1 Budget

- Phase 1 budget capped

### 4.2 Regulatory

- Explainability mandatory

## 6. Success Criteria

| # | Criterion | Measure | Target |
|---|-----------|---------|--------|
| 1 | Quote turnaround | p95 latency | < 5 min |
| 2 | Explainability coverage | decisions with reason codes | 100% |
| 3 | Uptime | SLA | 99.9% |

## 8. Stakeholder Map

| Name | Role | Interest | Influence | Engagement Strategy |
|------|------|----------|-----------|---------------------|
| Alice | Actuary | HIGH | HIGH | Manage Closely |
| Bob | CIO | MEDIUM | HIGH | Keep Satisfied |
"""

REQ_V1 = """# Project Requirements: Underwriting Platform

## Document Control

| Field | Value |
|-------|-------|
| Document ID | ARC-001-REQ-v1.0 |
| Project | Underwriting Platform |
| Status | DRAFT |
| Owner | Product Architect |

## Executive Summary

### Business Context

Insurers struggle with slow, opaque underwriting decisions. This project
delivers an explainable decisioning platform for motor lines.

### Objectives

- Reduce quote turnaround to under 5 minutes
- Provide decision explainability for regulators

### Expected Outcomes

- 40% fewer manual interventions

### Project Scope

#### In Scope

- Motor lines

#### Out of Scope

- Claims

## Stakeholders

| Name | Role | Organization | Involvement Level |
|------|------|--------------|-------------------|
| Alice | Actuary | Acme Insurance | High |

## Business Requirements

### BR-001: Quote decisioning

- **Description**: Produce a decision for a submitted quote
- **Priority**: MUST_HAVE
- **Stakeholder**: Actuary

## Functional Requirements

### User Personas

#### Persona: Underwriter

- **Goals**: Fast decisions
- **Pain Points**: Slow legacy system

### FR-001: Decision service

- **Description**: Expose a decision API
- **Priority**: MUST_HAVE

## Non-Functional Requirements (NFRs)

### NFR-P-001: Performance

- p95 under 500ms

## Integration Requirements

### INT-001: Policy admin

- **Purpose**: Sync policies
- **Integration Type**: API

## Data Requirements

### Data Entities

#### Entity: Quote

- **Description**: A quote request
- **Attributes**: id, premium

## Constraints and Assumptions

- TC-1: Must run on-prem
- A-1: Legacy data is clean

## Success Criteria and KPIs

- Quote turnaround p95 under 5 min

## Dependencies and Risks

- Legacy data migration risk
"""

OAAL_V1 = """# O-AA ADM Lite — Underwriting Platform

## Template

| Field | Value |
|-------|-------|
| Template | O-AA ADM Lite |
| Framework | OAA 1.0 |
| Sprint length | 2 weeks |
| Engagement window | Q3 2026 |
| Prerequisites | projects/001-underwriting |
| Owner | Delivery Architect |

## Sprint Map

| Sprint | TOGAF Phases | Focus | Duration | Key Output |
|--------|--------------|-------|----------|------------|
| Sprint 0 | A | Vision + Stakeholders | 1 week | vision.yaml |
| Sprint 1 | B | Current state | 2 weeks | BPCM |
"""

PRIN_V1 = """# Acme Insurance Enterprise Architecture Principles

## Document Control

| Field | Value |
|-------|-------|
| Document ID | ARC-000-PRIN-v1.0 |
| Status | APPROVED |

## I. Strategic Principles

### 1. Zero Lock-In

All platform decisions must keep exit costs bounded.

### 2. Own Your Data

Data residency is non-negotiable.
"""


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def build_tree_a(root: Path) -> Path:
    """Valid ADMP + REQ + OAAL + PRIN; STKE deliberately missing."""
    _write(root, "projects/001-underwriting/ARC-001-ADMP-v1.0.md", ADMP_V1)
    _write(root, "projects/001-underwriting/ARC-001-REQ-v1.0.md", REQ_V1)
    _write(root, "projects/001-underwriting/ARC-001-OAAL-v1.0.md", OAAL_V1)
    _write(root, "projects/000-global/ARC-000-PRIN-v1.0.md", PRIN_V1)
    return root


def build_tree_b(root: Path) -> Path:
    """Tree A plus a malformed REQ v2.0 (required Business Context missing)."""
    build_tree_a(root)
    bad_req = REQ_V1.replace(
        "### Business Context\n\nInsurers struggle with slow, opaque underwriting decisions. This project\ndelivers an explainable decisioning platform for motor lines.",
        "### Business Context\n",
    ).replace("ARC-001-REQ-v1.0", "ARC-001-REQ-v2.0")
    assert "This project" not in bad_req
    _write(root, "projects/001-underwriting/ARC-001-REQ-v2.0.md", bad_req)
    return root


def build_tree_c(root: Path) -> Path:
    """Two projects, each with its own REQ (project_id filter test)."""
    _write(root, "projects/001-alpha/ARC-001-REQ-v1.0.md",
           REQ_V1.replace("Underwriting Platform", "Alpha Platform"))
    _write(root, "projects/002-beta/ARC-002-REQ-v1.0.md",
           REQ_V1.replace("Underwriting Platform", "Beta Platform")
                 .replace("ARC-001-REQ-v1.0", "ARC-002-REQ-v1.0"))
    return root


# ── Discovery & precedence (§1–§2) ───────────────────────────────────────────

class TestDiscovery:
    def test_happy_tree_auto_populates(self, tmp_path):
        build_tree_a(tmp_path)
        ctx = load_arckit_artifacts(str(tmp_path))
        assert isinstance(ctx, ArcKitContext)
        assert ctx.has_valid_artifacts
        assert ctx.project_id == "001"
        # §1.1: ADMP Document Control wins for project_name
        assert ctx.project_name == "Underwriting Platform"
        # §3.4.1: ADMP §1 narrative is the primary description
        assert "decisioning service" in ctx.project_description
        assert len(ctx.project_description) <= 500
        # §2.5: PRIN is org-global, consumed despite project_id=001
        prin = [r for r in ctx.records if r.type == "PRIN"]
        assert len(prin) == 1 and prin[0].schema_valid
        assert "Zero Lock-In" in ctx.principles

    def test_no_artifacts(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        ctx = load_arckit_artifacts(str(tmp_path))
        assert not ctx.has_valid_artifacts
        assert ctx.records == []
        codes = [c for c, _ in ctx.errors]
        assert NO_ARTIFACTS in codes
        assert ctx.audit["summary"]["fallbackToInterview"] is True

    def test_missing_root(self):
        ctx = load_arckit_artifacts("/nonexistent/arckit/root")
        assert not ctx.has_valid_artifacts
        assert [c for c, _ in ctx.errors] == [NO_ARTIFACTS]

    def test_project_id_filter_scopes_selection(self, tmp_path):
        build_tree_c(tmp_path)
        ctx = load_arckit_artifacts(str(tmp_path), project_id="001")
        reqs = [r for r in ctx.records if r.type == "REQ"]
        assert len(reqs) == 1
        assert "001-alpha" in reqs[0].path
        assert ctx.project_name == "Alpha Platform"

    def test_pid_mismatch_ignored(self, tmp_path):
        # A REQ whose filename project id does not match its directory must
        # not leak into project 001 (§2 step 4).
        build_tree_a(tmp_path)
        _write(tmp_path, "projects/001-underwriting/ARC-002-REQ-v1.0.md",
               REQ_V1.replace("ARC-001-REQ-v1.0", "ARC-002-REQ-v1.0"))
        ctx = load_arckit_artifacts(str(tmp_path), project_id="001")
        reqs = [r for r in ctx.records if r.type == "REQ"]
        assert len(reqs) == 1
        assert "ARC-001-REQ" in Path(reqs[0].path).name

    def test_highest_version_wins(self, tmp_path):
        build_tree_a(tmp_path)
        v2 = REQ_V1.replace("ARC-001-REQ-v1.0", "ARC-001-REQ-v2.0")
        _write(tmp_path, "projects/001-underwriting/ARC-001-REQ-v2.0.md", v2)
        ctx = load_arckit_artifacts(str(tmp_path))
        reqs = [r for r in ctx.records if r.type == "REQ"]
        assert len(reqs) == 1
        assert reqs[0].version == "v2.0"

    def test_context_folder_at_project_dir(self, tmp_path):
        # context_folder pointing directly at the project dir (no projects/)
        proj = tmp_path / "001-underwriting"
        _write(proj, "ARC-001-ADMP-v1.0.md", ADMP_V1)
        ctx = load_arckit_artifacts(str(proj))
        assert ctx.has_valid_artifacts
        assert ctx.project_name == "Underwriting Platform"


# ── Validation & error taxonomy (§5, §6) ─────────────────────────────────────

class TestValidation:
    def test_malformed_req_v2_excluded(self, tmp_path):
        build_tree_b(tmp_path)
        ctx = load_arckit_artifacts(str(tmp_path))
        reqs = [r for r in ctx.records if r.type == "REQ"]
        # highest version (v2.0) selected and rejected — no REQ usable
        assert len(reqs) == 1
        assert reqs[0].version == "v2.0"
        assert not reqs[0].schema_valid
        assert any("Business Context" in e for e in reqs[0].errors)
        # ADMP still valid → context auto-populates from the valid subset
        assert ctx.has_valid_artifacts
        assert "ARC-001-ADMP" in ctx.audit["artefacts"][0]["path"] or any(
            "ADMP" in a["type"] and a["schemaValid"] for a in ctx.audit["artefacts"]
        )
        assert ctx.audit["summary"]["malformed"] >= 1

    def test_superseded_skipped(self, tmp_path):
        build_tree_a(tmp_path)
        _write(tmp_path, "projects/001-underwriting/ARC-001-STKE-v1.0.md",
               """# Stakeholder Drivers & Goals Analysis: Underwriting Platform

## Document Control

| Field | Value |
|-------|-------|
| Document ID | ARC-001-STKE-v1.0 |
| Project | Underwriting Platform |
| Status | SUPERSEDED |

## Stakeholder Identification

### Internal Stakeholders

| Name | Role | Influence | Interest | Engagement Strategy |
|------|------|-----------|----------|---------------------|
| Carol | CTO | HIGH | HIGH | Manage Closely |

## Stakeholder Drivers Analysis

### SD-1: CTO

- **Driver Statement**: Platform must stay ahead of model drift
- **Intensity**: HIGH
""")
        ctx = load_arckit_artifacts(str(tmp_path))
        stke = [r for r in ctx.records if r.type == "STKE"]
        assert len(stke) == 1
        assert stke[0].status == "SUPERSEDED"
        assert not stke[0].schema_valid
        assert ARTIFACT_SUPERSEDED in [c for c, _ in ctx.errors]
        assert ctx.audit["summary"]["superseded"] == 1
        # superseded STKE must not leak into seeds
        assert not any("Carol" in str(s) for s in ctx.seeds["stakeholders"])

    def test_frontmatter_doctype_mismatch(self, tmp_path):
        build_tree_a(tmp_path)
        bad = ADMP_V1.replace("docType: ADMP", "docType: REQ")
        _write(tmp_path, "projects/001-underwriting/ARC-001-ADMP-v2.0.md",
               bad.replace("ARC-001-ADMP-v1.0", "ARC-001-ADMP-v2.0"))
        ctx = load_arckit_artifacts(str(tmp_path))
        admps = [r for r in ctx.records if r.type == "ADMP"]
        assert admps[0].version == "v2.0"
        assert not admps[0].schema_valid
        assert any(MALFORMED_ARTIFACT in e for e in admps[0].errors)

    def test_unparseable_frontmatter(self, tmp_path):
        build_tree_a(tmp_path)
        # A real frontmatter fence whose YAML fails to parse → MALFORMED (§6.3 step 2)
        bad = "---\ndocType: [ADMP\n---\n" + ADMP_V1.split("---", 2)[2]
        _write(tmp_path, "projects/001-underwriting/ARC-001-ADMP-v3.0.md",
               bad.replace("ARC-001-ADMP-v1.0", "ARC-001-ADMP-v3.0"))
        ctx = load_arckit_artifacts(str(tmp_path))
        admps = [r for r in ctx.records if r.type == "ADMP"]
        assert admps[0].version == "v3.0"
        assert not admps[0].schema_valid
        assert any("frontmatter" in e.lower() for e in admps[0].errors)


# ── Extraction (§3.4) ────────────────────────────────────────────────────────

class TestExtraction:
    def setup_method(self, method):
        import pytest
        self._tmp = pytest.importorskip("tempfile").TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_tree_a(self.root)
        self.ctx = load_arckit_artifacts(str(self.root))

    def teardown_method(self, method):
        self._tmp.cleanup()

    def _parsed(self, type_code):
        for r in self.ctx.records:
            if r.type == type_code and r.schema_valid:
                return r.parsed
        raise AssertionError(f"no valid {type_code}")

    def test_admp_fields(self):
        p = self._parsed("ADMP")
        assert p["project"] == "Underwriting Platform"
        assert p["status"] == "APPROVED"
        assert len(p["scope_in"]) == 3
        assert len(p["scope_out"]) == 2
        assert len(p["success_criteria"]) == 3
        assert p["success_criteria"][0]["criterion"] == "Quote turnaround"
        assert [s["name"] for s in p["stakeholders"]] == ["Alice", "Bob"]
        assert len(p["drivers"]) == 2
        assert len(p["constraints"]) == 2

    def test_req_fields(self):
        p = self._parsed("REQ")
        assert p["business_context"].startswith("Insurers struggle")
        assert len(p["objectives"]) == 2
        assert p["brs"][0]["id"].lower() == "br-001"
        assert p["brs"][0]["priority"] == "MUST_HAVE"
        assert p["frs"][0]["id"].lower() == "fr-001"
        assert p["personas"]
        assert "p95 under 500ms" in p["nfrs"][list(p["nfrs"])[0]]
        assert p["integrations"][0]["purpose"] == "Sync policies"
        assert p["data_entities"][0]["description"] == "A quote request"
        assert any("TC-1" in c for c in p["constraints"])

    def test_oaal_fields(self):
        p = self._parsed("OAAL")
        assert p["header"]["template"] == "O-AA ADM Lite"
        assert p["header"]["sprint length"] == "2 weeks"
        assert len(p["sprint_map"]) == 2
        assert p["sprint_map"][0]["sprint"] == "Sprint 0"
        # §3.4.4: OAAL seeds context_folder when it references a repo
        assert self.ctx.context_folder_hint == "projects/001-underwriting"

    def test_prin_fields(self):
        p = self._parsed("PRIN")
        assert p["organization"].startswith("Acme Insurance")
        assert "Zero Lock-In" in p["principles"]
        assert "Own Your Data" in p["principles"]
        assert "Strategic Principles" not in p["principles"]

    def test_stakeholder_merge_dedup(self):
        # Alice appears in ADMP §8 and REQ §Stakeholders — merged once
        names = [s.get("name", "").lower() for s in self.ctx.seeds["stakeholders"]]
        assert names.count("alice") == 1

    def test_sprint_map_handoff(self):
        assert self.ctx.sprint_map
        assert json.dumps(self.ctx.sprint_map)  # serializable for artifacts


# ── Interview synthesis (§4.2) ───────────────────────────────────────────────

class TestInterviewSynthesis:
    def setup_method(self, method):
        import pytest
        self._tmp = pytest.importorskip("tempfile").TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_tree_a(self.root)
        self.ctx = load_arckit_artifacts(str(self.root))

    def teardown_method(self, method):
        self._tmp.cleanup()

    def test_all_contract_headings_present(self):
        notes = synthesize_interview_notes(self.ctx)
        for heading in (
            "Project Overview", "Core Behavior", "Data Model", "API Surface",
            "Stakeholders", "Success Criteria", "Constraints",
            "Non-Functional Requirements", "Edge Cases",
            "Architecture Principles", "Delivery Shape (Sprint Map)",
        ):
            assert f"## {heading}" in notes, f"missing §4.2 heading: {heading}"

    def test_deterministic(self):
        assert synthesize_interview_notes(self.ctx) == synthesize_interview_notes(self.ctx)

    def test_content_from_artifacts(self):
        notes = synthesize_interview_notes(self.ctx)
        assert "decisioning service" in notes          # ADMP §1
        assert "BR-001" in notes                       # REQ BR
        assert "FR-001" in notes                       # REQ FR
        assert "Alice" in notes                        # stakeholder merge
        assert "Sprint 0" in notes                     # OAAL handoff
        assert "Zero Lock-In" in notes                 # PRIN

    def test_truncation_limits(self):
        notes = synthesize_interview_notes(self.ctx)
        # description capped at 500 (§3.4.1), principles at 1000 (§3.4.5)
        assert len(self.ctx.project_description) <= 500
        assert len(self.ctx.principles) <= 1000
