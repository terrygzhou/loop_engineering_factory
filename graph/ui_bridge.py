"""
Skill progress bridge — nodes use this to report skill invocations
to the UI via LangGraph's custom stream (``get_stream_writer()``).

Events are emitted as ``{"type": "skill_progress", ...}`` payloads on the
"custom" stream mode. The Web bridge (frontend/backend/workflow_bridge.py)
consumes ``stream_mode=["values", "custom"]`` and shapes them into the
UI event schema (frontend/static/js/app.js keys off
``event.type === 'skill_progress'``).

EYW-233 (Task A): skill progress no longer travels through
``WorkflowState`` (no more ``state["skill_callback"]`` function), so
state is fully serializable and needs no checkpointer-side stripping.
Outside a runnable/stream context the writer is a no-op, which keeps
CLI runs and standalone test calls safe.
"""

import time
from typing import Any

from langgraph.config import get_stream_writer as _raw_get_stream_writer

_NOOP = lambda *a, **kw: None  # noqa: E731


def _writer():
    """Safe stream writer: no-op when called outside a runnable context."""
    try:
        return _raw_get_stream_writer() or _NOOP
    except RuntimeError:
        return _NOOP


def report_skill_running(skill_name: str):
    """Report that a skill invocation has started."""
    _writer()({"type": "skill_progress", "skill": skill_name, "event": "running"})


def report_skill_completed(
    skill_name: str, duration_s: float = 0, details: dict[str, Any] | None = None
):
    """Report that a skill invocation has completed."""
    _writer()(
        {
            "type": "skill_progress",
            "skill": skill_name,
            "event": "completed",
            "details": {"duration_s": duration_s, **(details or {})},
        }
    )


def report_skill_failed(skill_name: str, error: str = ""):
    """Report that a skill invocation failed."""
    _writer()(
        {
            "type": "skill_progress",
            "skill": skill_name,
            "event": "failed",
            "details": {"error": error},
        }
    )


class SkillTimer:
    """Helper that auto-reports skill running → completed (EYW-233: stateless)."""

    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        self.start = time.time()
        report_skill_running(skill_name)

    def complete(
        self, duration_s: float | None = None, details: dict[str, Any] | None = None
    ):
        elapsed = duration_s or (time.time() - self.start)
        report_skill_completed(self.skill_name, elapsed, details)

    def fail(self, error: str = ""):
        report_skill_failed(self.skill_name, error)
