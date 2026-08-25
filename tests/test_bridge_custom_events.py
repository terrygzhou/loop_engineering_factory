"""EYW-234 — Web bridge streams stream_mode=['values','custom'].

Covers:
- _emit_custom_event normalization (dict / non-dict writer payloads, phase
  fallback, reserved-action safety, standard event key shape)
- run_real end-to-end against a real LangGraph graph: node writer() events
  appear in bridge.events in real time, and values-derived events keep the
  legacy shape ({timestamp, phase, action, message, data}).
"""

import asyncio
import sys
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from workflow_bridge import WorkflowBridge

EVENT_KEYS = {"timestamp", "phase", "action", "message", "data"}


class _TinyState(TypedDict, total=False):
    phase: str
    done: bool


WRITER_PAYLOAD = {
    "type": "progress",
    "phase": "BUILD",
    "step": "UNIT_TEST",
    "detail": "pytest passed (42 tests) — item 7 complete",
    "ts": 1.0,
}


def _writer_node(state: _TinyState):
    w = get_stream_writer()
    w(WRITER_PAYLOAD)
    return {"phase": "BUILD", "done": True}


def _build_tiny_graph(checkpointer=None, auto_approve=False):
    g = StateGraph(_TinyState)
    g.add_node("writer_node", _writer_node)
    g.add_edge(START, "writer_node")
    g.add_edge("writer_node", END)
    return g.compile(checkpointer=checkpointer)


@pytest.fixture()
def bridge(tmp_path):
    b = WorkflowBridge()
    b._user_inputs_path = tmp_path / "user_inputs.json"
    b._use_real_workflow = True
    b._thread_id = None
    return b


# ── _emit_custom_event normalization ─────────────────────────────────


def test_emit_custom_event_dict_payload(bridge):
    bridge._last_phase = "PLAN"
    asyncio.run(
        bridge._emit_custom_event(
            {"type": "progress", "phase": "PLAN", "step": "status", "detail": "Generating plan", "ts": 1.0}
        )
    )
    ev = bridge.events[-1]
    assert set(ev.keys()) == EVENT_KEYS
    assert ev["phase"] == "PLAN"
    assert ev["action"] == "progress"
    assert ev["message"] == "Generating plan"
    assert ev["data"]["custom"]["step"] == "status"
    # recorded on the phase's message log too
    assert ev in bridge.phase_states["PLAN"]["messages"]


def test_emit_custom_event_dict_payload_phase_fallback(bridge):
    bridge._last_phase = "BUILD"
    asyncio.run(bridge._emit_custom_event({"type": "info", "detail": "no phase here"}))
    ev = bridge.events[-1]
    assert ev["phase"] == "BUILD"
    assert ev["action"] == "progress"
    assert ev["message"] == "no phase here"


def test_emit_custom_event_non_dict_payload(bridge):
    bridge._last_phase = None
    asyncio.run(bridge._emit_custom_event("plain string event"))
    ev = bridge.events[-1]
    assert set(ev.keys()) == EVENT_KEYS
    assert ev["phase"] == "SYSTEM"
    assert ev["action"] == "progress"
    assert ev["message"] == "plain string event"
    assert ev["data"]["custom"] == "plain string event"


def test_emit_custom_event_never_uses_reserved_actions(bridge):
    # Writer payloads carry type: 'error' for sub-step failures — those must
    # not map onto action='error', which would flip phase status in the UI.
    bridge._last_phase = "BUILD"
    asyncio.run(
        bridge._emit_custom_event(
            {"type": "error", "phase": "BUILD", "step": "error", "detail": "UAT failed", "ts": 1.0}
        )
    )
    ev = bridge.events[-1]
    assert ev["action"] == "progress"
    assert bridge.phase_states["BUILD"]["status"] == "pending"  # untouched


# ── run_real end-to-end: values + custom in one stream ───────────────


def test_run_real_streams_values_and_custom(bridge, tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_build_executor_state", lambda **kw: {})
    # Use the production checkpointer (official AsyncSqliteSaver via
    # CHECKPOINT_DB — exercises the real SQLite persistence path, EYW-235).
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    with patch("graph.main.build_graph", side_effect=_build_tiny_graph):
        asyncio.run(bridge.run_real())

    assert bridge.status == "complete"

    # 1) The node's writer() event surfaced in real time, normalized to the
    #    standard bridge event shape with the raw payload under data['custom'].
    customs = [e for e in bridge.events if "custom" in e.get("data", {})]
    assert len(customs) == 1
    ev = customs[0]
    assert set(ev.keys()) == EVENT_KEYS
    assert ev["phase"] == "BUILD"
    assert ev["action"] == "progress"
    assert ev["message"] == "pytest passed (42 tests) — item 7 complete"
    assert ev["data"]["custom"] == WRITER_PAYLOAD

    # 2) Values-derived events are unchanged in shape and presence.
    actions = [(e["phase"], e["action"]) for e in bridge.events]
    assert ("SYSTEM", "started") in actions
    assert ("BUILD", "started") in actions
    assert ("BUILD", "completed") in actions
    assert ("SYSTEM", "completed") in actions
    for e in bridge.events:
        assert set(e.keys()) == EVENT_KEYS
