"""
EYW-235: official SQLite checkpointer (langgraph-checkpoint-sqlite).

Replaces the previous hand-written 265-line custom SqliteSaver module. EYW-233 made
WorkflowState fully serializable, so the custom stripping / resume-quirk logic
had no reason to remain — the official ``AsyncSqliteSaver`` provides the same
SQLite storage, at the same DB file location (``CHECKPOINT_DB`` env, default
``<build_dir>/checkpoints.db``).

Design notes
------------
* Workflows run via ``graph.astream(...)`` (async runtime). The official sync
  ``SqliteSaver`` rejects async calls (``NotImplementedError``), so we use
  ``AsyncSqliteSaver``.
* ``AsyncSqliteSaver.__init__`` captures the running event loop, but the
  checkpointer is constructed synchronously (``WorkflowRunner.__init__``,
  bridge init) — so it is materialized lazily on first awaited use, inside
  the event loop the workflow actually runs in.
* The aiosqlite connection is established lazily on first use (the saver's
  ``_ensure_connected``). Each workflow run gets a fresh checkpointer
  instance against the same DB file — same behavior as before.
"""
from __future__ import annotations

from typing import Any

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class LazyAsyncSqliteSaver(BaseCheckpointSaver[str]):
    """Duck-type-compatible wrapper around the official AsyncSqliteSaver.

    All checkpointer calls are forwarded to the underlying official saver,
    which is materialized lazily on first awaited use (an event loop is
    guaranteed to be running there).

    Accepts a DB file path — the same location/behavior the hand-written
    ``SqliteSaver`` had. Schema setup (tables + WAL) is handled by the
    official saver on first write/read.
    """

    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self._saver: AsyncSqliteSaver | None = None

    # ── API-compatible factory (matches the old SqliteSaver API) ──

    @classmethod
    def from_conn_string(cls, conn_string: str) -> LazyAsyncSqliteSaver:
        """Create from a DB file path (same API as the old SqliteSaver)."""
        return cls(conn_string)

    # ── Lazy materialization ──

    def _materialize(self) -> AsyncSqliteSaver:
        if self._saver is None:
            # Requires a running event loop (AsyncSqliteSaver captures it).
            # The aiosqlite connection itself connects lazily on first use.
            self._saver = AsyncSqliteSaver(aiosqlite.connect(self.db_path))
        return self._saver

    # ── Async interface used by graph.astream / graph.aget_state ──

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._materialize().aget_tuple(config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await self._materialize().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._materialize().aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await self._materialize().adelete_thread(thread_id)

    async def close(self) -> None:
        """Close the underlying connection (releases its worker thread).

        Optional: production code may skip it and let the connection be
        GC'd, exactly as the previous hand-written saver did. Call it
        before the owning event loop closes (tests, short-lived runners)
        to avoid a lingering aiosqlite worker thread.
        """
        if self._saver is not None:
            await self._saver.conn.close()
            self._saver = None

    async def alist(
        self,
        config: RunnableConfig | None = None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        async for item in self._materialize().alist(
            config, filter=filter, before=before, limit=limit
        ):
            yield item

    # ── Forward anything else (setup, copy_thread, sync get_tuple, ...) ──

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in ("db_path", "_saver"):
            raise AttributeError(name)
        return getattr(self._materialize(), name)
