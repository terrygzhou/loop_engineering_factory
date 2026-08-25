"""
Integration tests: DISCOVER node × ArcKit artefact ingestion (EYW-171 §8, EYW-181).

Proves the pre-interrupt auto-population path end-to-end:
- valid ArcKit tree under context_folder → BOTH interrupts are skipped
  (the node returns without calling interrupt() — outside a LangGraph
  execution, interrupt() would raise, so a clean return is the proof),
- project_setup fields come from the artefacts (§1.1 precedence),
- interview_notes is the deterministic §4.2 synthesis,
- artifacts carry discover_artifact_audit (§6.4) and oaal_sprint_map (§7),
- no artefacts → node still completes via the suppressed-interrupt path.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# NOTE: graph.nodes.discover is imported inside the tests (not at module
# level) to match the repo convention in test_discover.py: the conftest
# autouse fixture patches langgraph.config.get_stream_writer, and the module
# must first be imported inside that patched context or every later
# out-of-graph call would hit the real langgraph binding.

from tests.test_arckit_loader import build_tree_a  # noqa: E402


def _run(tmp_path, state):
    from graph.nodes.discover import discover_node
    state.setdefault("cycle_id", "0")
    state.setdefault("trace_id", "test")
    # get_stream_writer() raises outside a graph context — return a callable
    # that swallows the single dict arg the node passes positionally.
    with patch("graph.nodes.discover.get_stream_writer",
               return_value=lambda *a, **k: None):
        return asyncio.run(discover_node(state))


class TestDiscoverArcKit:
    def test_autopopulated_run_skips_interrupts(self, tmp_path):
        tree = build_tree_a(tmp_path / "arckit")
        project_folder = tmp_path / "project"
        state = {
            "context_folder": str(tree),
            "project_folder": str(project_folder),
            "auto_approve_override": False,
            "force_hil": False,
        }
        result = _run(tmp_path, state)

        # §1.1: ADMP Document Control project row wins
        assert result["project_name"] == "Underwriting Platform"
        assert "decisioning service" in result["project_description"]
        # §4.2: deterministic auto-interview, not the LLM-generated stub
        assert "Auto-Interview: Underwriting Platform" in result["interview_notes"]
        assert result["discover_setup_done"] is True
        assert result["discover_interview_done"] is True

        # requirement.md still written (downstream contract unchanged)
        req = project_folder / "requirement.md"
        assert req.exists() and len(req.read_text()) > 100

        # §6.4 / §7: audit + OAAL handoff in artifacts
        audit = json.loads(result["artifacts"]["discover_artifact_audit"])
        assert audit["summary"]["valid"] >= 3
        assert audit["summary"]["fallbackToInterview"] is False
        sprint_map = json.loads(result["artifacts"]["oaal_sprint_map"])
        assert any(s.get("sprint") == "Sprint 0" for s in sprint_map)

    def test_no_artifacts_falls_back_to_generic_path(self, tmp_path):
        (tmp_path / "empty-context").mkdir()
        project_folder = tmp_path / "project"
        state = {
            "context_folder": str(tmp_path / "empty-context"),
            "project_folder": str(project_folder),
            "project_name": "Empty Project",
            "project_description": "A project with no ArcKit artefacts at all.",
            "auto_approve_override": False,
            "force_hil": False,
        }
        with patch("graph.nodes.discover.interrupt",
                   return_value={"interview_notes": "Human interview notes"}) as mock_i:
            result = _run(tmp_path, state)
        # Fallback path: the generic interview interrupt DID fire (§6.2),
        # resume payload is used, and the audit records NO_ARTIFACTS.
        assert mock_i.call_count == 1
        assert mock_i.call_args[0][0]["type"] == "interview"
        assert result["project_name"] == "Empty Project"
        assert result["interview_notes"] == "Human interview notes"
        audit = json.loads(result["artifacts"]["discover_artifact_audit"])
        assert audit["summary"]["discovered"] == 0
        assert audit["summary"]["fallbackToInterview"] is True
        assert "NO_ARTIFACTS" in " ".join(audit["errors"])

    def test_force_hil_preserved(self, tmp_path):
        tree = build_tree_a(tmp_path / "arckit")
        project_folder = tmp_path / "project"
        state = {
            "context_folder": str(tree),
            "project_folder": str(project_folder),
            "auto_approve_override": False,
            "force_hil": True,
        }
        with pytest.raises(Exception):
            _run(tmp_path, state)
        # force_hil must NOT auto-populate: the node reaches interrupt(),
        # which raises outside a graph execution (a clean return would mean
        # the HIL override was bypassed).
        assert True
