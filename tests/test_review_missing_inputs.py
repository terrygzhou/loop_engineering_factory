"""P0.5 — ARCH_REVIEW missing-build-inputs channel (arckit-tier2-ingestion).

User decision 2026-09-16: build-critical information still missing after
ArcKit ingestion is asked at the *existing* ARCH_REVIEW HIL gate — no new
pause, no routing change.

- interrupt payload gains ``missing_build_inputs`` (advisory) derived from
  ``artifacts.arckit_open_questions`` + "valuable but absent" ArcKit types
  (Tier-2 + W3 build-context DATA/TECH/OASEC/OAA-ADM-lite) in
  ``discover_artifact_audit``; the precomputed ``valuable_absent`` audit
  field is used when present (W3 arckit-build-context).
  in ``discover_artifact_audit``; field omitted when nothing is missing
  (byte-identical payload for non-ArcKit runs).
- resume accepts an optional ``answers`` mapping →
  ``artifacts.arch_review_answers`` (written when non-empty, both routes).
- ``openhands_build._build_prompt`` appends a "Review supplements" section
  only when answers exist.
"""

import json

import pytest

from graph.nodes import openhands_build
from graph.nodes import review as review_module
from graph.state import CycleMetrics


def _review_state(**over):
    base = {
        "cycle_id": "test-p05",
        "trace_id": "t-p05",
        "phase": "ARCH_REVIEW",
        "metrics": CycleMetrics(
            spec_confidence=0.95,
            arch_uncertainty=0.1,
            security_findings=0,
            review_revisions=0,
            uat_pass_rate=0.99,
        ),
        "context_folder": "",
        "project_path": "/tmp/proj",
        "auto_approve_override": False,
        "artifacts": {"plan": "plan text", "spec_refined": "spec text"},
    }
    base.update(over)
    return base


def _audit_json(valid_types=(), malformed_types=()):
    """discover_artifact_audit JSON mirroring loader §6.4 record shape."""
    records = []
    for t in valid_types:
        records.append(
            {
                "type": t,
                "path": f"projects/001/{t}.md",
                "version": "1.0",
                "status": "OK",
                "frontmatter": True,
                "schemaValid": True,
                "fieldsExtracted": [],
                "errors": [],
            }
        )
    for t in malformed_types:
        records.append(
            {
                "type": t,
                "path": f"projects/001/{t}.md",
                "version": "1.0",
                "status": "MALFORMED",
                "frontmatter": False,
                "schemaValid": False,
                "fieldsExtracted": [],
                "errors": ["missing mission"],
            }
        )
    return json.dumps(
        {
            "scanned_root": "/x",
            "project_id": "001",
            "artefacts": records,
            "errors": [],
            "summary": {},
        }
    )


OQ_JSON = json.dumps(
    [
        {"dimension": "D2", "question": "What is the RTO target for the API?"},
        {"dimension": "D5", "question": "Which jurisdiction's privacy rules apply?"},
    ]
)


# ── 4.1(a)/(b): payload field derivation ────────────────────────────────────


class TestMissingBuildInputsPayload:
    def test_open_questions_and_valuable_absent_in_payload(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: (captured.__setitem__("payload", p), {"approved": True})[1],
        )
        out = review_module.review_node(
            _review_state(
                artifacts={
                    "plan": "p",
                    "spec_refined": "s",
                    "arckit_open_questions": OQ_JSON,
                    "discover_artifact_audit": _audit_json(
                        valid_types=("OAPR",), malformed_types=("OASTR",)
                    ),
                }
            )
        )
        payload = captured["payload"]
        items = payload["missing_build_inputs"]
        assert any("What is the RTO target for the API?" in i for i in items)
        assert any("Which jurisdiction's privacy rules apply?" in i for i in items)
        # advisory "valuable but absent" entries for the four types without
        # a valid record (OASTR malformed counts as absent)
        for t in ("OASTR", "BPCM", "GAPA", "TRANS"):
            assert any(t in i for i in items), f"{t} advisory missing"
        # W3 arckit-build-context: build-context types are valuable too —
        # absent from this audit, so all four are listed
        for t in ("DATA", "TECH", "OASEC", "OAA-ADM-lite"):
            assert any(t in i for i in items), f"{t} advisory missing"
        # OAPR itself is present → not listed as absent
        assert not any("OAPR" in i and "Missing valuable" in i for i in items)
        assert out["artifacts"]["review_approved"] is True
        assert out["next_phase"] == "BUILD"

    def test_valuable_absent_without_open_questions(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: (captured.__setitem__("payload", p), {"approved": True})[1],
        )
        review_module.review_node(
            _review_state(
                artifacts={
                    "plan": "p",
                    "spec_refined": "s",
                    "discover_artifact_audit": _audit_json(valid_types=("ADMP",)),
                }
            )
        )
        items = captured["payload"]["missing_build_inputs"]
        assert any("OAPR" in i for i in items)
        assert any("TRANS" in i for i in items)
        # W3: build-context types listed as absent too
        for t in ("DATA", "TECH", "OASEC", "OAA-ADM-lite"):
            assert any(t in i for i in items), f"{t} advisory missing"

    def test_field_absent_for_non_arckit_run(self, monkeypatch):
        """(d) byte-identical payload to today when nothing is missing."""
        captured = {}
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: (captured.__setitem__("payload", p), {"approved": True})[1],
        )
        review_module.review_node(_review_state())
        assert "missing_build_inputs" not in captured["payload"]
        assert captured["payload"]["type"] == "review"

    def test_valuable_absent_field_used_when_present(self, monkeypatch):
        """W3 5.2 — the precomputed audit['valuable_absent'] list takes
        precedence over recomputing from the record set."""
        captured = {}
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: (captured.__setitem__("payload", p), {"approved": True})[1],
        )
        audit = json.loads(_audit_json(valid_types=("OAPR",)))
        # deliberately contradicts the record set (OAPR valid -> OAPR absent
        # is wrong by recompute; the field wins)
        audit["valuable_absent"] = ["OAPR"]
        review_module.review_node(
            _review_state(artifacts={"plan": "p", "spec_refined": "s",
                                     "discover_artifact_audit": json.dumps(audit)})
        )
        items = captured["payload"]["missing_build_inputs"]
        assert any("OAPR" in i for i in items)

    def test_malformed_json_inputs_never_raise(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: (captured.__setitem__("payload", p), {"approved": True})[1],
        )
        out = review_module.review_node(
            _review_state(
                artifacts={
                    "plan": "p",
                    "spec_refined": "s",
                    "arckit_open_questions": "not json {{{",
                    "discover_artifact_audit": "{broken",
                }
            )
        )
        # both sources unusable → nothing missing derivable → field omitted
        assert "missing_build_inputs" not in captured["payload"]
        assert out["next_phase"] == "BUILD"


# ── 4.1(c): resume `answers` → artifacts.arch_review_answers ────────────────

ANSWERS = {
    "D2 What is the RTO target for the API?": "4 hours",
    "D5 Which jurisdiction's privacy rules apply?": "AU Privacy Act 1988",
}


class TestAnswersResume:
    def test_answers_written_on_approve(self, monkeypatch):
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: {"approved": True, "answers": dict(ANSWERS)},
        )
        out = review_module.review_node(
            _review_state(
                artifacts={
                    "plan": "p",
                    "spec_refined": "s",
                    "arckit_open_questions": OQ_JSON,
                    "discover_artifact_audit": _audit_json(valid_types=("OAPR",)),
                }
            )
        )
        assert json.loads(out["artifacts"]["arch_review_answers"]) == ANSWERS
        assert out["artifacts"]["review_approved"] is True
        assert out["next_phase"] == "BUILD"

    def test_answers_written_on_reject(self, monkeypatch):
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: {
                "approved": False,
                "feedback": "data model gap",
                "answers": {"q1": "a1"},
            },
        )
        out = review_module.review_node(
            _review_state(artifacts={"plan": "p", "spec_refined": "s"})
        )
        assert json.loads(out["artifacts"]["arch_review_answers"]) == {"q1": "a1"}
        assert out["artifacts"]["review_approved"] is False
        assert out["next_phase"] == "PLAN"

    def test_key_omitted_when_no_answers(self, monkeypatch):
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: {"approved": True},
        )
        out = review_module.review_node(
            _review_state(artifacts={"plan": "p", "spec_refined": "s"})
        )
        assert "arch_review_answers" not in out["artifacts"]
        assert out["next_phase"] == "BUILD"

    def test_json_string_answers_accepted(self, monkeypatch):
        monkeypatch.setattr(
            review_module,
            "interrupt",
            lambda p: {"approved": True, "answers": json.dumps(ANSWERS)},
        )
        out = review_module.review_node(
            _review_state(artifacts={"plan": "p", "spec_refined": "s"})
        )
        assert json.loads(out["artifacts"]["arch_review_answers"]) == ANSWERS


# ── 4.3: _build_prompt "Review supplements" section ─────────────────────────


def _build_state(**over):
    base = {
        "project_name": "demo",
        "project_path": "/tmp/demo",
        "artifacts": {"spec_refined": "spec", "tasks": "tasks"},
    }
    base.update(over)
    return base


class TestBuildPromptSupplements:
    def test_supplements_appended_when_answers_present(self):
        prompt = openhands_build._build_prompt(
            _build_state(
                artifacts={
                    "spec_refined": "spec",
                    "tasks": "tasks",
                    "arch_review_answers": json.dumps(ANSWERS),
                }
            )
        )
        assert "REVIEW SUPPLEMENTS" in prompt
        assert "4 hours" in prompt
        assert "AU Privacy Act 1988" in prompt

    def test_prompt_byte_identical_without_answers(self):
        with_answers = openhands_build._build_prompt(_build_state())
        baseline = openhands_build._build_prompt(_build_state())
        assert with_answers == baseline
        assert "REVIEW SUPPLEMENTS" not in baseline

    def test_supplements_truncated_per_prompt_char_limit(self):
        big = {"D2 What is the RTO target for the API?": "x" * 100_000}
        prompt = openhands_build._build_prompt(
            _build_state(
                artifacts={
                    "spec_refined": "spec",
                    "tasks": "tasks",
                    "arch_review_answers": json.dumps(big),
                }
            )
        )
        assert "REVIEW SUPPLEMENTS" in prompt
        # the full 100k answer must not survive the PROMPT_CHAR_LIMIT (16k)
        assert "x" * 50_000 not in prompt
