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

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, cast

import httpx

from config.loader import config
from graph.nodes.build_subgraph_legacy import (
    BuildSubState,
    build_input_mapping,
    build_output_mapping,
    get_compiled_subgraph,
)

logger = logging.getLogger(__name__)

# -- Constants --------------------------------------------------------
POLL_INTERVAL = 5  # seconds between status polls
BUILD_TIMEOUT = 3600  # 1-hour hard limit (matches build_subgraph legacy)
PROMPT_CHAR_LIMIT = 16_000  # Truncate spec/tasks to avoid context overflow
STATUS_FINISHED = "finished"
_DEFAULT_WORKING_DIR = str(Path(tempfile.gettempdir()) / "oh_build")
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


# -- Conversation creation (agent-server v1.30.0) ---------------------
def _create_conversation(
    client: httpx.Client,
    prompt: str,
    project_path: str,
    secret_key: str,
    max_iterations: int = 50,
) -> str | None:
    """
    Create a conversation on agent-server v1.30.0.

    Unlike the legacy Gateway API, v1.30.0 requires inline LLM config
    per conversation (no persistent profiles). The model name needs the
    'openai/' prefix so LiteLLM inside the agent knows which provider
    to use for OpenAI-compatible endpoints.

    Returns conversation ID or None on failure.
    """
    llm_cfg = config.services.llm
    # Ensure model has provider prefix for LiteLLM compatibility
    model = llm_cfg.model
    if "/" not in model:
        model = f"openai/{model}"

    payload = {
        "workspace": {
            "kind": "LocalWorkspace",
            "working_dir": project_path or _DEFAULT_WORKING_DIR,
        },
        "agent": {
            "kind": "Agent",
            "llm": {
                "model": model,
                "base_url": llm_cfg.base_url,
                "api_key": llm_cfg.api_key,
                "temperature": llm_cfg.temperature or 0.1,
                "max_tokens": llm_cfg.max_tokens or 65535,
            },
            "tools": [
                {"name": "terminal"},
                {"name": "file_editor"},
            ],
        },
        "initial_message": {
            "content": [{"type": "text", "text": prompt}],
        },
        "max_iterations": max_iterations,
        "confirmation_policy": {"kind": "NeverConfirm"},
    }

    try:
        resp = client.post(
            "/api/conversations",
            json=payload,
            headers={"X-Api-Key": secret_key},
            timeout=60.0,
        )
        if resp.status_code in (409, 400):
            # Conversation already exists or bad payload — try to extract conv_id
            data = resp.json()
            conv_id = data.get("id")
            if conv_id:
                return conv_id
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("id")
    except httpx.HTTPError as e:
        logger.error("  -> [OPENHANDS] Failed to create conversation: %s", e)
        return None


# -- Prompt construction ----------------------------------------------
def _build_prompt(state: dict) -> str:
    """
    Construct the task prompt for the OpenHands agent.

    Pulls spec_refined and tasks from artifacts, truncates to avoid
    context overflow. Includes project_path for workspace alignment.
    """
    artifacts = state.get("artifacts", {})
    spec = (artifacts.get("spec_refined") or "")[:PROMPT_CHAR_LIMIT]
    tasks = (artifacts.get("tasks") or "")[:PROMPT_CHAR_LIMIT]
    project_path = state.get("project_path", "")
    project_name = state.get("project_name", "unknown")

    # Load solution.md if available (from PLAN phase)
    solution_md = artifacts.get("solution_md", "")
    if not solution_md and artifacts.get("solution_path"):
        try:
            import pathlib

            solution_md = pathlib.Path(artifacts["solution_path"]).read_text()
        except Exception:
            logger.debug("solution_path read failed", exc_info=True)

    return f"""You are a senior software engineer building a project end-to-end.

PROJECT: {project_name}
WORKSPACE: {project_path}
BUILD_REPORT_PATH: {project_path}/build_report.json

INSTRUCTIONS:
1. Generate the complete source code for the project
2. Create unit tests for each module
3. Write configuration files (docker-compose, requirements.txt, etc.)
4. Run the tests and fix any failures
5. Write a seed script for database initialization
6. Perform a security review of the generated code
7. For any user-facing UI (web pages, dashboards, forms, components), apply production-grade frontend engineering: accessible (WCAG 2.1 AA), responsive, semantic HTML, and visually polished — not a generic "AI-generated" look. Honor the spec's UI & User Experience section (screens, flows, design constraints) when present.

MANDATORY MACHINE-READABLE RESULT:
When you finish, you MUST write a file named build_report.json in the project
root containing ONLY valid JSON with this exact shape:
    {{
      "status": "pass" | "fail" | "partial",
      "test_results": "human-readable summary of test run",
      "files": ["relative/path/to/file", ...],
      "errors": ["first error if any", ...]
    }}
- "status" is "pass" only if tests run and all pass; "fail" if the build or
  tests cannot complete; "partial" if code exists but some tests fail.
- This file is parsed by the orchestrator and is the source of truth for
  whether the build succeeded. Keep it valid JSON; do not add commentary.

OUTPUT FORMAT:
For each file, output in this format:
=== FILE: relative/path/to/file.py ===
```python
<complete file contents>
```

After generating all files, run tests and report:
- Which tests passed/failed
- Any errors encountered
- Files created/modified

SPECIFICATION:
{spec}

TASKS:
{tasks}
"""


# -- Result parsing ---------------------------------------------------
# Decision 1: build_report.json is the primary, machine-readable BUILD
# result contract. The agent is instructed to write it; a missing/invalid
# manifest is a hard failure (typed exception), not a silent downgrade.
BUILD_REPORT_FILENAME = "build_report.json"


class BuildReportMissingError(Exception):
    """Raised when the OpenHands agent did not produce a valid
    ``build_report.json``. Decision 1 makes the manifest the source of
    truth; silently falling back to free-text parsing would violate
    Decision 2 (VERIFY gate) and Decision 3 (typed errors)."""


def _parse_build_report(project_path: str) -> dict | None:
    """Read and validate build_report.json if the agent produced one.

    Expected schema:
        {
          "status": "pass" | "fail" | "partial",
          "test_results": "...",
          "files": ["relative/path", ...],
          "errors": ["..."]
        }

    Returns a normalized dict with keys build_status, test_results,
    files_created, errors, build_log — or None when the manifest is
    missing or invalid, signalling callers to fall back to text parsing.
    """
    report_path = Path(project_path) / BUILD_REPORT_FILENAME
    if not report_path.exists():
        return None
    try:
        raw = json.loads(report_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "  -> [OPENHANDS] build_report.json unreadable (%s); falling back", e
        )
        return None

    if not isinstance(raw, dict) or "status" not in raw:
        return None
    status = str(raw.get("status", "partial")).lower()
    if status not in ("pass", "fail", "partial"):
        status = "partial"
    files = [str(f) for f in (raw.get("files") or []) if isinstance(f, str)]
    errors = [str(e) for e in (raw.get("errors") or []) if isinstance(e, str)]
    raw_tests = raw.get("test_results")
    test_results = "" if raw_tests is None else str(raw_tests)
    build_log = (
        f"BUILD manifest (status={status}): {len(files)} file(s), {len(errors)} error(s)\n"
        + "\n".join(errors[:5])
    )
    return {
        "build_status": status,
        "test_results": test_results,
        "files_created": files,
        "errors": errors,
        "build_log": build_log,
    }


# -- Conversation polling (agent-server v1.30.0) ---------------------
def _poll_conversation(
    client: httpx.Client,
    conv_id: str,
    secret_key: str,
    timeout: int = BUILD_TIMEOUT,
) -> str | None:
    """
    Poll GET /api/conversations/{conv_id} until finished/errored.
    Then fetch final response via GET /api/conversations/{conv_id}/agent_final_response.

    Returns the agent's final response text, or None on timeout/error.
    """
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = client.get(
                f"/api/conversations/{conv_id}",
                headers={"X-Api-Key": secret_key},
                timeout=30.0,
            )
            data = resp.json()

            status = data.get("execution_status", "")
            logger.debug("  -> [OPENHANDS] Conversation %s: %s", conv_id, status)

            if status in (STATUS_FINISHED, STATUS_ERROR):
                # Fetch the final response text
                try:
                    resp = client.get(
                        f"/api/conversations/{conv_id}/agent_final_response",
                        headers={"X-Api-Key": secret_key},
                        timeout=30.0,
                    )
                    result = resp.json()
                    return result.get("response", "")
                except (httpx.HTTPError, json.JSONDecodeError) as e:
                    logger.warning(
                        "  -> [OPENHANDS] Failed to fetch final response: %s", e
                    )
                return None

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("  -> [OPENHANDS] Poll error: %s", e)
        except TimeoutError:
            logger.warning("  -> [OPENHANDS] Poll timeout")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    logger.warning("  -> [OPENHANDS] Poll timeout after %ds", timeout)
    return None


# -- Local subgraph fallback ------------------------------------------
def _run_local_subgraph(state: dict) -> dict:
    """
    Run the compiled BUILD subgraph as local fallback.

    Uses proper LangGraph subgraph invocation with clean parent↔child
    state mapping — no internal state keys leak into WorkflowState.
    """
    logger.warning("  -> [OPENHANDS] Running local BUILD subgraph")
    child_state = build_input_mapping(state)
    compiled = get_compiled_subgraph()
    result = compiled.invoke(child_state)
    return build_output_mapping(cast(BuildSubState, result))


# -- OpenHands delegation helpers -------------------------------------
def _write_generated_files(state: dict, files: list[dict]) -> list[str]:
    """
    Write generated files to disk immediately.

    Writes to the project_path so downstream phases (SEED_DATA, VERIFY)
    can access them. Returns list of written paths.
    """
    project_path = state.get("project_path", "")
    root = Path(project_path)
    written = []
    for file_entry in files:
        rel_path = file_entry["path"]
        content = file_entry["content"]
        # Decision 1 (safety): reject absolute paths and any path that escapes
        # the project root (e.g. "../../etc/passwd") before writing.
        rel = Path(rel_path)
        if rel.is_absolute():
            logger.warning("Rejected absolute generated path: %s", rel_path)
            continue
        target = (root / rel).resolve() if root.exists() else (root / rel)
        try:
            target.relative_to(root.resolve() if root.exists() else root)
        except ValueError:
            logger.warning("Rejected path-traversal generated file: %s", rel_path)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(rel_path)
        except Exception as e:
            logger.warning("Failed to write %s: %s", rel_path, e)

    if written:
        logger.info("  -> [OPENHANDS] Wrote %d files to disk", len(written))
    return written


# -- Retry guard constants --------------------------------------------
BUILD_MAX_RETRIES = 2  # max BUILD->BUILD loops before halting (Decision 2/5)


def _merge_results(state: dict, parsed: dict) -> dict:
    """
    Merge OpenHands parsed results into WorkflowState as a partial update.

    This is the bridge between OpenHands text response and
    executor.py / edges.py quality gates.

    Retry counter (Decision 5): the BUILD retry count is persisted in
    `artifacts.loop_counts["BUILD"]` so LangGraph persists it across
    checkpoints. The edge router (route_phase) is a pure reader — it no
    longer mutates state. The node owns the increment, matching the
    pattern used by DEFINE/PLAN/VERIFY.
    """
    # -- Write files to disk immediately --
    _write_generated_files(state, parsed.get("generated_code", []))

    # -- Core artifacts delta --
    artifacts_delta: dict[str, str] = {
        "build_status": parsed["build_status"],
        "build_log": parsed["build_log"],
        "test_results": parsed["test_results"],
        "generated_code_files": parsed["files_created"],
        "build_errors": parsed["errors"],
    }

    # -- UAT proxy: derive pass_rate from build_status --
    status = parsed["build_status"]
    if status == "pass":
        artifacts_delta["uat_report"] = (
            f"OpenHands agent completed successfully.\n{parsed['build_log']}"
        )
        uat_pass_rate = 1.0
    elif status == "partial":
        artifacts_delta["uat_report"] = (
            "OpenHands agent completed with issues.\nErrors:\n"
            + "\n".join(parsed["errors"][:5])
        )
        uat_pass_rate = 0.5
    else:
        artifacts_delta["uat_report"] = (
            "OpenHands agent failed.\nErrors:\n" + "\n".join(parsed["errors"])
        )
        uat_pass_rate = 0.0

    # -- UAT pass rate via metrics update --
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(
            update={"uat_pass_rate": uat_pass_rate}
        )

    # -- Retry guard (Decision 5): single canonical counter in artifacts --
    # The previous top-level `_build_fail_count` was not persisted by
    # LangGraph and could reset on resume; this counter lives in
    # artifacts.loop_counts which the _dict_merge reducer persists.
    loop_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))
    fail_count = int(loop_counts.get("BUILD", 0))
    if status == "fail":
        fail_count += 1
        loop_counts["BUILD"] = fail_count
        if fail_count > BUILD_MAX_RETRIES:
            # Exceeded retry budget — halt the cycle (route to ERROR).
            logger.error(
                "  -> [OPENHANDS] Build failed %d times consecutively -- halting",
                fail_count,
            )
            # Keep error/next_phase/verify_status consistent with the BUILD
            # gate in edges.route_phase: a terminal BUILD failure halts the
            # cycle (route -> ERROR) instead of silently shipping a broken
            # project via the next_phase override.
            return {
                "phase": "BUILD",
                "error": (
                    f"Build failed {fail_count} times consecutively -- "
                    f"aborting. Errors: {parsed['errors'][:3]}"
                ),
                "next_phase": None,
                "artifacts": {**artifacts_delta, "loop_counts": loop_counts},
                "metrics": metrics_update,
            }

    # Reset counter on success (pass / partial) so a later failure starts
    # fresh; the BUILD->BUILD retry path will re-increment.
    if status != "fail":
        loop_counts["BUILD"] = 0

    # -- Next phase --
    next_phase = "SEED_DATA" if status == "pass" else None

    update: dict = {
        "phase": "BUILD",
        "artifacts": {**artifacts_delta, "loop_counts": loop_counts},
        "superweb_mode": "agent",
    }
    if next_phase:
        update["next_phase"] = next_phase
    if metrics_update:
        update["metrics"] = metrics_update

    logger.info(
        "  -> [OPENHANDS] BUILD complete: status=%s, files=%d, errors=%d, retry=%d",
        status,
        len(parsed["generated_code"]),
        len(parsed["errors"]),
        loop_counts.get("BUILD", 0),
    )

    return update


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

    1. Health-check OpenHands agent-server
    2. If available, delegate to OpenHands via Gateway API
    3. Otherwise, run the local BUILD subgraph (proper compiled LangGraph)

    Returns partial update dict (LangGraph reducer merges).
    """
    oh_cfg = config.services.openhands

    logger.info(
        "  -> [OPENHANDS] Starting BUILD via Gateway at %s",
        oh_cfg.url,
    )

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
        return _run_local_subgraph(state)

    # -- Delegate to OpenHands --
    try:
        return _delegate_to_openhands(state, oh_cfg)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.warning(
            "  -> [OPENHANDS] Connection failed: %s -- fallback",
            e,
        )
        return _run_local_subgraph(state)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 502, 503, 504):
            logger.warning(
                "  -> [OPENHANDS] Server error %d -- fallback",
                e.response.status_code,
            )
            return _run_local_subgraph(state)
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
