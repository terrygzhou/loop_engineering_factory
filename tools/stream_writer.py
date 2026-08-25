"""Safe stream-writer access for node code.

langgraph's ``get_stream_writer()`` raises ``RuntimeError`` when called
outside a runnable context (unit tests, CLI runs). Nodes need a no-op
fallback there, so this module wraps the call and never raises.

Tests that patch ``langgraph.config.get_stream_writer`` keep working: if the
patched value is callable it is returned as-is, otherwise (or if the real
call raises) a no-op writer is returned.
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from langgraph.config import get_stream_writer
except ImportError:  # pragma: no cover - langgraph is a hard dependency
    get_stream_writer = None  # type: ignore[assignment]

Writer = Callable[..., None]


def safe_stream_writer() -> Writer:
    """Return the active stream writer, or a no-op fallback when unavailable.

    The returned callable always accepts ``writer(event_dict)`` — positional
    and/or keyword arguments — so callers do not need to branch on context.
    """
    try:
        writer = get_stream_writer()  # type: ignore[misc]
    except Exception:
        return lambda *_args: None  # type: ignore[return-value]
    if writer is None:
        return lambda *_args: None  # type: ignore[return-value]
    return writer


def noop_writer(*_args: Any, **_kwargs: Any) -> None:
    """Explicit no-op stream writer (useful in tests and fixtures)."""
    return None
