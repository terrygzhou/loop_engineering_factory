"""
EYW-236: shared HIL/resume streaming loop.

ONE async generator owning the entire stream → interrupt → resume cycle for
LangGraph workflows. Previously duplicated by:

- ``WorkflowRunner._astream_with_hil`` (CLI, graph/executor.py) — values-only
  stream, ``except GraphInterrupt`` (dead path on LangGraph ≥1.x: interrupt()
  no longer raises; it yields ``__interrupt__`` in the values chunk).
- ``WorkflowBridge.run_real`` (Web, frontend/backend/workflow_bridge.py) —
  ``["values","custom"]`` stream, ``__interrupt__`` detection, per-phase
  review sections, abort racing.

What the generator owns (acceptance criteria, EYW-236):
- the astream loop with ``stream_mode=["values", "custom"]``
- interrupt detection: LangGraph 1.x ``__interrupt__`` in the values chunk,
  plus the legacy ``GraphInterrupt`` exception path for older versions
- suspended-vs-complete discrimination (``graph_state.next`` AND
  ``graph_state.interrupts`` — next can be empty while a pause is pending)
- interrupted phase / HIL type resolution
- input collection through a pluggable async input handler
  (CLI prompt / Web SSE polling / auto-approve no-op)
- resume payload construction (shared DISCOVER / ARCH_REVIEW / generic rules)
- resume via ``Command(resume=[...], update=...)``
- the post-stream "nodes still pending" quirk (interrupt_after edge)
- error / abort / complete signaling through the event sink

Adapters supply:
- ``input_handler(pause) -> user_input`` — dict | str | None (None = stop/abort)
- ``events`` — a ``WorkflowEvents`` sink (CLI observability / Web WS events)

Headless auto-approve stays a client-side behavior (EYW-232 verdict): the
graph is compiled with the auto_approve flag and the input handler may return
pre-generated answers without prompting. No server-side approval loop.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

logger = logging.getLogger("graph.runner")

# Node name → phase name (Web UI originally carried this map inline).
_NODE_PHASE_MAP = (
    ("discover", "DISCOVER"),
    ("define", "DEFINE"),
    ("plan", "PLAN"),
    ("review", "ARCH_REVIEW"),
    ("arch", "ARCH_REVIEW"),
    ("build", "BUILD"),
    ("seed", "SEED_DATA"),
    ("verify", "VERIFY"),
    ("ship", "SHIP"),
    ("reflect", "REFLECT"),
)


@dataclass
class HilPause:
    """A suspended HIL gate, as seen by the input handler."""

    phase: str
    hil_type: str | None
    state: dict[str, Any]
    interrupts: list[Any] = field(default_factory=list)


class WorkflowEvents:
    """Event sink for the shared runner.

    All hooks are no-ops by default; adapters override what they need.
    Hooks run in stream order: on_values/on_custom fire for every chunk,
    on_interrupt/on_resumed around each pause, on_complete/on_error at the
    terminal edge.
    """

    async def on_values(self, chunk: dict[str, Any], phase: str) -> None:
        """A values (state snapshot) chunk was yielded."""

    async def on_custom(self, payload: Any) -> None:
        """A node writer() 'custom' chunk was received."""

    async def on_interrupt(self, pause: HilPause) -> None:
        """Graph suspended for HIL input; input collection is about to start."""

    async def on_resumed(
        self,
        pause: HilPause,
        resume_data: dict[str, Any],
        update_data: dict[str, Any] | None,
    ) -> None:
        """Input collected; resuming with Command(resume=..., update=...)."""

    async def on_complete(self, final_state: dict[str, Any] | None) -> None:
        """Stream finished normally (graph complete)."""

    async def on_error(self, error: BaseException) -> None:
        """Stream failed; the generator returns after this hook."""

    async def on_stale_nodes(self, pending: list[str]) -> None:
        """Stream ended but pending nodes remain (interrupt_after quirk);
        the generator will re-stream with input=None."""

    async def on_aborted(self) -> None:
        """Abort requested; the generator returns without completing."""


def resolve_interrupted_phase(
    graph_state, chunk: dict[str, Any] | None, last_phase: str | None
) -> str:
    """Best-effort interrupted phase name.

    Prefers the interrupting node's name (graph_state.next[0] → phase map),
    falls back to the suspended state's phase / next_phase / last seen phase.
    """
    next_nodes = getattr(graph_state, "next", None) or ()
    if next_nodes:
        node_name = str(next_nodes[0])
        for needle, phase in _NODE_PHASE_MAP:
            if needle in node_name:
                return phase
    if chunk:
        return (
            chunk.get("phase") or chunk.get("next_phase") or (last_phase or "UNKNOWN")
        )
    return last_phase or "UNKNOWN"


def extract_interrupt_type(
    chunk_interrupts: Any | None, state_interrupts: Any | None
) -> str | None:
    """HIL type from the interrupt payload ('project_setup', 'interview', ...)."""
    sources = [chunk_interrupts, state_interrupts]
    for source in sources:
        if not source:
            continue
        first = (
            source[0] if isinstance(source, (list, tuple)) and len(source) > 0 else None
        )
        if first is None:
            continue
        value = getattr(first, "value", None)
        if isinstance(value, dict) and value.get("type"):
            return str(value["type"])
        if isinstance(value, str):
            return value
    return None


def parse_formatted_input(text: str) -> dict[str, str] | None:
    """Parse '[Label] value' formatted strings (Web frontend input format).

    Returns a dict of lower-cased snake_case keys, or None when the text is
    not in the recognized format.
    """
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("[") or "]" not in line:
            continue
        label, _, value = line.partition("]")
        key = label[1:].strip().lower().replace(" ", "_")
        if key:
            fields[key] = value.strip()
    if not fields:
        return None
    # Map common labels onto state keys
    mapping = {
        "project_name": "project_name",
        "description": "project_description",
        "context_folder": "context_folder",
    }
    out: dict[str, str] = {}
    for key, val in fields.items():
        out[mapping.get(key, key)] = val
    return out


def _interview_notes_from(user_input: Any) -> str:
    """Normalize interview answers (dict or str) into interview_notes text."""
    if isinstance(user_input, dict):
        if user_input.get("interview_notes"):
            return str(user_input["interview_notes"])
        # Structured answers: key → value lines (skip control keys)
        parts = []
        for k, v in user_input.items():
            if k in ("approved", "input_type", "_pause") or not v:
                continue
            parts.append(f"{k}: {v}")
        if parts:
            return "\n".join(parts)
        return ""
    return str(user_input or "")


def _parse_approval(user_input: Any) -> tuple[bool, str]:
    """(approved, feedback) from y/yes/True, bool, or {approved, feedback}."""
    if isinstance(user_input, dict):
        answer = user_input.get("approved", True)
        feedback = (
            user_input.get("feedback", user_input.get("user_review_comments", "")) or ""
        )
        if isinstance(answer, bool):
            return answer, str(feedback)
        return _parse_approval(answer)
    if isinstance(user_input, bool):
        return user_input, ""
    return str(user_input).strip().lower() in ("y", "yes", "true"), ""


def _as_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion for artifact counters (corrupt values → default)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_resume_payload(
    phase: str,
    hil_type: str | None,
    user_input: Any,
    *,
    auto_approve: bool = False,
    state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build (resume_data, update_data) for Command(resume=..., update=...).

    Merges the rules that used to live in two places
    (WorkflowRunner._astream_with_hil and WorkflowBridge._build_resume_data):

    - DISCOVER/project_setup: forward setup fields into the resume value and
      pre-seed the checkpoint (update) so the node re-run skips the setup
      gate cleanly (avoids the "orphaned resume" bug, EYW-234).
    - DISCOVER/interview: normalize answers to interview_notes; update
      pre-seeds discover_interview_done so the re-run consumes state.
    - ARCH_REVIEW: (approved, feedback) parsing shared by CLI y/n and the
      Web form dict.
    - generic (e.g. REFLECT): approved/feedback from the handler when
      present; auto_approve defaults to approved.

    ``update_data`` is None when nothing needs checkpoint pre-seeding.
    """
    state = state or {}
    if user_input is None:
        user_input = {"approved": True, "interview_notes": ""}
    if isinstance(user_input, str):
        # '[Label] value' format → dict; otherwise keep the raw string so
        # generic-phase y/n answers still parse (interview_notes coercion
        # happens per-phase below, not up front).
        user_input = parse_formatted_input(user_input) or user_input

    def _artifacts() -> dict[str, Any]:
        arts = dict(state.get("artifacts") or {})
        arts["discover_hil_count"] = _as_int(arts.get("discover_hil_count", 0), 0) + 1
        return arts

    if phase == "DISCOVER":
        if not isinstance(user_input, dict):
            user_input = {"interview_notes": str(user_input)}
        if hil_type == "interview":
            notes = _interview_notes_from(user_input)
            arts = _artifacts()
            arts["interview_notes"] = notes
            resume = {
                "human_approval_required": False,
                "interview_notes": notes,
                "discover_interview_done": True,
                "artifacts": arts,
            }
            update = {"interview_notes": notes, "discover_interview_done": True}
            return resume, update

        if hil_type == "project_setup":
            arts = _artifacts()
            resume = {
                "human_approval_required": False,
                "artifacts": arts,
            }
            update = {"discover_setup_done": True}
            for key in ("project_name", "project_description", "context_folder"):
                value = user_input.get(key)
                if key in user_input:
                    resume[key] = value
                if value:
                    update[key] = value
            return resume, update

        # Unknown DISCOVER type — fall back on hil count (legacy CLI heuristic)
        hil_count = _as_int(
            (state.get("artifacts") or {}).get("discover_hil_count", 0), 0
        )
        if hil_count == 0:
            return build_resume_payload(
                phase,
                "project_setup",
                user_input,
                auto_approve=auto_approve,
                state=state,
            )
        return build_resume_payload(
            phase, "interview", user_input, auto_approve=auto_approve, state=state
        )

    if phase == "ARCH_REVIEW":
        approved, feedback = _parse_approval(user_input)
        return {"approved": approved, "feedback": feedback}, None

    # Generic HIL phase (e.g. REFLECT)
    if isinstance(user_input, dict) and "approved" in user_input:
        approved, feedback = _parse_approval(user_input)
        return {
            "human_approval_required": False,
            "approved": approved,
            "feedback": feedback,
        }, None
    if isinstance(user_input, str):
        approved, feedback = _parse_approval(user_input)
        return {
            "human_approval_required": False,
            "approved": approved,
            "feedback": feedback,
        }, None
    if auto_approve:
        return {"human_approval_required": False, "approved": True}, None
    return {"human_approval_required": False}, None


InputHandler = Callable[[HilPause], Awaitable[Any]]


def _normalize_chunk(item: Any) -> tuple[str, Any]:
    """Normalize an astream item to (mode, payload).

    List stream mode yields (mode, payload) tuples; a bare dict is a values
    snapshot (legacy single-mode shape).
    """
    if (
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], str)
        and item[0] in ("values", "custom")
    ):
        return item[0], item[1]
    return "values", item


async def run_workflow(
    graph,
    *,
    config: dict[str, Any],
    input_state: Any,
    input_handler: InputHandler,
    events: WorkflowEvents,
    auto_approve: bool = False,
    abort_check: Callable[[], bool] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the workflow, pausing at every HIL gate, resuming, until complete.

    Yields values (state snapshot) chunks in stream order so adapters keep
    their last-chunk semantics.

    Args:
        graph: compiled LangGraph graph (with checkpointer).
        config: run config, e.g. {"configurable": {"thread_id": ...}}.
        input_state: initial state dict, None (resume an existing thread),
            or a pre-built Command.
        input_handler: async callable(pause) -> user input (dict|str|None).
            None return stops the run (abort).
        events: WorkflowEvents sink.
        auto_approve: used only for the generic-phase resume default.
        abort_check: optional sync flag getter checked between chunks.
    """
    current_input = input_state
    last_phase: str | None = None
    last_chunk: dict[str, Any] | None = None

    while True:
        if abort_check and abort_check():
            await events.on_aborted()
            return

        # Set when an interrupt was handled this cycle: the pending resume
        # Command is the next input. The stale-node check below MUST NOT
        # run in that case — a suspended task also shows up in
        # graph_state.next, and re-streaming with input=None would drop
        # the resume (infinite HIL loop).
        resumed = False

        try:
            async for item in graph.astream(
                current_input, stream_mode=["values", "custom"], config=config
            ):
                if abort_check and abort_check():
                    break

                mode, payload = _normalize_chunk(item)

                if mode == "custom":
                    await events.on_custom(payload)
                    continue

                chunk: dict[str, Any] = payload
                last_chunk = chunk

                # LangGraph 1.x: interrupt() no longer raises — it yields
                # __interrupt__ in the values chunk and the stream completes.
                if chunk.get("__interrupt__"):
                    graph_state = await graph.aget_state(config)
                    if not graph_state.next and not graph_state.interrupts:
                        # Normal end disguised as interrupt — finish cleanly.
                        clean = {k: v for k, v in chunk.items() if k != "__interrupt__"}
                        yield clean
                        await events.on_complete(clean)
                        return
                    last_phase = chunk.get("phase") or last_phase
                    pause = HilPause(
                        phase=resolve_interrupted_phase(graph_state, chunk, last_phase),
                        hil_type=extract_interrupt_type(
                            chunk.get("__interrupt__"), graph_state.interrupts
                        ),
                        state=graph_state.values or {},
                        interrupts=list(graph_state.interrupts or []),
                    )
                    await events.on_interrupt(pause)
                    user_input = await input_handler(pause)
                    if user_input is None:
                        await events.on_aborted()
                        return
                    resume_data, update_data = build_resume_payload(
                        pause.phase,
                        pause.hil_type,
                        user_input,
                        auto_approve=auto_approve,
                        state=pause.state,
                    )
                    await events.on_resumed(pause, resume_data, update_data)
                    current_input = Command(resume=[resume_data], update=update_data)
                    resumed = True
                    break

                phase = chunk.get("phase", "UNKNOWN")
                if phase != last_phase:
                    last_phase = phase
                await events.on_values(chunk, phase)
                yield chunk

        except GraphInterrupt:  # legacy LangGraph (<1.x) raise-path; see comment below
            # Legacy LangGraph (<1.x) raised the interrupt instead of
            # yielding __interrupt__. Same suspension path.
            graph_state = await graph.aget_state(config)
            if not graph_state.next and not graph_state.interrupts:
                await events.on_complete(last_chunk)
                return
            pause = HilPause(
                phase=resolve_interrupted_phase(graph_state, None, last_phase),
                hil_type=extract_interrupt_type(None, graph_state.interrupts),
                state=graph_state.values or {},
                interrupts=list(graph_state.interrupts or []),
            )
            last_phase = pause.phase
            await events.on_interrupt(pause)
            user_input = await input_handler(pause)
            if user_input is None:
                await events.on_aborted()
                return
            resume_data, update_data = build_resume_payload(
                pause.phase,
                pause.hil_type,
                user_input,
                auto_approve=auto_approve,
                state=pause.state,
            )
            await events.on_resumed(pause, resume_data, update_data)
            current_input = Command(resume=[resume_data], update=update_data)
            resumed = True

        except Exception as e:  # noqa: BLE001 — signal, never crash the adapter
            await events.on_error(e)
            return

        if abort_check and abort_check():
            await events.on_aborted()
            return

        if resumed:
            # Interrupt path: re-stream the pending resume Command. (The
            # async-for above has ended — Pregel completes the step when a
            # node interrupts — so control lands here on both interrupt
            # branches.)
            continue

        # Normal stream end — interrupt_after can leave pending nodes behind
        # (e.g. DISCOVER → DEFINE). If next is non-empty, re-stream with
        # input=None to continue from the checkpoint.
        graph_state = await graph.aget_state(config)
        if graph_state.next:
            await events.on_stale_nodes(list(graph_state.next))
            current_input = None
            continue

        await events.on_complete(last_chunk)
        return
