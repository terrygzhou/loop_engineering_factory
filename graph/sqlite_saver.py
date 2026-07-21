"""
Custom SQLite checkpoint saver for LangGraph.

Replaces langgraph.checkpoint.sqlite which was removed in langgraph >= 1.0.
"""
import sqlite3
import json
import threading
import uuid
from typing import Any, Iterator, Optional, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langchain_core.runnables import RunnableConfig

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint BLOB NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    value BLOB NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id, task_id, channel)
);
"""

class SqliteSaver(BaseCheckpointSaver[int]):
    """Thread-safe SQLite checkpoint saver.

    Each thread gets its own sqlite3.Connection via threading.local(),
    avoiding cross-thread ProgrammingError when LangGraph dispatches
    nodes to a thread pool.
    """

    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self._local = threading.local()
        # Init schema in the main thread immediately
        self._get_conn()

    def _get_conn(self) -> sqlite3.Connection:
        """Lazily create a per-thread connection with schema."""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path)
            cur = self._local.conn.cursor()
            cur.executescript(_INIT_SQL)
            self._local.conn.commit()
        return self._local.conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """Property alias for backwards compat with rest of class."""
        return self._get_conn()

    @classmethod
    def from_conn_string(cls, conn_string: str) -> "SqliteSaver":
        """Create from file path or URI (matches original SqliteSaver API)."""
        return cls(conn_string)

    # ── Sync methods ──

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        cfg = config.get("configurable", {})
        thread_id = cfg.get("thread_id")
        if not thread_id:
            return None
        cur = self._conn.cursor()
        cur.execute(
            "SELECT checkpoint_id, parent_checkpoint_id, checkpoint, metadata "
            "FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_id DESC LIMIT 1",
            (thread_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cp_id, parent_id, blob, meta_str = row
        # Use serde to deserialize
        checkpoint = self._deserialize(blob)
        metadata = json.loads(meta_str) if meta_str else {}
        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}}
                if parent_id else None
            ),
        )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None:
            config = {}
        cfg = config.get("configurable", {})
        thread_id = cfg.get("thread_id")
        query = "SELECT checkpoint_id, parent_checkpoint_id, checkpoint, metadata FROM checkpoints"
        params = []
        if thread_id:
            query += " WHERE thread_id = ?"
            params.append(thread_id)
        query += " ORDER BY checkpoint_id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        cur = self._conn.cursor()
        cur.execute(query, params)
        for cp_id, parent_id, blob, meta_str in cur.fetchall():
            checkpoint = self._deserialize(blob)
            metadata = json.loads(meta_str) if meta_str else {}
            yield CheckpointTuple(
                config={"configurable": {"thread_id": thread_id, "checkpoint_id": cp_id}},
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=(
                    {"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}}
                    if parent_id else None
                ),
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        cfg = config.get("configurable", {})
        thread_id = cfg.get("thread_id")
        cp_id = checkpoint.get("id", str(uuid.uuid4()))
        parent_id = cfg.get("parent_checkpoint_id")
        blob = self._serialize(checkpoint)
        meta_str = json.dumps(metadata) if metadata else "{}"
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO checkpoints (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (thread_id, cp_id, parent_id, blob, meta_str),
        )
        self._conn.commit()
        return {"configurable": {"thread_id": thread_id, "checkpoint_id": cp_id}}

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        cfg = config.get("configurable", {})
        thread_id = cfg.get("thread_id")
        cp_id = cfg.get("checkpoint_id")
        if not thread_id or not cp_id:
            return
        cur = self._conn.cursor()
        for channel, value in writes:
            blob = self._serialize(value)
            cur.execute(
                "INSERT OR REPLACE INTO writes (thread_id, checkpoint_id, task_id, channel, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (thread_id, cp_id, task_id, channel, blob),
            )
        self._conn.commit()

    def delete_thread(self, thread_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        cur.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        self._conn.commit()

    # ── Serialization helpers ──

    def _serialize(self, obj: Any) -> bytes:
        """Serialize using the base serde (msgpack via dumps_typed)."""
        _, blob = self.serde.dumps_typed(obj)
        return blob

    def _deserialize(self, blob: bytes) -> Any:
        """Deserialize using the base serde (msgpack via loads_typed)."""
        return self.serde.loads_typed(("msgpack", blob))

    # ── Async wrappers (simple sync delegation) ──

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return self.get_tuple(config)

    async def alist(
        self, config, *, filter=None, before=None, limit=None
    ):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str):
        self.delete_thread(thread_id)
