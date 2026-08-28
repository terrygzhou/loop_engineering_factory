"""Abort manager — shared abort signal for workflow cancellation.

Usage:
    manager = AbortManager.get()
    manager.clear()         # before start
    manager.signal()       # on abort
    await manager.wait(1.0) # in workflow loop
"""

import asyncio


class AbortManager:
    _instance: "AbortManager | None" = None

    def __init__(self):
        self._abort_event = asyncio.Event()

    @classmethod
    def get(cls) -> "AbortManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def signal(self):
        self._abort_event.set()

    def clear(self):
        self._abort_event.clear()

    @property
    def is_aborted(self) -> bool:
        return self._abort_event.is_set()

    async def wait(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._abort_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
