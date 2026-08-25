"""Tests for graph/checkpointer.py — official AsyncSqliteSaver (EYW-235).

Replaces tests/test_sqlite_saver.py (the hand-written graph/sqlite_saver.py
was deleted in EYW-235). Covers:

- lazy materialization + schema setup (checkpoints/writes tables)
- put/get round-trip, overwrite, missing thread
- put_writes, delete_thread
- list + limit
- concurrency: multiple threads/loops writing the same DB file
  (one checkpointer per event loop — the production pattern)
- full WorkflowState round-trip (EYW-233: fully serializable, no stripping)
- graph-level HIL interrupt → resume → cross-instance persistence (e2e)
- old module is gone (guard against re-introduction)
"""
import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest


def _run(coro):
    """Run a coroutine in a fresh event loop (matches production: one loop
    per workflow run)."""
    return asyncio.run(coro)


def _config(thread_id: str = "test-thread", checkpoint_id: str | None = None) -> dict:
    """RunnableConfig as the Pregel runtime provides it (checkpoint_ns is
    always injected by the runtime)."""
    cfg = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id:
        cfg["checkpoint_id"] = checkpoint_id
    return {"configurable": cfg}


class TestLazySaverInit:
    def test_init_is_lazy_no_db_touch(self, tmp_path):
        """Construction is pure attribute setup — no connection, no schema."""
        from graph.checkpointer import LazyAsyncSqliteSaver

        db = str(tmp_path / "test.db")
        saver = LazyAsyncSqliteSaver(db)
        assert saver.db_path == db
        assert not Path(db).exists()  # nothing created until first use

    def test_from_conn_string(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        db = str(tmp_path / "test.db")
        saver = LazyAsyncSqliteSaver.from_conn_string(db)
        assert saver.db_path == db

    def test_schema_created_on_first_use(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        db = str(tmp_path / "test.db")
        saver = LazyAsyncSqliteSaver(db)

        async def use():
            cp = {"id": "cp-001", "v": 1, "ts": "2024-01-01T00:00:00Z", "step": 1}
            result = await saver.aput(_config(), cp, {"source": "test"}, {})
            await saver.close()
            return result

        _run(use())
        conn = sqlite3.connect(db)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "checkpoints" in tables
        assert "writes" in tables


class TestLazySaverPut:
    def _cp(self, cp_id: str = "cp-001") -> dict:
        return {"id": cp_id, "v": 1, "ts": "2024-01-01T00:00:00Z", "step": 1}

    def test_put_and_get(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            result = await saver.aput(_config(), self._cp(), {"source": "test"}, {})
            fetched = await saver.aget_tuple(_config())
            await saver.close()
            return result, fetched

        result, fetched = _run(use())
        assert result["configurable"]["thread_id"] == "test-thread"
        assert "checkpoint_id" in result["configurable"]
        assert fetched is not None
        assert fetched.checkpoint["id"] == "cp-001"
        assert fetched.metadata.get("source") == "test"

    def test_put_overwrites_existing(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.aput(_config(), self._cp("cp-001"), {}, {})
            await saver.aput(_config(), self._cp("cp-002"), {"v": 2}, {})
            fetched = await saver.aget_tuple(_config())
            await saver.close()
            return fetched

        fetched = _run(use())
        assert fetched.checkpoint["id"] == "cp-002"
        assert fetched.metadata.get("v") == 2

    def test_get_nonexistent_thread(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.setup()
            out = await saver.aget_tuple(_config("nonexistent"))
            await saver.close()
            return out

        assert _run(use()) is None

    def test_put_writes(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.aput(_config(), self._cp("cp-001"), {}, {})
            await saver.aput_writes(
                _config(checkpoint_id="cp-001"),
                [("channel_a", "value_a"), ("channel_b", "value_b")],
                task_id="task-1",
            )
            await saver.close()

        _run(use())  # just verify no exception

    def test_delete_thread(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.aput(_config("to-delete"), self._cp(), {}, {})
            before = await saver.aget_tuple(_config("to-delete"))
            await saver.adelete_thread("to-delete")
            after = await saver.aget_tuple(_config("to-delete"))
            await saver.close()
            return before, after

        before, after = _run(use())
        assert before is not None
        assert after is None


class TestLazySaverList:
    def _cp(self, cp_id: str) -> dict:
        return {"id": cp_id, "v": 1, "ts": "2024-01-01T00:00:00Z", "step": 1}

    def test_list_returns_checkpoints(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.aput(_config("thread-a"), self._cp("cp-001"), {"n": 1}, {})
            await saver.aput(_config("thread-a"), self._cp("cp-002"), {"n": 2}, {})
            out = [t async for t in saver.alist(_config("thread-a"))]
            await saver.close()
            return out

        results = _run(use())
        assert len(results) == 2

    def test_list_with_limit(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            for i in range(3):
                await saver.aput(_config("thread-a"), self._cp(f"cp-00{i+1}"), {}, {})
            out = [t async for t in saver.alist(_config("thread-a"), limit=2)]
            await saver.close()
            return out

        results = _run(use())
        assert len(results) == 2

    def test_list_no_thread_id(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))

        async def use():
            await saver.aput(_config("t1"), self._cp("cp-001"), {}, {})
            await saver.aput(_config("t2"), self._cp("cp-002"), {}, {})
            out = [t async for t in saver.alist(None)]
            await saver.close()
            return out

        results = _run(use())
        assert len(results) == 2


class TestLazySaverConcurrent:
    """One checkpointer per event loop (the production pattern): each thread
    runs its own asyncio.run() with its own saver against the same DB file."""

    def test_concurrent_writes(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver

        db = str(tmp_path / "test.db")
        errors: list[str] = []
        lock = threading.Lock()

        def worker(thread_num: int):
            async def run():
                saver = LazyAsyncSqliteSaver(db)
                for i in range(10):
                    cfg = _config(f"thread-{thread_num}")
                    cp = {
                        "id": f"cp-{thread_num}-{i}",
                        "v": 1,
                        "ts": "2024-01-01T00:00:00Z",
                        "step": i,
                    }
                    await saver.aput(cfg, cp, {"worker": thread_num}, {})
                await saver.close()

            try:
                asyncio.run(run())
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors}"

        # All 40 checkpoints persisted across the per-loop savers.
        async def verify():
            saver = LazyAsyncSqliteSaver(db)
            total = 0
            for i in range(4):
                total += len([t async for t in saver.alist(_config(f"thread-{i}"))])
            await saver.close()
            return total

        assert _run(verify()) == 40


class TestWorkflowStateRoundTrip:
    """EYW-233 (Task A) + EYW-235: WorkflowState is fully serializable.

    ``skill_callback`` (a Python callable) no longer lives in state, so the
    state round-trips through the official checkpointer with no stripping.
    """

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
        from graph.checkpointer import LazyAsyncSqliteSaver

        saver = LazyAsyncSqliteSaver(str(tmp_path / "test.db"))
        checkpoint = {
            "id": "cp-rt-1",
            "v": 1,
            "ts": "2026-08-25T00:00:00Z",
            "step": 1,
            "channel_values": self._make_state(),
        }

        async def use():
            await saver.aput(_config("roundtrip-thread"), checkpoint, {"source": "test"}, {})
            fetched = await saver.aget_tuple(_config("roundtrip-thread"))
            await saver.close()
            return fetched

        fetched = _run(use())
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


class TestOldSaverGone:
    def test_module_removed(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("graph.sqlite_saver")


class TestGraphInterruptResumeE2E:
    """HIL interrupt → resume through the production checkpointer, on a real
    compiled StateGraph — the acceptance path for EYW-235 (checkpointer
    level, no LLM needed)."""

    def _build_graph(self):
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt

        class S(TypedDict):
            total: int
            answer: str

        def node_a(state: S):
            return {"total": state["total"] + 1}

        def node_b(state: S):
            ans = interrupt("ARCH_REVIEW gate: approve?")
            return {"answer": ans}

        g = StateGraph(S)
        g.add_node("a", node_a)
        g.add_node("b", node_b)
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        return g

    def test_interrupt_resume_and_persistence(self, tmp_path):
        from graph.checkpointer import LazyAsyncSqliteSaver
        from langgraph.types import Command

        db = str(tmp_path / "cp.db")
        builder = self._build_graph()
        config = {"configurable": {"thread_id": "e2e-1", "checkpoint_ns": ""}}

        async def use():
            # ── Run 1: stream until the interrupt suspends the graph ──
            saver = LazyAsyncSqliteSaver.from_conn_string(db)
            graph = builder.compile(checkpointer=saver)

            async for _ in graph.astream({"total": 0}, config, stream_mode="values"):
                pass  # stream ends when the graph suspends at interrupt()

            st = await graph.aget_state(config)
            assert st.next, "graph should be suspended at the HIL gate"
            assert "answer" not in (st.values or {})

            # ── Run 2 (same loop): resume with Command(resume=...) ──
            out = None
            async for chunk in graph.astream(Command(resume="yes"), config, stream_mode="values"):
                out = chunk
            assert out is not None and out["answer"] == "yes"
            assert out["total"] == 1

            # ── Run 3 (fresh loop + fresh checkpointer, same DB file):
            #    persisted state must be readable — proves the SQLite file
            #    is the source of truth, not in-memory state.
            saver2 = LazyAsyncSqliteSaver.from_conn_string(db)
            graph2 = builder.compile(checkpointer=saver2)
            st2 = await graph2.aget_state(config)
            assert st2.values["answer"] == "yes"
            assert st2.values["total"] == 1
            assert not st2.next, "resumed graph should be complete"
            await saver.close()
            await saver2.close()

        _run(use())
        assert Path(db).exists(), "checkpoint DB file must exist on disk"
