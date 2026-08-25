"""Tests for graph/ui_bridge.py — skill progress via the node writer() custom stream.

EYW-233 (Task A): skill progress no longer travels through WorkflowState
(no ``state["skill_callback"]``). Nodes emit ``{"type": "skill_progress", ...}``
payloads via LangGraph's ``get_stream_writer()``; the Web bridge consumes
``stream_mode=["values", "custom"]`` and re-shapes them for the UI.
"""
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

sys_path_hack = Path(__file__).resolve().parent.parent
import sys
if str(sys_path_hack) not in sys.path:
    sys.path.insert(0, str(sys_path_hack))

# Capture the REAL get_stream_writer at import (collection) time — before
# any test runs — because conftest's autouse fixture patches
# langgraph.config.get_stream_writer to a no-op for the duration of each
# test. A `from langgraph.config import ...` inside a test body would
# capture the mock, not the real function.
from langgraph.config import get_stream_writer as real_get_stream_writer


class TestReportFunctions:
    """report_skill_* emit skill_progress payloads via the stream writer."""

    def _capture_writer(self, monkeypatch):
        import graph.ui_bridge as ui_bridge
        captured = []

        def fake_get_stream_writer():
            return lambda payload=None, **kw: captured.append(payload)

        monkeypatch.setattr(ui_bridge, "_raw_get_stream_writer", fake_get_stream_writer)
        return captured

    def test_running_payload(self, monkeypatch):
        from graph.ui_bridge import report_skill_running
        captured = self._capture_writer(monkeypatch)
        report_skill_running("coding-principles")
        assert captured == [{"type": "skill_progress", "skill": "coding-principles", "event": "running"}]

    def test_completed_payload_with_details(self, monkeypatch):
        from graph.ui_bridge import report_skill_completed
        captured = self._capture_writer(monkeypatch)
        report_skill_completed("fabric-prompts", duration_s=1.5, details={"chars": 100})
        assert captured == [{
            "type": "skill_progress",
            "skill": "fabric-prompts",
            "event": "completed",
            "details": {"duration_s": 1.5, "chars": 100},
        }]

    def test_failed_payload(self, monkeypatch):
        from graph.ui_bridge import report_skill_failed
        captured = self._capture_writer(monkeypatch)
        report_skill_failed("spec-driven-development", error="boom")
        assert captured == [{
            "type": "skill_progress",
            "skill": "spec-driven-development",
            "event": "failed",
            "details": {"error": "boom"},
        }]

    def test_outside_runnable_context_is_noop(self, monkeypatch):
        """A raising get_stream_writer (outside a runnable) must not crash nodes."""
        from graph.ui_bridge import report_skill_running

        def exploding():
            raise RuntimeError("Called get_config outside of a runnable context")

        import graph.ui_bridge as ui_bridge
        monkeypatch.setattr(ui_bridge, "_raw_get_stream_writer", exploding)
        report_skill_running("x")  # must not raise


class TestSkillTimer:
    """SkillTimer is stateless (EYW-233): no WorkflowState argument."""

    def test_no_state_argument_in_signature(self):
        import inspect
        from graph.ui_bridge import SkillTimer
        params = list(inspect.signature(SkillTimer.__init__).parameters)
        assert params == ["self", "skill_name"]

    def test_timer_emits_running_then_completed(self, monkeypatch):
        import graph.ui_bridge as ui_bridge
        captured = []
        monkeypatch.setattr(
            ui_bridge,
            "_raw_get_stream_writer",
            lambda: (lambda payload=None, **kw: captured.append(payload)),
        )
        from graph.ui_bridge import SkillTimer
        timer = SkillTimer("doubt-driven-development")
        timer.complete(duration_s=2.5)
        assert [c["event"] for c in captured] == ["running", "completed"]
        assert captured[0]["skill"] == "doubt-driven-development"
        assert captured[1]["details"]["duration_s"] == 2.5

    def test_timer_fail(self, monkeypatch):
        import graph.ui_bridge as ui_bridge
        captured = []
        monkeypatch.setattr(
            ui_bridge,
            "_raw_get_stream_writer",
            lambda: (lambda payload=None, **kw: captured.append(payload)),
        )
        from graph.ui_bridge import SkillTimer
        timer = SkillTimer("planning-and-task-breakdown")
        timer.fail("error: timeout")
        assert [c["event"] for c in captured] == ["running", "failed"]
        assert captured[1]["details"]["error"] == "error: timeout"


class TestWriterStreamPlumbing:
    """End-to-end: a node's writer() skill events arrive on the 'custom' stream."""

    def test_skill_events_reach_custom_stream(self):
        import asyncio
        from langgraph.graph import END, START, StateGraph

        from graph.ui_bridge import report_skill_completed, report_skill_running

        # Bind the REAL get_stream_writer (captured at module level, above)
        # inside ui_bridge so the conftest autouse no-op patch
        # (langgraph.config) cannot shadow it.
        import graph.ui_bridge as ui_bridge

        def node(state):
            report_skill_running("e2e-skill")
            report_skill_completed("e2e-skill", duration_s=0.1)
            return {"phase": "DONE"}

        graph = StateGraph(dict)
        graph.add_node("e2e", node)
        graph.add_edge(START, "e2e")
        graph.add_edge("e2e", END)
        compiled = graph.compile()

        custom_events = []

        async def _run():
            async for item in compiled.astream(
                {"phase": "START"}, stream_mode=["values", "custom"]
            ):
                mode, payload = item
                if mode == "custom":
                    custom_events.append(payload)

        with patch.object(
            ui_bridge, "_raw_get_stream_writer", real_get_stream_writer
        ):
            asyncio.run(_run())

        skills = [e for e in custom_events if e.get("type") == "skill_progress"]
        assert [e["event"] for e in skills] == ["running", "completed"]
        assert all(e["skill"] == "e2e-skill" for e in skills)
