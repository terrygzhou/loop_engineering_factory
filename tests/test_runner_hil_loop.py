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
- E12: the DISCOVER node owns ``discover_hil_count`` — the runner does not
  pre-seed or increment it in the resume payload or checkpoint update, and
  two sequential DISCOVER resumes yield a counter of 2 read back from
  state's ``artifacts`` (the reader's source of truth).
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
    # checkpoint pre-seeded so the node re-run skips the setup gate cleanly
    # (EYW-234 "orphaned resume" guard). E12: the runner no longer
    # pre-seeds or increments discover_hil_count — the DISCOVER node owns
    # it in its returned artifacts delta.
    assert len(events.resumed) == 1
    _, resume_data, update_data = events.resumed[0]
    assert resume_data["project_name"] == "P"
    assert "artifacts" not in resume_data
    assert "discover_hil_count" not in (update_data or {})
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


# ── E12: DISCOVER owns discover_hil_count ─────────────────────────────
#
# Spec (human-in-the-loop delta, "DISCOVER owns its HIL counter"):
# the counter is written exclusively by the DISCOVER node in its returned
# artifacts delta; the runner neither pre-seeds nor increments it, and
# the "unknown hil_type → dispatch on persisted count" legacy branch is
# gone (the active Web path always knows hil_type).
#
# The synthetic DISCOVER node below mirrors the ownership move: it reads
# the current count from state["artifacts"] and returns the incremented
# value in its own artifacts delta — no side channel.


class HILState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    phase: str
    hil_type_seen: str
    discover_setup_done: bool
    discover_interview_done: bool
    interview_notes: str
    project_name: str
    project_description: str
    context_folder: str
    artifacts: dict


def _make_graph_two_discover_pauses():
    """DISCOVER node with two sequential interrupts (setup, then
    interview) on one thread — mirrors the real node's dual-pause shape
    (both interrupts fire from the same node context; on re-run the
    second interrupt fires only if the first was already resumed).

    The node itself owns discover_hil_count: it reads the current value
    from state["artifacts"] and returns the incremented delta."""

    def discover_node(state):
        arts = dict(state.get("artifacts") or {})
        count = int(arts.get("discover_hil_count") or 0)
        setup = interrupt({"type": "project_setup", "question": "name?"})
        if isinstance(setup, list):
            setup = setup[0] if setup else {}
        setup = setup or {}
        arts["discover_hil_count"] = count + 1
        arts["interview_notes"] = arts.get("interview_notes", "")
        if not state.get("discover_setup_done"):
            # First pause in this node re-run: return after setup, so the
            # next re-stream reaches the second interrupt in the same
            # node context.
            return {
                "phase": "DISCOVER",
                "hil_type_seen": "project_setup",
                "discover_setup_done": True,
                "project_name": setup.get("project_name", ""),
                "project_description": setup.get("project_description", ""),
                "context_folder": setup.get("context_folder", ""),
                "artifacts": arts,
            }
        # Second pause: setup already done, fire the interview interrupt.
        answers = interrupt({"type": "interview", "question": "interview?"})
        if isinstance(answers, list):
            answers = answers[0] if answers else {}
        answers = answers or {}
        arts2 = dict(arts)
        arts2["discover_hil_count"] = count + 2
        arts2["interview_notes"] = answers.get("interview_notes", "")
        return {
            "phase": "DISCOVER",
            "hil_type_seen": "interview",
            "discover_interview_done": True,
            "interview_notes": answers.get("interview_notes", ""),
            "artifacts": arts2,
        }

    def plan_node(state):
        return {"phase": "PLAN", "messages": [AIMessage(content="c")]}

    g = StateGraph(HILState)
    g.add_node("discover", discover_node)
    g.add_node("plan", plan_node)
    g.add_edge(START, "discover")
    g.add_edge("discover", "plan")
    g.add_edge("plan", END)
    return g.compile(checkpointer=MemorySaver())


def test_two_discover_resumes_yield_hil_count_two_read_from_state():
    """E12 spec scenario: two DISCOVER resumes (setup, then interview) →
    after the second resume ``state['artifacts']['discover_hil_count'] == 2``,
    read from state's artifacts (the reader's source of truth)."""
    graph = _make_graph_two_discover_pauses()
    events = CollectEvents()
    pauses: list = []

    async def handler(pause):
        pauses.append(pause)
        if pause.hil_type == "project_setup":
            return {"project_name": "P", "project_description": "D"}
        return {"interview_notes": "answers"}

    async def main():
        async for _ in run_workflow(
            graph,
            config={"configurable": {"thread_id": "e12-two-pauses"}},
            input_state={"artifacts": {}},
            input_handler=handler,
            events=events,
            auto_approve=False,
        ):
            pass

    asyncio.run(main())

    # Both DISCOVER pauses were observed with the correct hil_type.
    assert [p.hil_type for p in pauses] == ["project_setup", "interview"]

    # The runner did not pre-seed or increment the counter in the resume
    # payload or the checkpoint update — it is the node's to own.
    for _, resume_data, update_data in events.resumed:
        arts = resume_data.get("artifacts")
        assert not isinstance(arts, dict) or "discover_hil_count" not in arts
        upd = update_data or {}
        assert "discover_hil_count" not in upd

    # The node's own returned delta is what persisted the counter — read
    # back from state's artifacts (the reader's source of truth), not a
    # side channel.
    final = events.complete_state
    assert final["artifacts"]["discover_hil_count"] == 2


def test_discover_resume_payload_has_no_hil_count_increment():
    """E12: the runner's DISCOVER resume paths carry no pre-seeded or
    incremented discover_hil_count — neither in the resume value's
    artifacts nor in the checkpoint update dict."""
    from graph.runner import build_resume_payload

    # project_setup resume: no counter in the resume value, none in update.
    resume, update = build_resume_payload(
        "DISCOVER", "project_setup", {"project_name": "P"}, state={"artifacts": {}}
    )
    arts = resume.get("artifacts")
    assert not isinstance(arts, dict) or "discover_hil_count" not in arts
    assert "discover_hil_count" not in (update or {})

    # interview resume: same contract.
    resume2, update2 = build_resume_payload(
        "DISCOVER", "interview", {"interview_notes": "n"}, state={"artifacts": {}}
    )
    assert "interview_notes" in (update2 or {})
    assert "discover_hil_count" not in (update2 or {})
    assert "discover_hil_count" not in resume2

    # Unknown DISCOVER hil_type (None): the legacy "fall back on persisted
    # hil count" dispatch branch is gone. The active Web path always knows
    # hil_type from the interrupt payload, so an unknown type takes the
    # interview semantics with no read of the persisted counter.
    resume3, update3 = build_resume_payload(
        "DISCOVER", None, {"interview_notes": "n"}, state={"artifacts": {}}
    )
    assert "discover_interview_done" in (update3 or {})
    assert "discover_hil_count" not in (update3 or {})
    assert "discover_hil_count" not in resume3
