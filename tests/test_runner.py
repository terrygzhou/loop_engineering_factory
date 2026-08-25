"""EYW-236: shared HIL/resume generator — payload rules + loop mechanics.

Complements test_runner_hil_loop.py (pause → resume → complete cycle, abort,
handler errors) with:

- parse_formatted_input: the Web '[Label] value' string format
- build_resume_payload: the DISCOVER / ARCH_REVIEW / generic resume rules that
  used to live duplicated in WorkflowRunner._astream_with_hil and
  WorkflowBridge._build_resume_data
- run_workflow loop mechanics on synthetic graphs: custom stream events,
  abort_check mid-stream, the interrupt_after stale-node re-stream quirk,
  node error signaling, and the Web-style formatted-input flow
- a CLI adapter smoke through the real WorkflowRunner._astream_with_hil
  (auto-approve input handler + CLI event sink over a synthetic graph)

The conftest autouse fixture no-ops langgraph's get_stream_writer; this
module overrides it so node writer() calls flow through the "custom"
stream mode (EYW-234 plumbing).
"""

import asyncio
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph.runner import (
    WorkflowEvents,
    build_resume_payload,
    parse_formatted_input,
    run_workflow,
)


@pytest.fixture(autouse=True)
def mock_langgraph_stream_writer():
    """Module override of the conftest autouse fixture: keep the REAL
    get_stream_writer so custom chunks reach the shared loop."""
    yield


# ── Synthetic graphs ─────────────────────────────────────────────────


class MiniState(TypedDict, total=False):
    phase: str
    collected_setup: Any
    approved: Any
    done: Any


def _interrupting_graph():
    """Two HIL gates: DISCOVER (project_setup) then ARCH_REVIEW."""

    def discover(state):
        from langgraph.config import get_stream_writer

        get_stream_writer()(
            {
                "type": "progress",
                "phase": "DISCOVER",
                "step": "status",
                "detail": "discovering",
                "ts": 0,
            }
        )
        answer = interrupt({"type": "project_setup", "prompt": "setup?"})
        return {"phase": "DISCOVER", "collected_setup": str(answer)}

    def review(state):
        verdict = interrupt({"type": "arch_review", "prompt": "approve?"})
        # LangGraph wraps the resume payload in a list when resumed via
        # Command(resume=[...]) — unwrap like the real review_node does.
        if isinstance(verdict, list):
            verdict = verdict[0] if verdict else {}
        return {"phase": "ARCH_REVIEW", "approved": verdict}

    g = StateGraph(MiniState)
    g.add_node("discover", discover)
    g.add_node("review", review)
    g.add_edge(START, "discover")
    g.add_edge("discover", "review")
    g.add_edge("review", END)
    return g.compile(checkpointer=MemorySaver())


def _passthrough_graph(interrupt_after=None):
    """Two non-interrupting nodes (abort / stale-node mechanics)."""

    def discover(state):
        return {"phase": "DISCOVER"}

    def review(state):
        return {"phase": "ARCH_REVIEW", "done": True}

    g = StateGraph(MiniState)
    g.add_node("discover", discover)
    g.add_node("review", review)
    g.add_edge(START, "discover")
    g.add_edge("discover", "review")
    g.add_edge("review", END)
    return g.compile(checkpointer=MemorySaver(), interrupt_after=interrupt_after)


def _erroring_graph():
    def discover(state):
        raise ValueError("node boom")

    g = StateGraph(MiniState)
    g.add_node("discover", discover)
    g.add_edge(START, "discover")
    g.add_edge("discover", END)
    return g.compile(checkpointer=MemorySaver())


class RecordingEvents(WorkflowEvents):
    def __init__(self, reraise_on_error=False):
        self.values: list[tuple[dict, str]] = []
        self.customs: list[Any] = []
        self.interrupts: list = []
        self.resumes: list[tuple[str, dict, dict | None]] = []
        self.completes: list = []
        self.errors: list[BaseException] = []
        self.stale: list[list[str]] = []
        self.aborts: list[bool] = []
        self.reraise_on_error = reraise_on_error

    async def on_values(self, chunk, phase):
        self.values.append((chunk, phase))

    async def on_custom(self, payload):
        self.customs.append(payload)

    async def on_interrupt(self, pause):
        self.interrupts.append(pause)

    async def on_resumed(self, pause, resume_data, update_data):
        self.resumes.append((pause.phase, resume_data, update_data))

    async def on_complete(self, final_state):
        self.completes.append(final_state)

    async def on_error(self, error):
        self.errors.append(error)
        if self.reraise_on_error:
            raise error

    async def on_stale_nodes(self, pending):
        self.stale.append(pending)

    async def on_aborted(self):
        self.aborts.append(True)


def _run(graph, *, handler, events=None, input_state=None, **kw):
    ev = events or RecordingEvents()
    config = kw.pop("config", None) or {"configurable": {"thread_id": "runner-test"}}

    async def go():
        chunks = []
        async for c in run_workflow(
            graph,
            config=config,
            input_state=input_state if input_state is not None else {},
            input_handler=handler,
            events=ev,
            **kw,
        ):
            chunks.append(c)
        return chunks

    return asyncio.run(go()), ev


# ── parse_formatted_input ────────────────────────────────────────────


class TestParseFormattedInput:
    def test_labels_map_to_canonical_keys(self):
        text = (
            "[Project Name] ContactHub\n"
            "[Description] App for contacts\n"
            "[Context Folder] /data"
        )
        assert parse_formatted_input(text) == {
            "project_name": "ContactHub",
            "project_description": "App for contacts",
            "context_folder": "/data",
        }

    def test_unknown_labels_become_snake_case_keys(self):
        assert parse_formatted_input("[Core Behavior] do things") == {
            "core_behavior": "do things"
        }

    def test_non_formatted_returns_none(self):
        assert parse_formatted_input("just plain text") is None
        assert parse_formatted_input("") is None
        assert parse_formatted_input("[broken label") is None


# ── build_resume_payload ─────────────────────────────────────────────


class TestBuildResumePayload:
    def test_discover_project_setup_forwards_fields_and_preseeds(self):
        user = {
            "project_name": "P",
            "project_description": "D",
            "context_folder": "/c",
            "_pause": "project_setup",
        }
        resume, update = build_resume_payload("DISCOVER", "project_setup", user)
        assert resume["human_approval_required"] is False
        assert resume["project_name"] == "P"
        assert resume["artifacts"]["discover_hil_count"] == 1
        assert update == {
            "discover_setup_done": True,
            "project_name": "P",
            "project_description": "D",
            "context_folder": "/c",
        }

    def test_discover_project_setup_skips_empty_fields_in_update(self):
        resume, update = build_resume_payload(
            "DISCOVER", "project_setup", {"project_name": "P"}
        )
        assert resume["project_name"] == "P"
        assert "project_description" not in update
        assert "context_folder" not in update

    def test_discover_interview_uses_preformed_notes(self):
        resume, update = build_resume_payload(
            "DISCOVER", "interview", {"interview_notes": "n1"}
        )
        assert resume["interview_notes"] == "n1"
        assert resume["discover_interview_done"] is True
        assert update == {"interview_notes": "n1", "discover_interview_done": True}

    def test_discover_interview_converts_structured_answers(self):
        resume, _ = build_resume_payload(
            "DISCOVER",
            "interview",
            {"core_behavior": "cb", "data_model": "dm", "approved": True},
        )
        assert resume["interview_notes"] == "core_behavior: cb\ndata_model: dm"

    def test_discover_interview_plain_string_coerced_per_phase(self):
        resume, _ = build_resume_payload("DISCOVER", "interview", "my freeform answer")
        assert resume["interview_notes"] == "my freeform answer"

    def test_discover_formatted_string_routes_to_project_setup(self):
        text = "[Project Name] P\n[Description] D"
        resume, update = build_resume_payload("DISCOVER", "interview", text)
        # parse_formatted_input turns it into a dict; the interview branch
        # then normalizes it to notes.
        assert resume["interview_notes"] == "project_name: P\nproject_description: D"

    def test_discover_unknown_type_falls_back_on_hil_count(self):
        # hil_count 0 → setup semantics
        resume, update = build_resume_payload(
            "DISCOVER", None, {"project_name": "P"}, state={}
        )
        assert update["discover_setup_done"] is True
        # hil_count >= 1 → interview semantics
        resume2, update2 = build_resume_payload(
            "DISCOVER", None, {"interview_notes": "n"},
            state={"artifacts": {"discover_hil_count": 1}},
        )
        assert update2 == {"interview_notes": "n", "discover_interview_done": True}

    def test_arch_review_parses_y_n(self):
        resume, update = build_resume_payload("ARCH_REVIEW", "arch_review", "y")
        assert resume == {"approved": True, "feedback": ""}
        assert update is None
        resume, _ = build_resume_payload("ARCH_REVIEW", "arch_review", "no")
        assert resume["approved"] is False

    def test_arch_review_dict_with_feedback(self):
        resume, _ = build_resume_payload(
            "ARCH_REVIEW", None, {"approved": False, "feedback": "fix it"}
        )
        assert resume == {"approved": False, "feedback": "fix it"}

    def test_generic_phase_dict_and_string(self):
        resume, _ = build_resume_payload("REFLECT", None, {"approved": True, "feedback": "f"})
        assert resume == {
            "human_approval_required": False,
            "approved": True,
            "feedback": "f",
        }
        resume, _ = build_resume_payload("REFLECT", None, "yes")
        assert resume["approved"] is True
        resume, _ = build_resume_payload("REFLECT", None, "no")
        assert resume["approved"] is False

    def test_generic_phase_none_input_defaults_to_approved(self):
        resume, _ = build_resume_payload("REFLECT", None, None)
        assert resume["approved"] is True

    def test_generic_phase_auto_approve_default(self):
        resume, _ = build_resume_payload("REFLECT", None, {"other": 1}, auto_approve=True)
        assert resume == {"human_approval_required": False, "approved": True}

    def test_generic_phase_without_approval_defaults_to_hil_flag(self):
        resume, _ = build_resume_payload("REFLECT", None, {"other": 1})
        assert resume == {"human_approval_required": False}

    def test_corrupt_hil_count_does_not_raise(self):
        resume, update = build_resume_payload(
            "DISCOVER", None, {"interview_notes": "n"},
            state={"artifacts": {"discover_hil_count": "garbage"}},
        )
        # corrupt counter → treated as 0 → setup fallback
        assert update["discover_setup_done"] is True


# ── run_workflow loop mechanics ──────────────────────────────────────


class TestRunWorkflowLoop:
    def test_custom_stream_events_reach_sink(self):
        async def handler(pause):
            return {"project_name": "P"} if pause.phase == "DISCOVER" else {
                "approved": True,
                "feedback": "ok",
            }

        _, ev = _run(_interrupting_graph(), handler=handler)
        assert ev.customs, "node writer() payload must reach on_custom"
        assert ev.customs[0]["type"] == "progress"
        assert ev.customs[0]["phase"] == "DISCOVER"
        # and the run still completes normally
        assert len(ev.completes) == 1

    def test_abort_check_before_stream(self):
        async def handler(pause):
            raise AssertionError("handler must not be called")

        chunks, ev = _run(_interrupting_graph(), handler=handler, abort_check=lambda: True)
        assert chunks == []
        assert ev.aborts == [True]
        assert ev.completes == [] and ev.interrupts == []

    def test_abort_check_mid_stream(self):
        graph = _passthrough_graph()
        ev = RecordingEvents()

        def abort_after_first_chunk():
            return len(ev.values) >= 1

        # events=ev so the closure observes the SAME sink the loop feeds.
        _run(
            graph,
            handler=lambda p: None,
            events=ev,
            abort_check=abort_after_first_chunk,
        )
        assert len(ev.values) == 1  # only the first values chunk processed
        assert ev.aborts == [True]
        assert ev.completes == []

    def test_stale_nodes_restream_after_interrupt_after(self):
        """interrupt_after ends the stream with pending nodes; the shared
        loop must re-stream with input=None (not drop a resume)."""
        graph = _passthrough_graph(interrupt_after=["discover"])

        async def handler(pause):
            raise AssertionError("no interrupts in this graph")

        chunks, ev = _run(graph, handler=handler)
        assert ev.stale == [["review"]]
        assert len(ev.completes) == 1
        assert ev.completes[0]["done"] is True
        # The re-stream (input=None) echoes the last state snapshot before
        # running the pending node — the pre-EYW-236 loops saw that chunk
        # too, so it must stay.
        assert [ph for _, ph in ev.values] == ["DISCOVER", "DISCOVER", "ARCH_REVIEW"]
        assert len(chunks) == 3  # re-streamed chunks are yielded too

    def test_node_error_signals_on_error(self):
        async def handler(pause):
            raise AssertionError("handler must not be called")

        _, ev = _run(_erroring_graph(), handler=handler)
        assert len(ev.errors) == 1
        assert isinstance(ev.errors[0], ValueError)
        assert str(ev.errors[0]) == "node boom"
        assert ev.completes == [] and ev.aborts == []

    def test_node_error_reraising_sink_propagates(self):
        """Bridge-style sink: on_error re-raises so the adapter's legacy
        except-Exception side effects run (run_real contract)."""
        async def handler(pause):
            raise AssertionError("handler must not be called")

        ev = RecordingEvents(reraise_on_error=True)

        async def go():
            async for _ in run_workflow(
                _erroring_graph(),
                config={"configurable": {"thread_id": "reraise"}},
                input_state={},
                input_handler=handler,
                events=ev,
            ):
                pass

        with pytest.raises(ValueError, match="node boom"):
            asyncio.run(go())
        assert len(ev.errors) == 1

    def test_web_style_formatted_string_flow(self):
        """Web HIL form: '[Label] value' text for setup, dict for review."""

        async def handler(pause):
            if pause.phase == "DISCOVER":
                return "[Project Name] WebApp\n[Description] demo\n[Context Folder] /data"
            return {"approved": True, "feedback": "web ok"}

        _, ev = _run(_interrupting_graph(), handler=handler)
        _, resume_data, update_data = ev.resumes[0]
        assert resume_data["project_name"] == "WebApp"
        assert resume_data["project_description"] == "demo"
        assert update_data["discover_setup_done"] is True
        assert update_data["context_folder"] == "/data"
        assert ev.resumes[1][1] == {"approved": True, "feedback": "web ok"}
        assert len(ev.completes) == 1

    def test_resume_value_reaches_rerun_node(self):
        async def handler(pause):
            return {"project_name": "ReachMe"} if pause.phase == "DISCOVER" else {
                "approved": True,
                "feedback": "ok",
            }

        _, ev = _run(_interrupting_graph(), handler=handler)
        final = ev.completes[0]
        assert "ReachMe" in final["collected_setup"]
        assert final["approved"] == {"approved": True, "feedback": "ok"}


# ── CLI adapter smoke (real WorkflowRunner, synthetic graph) ─────────


class TestCliAdapterSmoke:
    def test_auto_approve_run_through_cli_adapter(self, mock_project_path):
        """Headless auto-approve through the REAL CLI adapter:
        WorkflowRunner._astream_with_hil supplies the CLI input handler
        (_hil_cli → _hil_auto_approve) and the CLI event sink; the shared
        loop does the stream/interrupt/resume work.
        """
        from graph.executor import WorkflowRunner

        runner = WorkflowRunner(auto_approve=True)
        runner.graph = _interrupting_graph()
        state = {"project_name": "smoke_cli", "artifacts": {}, "phase": "DISCOVER"}

        async def go():
            out = []
            async for chunk in runner._astream_with_hil(
                state, True, on_hil=runner._hil_cli
            ):
                out.append(chunk)
            return out

        chunks = asyncio.run(go())
        assert len(chunks) >= 2, "values chunks must flow through the CLI adapter"
        assert chunks[-1]["phase"] == "ARCH_REVIEW"
        # auto-approve answered the setup gate with its defaults (the
        # synthetic graph has no project_name channel, so _hil_auto_approve
        # falls back to "crm_test") — the resume value reached the node.
        assert "crm_test" in chunks[-2]["collected_setup"]
        # auto-approve answered the review gate with approved=True
        assert chunks[-1]["approved"] == {"approved": True, "feedback": "Auto-approved"}
