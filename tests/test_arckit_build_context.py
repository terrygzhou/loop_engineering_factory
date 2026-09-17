"""W3 arckit-build-context — loader extractors for DATA / TECH / OASEC /
OAA-ADM-lite (tasks 1.1-1.7).

Fixtures:
- build-context/   : full tree — DATA + TECH + OASEC + vision.md (OAA-ADM-lite)
- adm-data-tech/   : partial tree — DATA + TECH only
- oaa-lite-neg/    : DISC.md with NO fenced vision block (must not ingest)
- oaa-lite-canonical/ : canonical ARC-NNN-OAAL file carrying a vision block
                        (canonical type wins; lite fallback must not claim it)
"""

from __future__ import annotations

from pathlib import Path

from tools.arckit_loader import load_arckit_artifacts

FIXTURES = Path(__file__).parent / "fixtures" / "arckit"
FULL_TREE = FIXTURES / "build-context"
PARTIAL_TREE = FIXTURES / "adm-data-tech"
LITE_NEG = FIXTURES / "oaa-lite-neg"
LITE_CANON = FIXTURES / "oaa-lite-canonical"
VISION_MD = FULL_TREE / "vision.md"


def _lite_types(ctx) -> list[str]:
    return [r.type for r in ctx.records if r.type == "OAA-ADM-lite"]


# ── 1.2 DATA extractor ───────────────────────────────────────────────────────


class TestDataExtractor:
    def test_data_discovered_and_parsed(self):
        ctx = load_arckit_artifacts(str(PARTIAL_TREE))
        data = [r for r in ctx.records if r.type == "DATA"]
        assert len(data) == 1
        assert data[0].schema_valid
        assert ctx.data_model, "data_model must be set when a valid DATA exists"

    def test_data_entities_parsed(self):
        ctx = load_arckit_artifacts(str(PARTIAL_TREE))
        entities = ctx.data_model["entities"]
        assert entities
        names = [e.get("entity") or e.get("entity_name") for e in entities]
        assert "Policyholder (golden record)" in names
        # MPC-insurance DATA §2 catalog rows carry domain + classification
        row = next(e for e in entities if e.get("entity") == "Policy")
        assert row.get("domain") == "Policy"
        assert row.get("classification") == "Internal"

    def test_data_domains_and_classification(self):
        ctx = load_arckit_artifacts(str(PARTIAL_TREE))
        domains = ctx.data_model.get("domains", [])
        # MPC DATA has no "Data Domains" table — the extractor derives the
        # distinct domain values from the entity catalog rows (dict rows).
        assert domains
        assert any(d.get("domain") == "Claim" for d in domains), domains

    def test_data_partial_tree_leaves_others_unset(self):
        ctx = load_arckit_artifacts(str(PARTIAL_TREE))
        assert ctx.security_controls == {}
        assert ctx.nfr_constraints == {}


# ── 1.3 TECH extractor ───────────────────────────────────────────────────────


class TestTechExtractor:
    def test_tech_tables_parsed(self):
        ctx = load_arckit_artifacts(str(PARTIAL_TREE))
        istd = ctx.integration_standards
        assert istd, "integration_standards must be set when a valid TECH exists"
        assert any(
            r.get("standard") == "REST" for r in istd["api_standards"]
        ), istd["api_standards"]
        assert any(
            r.get("pattern") == "Event Streaming" for r in istd["messaging_patterns"]
        ), istd["messaging_patterns"]
        assert any(
            r.get("control") == "Authentication" for r in istd["integration_security"]
        ), istd["integration_security"]


# ── 1.4 OASEC extractor ──────────────────────────────────────────────────────


class TestOasecExtractor:
    def test_oasec_controls_parsed(self):
        ctx = load_arckit_artifacts(str(FULL_TREE))
        sc = ctx.security_controls
        assert sc, "security_controls must be set when a valid OASEC exists"
        assert any(
            "Secure by design" in str(r.get("pillar", "")) for r in sc.get("pillars", [])
        ), sc.get("pillars")
        assert any(
            r.get("sprint") == "Sprint 1" for r in sc.get("threats", [])
        ), sc.get("threats")
        assert any(
            "No secrets in repo" in str(r.get("guardrail", ""))
            for r in sc.get("guardrails", [])
        ), sc.get("guardrails")


# ── 1.5 OAA-ADM-lite extractor ──────────────────────────────────────────────


class TestOaaAdmLiteExtractor:
    def test_vision_md_ingested_as_lite(self):
        ctx = load_arckit_artifacts(str(FULL_TREE))
        lites = _lite_types(ctx)
        assert lites == ["OAA-ADM-lite"]
        rec = next(r for r in ctx.records if r.type == "OAA-ADM-lite")
        assert rec.schema_valid
        assert rec.version == "v1.0"
        assert rec.parsed.get("document_id") == "ARC-001-VIS-v1.0"

    def test_nfr_constraints_fields(self):
        ctx = load_arckit_artifacts(str(FULL_TREE))
        nfr = ctx.nfr_constraints
        assert nfr, "nfr_constraints must be set when a valid OAA-ADM-lite exists"
        assert nfr["use_cases"] == [
            "customer_tracking_qa",
            "document_analysis",
            "route_logistics_advisory",
        ]
        assert nfr["user_count"] == 5000
        assert nfr["latency_requirement_ms"] == 2000
        assert nfr["budget_aud"] == 1500000
        assert nfr["infrastructure"] == "hybrid"
        assert nfr["jurisdiction"] == "AU"
        assert nfr["data_classification"] == "regulated"

    def test_no_vision_block_not_ingested(self):
        ctx = load_arckit_artifacts(str(LITE_NEG))
        assert _lite_types(ctx) == []
        assert ctx.nfr_constraints == {}

    def test_canonical_named_file_not_reclaimed_as_lite(self):
        """A canonical ARC-NNN-OAAL file with a vision block stays OAAL."""
        ctx = load_arckit_artifacts(str(LITE_CANON))
        assert _lite_types(ctx) == []
        assert ctx.nfr_constraints == {}
        assert any(r.type == "OAAL" for r in ctx.records)

    def test_lite_via_projects_primary_glob(self, tmp_path):
        proj = tmp_path / "projects" / "007-vision"
        proj.mkdir(parents=True)
        (proj / "vision.md").write_text(VISION_MD.read_text())
        ctx = load_arckit_artifacts(str(tmp_path))
        assert _lite_types(ctx) == ["OAA-ADM-lite"]

    def test_lite_in_explicit_files_mode(self):
        """files= mode must bypass the canonical-filename check for lite."""
        ctx = load_arckit_artifacts("", files=[str(VISION_MD)])
        assert _lite_types(ctx) == ["OAA-ADM-lite"]
        assert ctx.nfr_constraints["use_cases"]


# ── 1.6 malformed build-context artefacts: audit + skip, never fatal ───────


class TestMalformedBuildContext:
    def test_data_without_entities_is_invalid_and_skipped(self, tmp_path):
        good = PARTIAL_TREE / "ARC-000-DATA-v1.0.md"
        (tmp_path / "ARC-000-DATA-v1.0.md").write_text(
            good.read_text().split("## 2. Data Entities Catalog")[0]
            + "## 2. Data Entities Catalog\n\nNo tables here, just prose.\n"
        )
        (tmp_path / "ARC-000-TECH-v1.0.md").write_text(
            (PARTIAL_TREE / "ARC-000-TECH-v1.0.md").read_text()
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        data = next(r for r in ctx.records if r.type == "DATA")
        assert not data.schema_valid
        assert any("SCHEMA_VALIDATION_FAILED" in e for e in data.errors)
        # malformed DATA is skipped, valid TECH still consumed — never fatal
        assert any(
            r.type == "TECH" and r.schema_valid for r in ctx.records
        )
        assert ctx.data_model == {}
        assert ctx.integration_standards

    def test_vision_without_use_cases_is_invalid(self, tmp_path):
        text = VISION_MD.read_text().replace(
            'use_cases: ["customer_tracking_qa", "document_analysis", "route_logistics_advisory"]',
            "use_cases: []",
        )
        (tmp_path / "vision.md").write_text(text)
        ctx = load_arckit_artifacts(str(tmp_path))
        lites = _lite_types(ctx)
        assert lites == ["OAA-ADM-lite"]
        rec = next(r for r in ctx.records if r.type == "OAA-ADM-lite")
        assert not rec.schema_valid
        assert ctx.nfr_constraints == {}

    def test_broken_yaml_vision_is_malformed_not_fatal(self, tmp_path):
        body = VISION_MD.read_text().split("```yaml")[0]
        (tmp_path / "vision.md").write_text(
            body + "```yaml\nvision: {scope: [broken\n```\n"
        )
        ctx = load_arckit_artifacts(str(tmp_path))
        assert ctx.nfr_constraints == {}
        recs = _lite_types(ctx)
        assert len(recs) == 1  # recorded, skipped — scan completed
        audit = ctx.audit
        assert any("vision" in e.lower() for e in audit["errors"]), audit["errors"]
