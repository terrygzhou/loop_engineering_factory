"""
Build proxy — HTTP client that delegates the BUILD phase to the builder service.

Polls the builder for completion status. Falls back to the local build_subgraph
if the builder is unreachable.
"""
import asyncio
import uuid
from typing import Callable

import httpx

POLL_INTERVAL = 5  # seconds between status polls
BUILD_TIMEOUT = 3600  # 1 hour hard limit


class BuildProxy:
    """Async HTTP client for the builder service."""

    def __init__(self, builder_url: str, timeout: float = 300.0):
        self.builder_url = builder_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def build(self, state: dict) -> dict:
        """Submit a build to the builder service and poll until complete.

        Returns partial update dict (LangGraph reducer merges).
        """
        build_id = (
            f"{state['project_name']}-{state.get('cycle_id', 'local')}"
            f"-{uuid.uuid4().hex[:8]}"
        )

        artifacts = state.get("artifacts", {}) or {}

        # ── Build request payload ──
        solution_md = artifacts.get("solution_md", "")
        if not solution_md and artifacts.get("solution_path"):
            try:
                import pathlib
                solution_md = pathlib.Path(artifacts["solution_path"]).read_text()
            except Exception:
                pass

        req = {
            "build_id": build_id,
            "project_name": state["project_name"],
            "project_path": state.get("project_path", ""),
            "spec_text": artifacts.get("spec_refined", ""),
            "tasks_text": artifacts.get("tasks", ""),
            "backlog": state.get("build_backlog") or [],
            "solution_md": solution_md,
        }

        # ── Submit build to builder ──
        response = await self.client.post(
            f"{self.builder_url}/api/build",
            json=req,
        )
        response.raise_for_status()
        print(f"  → [BUILD_PROXY] Build {build_id} submitted to builder")

        # ── Poll until complete ──
        loop = asyncio.get_running_loop()
        start = loop.time()

        while True:
            await asyncio.sleep(POLL_INTERVAL)

            status_resp = await self.client.get(
                f"{self.builder_url}/api/build/{build_id}"
            )
            status_resp.raise_for_status()
            status = status_resp.json()

            if status["status"] in ("pass", "fail", "partial"):
                print(
                    f"  → [BUILD_PROXY] Build {build_id} completed: "
                    f"{status['status']}"
                )
                return self._merge_results(state, status)

            elapsed = loop.time() - start
            if elapsed > BUILD_TIMEOUT:
                print(f"  → [BUILD_PROXY] Build {build_id} timed out")
                return {
                    "error": f"Build proxy timeout after {BUILD_TIMEOUT}s",
                    "phase": "BUILD",
                }

            print(
                f"  → [BUILD_PROXY] Build status: "
                f"{status.get('status', 'unknown')} "
                f"({status.get('sub_phase', 'unknown')})"
            )

    # ── Result merging ──

    @staticmethod
    def _merge_results(state: dict, build_status: dict) -> dict:
        """Merge builder results back as a partial state update."""
        # Artifacts delta
        artifacts_delta: dict[str, str] = {
            "build_status": build_status["status"],
            "build_progress": build_status.get("progress", []),
            "build_errors": build_status.get("errors", []),
            "build_artifacts": build_status.get("artifacts", {}),
        }

        # Metrics update
        current_metrics = state.get("metrics")
        metrics_update = None
        if current_metrics and hasattr(current_metrics, "model_copy"):
            metrics_update = current_metrics.model_copy()

        # Retry guard
        fail_count = state.get("_build_fail_count", 0)
        status = build_status["status"]
        if status == "fail":
            fail_count += 1
            if fail_count >= 3:
                return {
                    "phase": "BUILD",
                    "error": (
                        f"Build failed {fail_count} times consecutively — "
                        f"aborting to prevent infinite retry loop. "
                        f"Errors: {build_status.get('errors', [])}"
                    ),
                    "next_phase": "REFLECT",
                    "artifacts": artifacts_delta,
                    "_build_fail_count": fail_count,
                }

        update: dict = {
            "phase": "BUILD",
            "artifacts": artifacts_delta,
            "build_backlog": build_status.get("progress", []),
        }
        if metrics_update:
            update["metrics"] = metrics_update

        if status == "pass":
            update["next_phase"] = "SHIP"
        elif status == "fail":
            update["_build_fail_count"] = fail_count

        return update

    # ── Lifecycle ──

    async def close(self):
        await self.client.aclose()


# ── Fallback: local build via build_subgraph ──
def _build_local(state: dict) -> dict:
    """Run the build locally using the existing build_subgraph."""
    from graph.nodes.build_subgraph_legacy import (
        build_input_mapping,
        build_output_mapping,
        build_subgraph,
    )

    child_state = build_input_mapping(state)
    compiled = build_subgraph().compile()
    result = compiled.invoke(child_state)
    return build_output_mapping(result)


# ── Public factory ──
def build_proxy_node(
    builder_url: str = "http://builder:8200",
) -> Callable[[dict], dict]:
    """
    Factory that returns a node function for LangGraph.

    Tries the remote builder first. If unreachable, falls back to
    the local build_subgraph so the orchestrator never dead-ends.

    Returns partial update dict (LangGraph reducer merges).
    """
    def _node(state: dict) -> dict:
        proxy = BuildProxy(builder_url)
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(proxy.build(state))
            loop.run_until_complete(proxy.client.aclose())
            loop.close()
            return result
        except (httpx.ConnectError, httpx.ConnectTimeout, ConnectionError):
            print(
                f"  → [BUILD_PROXY] Builder at {builder_url} unreachable; "
                f"falling back to local build"
            )
            return _build_local(state)
        except Exception:
            print(
                f"  → [BUILD_PROXY] Unexpected error from builder at "
                f"{builder_url}; falling back to local build"
            )
            return _build_local(state)

    return _node