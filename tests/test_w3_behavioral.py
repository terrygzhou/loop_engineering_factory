"""
W3 Behavioral Node Tests
========================

End-to-end behavioural tests for workflow nodes, verifying:
  - Happy path: node returns the expected partial-update shape
  - Error path: node handles LLM=None / fatal errors correctly
  - State invariants: phase/next_phase/artifacts keys are set as documented

These tests run WITHOUT a live LLM (invoke_skill → None) and WITHOUT
a live OpenHands server. They verify the STATE MACHINE, not LLM content.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from graph.state import CycleMetrics
from graph.edges import route_phase


# ── Helpers ──────────────────────────────────────────────────────────


def _base_state(phase: str, **artifacts) -> dict:
    """Build a minimal valid WorkflowState dict for node tests."""
    return {
        "phase": phase,
        "project_name": "test-project",
        "project_path": "/tmp/test-project",
        "auto_approve_override": True,
        "force_hil": False,
        "metrics": CycleMetrics(),
        "artifacts": dict(artifacts),
        "error": None,
        "next_phase": None,
        "cycle_id": "test-cycle-001",
        "trace_id": "test-trace-001",
    }


# ── SEED_DATA ────────────────────────────────────────────────────────


def test_seed_data_pass_through():
    """SEED_DATA is a placeholder: sets phase=SEED_DATA, next_phase=VERIFY."""
    from graph.nodes.seed_data import seed_data_node

    s = _base_state("SEED_DATA", spec_refined="test spec")
    with patch("graph.nodes.seed_data.safe_stream_writer", return_value=lambda x: None), \
         patch("graph.nodes.seed_data.AuditLog", MagicMock()):
        out = seed_data_node(s)

    assert out["phase"] == "SEED_DATA"
    assert out["next_phase"] == "VERIFY"


# ── SHIP ─────────────────────────────────────────────────────────────


def test_ship_happy_path_no_llm():
    """SHIP with LLM=None must set phase=SHIP and next_phase=REFLECT."""
    from graph.nodes.ship import ship_node

    s = _base_state(
        "SHIP",
        build_log="test build log",
        test_results="3 passed",
    )
    with patch("graph.nodes.ship.safe_stream_writer", return_value=lambda x: None), \
         patch("graph.nodes.ship.invoke_skill", return_value="observability added"), \
         patch("graph.nodes.ship.build_skill_registry", return_value=MagicMock()), \
         patch("graph.nodes.ship.os", MagicMock()):
        out = ship_node(s)

    assert out["phase"] == "SHIP"
    assert out["next_phase"] == "REFLECT"


# ── REFLECT ──────────────────────────────────────────────────────────


def test_reflect_terminal_no_llm():
    """REFLECT with LLM=None must set phase=REFLECT and next_phase=END."""
    from graph.nodes.reflect import reflect_node
    from config.loader import config as _cfg
    import tempfile, os

    s = _base_state(
        "REFLECT",
        build_log="log",
        test_results="3 passed",
    )

    # Create a temp guardrails file so yaml.safe_load succeeds
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("min_spec_confidence: 0.8\nmax_arch_uncertainty: 0.5\n")
        guardrails_file = f.name

    try:
        mock_aggregator = MagicMock()
        mock_aggregator.get_historical_patterns.return_value = []
        # generate_config_diffs returns a dict with "changes" key
        with patch("graph.nodes.reflect.safe_stream_writer", return_value=lambda x: None), \
             patch("graph.nodes.reflect.get_llm", return_value=None), \
             patch("graph.nodes.reflect.invoke_skill", return_value=None), \
             patch("graph.nodes.reflect.build_skill_registry", return_value=MagicMock()), \
             patch("graph.nodes.reflect.FeedbackAggregator", return_value=mock_aggregator), \
             patch("graph.nodes.reflect.generate_config_diffs",
                   return_value={"changes": [], "summary": "no changes"}), \
             patch("graph.nodes.reflect.dry_run_validation", return_value=True), \
             patch("graph.nodes.reflect.get_chroma_client", return_value=None), \
             patch.object(_cfg.paths, "guardrails_path", guardrails_file), \
             patch.object(_cfg.paths, "storage_dir", tempfile.mkdtemp()):
            out = reflect_node(s)

        assert out["phase"] == "REFLECT"
        assert out.get("next_phase") == "END"
    finally:
        os.unlink(guardrails_file)


# ── VERIFY: deterministic gate behaviour ────────────────────────────


def test_verify_llm_fatal_routes_to_error(tmp_path, monkeypatch):
    """When the code-review LLM returns None (fatal), verify_node must
    return next_phase='ERROR' — the LLM-fatal escape hatch.

    The config's skill_registry_path defaults to /app/skills (Docker path)
    which doesn't exist on the host. We point it at the local skills/ dir
    so build_skill_registry finds the pre-commit-review skill and
    the LLM code path is actually exercised.
    """
    import os
    import graph.nodes.verify as verify_mod
    from config.loader import config as _cfg

    local_skills = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")

    # Build state with a VALID project_path (tmp_path has main.py)
    s = _base_state("VERIFY")
    s["project_path"] = str(tmp_path)
    s["artifacts"]["test_results"] = json.dumps({"pytest_pass": 5, "pytest_fail": 0})
    s["artifacts"]["loop_counts"] = {}

    # Create a source file so the LLM path is exercised
    (tmp_path / "main.py").write_text("print('hi')\n")

    # Point skill registry at local skills/ dir (config defaults to /app/skills)
    monkeypatch.setattr(_cfg.workflow, "skill_registry_path", local_skills)

    # Patch invoke_skill to return None (simulating LLM fatal failure)
    monkeypatch.setattr(verify_mod, "invoke_skill", lambda *a, **k: None)

    out = verify_mod.verify_node(s)

    assert out["phase"] == "VERIFY"
    assert out["next_phase"] == "ERROR"
    assert out["error"] is not None


def test_verify_pass_writes_verify_status(tmp_path, monkeypatch):
    """When test_results shows 0 failures and LLM returns a valid review,
    verify_status must be 'pass'."""
    import os
    import graph.nodes.verify as verify_mod
    from config.loader import config as _cfg

    local_skills = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")

    s = _base_state("VERIFY")
    s["project_path"] = str(tmp_path)
    s["artifacts"]["test_results"] = json.dumps({"pytest_pass": 5, "pytest_fail": 0})
    s["artifacts"]["loop_counts"] = {}

    (tmp_path / "main.py").write_text("print('hi')\n")

    # Point skill registry at local skills/ dir
    monkeypatch.setattr(_cfg.workflow, "skill_registry_path", local_skills)

    # LLM returns a valid review (no critical findings)
    monkeypatch.setattr(verify_mod, "invoke_skill",
                        lambda *a, **k: "## Verdict: approve\nNo critical issues found.")

    out = verify_mod.verify_node(s)

    assert out["phase"] == "VERIFY"
    assert out["artifacts"]["verify_status"] == "pass"


# ── DISCOVER: HIL bypass path ────────────────────────────────────────


def test_discover_auto_approve_no_llm():
    """DISCOVER with auto_approve=True must skip interrupts and
    return phase=DISCOVER, next_phase=DEFINE."""
    import asyncio
    from graph.nodes.discover import discover_node

    s = _base_state(
        "DISCOVER",
        interview_notes="test interview notes",
        project_context="test context",
    )
    with patch("graph.nodes.discover.safe_stream_writer", return_value=lambda x: None), \
         patch("graph.nodes.discover.invoke_skill", return_value="# Discovery\nProject: test"), \
         patch("graph.nodes.discover.build_skill_registry", return_value={
             "fabric-prompts": {"content": "skill"},
             "coding-principles": {"content": "principles"},
         }), \
         patch("graph.nodes.discover.AuditLog", MagicMock()):
        loop = asyncio.new_event_loop()
        try:
            out = loop.run_until_complete(discover_node(s))
        finally:
            loop.close()

    assert out["phase"] == "DISCOVER"
    assert out["next_phase"] == "DEFINE"


# ── route_phase: integration with node outputs ──────────────────────


def test_route_verify_pass_goes_to_ship():
    """verify_status=pass must route to SHIP."""
    s = {
        "phase": "VERIFY",
        "metrics": CycleMetrics(),
        "artifacts": {"verify_status": "pass", "loop_counts": {}},
        "error": None,
        "next_phase": "SHIP",
    }
    assert route_phase(s) == "SHIP"


def test_route_verify_fail_loops_to_build():
    """verify_status=fail with budget available must loop to BUILD."""
    s = {
        "phase": "VERIFY",
        "metrics": CycleMetrics(),
        "artifacts": {"verify_status": "fail", "loop_counts": {"VERIFY": 1}},
        "error": None,
        "next_phase": None,
    }
    assert route_phase(s) == "BUILD"


def test_route_verify_budget_exhausted_halts():
    """Exhausted VERIFY counter must route to ERROR (never SHIP)."""
    s = {
        "phase": "VERIFY",
        "metrics": CycleMetrics(),
        "artifacts": {"verify_status": "fail", "loop_counts": {"VERIFY": 2}},
        "error": None,
        "next_phase": None,
    }
    assert route_phase(s) == "ERROR"


def test_route_verify_llm_fatal_routes_to_error():
    """The LLM-fatal escape hatch (error set, next_phase=None) must
    route to the ERROR terminal."""
    s = {
        "phase": "VERIFY",
        "metrics": CycleMetrics(),
        "artifacts": {"verify_status": "fail", "loop_counts": {"VERIFY": 0}},
        "error": "LLM failed",
        "next_phase": None,
    }
    assert route_phase(s) == "ERROR"


# ── BUILD: _merge_results state invariants ──────────────────────────


def test_build_merge_pass_resets_counter():
    """A passing BUILD must reset loop_counts['BUILD'] to 0."""
    from graph.nodes import openhands_build as ob

    state = {
        "project_path": "/tmp/x",
        "artifacts": {"loop_counts": {"BUILD": 1}},
        "metrics": None,
    }
    parsed = {
        "build_status": "pass",
        "build_log": "ok",
        "test_results": "3 passed",
        "files_created": ["a.py"],
        "errors": [],
        "generated_code": [],
    }
    with patch.object(ob, "_write_generated_files", return_value=[]):
        out = ob._merge_results(state, parsed)
    assert out["artifacts"]["loop_counts"]["BUILD"] == 0
    assert out["next_phase"] == "SEED_DATA"


def test_build_merge_fail_increments_counter():
    """A failing BUILD with budget available must increment the counter
    and leave next_phase unset (retry path)."""
    from graph.nodes import openhands_build as ob

    state = {
        "project_path": "/tmp/x",
        "artifacts": {"loop_counts": {"BUILD": 0}},
        "metrics": None,
    }
    parsed = {
        "build_status": "fail",
        "build_log": "err",
        "test_results": "1 failed",
        "files_created": [],
        "errors": ["boom"],
        "generated_code": [],
    }
    with patch.object(ob, "_write_generated_files", return_value=[]):
        out = ob._merge_results(state, parsed)
    assert out["artifacts"]["loop_counts"]["BUILD"] == 1
    # next_phase is only set on pass; on fail it's absent (retry)
    assert "next_phase" not in out or out.get("next_phase") is None


def test_build_merge_halt_sets_error():
    """A failing BUILD at budget must set error and next_phase=None."""
    from graph.nodes import openhands_build as ob

    state = {
        "project_path": "/tmp/x",
        "artifacts": {"loop_counts": {"BUILD": ob.BUILD_MAX_RETRIES}},
        "metrics": None,
    }
    parsed = {
        "build_status": "fail",
        "build_log": "err",
        "test_results": "1 failed",
        "files_created": [],
        "errors": ["boom"],
        "generated_code": [],
    }
    with patch.object(ob, "_write_generated_files", return_value=[]):
        out = ob._merge_results(state, parsed)
    assert out["error"] is not None
    assert out["next_phase"] is None
    assert "times" in out["error"]
