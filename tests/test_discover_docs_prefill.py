"""
DISCOVER doc-prefill: when the context folder holds PLAIN documents (not
ArcKit-typed), the interview interrupt is pre-filled with answers extracted
from the docs; categories the docs answer are removed from the question
list so the user is never re-asked about information the docs already
contain. The human still confirms (the interrupt always fires).

Behavioral contract under test:
- no plain docs            → interview fires with the full question list
                             (unchanged from today), no `prefill` key
- plain docs, LLM ok      → interrupt payload carries `prefill` for answered
                             categories; `questions` only contains the gaps
- LLM fatal (None)        → degrades to today's behavior (full question
                             list, no prefill key)
- ArcKit-typed docs       → auto-populate path is untouched: no interrupt at
                             all (covered by test_discover_arckit.py, not
                             re-tested here)
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import graph.nodes.discover inside the test functions (repo convention,
# see test_discover_arckit.py header comment).


def _run(tmp_path, state):
    from graph.nodes.discover import discover_node

    state.setdefault("cycle_id", "0")
    state.setdefault("trace_id", "test")
    with patch(
        "tools.stream_writer.get_stream_writer", return_value=lambda *a, **k: None
    ):
        return asyncio.run(discover_node(state))


def _plain_doc_tree(tmp_path):
    """A context folder with plain documents (no ARC-* filenames)."""
    ctx = tmp_path / "docs"
    ctx.mkdir()
    (ctx / "spec.md").write_text(
        "# Payroll Service\n\n"
        "## Overview\nA payroll computation service for SMEs.\n\n"
        "## API\nGET /payroll/runs lists runs; POST /payroll/runs triggers one.\n\n"
        "## Data\nEntity: Employee (id, name, salary). Entity: PayRun (id, date).\n\n"
        "## Non-Functional\n99% availability; encrypt PII at rest.\n"
    )
    (ctx / "notes.txt").write_text(
        "Stakeholders: HR manager, finance. Auth: SSO only.\n"
    )
    return ctx


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock invoke_skill at both module and node-global bindings."""
    import graph.nodes.discover  # noqa: F401 — ensure module loaded before patching

    captured = {}

    def fake(*args, **kwargs):
        captured["call"] = (args, kwargs)
        return json.dumps(
            {
                "seed": {
                    "core_behavior": "Compute and pay salaries on a schedule",
                    "data_model": "Employee (id, name, salary); PayRun (id, date)",
                    "non_functional": "99% availability; encrypt PII at rest",
                },
                "unanswered": ["integration", "api_surface", "ui_template"],
            }
        )

    monkeypatch.setattr("tools.llm.invoke_skill", fake)
    monkeypatch.setattr("graph.nodes.discover.invoke_skill", fake)
    return captured


@pytest.fixture
def mock_llm_fail(monkeypatch):
    def fake(*args, **kwargs):
        return None

    monkeypatch.setattr("tools.llm.invoke_skill", fake)
    monkeypatch.setattr("graph.nodes.discover.invoke_skill", fake)
    return fake


class TestDocPrefill:
    def test_no_docs_no_prefill_key(self, tmp_path):
        (tmp_path / "empty-docs").mkdir()
        state = {
            "context_folder": str(tmp_path / "empty-docs"),
            "project_folder": str(tmp_path / "project"),
            "project_name": "P",
            "project_description": "A project whose context folder holds no documents at all, just code.",
            "auto_approve_override": False,
            "force_hil": False,
        }
        with patch(
            "graph.nodes.discover.interrupt",
            return_value={"interview_notes": "Human interview notes"},
        ) as mock_i:
            result = _run(tmp_path, state)
        assert mock_i.call_count == 1
        payload = mock_i.call_args[0][0]
        assert payload["type"] == "interview"
        assert "prefill" not in payload
        assert len(payload["questions"]) >= 6  # full list, unchanged
        assert result["interview_notes"] == "Human interview notes"

    def test_docs_prefill_answers_and_trims_questions(
        self, tmp_path, mock_llm
    ):
        ctx = _plain_doc_tree(tmp_path)
        state = {
            "context_folder": str(ctx),
            "project_folder": str(tmp_path / "project"),
            "project_name": "Payroll Service",
            "project_description": "Payroll computation service for SMEs.",
            "auto_approve_override": False,
            "force_hil": False,
        }
        with patch(
            "graph.nodes.discover.interrupt",
            return_value={"interview_notes": "Confirmed prefill notes"},
        ) as mock_i:
            result = _run(tmp_path, state)

        # The interrupt still fired exactly once — human confirms.
        assert mock_i.call_count == 1
        payload = mock_i.call_args[0][0]
        assert payload["type"] == "interview"

        # Prefilled answers are present, keyed by the question key the
        # LLM produced them for.
        assert payload["prefill"]["core_behavior"] == (
            "Compute and pay salaries on a schedule"
        )
        assert payload["prefill"]["data_model"]

        # Questions the docs answered are NOT re-asked.
        asked_keys = [q["key"] for q in payload["questions"]]
        assert "core_behavior" not in asked_keys
        assert "data_model" not in asked_keys
        assert "non_functional" not in asked_keys
        # Gaps are still asked.
        assert "integration" in asked_keys
        assert "api_surface" in asked_keys

        # Note informs the human that docs pre-filled the session.
        assert "document" in payload.get("note", "").lower()

        # The resume contract is unchanged: interview_notes string.
        assert result["interview_notes"] == "Confirmed prefill notes"

    def test_llm_fatal_degrades_to_full_interview(self, tmp_path, mock_llm_fail):
        ctx = _plain_doc_tree(tmp_path)
        state = {
            "context_folder": str(ctx),
            "project_folder": str(tmp_path / "project"),
            "project_name": "Payroll Service",
            "project_description": "Payroll computation service for SMEs.",
            "auto_approve_override": False,
            "force_hil": False,
        }
        with patch(
            "graph.nodes.discover.interrupt",
            return_value={"interview_notes": "Human interview notes"},
        ) as mock_i:
            result = _run(tmp_path, state)
        payload = mock_i.call_args[0][0]
        assert "prefill" not in payload
        assert len(payload["questions"]) >= 6
        assert result["interview_notes"] == "Human interview notes"

    def test_arckit_typed_docs_still_skip_interview(self, tmp_path, mock_llm):
        # Regression guard: when valid ArcKit artefacts exist, the
        # auto-populate path is untouched and no interrupt fires at all.
        from tests.test_arckit_loader import build_tree_a

        tree = build_tree_a(tmp_path / "arckit")
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        # interrupt() outside a graph would raise — a clean return proves
        # no gate fired on this path. The ArcKit auto-populate path must not
        # invoke the doc-prefill LLM.
        result = _run(tmp_path, state)
        assert "Auto-Interview:" in result["interview_notes"]
        assert "call" not in mock_llm  # doc-prefill LLM never ran


class TestPlainDocCollection:
    """_collect_plain_docs unit behavior (no graph execution)."""

    def test_excludes_arckit_names(self, tmp_path):
        from graph.nodes.discover import _collect_plain_docs

        (tmp_path / "ARC-001-REQ-v1.0.md").write_text("x")
        (tmp_path / "vision.md").write_text("y")
        files = _collect_plain_docs(str(tmp_path))
        names = [Path(f).name for f in files]
        assert "vision.md" in names
        assert "ARC-001-REQ-v1.0.md" not in names

    def test_respects_size_and_count_caps(self, tmp_path):
        from graph.nodes.discover import _collect_plain_docs

        for i in range(40):
            (tmp_path / f"doc{i:02d}.md").write_text("a" * 100)
        files = _collect_plain_docs(str(tmp_path))
        assert len(files) <= 20

    def test_nonexistent_dir(self, tmp_path):
        from graph.nodes.discover import _collect_plain_docs

        assert _collect_plain_docs(str(tmp_path / "nope")) == []
