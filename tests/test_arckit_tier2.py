"""Tier-2 ArcKit ingestion — P0 wave: OAPR (spec: arckit-tier2-ingestion).

Covers tasks 2.1(a)–(f): discovery of OAPR via the canonical globs,
extraction of mission/outcome/backlog/D1–D10 coverage, description
precedence, open-questions synthesis, and DISCOVER artifact keys
(`arckit_product_backlog`, `arckit_open_questions`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_arckit_loader import ADMP_V1, REQ_V1, _write, build_tree_a
from tools.arckit_loader import load_arckit_artifacts, synthesize_interview_notes

FIXTURES = Path(__file__).parent / "fixtures" / "arckit"
OAPR_DUMMY = FIXTURES / "oaa-dummy" / "ARC-001-OAPR-v1.0.md"
OAPR_PARCEL = FIXTURES / "parceltrack" / "ARC-001-OAPR-v1.0.md"


def _tree_with_oapr(root: Path, oapr: Path) -> Path:
    """Full Tier-1 tree + one OAPR artefact; mirrors real generated trees."""
    build_tree_a(root)
    target = root / "projects/001-underwriting"
    target.mkdir(parents=True, exist_ok=True)
    (target / oapr.name).write_text(oapr.read_text())
    return root


# ── 2.1(a): OAPR discovery ────────────────────────────────────────────────────


class TestOaprDiscovery:
    def test_oapr_discovered_via_primary_glob(self, tmp_path):
        tree = _tree_with_oapr(tmp_path, OAPR_DUMMY)
        ctx = load_arckit_artifacts(str(tree))
        types = [r.type for r in ctx.records]
        assert "OAPR" in types
        oapr = next(r for r in ctx.records if r.type == "OAPR")
        assert oapr.schema_valid
        assert oapr.errors == []

    def test_oapr_schema_validation_requires_mission_and_backlog(self, tmp_path):
        bad = OAPR_DUMMY.read_text().replace("### 1.1 Product Mission Statement", "")
        _write(tmp_path, "projects/001-underwriting/ARC-001-OAPR-v1.0.md", bad)
        ctx = load_arckit_artifacts(str(tmp_path), project_id="001")
        oapr = next(r for r in ctx.records if r.type == "OAPR")
        assert not oapr.schema_valid
        assert oapr.errors  # recorded, scan not aborted

    def test_oapr_highest_version_wins(self, tmp_path):
        text = OAPR_DUMMY.read_text()
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md", text)
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v2.0.md", text.replace(
            "# Agile Product Architecture", "# Agile Product Architecture v2"))
        ctx = load_arckit_artifacts(str(tmp_path), project_id="001")
        oapr = [r for r in ctx.records if r.type == "OAPR"]
        assert len(oapr) == 1
        assert oapr[0].version == "v2.0"

    def test_oapr_malformed_recorded_not_fatal(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-ADMP-v1.0.md", ADMP_V1)
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md", "no H1 here")
        ctx = load_arckit_artifacts(str(tmp_path))
        admp = next(r for r in ctx.records if r.type == "ADMP")
        oapr = next(r for r in ctx.records if r.type == "OAPR")
        assert admp.schema_valid
        assert not oapr.schema_valid
        assert ctx.has_valid_artifacts


# ── 2.1(b): OAPR extraction ──────────────────────────────────────────────────


class TestOaprExtraction:
    def test_mission_outcome_backlog_parsed(self, tmp_path):
        tree = _tree_with_oapr(tmp_path, OAPR_DUMMY)
        ctx = load_arckit_artifacts(str(tree))
        parsed = next(r.parsed for r in ctx.records if r.type == "OAPR")
        assert parsed["mission"]
        assert "platform" in parsed["mission"].lower() or "core" in parsed["mission"].lower()
        assert parsed["outcome"]  # §1.2 table rows
        assert parsed["backlog"]  # §3 table rows
        assert parsed["d_dimensions"]  # §7 rows when present; absent on dummy

    def test_parceltrack_mission_and_backlog(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md",
               OAPR_PARCEL.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        parsed = next(r.parsed for r in ctx.records if r.type == "OAPR")
        assert "ParcelTrack" in parsed["mission"]
        assert "real-time parcel visibility" in parsed["mission"]
        assert [r.get("Epic") for r in parsed["backlog"]] == [
            "A — Real-time tracking pipeline",
            "B — AI delivery advisory",
            "C — Customer comms automation",
        ]

    def test_parceltrack_tbd_dimensions_yield_open_questions(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md",
               OAPR_PARCEL.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        parsed = next(r.parsed for r in ctx.records if r.type == "OAPR")
        oq = parsed["open_questions"]
        dims = {q["dimension"] for q in oq}
        assert dims == {"D2", "D5", "D8"}
        for q in oq:
            assert q["question"].strip()
        q2 = next(q for q in oq if q["dimension"] == "D2")
        assert "business capabilities" in q2["question"]


# ── 2.1(c): description precedence ADMP → REQ → OAPR ─────────────────────────


class TestDescriptionPrecedence:
    def test_admp_wins_over_oapr(self, tmp_path):
        tree = _tree_with_oapr(tmp_path, OAPR_DUMMY)
        ctx = load_arckit_artifacts(str(tree))
        assert "decisioning service" in ctx.project_description

    def test_req_wins_when_admp_absent(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-REQ-v1.0.md", REQ_V1)
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md",
               OAPR_PARCEL.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        assert "Underwriting Platform" in ctx.project_description
        assert "ParcelTrack" not in ctx.project_description

    def test_oapr_mission_when_only_oapr(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md",
               OAPR_PARCEL.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        assert "ParcelTrack" in ctx.project_description
        assert "real-time parcel visibility" in ctx.project_description
        assert len(ctx.project_description) <= 500

    def test_no_description_sources(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        ctx = load_arckit_artifacts(str(tmp_path))
        assert ctx.project_description == ""


# ── 2.1(d): open-questions interview section ─────────────────────────────────


class TestOpenQuestionsNotes:
    def test_section_emitted_when_tbd_rows_exist(self, tmp_path):
        _write(tmp_path, "projects/001-x/ARC-001-OAPR-v1.0.md",
               OAPR_PARCEL.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        notes = synthesize_interview_notes(ctx)
        assert "Open questions (OAPR D1–D10)" in notes
        assert "business capabilities" in notes
        assert "current state" in notes.lower()

    def test_no_section_when_full_coverage_or_absent(self, tmp_path):
        tree = _tree_with_oapr(tmp_path, OAPR_DUMMY)  # dummy OAPR: no D rows
        ctx = load_arckit_artifacts(str(tree))
        assert "Open questions (OAPR D1–D10)" not in synthesize_interview_notes(ctx)


# ── 2.1(e)/(f): DISCOVER artifact keys ────────────────────────────────────────


class TestDiscoverOaprKeys:
    """DISCOVER node writes the new artifact keys.

    The DISCOVER node makes several LLM/skill calls per run; in sandboxes
    where the configured LLM endpoint is unreachable (and where
    ``asyncio.to_thread`` worker hand-offs can stall), those calls would
    hang the test. ``invoke_skill`` is mocked (same pattern as
    TestDiscoverArcKitArtifactList) and the three LLM-backed helpers are
    replaced with deterministic fakes so the node runs end-to-end fast in
    any environment. The assertions target only the OAPR artifact keys,
    which the fakes do not touch."""

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

        # This sandbox stalls cross-thread asyncio hand-offs (~20 s); run the
        # node's sync helpers inline so the test is deterministic everywhere.
        async def fast_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("asyncio.to_thread", fast_to_thread)
        return fake

    def test_backlog_key_written_when_oapr_valid(self, tmp_path, mock_llm):
        from tests.test_discover_arckit import _run

        tree = _tree_with_oapr(tmp_path / "arckit", OAPR_DUMMY)
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)
        assert "arckit_product_backlog" in result["artifacts"]
        assert "arckit_open_questions" not in result["artifacts"]

    def test_open_questions_key_written_when_tbd_rows(self, tmp_path, mock_llm):
        from tests.test_discover_arckit import _run

        tree = _tree_with_oapr(tmp_path / "arckit", OAPR_PARCEL)
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)
        oq = result["artifacts"]["arckit_open_questions"]
        import json

        pairs = {q["dimension"] for q in json.loads(oq)}
        assert pairs == {"D2", "D5", "D8"}

    def test_no_keys_without_oapr(self, tmp_path, mock_llm):
        from tests.test_discover_arckit import _run

        tree = build_tree_a(tmp_path / "arckit")
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)
        assert "arckit_product_backlog" not in result["artifacts"]
        assert "arckit_open_questions" not in result["artifacts"]
