"""Tests for graph/sqlite_saver.py — checkpoint persistence, concurrent access."""
import json
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestSqliteSaverInit:
    """Test SqliteSaver initialization."""

    def test_init_creates_schema(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        db_path = str(tmp_path / "test.db")
        saver = SqliteSaver(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "checkpoints" in tables
        assert "writes" in tables
        conn.close()

    def test_from_conn_string(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        db_path = str(tmp_path / "test.db")
        saver = SqliteSaver.from_conn_string(db_path)
        assert saver.db_path == db_path


class TestSqliteSaverPut:
    """Test checkpoint persistence."""

    def _make_config(self, thread_id: str = "test-thread") -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _make_checkpoint(self, cp_id: str = "cp-001") -> dict:
        return {"id": cp_id, "v": 1, "ts": "2024-01-01T00:00:00Z", "step": 1}

    def test_put_and_get(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config()
        checkpoint = self._make_checkpoint()
        metadata = {"source": "test"}

        result = saver.put(config, checkpoint, metadata, None)
        assert result["configurable"]["thread_id"] == "test-thread"
        assert "checkpoint_id" in result["configurable"]

        fetched = saver.get_tuple(config)
        assert fetched is not None
        assert fetched.checkpoint["id"] == "cp-001"
        assert fetched.metadata == {"source": "test"}

    def test_put_overwrites_existing(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config()
        saver.put(config, self._make_checkpoint("cp-001"), {}, None)
        saver.put(config, self._make_checkpoint("cp-002"), {"v": 2}, None)

        fetched = saver.get_tuple(config)
        assert fetched.checkpoint["id"] == "cp-002"
        assert fetched.metadata == {"v": 2}

    def test_get_nonexistent_thread(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config("nonexistent")
        fetched = saver.get_tuple(config)
        assert fetched is None

    def test_put_writes(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config()
        saver.put(config, self._make_checkpoint("cp-001"), {}, None)
        cp_id = config["configurable"].get("checkpoint_id")

        # Put after the checkpoint so cp_id is set
        saver.put_writes(
            {"configurable": {"thread_id": "test-thread", "checkpoint_id": "cp-001"}},
            [("channel_a", "value_a"), ("channel_b", "value_b")],
            task_id="task-1",
        )
        # Just verify no exception

    def test_delete_thread(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config("to-delete")
        saver.put(config, self._make_checkpoint(), {}, None)

        fetched = saver.get_tuple(config)
        assert fetched is not None

        saver.delete_thread("to-delete")
        fetched = saver.get_tuple(config)
        assert fetched is None


class TestSqliteSaverList:
    """Test listing checkpoints."""

    def test_list_returns_checkpoints(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = {"configurable": {"thread_id": "thread-a"}}
        saver.put(config, self._make_checkpoint("cp-001"), {"n": 1}, None)
        saver.put(config, self._make_checkpoint("cp-002"), {"n": 2}, None)

        results = list(saver.list(config))
        assert len(results) == 2

    def test_list_with_limit(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = {"configurable": {"thread_id": "thread-a"}}
        saver.put(config, self._make_checkpoint("cp-001"), {}, None)
        saver.put(config, self._make_checkpoint("cp-002"), {}, None)
        saver.put(config, self._make_checkpoint("cp-003"), {}, None)

        results = list(saver.list(config, limit=2))
        assert len(results) == 2

    def test_list_no_thread_id(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        # No thread filter — returns all
        saver.put(
            {"configurable": {"thread_id": "t1"}},
            self._make_checkpoint("cp-001"), {}, None
        )
        saver.put(
            {"configurable": {"thread_id": "t2"}},
            self._make_checkpoint("cp-002"), {}, None
        )
        results = list(saver.list(None))
        assert len(results) == 2

    def _make_checkpoint(self, cp_id: str = "cp-001") -> dict:
        return {"id": cp_id, "v": 1, "ts": "2024-01-01T00:00:00Z", "step": 1}


class TestSqliteSaverConcurrent:
    """Test thread safety of SQLite saver."""

    def test_concurrent_writes(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))

        errors = []

        def worker(thread_num):
            try:
                for i in range(10):
                    config = {"configurable": {"thread_id": f"thread-{thread_num}"}}
                    cp = {
                        "id": f"cp-{thread_num}-{i}",
                        "v": 1,
                        "ts": "2024-01-01T00:00:00Z",
                        "step": i,
                    }
                    saver.put(config, cp, {"worker": thread_num}, None)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors}"

    def test_per_thread_connections(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        conn1 = saver._get_conn()
        conn2 = saver._get_conn()
        # Same thread should return same connection
        assert conn1 is conn2


class TestWorkflowStateRoundTrip:
    """EYW-233 (Task A): WorkflowState is fully serializable.

    ``skill_callback`` (a Python callable) no longer lives in state — skill
    progress moved to the node ``writer()`` "custom" stream — so the state
    round-trips through the checkpointer with zero stripping required and
    ``SqliteSaver._strip_unserializable`` is gone.
    """

    def _make_config(self, thread_id: str = "roundtrip-thread") -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _make_state(self) -> dict:
        from graph.state import CycleMetrics
        return {
            "cycle_id": "1",
            "phase": "PLAN",
            "metrics": CycleMetrics(review_revisions=2, task_count=7),
            "feedback": [{"skill": "doubt-driven-development", "output": "risk A"}],
            "feedback_context": "context",
            "config_version": "1",
            "human_approval_required": True,
            "next_phase": "ARCH_REVIEW",
            "project_name": "TestApp",
            "project_path": "output/TestApp",
            "project_folder": "TestApp",
            "project_description": "A test app",
            "skip_discover": False,
            "context_folder": "",
            "error": None,
            "diagrams": {"context": "digraph { A -> B; }"},
            "diagram_status": "approved",
            "diagram_feedback": "",
            "improve_mode": False,
            "auto_approve_override": None,
            "force_hil": False,
            "interview_notes": "notes",
            "discover_setup_done": True,
            "discover_interview_done": True,
            "trace_id": "trace-1",
            "superweb_mode": "",
            "superweb_agent_report": None,
            "artifacts": {"plan": "task breakdown", "spec": "# spec"},
            "project_context": "",
            "spec_text": "# spec",
            "spec_refined": "",
            "plan": "tasks",
            "tasks": "tasks",
            "backlog": [],
            "diagram_pngs": {},
            "user_review_comments": "",
            "status": "running",
            "retry_count": 0,
            "tasks_text": "",
            "solution_md": "",
        }

    def test_full_state_round_trips_without_stripping(self, tmp_path):
        from graph.sqlite_saver import SqliteSaver
        saver = SqliteSaver(str(tmp_path / "test.db"))
        config = self._make_config()
        checkpoint = {
            "id": "cp-rt-1",
            "v": 1,
            "ts": "2026-08-25T00:00:00Z",
            "step": 1,
            "channel_values": self._make_state(),
        }
        saver.put(config, checkpoint, {"source": "test"}, None)
        fetched = saver.get_tuple(config)
        assert fetched is not None
        restored = fetched.checkpoint["channel_values"]
        # No keys dropped, values intact.
        assert restored["phase"] == "PLAN"
        assert restored["artifacts"] == {"plan": "task breakdown", "spec": "# spec"}
        assert restored["metrics"].review_revisions == 2
        assert restored["metrics"].task_count == 7
        assert restored["feedback"] == [
            {"skill": "doubt-driven-development", "output": "risk A"}
        ]
        # The old non-serializable key no longer exists in state at all.
        assert "skill_callback" not in restored

    def test_strip_unserializable_is_gone(self):
        from graph.sqlite_saver import SqliteSaver
        assert not hasattr(SqliteSaver, "_strip_unserializable")
        assert hasattr(SqliteSaver, "_serialize")  # serialization path intact
