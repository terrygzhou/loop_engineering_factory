"""Abort manager — per-workflow abort signal for workflow cancellation.

E4: two caches, each keyed so a stale state is never observed:

- per-workflow: the manager instance is keyed on the workflow id, so two
  concurrent workflows each get a dedicated manager and never share an
  abort flag.
- per-loop: the ``asyncio.Event`` is created lazily on first use inside
  the running loop (per-loop recreation), so an event created on loop A
  is NEVER observed on loop B — cross-loop ``is_aborted`` / ``wait`` see
  a fresh state rather than a stale one.

Usage:
    manager = AbortManager.get("wf-1")   # or get() for the default workflow
    manager.clear()         # before start
    manager.signal()       # on abort
    await manager.wait(1.0) # in workflow loop
"""

import asyncio
import itertools
import weakref as _weakref

_DEFAULT_WORKFLOW_ID = "__default__"
# Monotonic counter assigned per running loop object (weak ref). CPython's
# id() is not stable (GC can reuse a dead loop's address), so each live
# loop object is tagged with a unique, never-reused counter value. The
# weakref keeps the cache itself from pinning dead loops.
_LOOP_TAGS: "_weakref.WeakKeyDictionary" = _weakref.WeakKeyDictionary()
_LOOP_CTR = itertools.count(1)


def _loop_id() -> int:
    """Stable identifier for the running loop; 0 when no loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0
    stable = _LOOP_TAGS.get(loop)
    if stable is None:
        stable = next(_LOOP_CTR)
        _LOOP_TAGS[loop] = stable
    return stable


class AbortManager:
    """Abort signal scoped to one workflow id.

    ``get(workflow_id)`` returns a manager dedicated to that workflow; the
    no-arg ``get()`` keeps the module default for single-workflow callers.
    The underlying ``asyncio.Event`` is created lazily on first use inside
    the owning loop (per-loop recreation), so a manager observed across
    loops always sees a fresh, un-aborted state.
    """

    # (workflow_id, loop_id) -> dedicated manager instance
    _managers: dict[tuple[str, int], "AbortManager"] = {}

    def __init__(self, workflow_id: str = _DEFAULT_WORKFLOW_ID):
        self._workflow_id = workflow_id
        # Per-loop event cache: loop_id -> asyncio.Event (recreated per
        # loop so a stale cross-loop event is never observed).
        self._events: dict[int, asyncio.Event] = {}

    @classmethod
    def get(cls, workflow_id: str | None = None) -> "AbortManager":
        wf = workflow_id if workflow_id is not None else _DEFAULT_WORKFLOW_ID
        key = (wf, _loop_id())
        manager = cls._managers.get(key)
        if manager is None:
            manager = cls(wf)
            cls._managers[key] = manager
        return manager

    def _event(self) -> asyncio.Event:
        """Event for the current loop; created on first use in this loop."""
        loop_id = _loop_id()
        event = self._events.get(loop_id)
        if event is None:
            event = asyncio.Event()
            self._events[loop_id] = event
        return event

    def clear(self):
        self._event().clear()

    def signal(self):
        self._event().set()

    @property
    def is_aborted(self) -> bool:
        return self._event().is_set()

    async def wait(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._event().wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
