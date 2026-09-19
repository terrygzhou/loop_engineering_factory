"""
OpenHands BUILD node -- delegates to OpenHands agent-server (v1.30.0) via native API.

Primary path: health-check → POST /api/conversations → poll execution_status → parse final response.
Fallback path: invoke the compiled BUILD subgraph (build_subgraph_legacy.py) as a proper
LangGraph subgraph with clean parent↔child state mapping.

API endpoints used (agent-server v1.30.0):
- POST /api/conversations         -> creates conversation with inline LLM config
- GET  /api/conversations/{id}    -> polls execution_status (idle/running/finished/error)
- GET  /api/conversations/{id}/agent_final_response -> retrieves agent's final response text
"""

import logging
import time  # noqa: F401 — monkeypatch target for `ob.time.sleep` (node-module-seams spec)
from typing import Any

import httpx

from config.loader import config
from tools.audit_logger import AuditLog

# Re-exports for the seam-split sibling modules (node-module-seams spec).
# Kept so existing test imports (`from graph.nodes import openhands_build as ob`)
# and intra-graph call sites continue to resolve to the same names.
from graph.nodes.openhands_client import (  # noqa: F401
    _create_conversation,
    _poll_conversation,
    BUILD_TIMEOUT,
    POLL_INTERVAL,
    PROMPT_CHAR_LIMIT,
    STATUS_ERROR,
    STATUS_FINISHED,
    STATUS_TIMEOUT,
    _DEFAULT_WORKING_DIR,
)
from graph.nodes.openhands_prompt import _build_prompt  # noqa: F401
from graph.nodes.openhands_report import (  # noqa: F401
    BUILD_REPORT_FILENAME,
    BuildReportMissingError,
    _parse_build_report,
)
from graph.nodes.openhands_merge import (  # noqa: F401
    BUILD_MAX_RETRIES,
    _merge_results,
    _run_local_subgraph,
    _write_generated_files,
)

logger = logging.getLogger(__name__)


def _delegate_to_openhands(state: dict, oh_cfg) -> dict:
    """
    Delegate BUILD to OpenHands agent-server v1.30.0.

    Creates a conversation with inline LLM config, polls for completion,
    fetches the agent's final response, and merges results into WorkflowState.
    """
    gateway_url = oh_cfg.url
    secret_key = oh_cfg.secret_key
    timeout = oh_cfg.timeout

    # -- Build prompt --
    prompt = _build_prompt(state)
    project_path = state.get("project_path", "")

    with httpx.Client(base_url=gateway_url, timeout=30.0) as client:
        # Create conversation (replaces legacy _ensure_build_profile + POST /v1/chat)
        conv_id = _create_conversation(client, prompt, project_path, secret_key)
        if not conv_id:
            logger.error("  -> [OPENHANDS] Failed to create conversation -- fallback")
            return _run_local_subgraph(state)

        logger.info("  -> [OPENHANDS] Conversation %s created", conv_id)

        # -- Poll for completion --
        assistant_text = _poll_conversation(
            client, conv_id, secret_key, timeout=timeout
        )

        if not assistant_text:
            logger.warning(
                "  -> [OPENHANDS] Conversation %s returned empty or timed out", conv_id
            )
            return _run_local_subgraph(state)

    # -- Parse results (Decision 1) --
    # The build_report.json manifest is the source of truth (Decision 1).
    # Decision 3 (typed LLM errors) and Decision 2 (VERIFY gate) both
    # require that a missing/invalid manifest is treated as a hard failure
    # rather than silently downgraded to a weaker signal — so we raise
    # instead of falling back to free-text parsing.
    parsed = _parse_build_report(project_path)
    if parsed is None:
        logger.error(
            "  -> [OPENHANDS] %s missing or invalid for %s — treating as build failure",
            BUILD_REPORT_FILENAME,
            project_path,
        )
        raise BuildReportMissingError(
            f"{BUILD_REPORT_FILENAME} was not produced or could not be parsed at {project_path}"
        )
    parsed["_source"] = "manifest"
    return _merge_results(state, parsed)


# -- Main node function -----------------------------------------------
def openhands_build_wrapper(state: dict) -> dict:
    """
    LangGraph node: wrapper for BUILD subgraph.

    1. If artifacts.build_mode == "subgraph", run the local BUILD subgraph directly.
    2. Otherwise, health-check OpenHands agent-server; delegate if available.
    3. If health check or delegation fails, fall back to the local BUILD subgraph.

    Returns partial update dict (LangGraph reducer merges).
    """
    oh_cfg = config.services.openhands

    # HIL BUILD-mode choice: "subgraph" forces the local subgraph;
    # "openhands" (default) uses the agent-server when reachable.
    build_mode = (state.get("artifacts") or {}).get("build_mode", "openhands")

    if build_mode == "subgraph":
        logger.info(
            "  -> [OPENHANDS] build_mode=subgraph — running local BUILD subgraph directly"
        )
        audit_sub = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
        audit_sub.log_node_input(
            "BUILD",
            {
                "project_path": state.get("project_path", ""),
                "route": "local-subgraph-forced",
            },
        )
        result = _run_local_subgraph(state)
        status = (result.get("artifacts") or {}).get("build_status", "")
        audit_sub.log_node_output(
            "BUILD", {"route": "local-subgraph-forced", "status": status or "pass"}
        )
        return result

    logger.info(
        "  -> [OPENHANDS] Starting BUILD via Gateway at %s",
        oh_cfg.url,
    )
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input(
        "BUILD",
        {"project_path": state.get("project_path", ""), "gateway_url": str(oh_cfg.url)},
    )

    def _finish(result: dict, route: str) -> dict:
        status = (result.get("artifacts") or {}).get("build_status", "")
        audit.log_node_output("BUILD", {"route": route, "status": status or "pass"})
        return result

    # -- Health check --
    try:
        with httpx.Client(base_url=oh_cfg.url, timeout=10.0) as client:
            resp = client.get("/health", timeout=5.0)
            if resp.status_code not in (200, 204):
                raise httpx.RemoteProtocolError("Unhealthy")
    except (httpx.HTTPError, TimeoutError, ConnectionError) as e:
        logger.warning(
            "  -> [OPENHANDS] Health check failed: %s -- fallback",
            e,
        )
        return _finish(_run_local_subgraph(state), "local-subgraph-fallback")

    # -- Delegate to OpenHands --
    try:
        return _finish(_delegate_to_openhands(state, oh_cfg), "openhands")
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.warning(
            "  -> [OPENHANDS] Connection failed: %s -- fallback",
            e,
        )
        return _finish(_run_local_subgraph(state), "local-subgraph-fallback")
    except httpx.HTTPStatusError as e:
        # UAT finding: a 5xx (e.g. OpenHands event_service PermissionError)
        # used to fall through to "raise" because only 4xx/5xx were listed.
        # Any gateway failure — 4xx AND 5xx — falls back to the local
        # subgraph so a server-side bug can't crash the whole cycle.
        if e.response.status_code < 500:
            raise
        logger.warning(
            "  -> [OPENHANDS] Server error %d -- fallback",
            e.response.status_code,
        )
        return _finish(_run_local_subgraph(state), "local-subgraph-fallback")
    except BuildReportMissingError as e:
        audit.log_node_output(
            "BUILD", {"route": "openhands", "status": "fail", "error": str(e)}
        )
        raise


# Backward compatibility alias — consumers that imported openhands_build_node
# directly will still work.
openhands_build_node = openhands_build_wrapper


# -- Public factory (same interface as build_proxy_node) --------------
def openhands_build_proxy_factory(
    builder_url: str = "",  # Deprecated: kept for API compatibility
) -> Any:
    """
    Factory for LangGraph integration.

    Returns openhands_build_wrapper (aliased as openhands_build_node for
    backward compatibility) wrapped for use with the existing
    build_proxy_node interface.

    Decision 5 (async BUILD): the wrapper is exposed to LangGraph as an
    async node so the event loop is not blocked for the 1-hour OpenHands
    poll window. The heavy lifting (HTTP polling, subprocess writes, local
    subgraph) still runs in a worker thread via asyncio.to_thread so a
    hung OpenHands can't freeze the UI.
    """

    async def _async_build(state: dict) -> dict:
        import asyncio

        return await asyncio.to_thread(openhands_build_wrapper, state)

    return _async_build
