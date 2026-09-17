"""Tier-2 ArcKit ingestion — P1 wave (spec: arckit-tier2-ingestion).

Tasks 5–7: OASTR extractor + `arckit_strategy_waves`, TRANS wave fallback
(OASTR wins, neither → unset), BPCM + GAPA seed/notes merge. All types
discovered via the canonical globs and audited per §6.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_arckit_loader import _write, build_tree_a
from tools.arckit_loader import load_arckit_artifacts, synthesize_interview_notes

FIXTURES = Path(__file__).parent / "fixtures" / "arckit"
OASTR_DUMMY = FIXTURES / "oaa-dummy" / "ARC-001-OASTR-v1.0.md"
TRANS_DUMMY = FIXTURES / "oaa-dummy" / "ARC-001-TRANS-v1.0.md"
TRANS_ADM = FIXTURES / "adm-australian-post" / "ARC-001-TRANS-v1.0.md"
BPCM_ADM = FIXTURES / "adm-australian-post" / "ARC-001-BPCM-v1.0.md"
GAPA_ADM = FIXTURES / "adm-australian-post" / "ARC-001-GAPA-v1.0.md"


def _tree_with(root: Path, *files: Path) -> Path:
    """Copy fixture artefacts into a `projects/001-underwriting/` tree."""
    target = root / "projects" / "001-underwriting"
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        (target / f.name).write_text(f.read_text())
    return root


# ── 5.1: OASTR extractor + strategy waves ────────────────────────────────────


class TestOastrExtraction:
    def test_oastr_valid_and_parsed(self, tmp_path):
        tree = _tree_with(tmp_path, OASTR_DUMMY)
        ctx = load_arckit_artifacts(str(tree))
        rec = next(r for r in ctx.records if r.type == "OASTR")
        assert rec.schema_valid, rec.errors
        p = rec.parsed
        assert p["document_id"] == "ARC-001-OASTR-v1.0"
        dims = {d.get("dimension", ""): d.get("description", "") for d in p["dimensions"]}
        assert "Customer Segments" in dims and "Value Proposition" in dims
        assert p["defend"], "defend track rows missing"
        assert p["attack"], "attack track rows missing"
        assert [w["wave"] for w in p["waves"]] == ["1", "2", "3"]
        w1 = p["waves"][0]
        assert "Quick Wins" in w1["title"]
        assert "Security hardening" in w1["defend"]
        assert "Secure baseline" in w1["outcome"]

    def test_strategy_waves_from_oastr(self, tmp_path):
        ctx = load_arckit_artifacts(str(_tree_with(tmp_path, OASTR_DUMMY)))
        assert [w["wave"] for w in ctx.strategy_waves] == ["1", "2", "3"]

    def test_oastr_objectives_and_outcome_seeds(self, tmp_path):
        ctx = load_arckit_artifacts(str(_tree_with(tmp_path, OASTR_DUMMY)))
        joined = "\n".join(ctx.seeds["objectives"])
        assert "Value Proposition" in joined
        outcomes = "\n".join(ctx.seeds["outcomes"])
        assert "Secure baseline" in outcomes

    def test_oastr_without_canvas_is_malformed(self, tmp_path):
        _write(
            tmp_path, "projects/001-underwriting/ARC-001-OASTR-v1.0.md",
            "\n".join(
                [
                    "# Agile Strategy Canvas",
                    "",
                    "## 1. Introduction",
                    "Just prose, no canvas.",
                    "",
                    "## 4. Transformation Sequencing",
                    "### Wave 1: Solo",
                    "- **Defend**: x",
                    "- **Attack**: y",
                    "- **Outcome**: z",
                ]
            ),
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        rec = next(r for r in ctx.records if r.type == "OASTR")
        assert rec.schema_valid is False
        assert any("canvas" in e.lower() for e in rec.errors)


# ── 6.1: TRANS wave fallback ──────────────────────────────────────────────────


class TestTransFallback:
    def test_trans_waves_when_no_oastr(self, tmp_path):
        tree = _tree_with(tmp_path, BPCM_ADM, GAPA_ADM, TRANS_ADM)
        ctx = load_arckit_artifacts(str(tree))
        assert [w["wave"] for w in ctx.strategy_waves] == ["1", "2"]
        w1 = ctx.strategy_waves[0]
        assert w1["name"] == "Foundation & Hardening"
        assert "AU-resident" in w1["objective"]
        assert w1["governance_gate"].startswith("Wave 1 Complete")
        assert "AU-resident data platform live" in w1["key_deliverables"][0]

    def test_oastr_beats_trans(self, tmp_path):
        tree = _tree_with(tmp_path, OASTR_DUMMY, TRANS_DUMMY)
        ctx = load_arckit_artifacts(str(tree))
        # OASTR rows carry a `title` key; TRANS rows carry `name`
        assert "title" in ctx.strategy_waves[0]
        assert "name" not in ctx.strategy_waves[0]

    def test_unset_when_neither_present(self, tmp_path):
        ctx = load_arckit_artifacts(
            str(_tree_with(tmp_path, FIXTURES / "parceltrack" / "ARC-001-OAPR-v1.0.md"))
        )
        assert ctx.strategy_waves == []

    def test_trans_without_waves_is_malformed(self, tmp_path):
        _write(
            tmp_path, "projects/001-underwriting/ARC-001-TRANS-v1.0.md",
            "\n".join(
                [
                    "# Transition Architecture",
                    "",
                    "## 1. Transition Overview",
                    "",
                    "| Architecture | Scope | Duration | Investment |",
                    "|--------------|-------|----------|------------|",
                    "| Architecture 1 (Baseline) | Current state | — | — |",
                ]
            ),
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        rec = next(r for r in ctx.records if r.type == "TRANS")
        assert rec.schema_valid is False


# ── 7.1: BPCM + GAPA seeds ────────────────────────────────────────────────────


class TestBpcmGapaSeeds:
    def test_bpcm_valid_and_parsed(self, tmp_path):
        tree = _tree_with(tmp_path, BPCM_ADM)
        ctx = load_arckit_artifacts(str(tree))
        rec = next(r for r in ctx.records if r.type == "BPCM")
        assert rec.schema_valid, rec.errors
        p = rec.parsed
        assert len(p["hierarchy"]["l1"]) == 5
        assert p["hierarchy"]["l1"][0]["domain_id"] == "C1.0"
        assert len(p["maturity"]) == 5
        assert p["maturity"][0]["capability"] == "C1.0 Customer Digital Experience"
        assert len(p["value_stream"]) == 5

    def test_bpcm_capabilities_section_in_notes(self, tmp_path):
        ctx = load_arckit_artifacts(str(_tree_with(tmp_path, BPCM_ADM)))
        notes = synthesize_interview_notes(ctx)
        assert "## Capabilities" in notes
        assert "C1.0 Customer Digital Experience" in notes
        assert "VS-001" in notes
        assert "L2" in notes and "L4" in notes

    def test_bpcm_without_hierarchy_is_malformed(self, tmp_path):
        _write(
            tmp_path, "projects/001-underwriting/ARC-001-BPCM-v1.0.md",
            "\n".join(
                [
                    "# Business Capability Map",
                    "",
                    "## 1. Capability Hierarchy",
                    "Prose only, no tables in this depth.",
                ]
            ),
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        rec = next(r for r in ctx.records if r.type == "BPCM")
        assert rec.schema_valid is False

    def test_gapa_valid_and_parsed(self, tmp_path):
        tree = _tree_with(tmp_path, GAPA_ADM)
        ctx = load_arckit_artifacts(str(tree))
        rec = next(r for r in ctx.records if r.type == "GAPA")
        assert rec.schema_valid, rec.errors
        p = rec.parsed
        assert len(p["gaps"]) == 5
        assert p["gaps"][1]["capability"].startswith("C2.0")
        assert len(p["risk_mappings"]) == 3
        assert len(p["constraints"]) == 3

    def test_gapa_seeds_constraints_and_risks(self, tmp_path):
        ctx = load_arckit_artifacts(str(_tree_with(tmp_path, GAPA_ADM)))
        constraints = "\n".join(ctx.seeds["constraints"])
        assert "C2.0: Logistics Data & Insights: L1 → L4" in constraints
        assert "$12M AUD" in constraints
        risks = "\n".join(ctx.seeds["risks"])
        assert "G-002" in risks and "APP-11" in risks

    def test_gapa_without_content_is_malformed(self, tmp_path):
        _write(
            tmp_path, "projects/001-underwriting/ARC-001-GAPA-v1.0.md",
            "\n".join(["# Gap Analysis", "", "## 1. Capability Gap Matrix", ""]),
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        rec = next(r for r in ctx.records if r.type == "GAPA")
        assert rec.schema_valid is False

    def test_all_p1_types_audited(self, tmp_path):
        tree = _tree_with(tmp_path, BPCM_ADM, GAPA_ADM, TRANS_ADM)
        ctx = load_arckit_artifacts(str(tree))
        valid = {r.type for r in ctx.records if r.schema_valid}
        assert {"BPCM", "GAPA", "TRANS"} <= valid
        assert ctx.audit["summary"]["valid"] == 3

    def test_p1_types_discovered_via_canonical_globs(self, tmp_path):
        tree = _tree_with(tmp_path, BPCM_ADM, GAPA_ADM, TRANS_ADM)
        ctx = load_arckit_artifacts(str(tree))
        types = {r.type for r in ctx.records}
        assert {"BPCM", "GAPA", "TRANS"} <= types


# ── 5.2: DISCOVER writes arckit_strategy_waves ───────────────────────────────


class TestDiscoverStrategyWaves:
    """DISCOVER node writes `arckit_strategy_waves` (node-level, mocked LLM)."""

    @pytest.fixture
    def mock_llm(self, monkeypatch):
        import graph.nodes.discover  # noqa: F401  ensure module before patch

        def fake(*args, **kwargs):
            return "[MOCK-LLM]"

        monkeypatch.setattr("tools.llm.invoke_skill", fake)
        monkeypatch.setattr("graph.nodes.discover.invoke_skill", fake)
        monkeypatch.setattr(
            "graph.nodes.discover._refine_idea", lambda *a, **k: "[MOCK-REFINE]"
        )
        monkeypatch.setattr(
            "graph.nodes.discover._build_context", lambda *a, **k: "{}"
        )
        monkeypatch.setattr(
            "graph.nodes.discover._generate_requirement_via_fabric",
            lambda *a, **k: "# Mock requirement\n",
        )

        async def fast_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("asyncio.to_thread", fast_to_thread)
        return fake

    def test_strategy_waves_key_written_when_oastr_valid(self, tmp_path, mock_llm):
        import json

        from tests.test_discover_arckit import _run

        tree = _tree_with(tmp_path / "arckit", OASTR_DUMMY)
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)
        waves = json.loads(result["artifacts"]["arckit_strategy_waves"])
        assert [w["wave"] for w in waves] == ["1", "2", "3"]

    def test_strategy_waves_key_absent_when_neither(self, tmp_path, mock_llm):
        from tests.test_discover_arckit import _run

        # No OASTR and no TRANS in this tree -> key must stay unset.
        tree = build_tree_a(tmp_path / "arckit")
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)
        assert "arckit_strategy_waves" not in result["artifacts"]
