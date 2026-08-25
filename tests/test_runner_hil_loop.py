"""EYW-236: shared HIL/resume runner (graph/runner.py) behavior tests.

run_workflow is the unified stream → interrupt → resume loop shared by the
CLI (graph/executor.py) and the Web bridge (frontend/backend/workflow_bridge.py).
These tests pin its contract against a real compiled LangGraph state graph:

- __interrupt__ detection fires (LangGraph 1.x yields it in the values chunk)
- the input handler receives a HilPause with node-name-resolved phase
- on_interrupt → on_resumed → on_complete fire in order with the right payloads
- DISCOVER/project_setup resume payload + checkpoint pre-seed (update)
- abort via handler=None exits cleanly via on_aborted (no error event)
- a raised input-handler error surfaces through on_error, then propagates
"""
import asyncio

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from typing import Annotated, TypedDict

from graph.runner import WorkflowEvents, run_workflow


class S(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    phase: str
    saw_resume: bool


def _make_graph(hil_type: str = "project_setup"):
    g = StateGraph(S)

    def define_node(state):
        return {"phase": "DEFINE", "messages": [AIMessage(content="a")]}

    def discover_node(state):
        # interrupt(): pauses here; on resume, interrupt() returns the
        # resume value so the node can observe it.
        _ = interrupt({"type": hil_type, "question": "Q?"})
        return {"saw_resume": True, "phase": "DISCOVER"}

    def plan_node(state):
        return {"phase": "PLAN", "messages": [AIMessage(content="c")]}

    g.add_node("define", define_node)
    g.add_node("discover", discover_node)
    g.add_node("plan", plan_node)
    g.add_edge(START, "define")
    g.add_edge("define", "discover")
    g.add_edge("discover", "plan")
    g.add_edge("plan", END)
    return g.compile(checkpointer=MemorySaver())


class CollectEvents(WorkflowEvents):
    def __init__(self):
        self.values, self.interrupts, self.resumed, self.completed = [], [], [], []
        self.errors, self.stale, self.aborted = [], [], []
        self.complete_state = None

    async def on_values(self, chunk, phase):
        self.values.append(phase)

    async def on_interrupt(self, pause):
        self.interrupts.append(pause)

    async def on_resumed(self, pause, resume_data, update_data):
        self.resumed.append((pause, resume_data, update_data))

    async def on_complete(self, final_state):
        self.completed.append(final_state)
        self.complete_state = final_state

    async def on_error(self, error):
        self.errors.append(error)
        raise error  # propagate like the CLI/bridge sinks

    async def on_stale_nodes(self, pending):
        self.stale.append(pending)

    async def on_aborted(self):
        self.aborted.append(True)


def test_interrupt_resume_cycle():
    """Full pause → handler → resume → completion through the shared loop."""
    graph = _make_graph()
    events = CollectEvents()
    seen = {}

    async def handler(pause):
        seen["phase"] = pause.phase
        seen["hil_type"] = pause.hil_type
        seen["state_phase"] = pause.state.get("phase")
        return {"project_name": "P", "answers": "ok"}

    async def main():
        async for _ in run_workflow(
            graph,
            config={"configurable": {"thread_id": "t1"}},
            input_state={"phase": "START"},
            input_handler=handler,
            events=events,
            auto_approve=False,
        ):
            pass

    asyncio.run(main())

    # Exactly one pause, resolved to the interrupting node's phase.
    assert len(events.interrupts) == 1
    pause = events.interrupts[0]
    assert pause.phase == "DISCOVER"  # node-name map, not the stale chunk phase
    assert pause.hil_type == "project_setup"
    assert pause.state.get("phase") == "DEFINE"  # channel values at pause time
    assert pause.interrupts and pause.interrupts[0].value["type"] == "project_setup"

    assert seen["phase"] == "DISCOVER"
    assert seen["hil_type"] == "project_setup"
    assert seen["state_phase"] == "DEFINE"

    # Resume payload: DISCOVER/project_setup rules — setup field forwarded,
    # hil counter incremented, checkpoint pre-seeded so the node re-run skips
    # the setup gate cleanly (EYW-234 "orphaned resume" guard).
    assert len(events.resumed) == 1
    _, resume_data, update_data = events.resumed[0]
    assert resume_data["project_name"] == "P"
    assert resume_data["artifacts"]["discover_hil_count"] == 1
    assert update_data == {"discover_setup_done": True, "project_name": "P"}

    # Graph completed: node after the pause ran, saw the resume value.
    assert len(events.completed) == 1
    assert events.complete_state.get("saw_resume") is True
    assert events.complete_state.get("phase") == "PLAN"
    # LangGraph streams the initial input snapshot as the first values chunk
    # (same as the pre-EYW-236 CLI/Web loops, which processed it too — the
    # real workflow input carries phase="DISCOVER", so this is the "DISCOVER
    # started" event on first render). Then one chunk per completed node.
    assert events.values[0] == "START"
    assert "DEFINE" in events.values and "DISCOVER" in events.values


def test_abort_between_pauses():
    """abort_check tripping at a pause exits via on_aborted, not on_error."""
    graph = _make_graph()
    events = CollectEvents()

    async def handler(pause):
        return None  # handler observed the abort and declines to resume

    async def main():
        async for _ in run_workflow(
            graph,
            config={"configurable": {"thread_id": "t2"}},
            input_state={"phase": "START"},
            input_handler=handler,
            events=events,
            auto_approve=False,
            abort_check=lambda: True,
        ):
            pass

    asyncio.run(main())
    assert events.aborted == [True]
    assert events.errors == []
    assert events.completed == []


def test_handler_error_surfaces_through_on_error():
    """An input-handler exception is reported via on_error, then propagated."""
    graph = _make_graph()
    events = CollectEvents()

    async def handler(pause):
        raise RuntimeError("boom")

    async def main():
        async for _ in run_workflow(
            graph,
            config={"configurable": {"thread_id": "t3"}},
            input_state={"phase": "START"},
            input_handler=handler,
            events=events,
            auto_approve=False,
        ):
            pass

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(main())
    assert len(events.errors) == 1
    assert isinstance(events.errors[0], RuntimeError)
