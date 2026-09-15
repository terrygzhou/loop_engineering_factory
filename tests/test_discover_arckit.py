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
    # safe_stream_writer() falls back to no-op outside a graph context; patch
    # the source binding so the node's writer is a known no-op callable that
    # swallows the single dict arg the node passes positionally.
    with patch(
        "tools.stream_writer.get_stream_writer", return_value=lambda *a, **k: None
    ):
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
        with patch(
            "graph.nodes.discover.interrupt",
            return_value={"interview_notes": "Human interview notes"},
        ) as mock_i:
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

    def test_force_hil_valid_artifacts_still_autopopulate(self, tmp_path):
        # arckit-web-ingestion: the pre-scan now runs under forced HIL
        # (Web bridge sets force_hil=True). Valid ArcKit context
        # auto-populates and skips BOTH interrupts, per EYW-171 §4.1 —
        # no exception from interrupt() outside a graph context.
        tree = build_tree_a(tmp_path / "arckit")
        project_folder = tmp_path / "project"
        state = {
            "context_folder": str(tree),
            "project_folder": str(project_folder),
            "auto_approve_override": False,
            "force_hil": True,
        }
        result = _run(tmp_path, state)
        assert result["project_name"] == "Underwriting Platform"
        assert result["discover_setup_done"] is True
        assert result["discover_interview_done"] is True
        audit = json.loads(result["artifacts"]["discover_artifact_audit"])
        assert audit["summary"]["valid"] >= 3
        assert audit["summary"]["fallbackToInterview"] is False

    def test_force_hil_no_artifacts_keeps_interview(self, tmp_path):
        # HIL preserved when the context holds no valid ArcKit artefacts:
        # the generic interview gate still fires under force_hil.
        (tmp_path / "empty-context").mkdir()
        project_folder = tmp_path / "project"
        # Mirror the Web bridge: setup is pre-seeded (discover_setup_done),
        # so the gate that must fire under forced HIL is the interview one.
        state = {
            "context_folder": str(tmp_path / "empty-context"),
            "project_folder": str(project_folder),
            "project_name": "Empty Project",
            "project_description": "No ArcKit artefacts at all.",
            "discover_setup_done": True,
            "auto_approve_override": False,
            "force_hil": True,
        }
        with patch(
            "graph.nodes.discover.interrupt",
            return_value={"interview_notes": "Human interview notes"},
        ) as mock_i:
            result = _run(tmp_path, state)
        assert mock_i.call_count == 1
        assert mock_i.call_args[0][0]["type"] == "interview"
        assert result["interview_notes"] == "Human interview notes"
        audit = json.loads(result["artifacts"]["discover_artifact_audit"])
        assert audit["summary"]["fallbackToInterview"] is True


# ── Explicit artefact list input (option 1+2) ─────────────────────────────────

class TestDiscoverArcKitArtifactList:
    """Explicit artefact list: `arckit_artifacts` state key + HIL setup field.

    The DISCOVER node makes several LLM calls per run; in sandboxes where the
    configured LLM endpoint is unreachable each call would burn the 180 s
    invoke timeout, so these tests mock `invoke_skill` at both the module
    binding and the node-global binding (discover.py imports it at top level
    and re-imports lazily inside helpers)."""

    @pytest.fixture
    def mock_llm(self, monkeypatch):
        import graph.nodes.discover  # ensure the module exists before patching

        def fake(*args, **kwargs):
            return "[MOCK-LLM]"

        monkeypatch.setattr("tools.llm.invoke_skill", fake)
        monkeypatch.setattr("graph.nodes.discover.invoke_skill", fake)
        return fake

    def _tree(self, tmp_path):
        tree = build_tree_a(tmp_path / "arckit")
        admp = str(tree / "projects/001-underwriting/ARC-001-ADMP-v1.0.md")
        oaal = str(tree / "projects/001-underwriting/ARC-001-OAAL-v1.0.md")
        return tree, admp, oaal

    def test_state_key_passed_as_files_to_loader(self, tmp_path, mock_llm):
        tree, admp, oaal = self._tree(tmp_path)
        from tools.arckit_loader import load_arckit_artifacts

        real_ctx = load_arckit_artifacts(str(tree), files=[admp, oaal])
        state = {
            "context_folder": str(tree),
            "arckit_artifacts": [admp, oaal],
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": False,
        }
        with patch(
            "tools.arckit_loader.load_arckit_artifacts", return_value=real_ctx
        ) as mock_load:
            result = _run(tmp_path, state)
        mock_load.assert_called_once_with(str(tree), files=[admp, oaal])
        # explicit list is the active ingestion source — carried in the result
        assert result["arckit_artifacts"] == [admp, oaal]

    def test_hil_setup_field_populates_state_key(self, tmp_path, mock_llm):
        tree, admp, oaal = self._tree(tmp_path)
        state = {
            "context_folder": "",
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": True,
        }
        setup_payload = {
            "project_name": "Underwriting Platform",
            "project_description": "Decisioning service",
            "context_folder": str(tree),
            "arckit_artifacts": f"{admp}\n{oaal}\n",
        }
        with patch(
            "graph.nodes.discover.interrupt",
            side_effect=[setup_payload, {"interview_notes": "hi"}],
        ):
            result = _run(tmp_path, state)
        assert result["arckit_artifacts"] == [admp, oaal]
        # explicit list drove the audit (re-scan with files= after resume)
        audit = json.loads(result["artifacts"]["discover_artifact_audit"])
        assert audit["summary"]["valid"] >= 1

    def test_hil_empty_field_leaves_key_unset(self, tmp_path, mock_llm):
        tree, _admp, _oaal = self._tree(tmp_path)
        state = {
            "context_folder": str(tree),
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": True,
        }
        setup_payload = {
            "project_name": "P",
            "project_description": "D",
            "context_folder": str(tree),
            "arckit_artifacts": "",
        }
        with patch(
            "graph.nodes.discover.interrupt",
            side_effect=[setup_payload, {"interview_notes": "hi"}],
        ):
            result = _run(tmp_path, state)
        assert "arckit_artifacts" not in result

    def test_setup_interrupt_payload_includes_optional_field(self, tmp_path, mock_llm):
        state = {
            "context_folder": "",
            "project_folder": str(tmp_path / "project"),
            "auto_approve_override": False,
            "force_hil": True,
        }
        payloads = []

        def fake_interrupt(payload):
            payloads.append(payload)
            if payload.get("type") == "project_setup":
                return {
                    "project_name": "P",
                    "project_description": "D",
                    "context_folder": "",
                    "arckit_artifacts": "",
                }
            return {"interview_notes": "hi"}

        with patch("graph.nodes.discover.interrupt", side_effect=fake_interrupt):
            _run(tmp_path, state)
        fields = {f["key"]: f for f in payloads[0]["fields"]}
        assert "arckit_artifacts" in fields
        assert fields["arckit_artifacts"]["required"] is False
