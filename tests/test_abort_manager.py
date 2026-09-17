"""Tests for E4 — per-workflow AbortManager (tasks.md §3).

AbortManager.get(workflow_id) SHALL key its cached state on the owning
event loop AND the workflow id:
- two managers for two workflow ids on the same loop are isolated;
- an event created on loop A is never observed on loop B (per-loop
  recreation on first use in the running loop — fresh un-aborted state);
- the module-level no-arg get() keeps working (default workflow id).
"""
import asyncio
import sys
from pathlib import Path

sys_path_hack = Path(__file__).resolve().parent.parent
if str(sys_path_hack) not in sys.path:
    sys.path.insert(0, str(sys_path_hack))

from frontend.backend.abort_manager import AbortManager  # noqa: E402


class TestWorkflowIsolation:
    """Two concurrent workflows on the same loop must not share a flag."""

    def test_signal_one_does_not_affect_other(self):
        async def scenario():
            mgr_a = AbortManager.get("wf-a")
            mgr_b = AbortManager.get("wf-b")
            mgr_a.clear()
            mgr_b.clear()
            mgr_a.signal()
            assert mgr_a.is_aborted is True
            assert mgr_b.is_aborted is False
            mgr_b.signal()
            assert mgr_a.is_aborted is True
            assert mgr_b.is_aborted is True

        asyncio.run(scenario())

    def test_wait_isolates_workflows(self):
        async def scenario():
            mgr_b = AbortManager.get("wf-b")
            mgr_b.clear()
            result = await mgr_b.wait(0.1)
            assert result is False  # B not aborted → wait times out

        asyncio.run(scenario())


class TestCrossLoopRecreation:
    """An event created on loop A must not be observed on loop B."""

    def test_fresh_loop_observes_fresh_state(self):
        # Loop 1: use + signal the manager, then exit.
        async def first_loop():
            mgr = AbortManager.get("wf-x")
            mgr.clear()
            mgr.signal()
            assert mgr.is_aborted is True

        asyncio.run(first_loop())

        # Loop 2 (fresh): the cached event from loop 1 must not be
        # observed — wait() on the fresh loop sees a fresh, un-aborted
        # state and times out cleanly.
        async def second_loop():
            mgr = AbortManager.get("wf-x")
            assert mgr.is_aborted is False
            assert await mgr.wait(0.1) is False

        asyncio.run(second_loop())


class TestDefaultWorkflowId:
    """Module-level no-arg get() keeps working for single-workflow callers."""

    def test_get_without_id_returns_manager(self):
        m = AbortManager.get()
        assert isinstance(m, AbortManager)

    def test_default_isolated_from_named_workflow(self):
        async def scenario():
            default = AbortManager.get()
            named = AbortManager.get("wf-z")
            assert default is not named  # dedicated managers per workflow
            named.clear()
            named.signal()
            assert default.is_aborted is False  # B's signal did not leak to default
            default.clear()
            assert named.is_aborted is True

        asyncio.run(scenario())
