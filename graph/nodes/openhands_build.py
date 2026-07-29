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
import re
import time
import logging
from typing import Optional

import httpx

from config.loader import config
from graph.nodes.build_subgraph_legacy import (
    build_input_mapping,
    build_output_mapping,
    get_compiled_subgraph,
)

logger = logging.getLogger(__name__)

# -- Constants --------------------------------------------------------
POLL_INTERVAL = 5         # seconds between status polls
BUILD_TIMEOUT = 3600       # 1-hour hard limit (matches build_subgraph legacy)
PROMPT_CHAR_LIMIT = 16_000 # Truncate spec/tasks to avoid context overflow
STATUS_FINISHED = "finished"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"

# -- Conversation creation (agent-server v1.30.0) ---------------------
def _create_conversation(client: httpx.Client, prompt: str, project_path: str,
                         secret_key: str, max_iterations: int = 50) -> Optional[str]:
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
            "working_dir": project_path or "/tmp/oh_build",
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
            pass

    return f"""You are a senior software engineer building a project end-to-end.

PROJECT: {project_name}
WORKSPACE: {project_path}

INSTRUCTIONS:
1. Generate the complete source code for the project
2. Create unit tests for each module
3. Write configuration files (docker-compose, requirements.txt, etc.)
4. Run the tests and fix any failures
5. Write a seed script for database initialization
6. Perform a security review of the generated code

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
def _parse_assistant_text(text: str) -> dict:
    """
    Parse the OpenHands assistant text response into structured artifacts.

    OpenHands returns assistant messages (text), not structured JSON.
    We extract:
    - File blocks: === FILE: path === ... ===
    - Test results: explicit pass/fail mentions
    - Error messages: error/failure/exception text
    - Overall status: derived from content

    This is the bridge between Gateway response and WorkflowState artifacts.
    """
    result = {
        "generated_code": [],     # list of {"path": str, "content": str}
        "test_results": "",       # raw test output text
        "build_log": "",         # file list / commands executed
        "build_status": "pass",  # "pass", "fail", "partial"
        "files_created": [],     # list of file paths
        "errors": [],           # extracted error messages
    }

    if not text or not text.strip():
        result["build_status"] = "partial"
        result["errors"].append("Empty response from OpenHands agent")
        return result

    # -- Extract file blocks --
    file_pattern = re.compile(
        r"=== FILE: ([^\n=]+) ===\s*\n```(\w+)?\s*\n(.*?)```",
        re.DOTALL,
    )
    for match in file_pattern.finditer(text):
        file_path = match.group(1).strip()
        content = match.group(3).strip()
        result["generated_code"].append({"path": file_path, "content": content})
        result["files_created"].append(file_path)

    # -- Also extract unlabelled code blocks (no === FILE header) --
    # For agents that produce markdown without the FILE marker
    if not result["generated_code"]:
        loose_code = re.compile(r"```(\w+)\s*\n(.*?)```", re.DOTALL)
        for match in loose_code.finditer(text):
            lang = match.group(1)
            content = match.group(2).strip()
            if lang in ("python", "bash", "yaml", "toml", "json", "html", "css"):
                result["generated_code"].append({
                    "path": f"generated_{len(result['generated_code']) + 1}.{lang}",
                    "content": content,
                })

    # -- Extract test results --
    test_section = re.search(
        r"(TEST RESULTS|TEST OUTPUT|pytest|test result)[\s\S]{0,500}",
        text, re.IGNORECASE,
    )
    if test_section:
        result["test_results"] = test_section.group(0)

    # -- Extract errors --
    error_patterns = [
        r"(?:error|failed|exception|fail)[^\n]{0,200}",
        r"(?:\u26a0|\u2717|\u274c)\s*[^\n]{0,200}",
    ]
    for pattern in error_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            err_text = match.group(0).strip()
            # Avoid false positives from "no errors found"
            if not re.search(r"no\s+(?:error|fail)", err_text, re.IGNORECASE):
                result["errors"].append(err_text)

    # -- Derive build status --
    has_errors = bool(result["errors"])
    has_code = bool(result["generated_code"])
    has_pass = bool(re.search(r"(all passed|tests? passed|success)", text, re.IGNORECASE))

    if has_errors and not has_code:
        result["build_status"] = "fail"
    elif has_errors and has_code:
        result["build_status"] = "partial"
    elif has_code and has_pass:
        result["build_status"] = "pass"
    elif has_code:
        result["build_status"] = "pass"  # Code generated, no explicit failures
    else:
        result["build_status"] = "partial"

    # -- Build log: summary of files + commands --
    result["build_log"] = (
        f"Files created: {len(result['files_created'])}\n"
        f"Files: {', '.join(result['files_created'][:20])}\n"
        f"Errors: {len(result['errors'])}\n"
    )

    return result


# -- Conversation polling (agent-server v1.30.0) ---------------------
def _poll_conversation(
    client: httpx.Client,
    conv_id: str,
    secret_key: str,
    timeout: int = BUILD_TIMEOUT,
) -> Optional[str]:
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
                    logger.warning("  -> [OPENHANDS] Failed to fetch final response: %s", e)
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
    return build_output_mapping(result)


# -- OpenHands delegation helpers -------------------------------------
def _write_generated_files(state: dict, files: list[dict]) -> list[str]:
    """
    Write generated files to disk immediately.

    Writes to the project_path so downstream phases (SEED_DATA, VERIFY)
    can access them. Returns list of written paths.
    """
    project_path = state.get("project_path", "")
    written = []
    for file_entry in files:
        rel_path = file_entry["path"]
        content = file_entry["content"]
        full_path = f"{project_path}/{rel_path}"
        try:
            import pathlib
            p = pathlib.Path(full_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            written.append(rel_path)
        except Exception as e:
            logger.warning("Failed to write %s: %s", rel_path, e)

    if written:
        logger.info("  -> [OPENHANDS] Wrote %d files to disk", len(written))
    return written


def _merge_results(state: dict, parsed: dict) -> dict:
    """
    Merge OpenHands parsed results into WorkflowState as a partial update.

    This is the bridge between OpenHands text response and
    executor.py / edges.py quality gates.
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
        artifacts_delta["uat_report"] = f"OpenHands agent completed successfully.\n{parsed['build_log']}"
        uat_pass_rate = 1.0
    elif status == "partial":
        artifacts_delta["uat_report"] = f"OpenHands agent completed with issues.\nErrors:\n" + "\n".join(parsed["errors"][:5])
        uat_pass_rate = 0.5
    else:
        artifacts_delta["uat_report"] = f"OpenHands agent failed.\nErrors:\n" + "\n".join(parsed["errors"])
        uat_pass_rate = 0.0

    # -- UAT pass rate via metrics update --
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(update={"uat_pass_rate": uat_pass_rate})

    # -- Retry guard --
    fail_count = state.get("_build_fail_count", 0)
    if status == "fail":
        fail_count += 1
        if fail_count >= 3:
            return {
                "phase": "BUILD",
                "error": (
                    f"Build failed {fail_count} times consecutively -- "
                    f"aborting. Errors: {parsed['errors'][:3]}"
                ),
                "next_phase": "REFLECT",
                "artifacts": artifacts_delta,
                "_build_fail_count": fail_count,
            }

    # -- Next phase --
    next_phase = "SEED_DATA" if status == "pass" else None

    update: dict = {
        "phase": "BUILD",
        "artifacts": artifacts_delta,
        "superweb_mode": "agent",
    }
    if next_phase:
        update["next_phase"] = next_phase
    if metrics_update:
        update["metrics"] = metrics_update
    if status == "fail":
        update["_build_fail_count"] = fail_count
    else:
        update["_build_fail_count"] = 0

    logger.info(
        "  -> [OPENHANDS] BUILD complete: status=%s, files=%d, errors=%d",
        status,
        len(parsed["generated_code"]),
        len(parsed["errors"]),
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
        assistant_text = _poll_conversation(client, conv_id, secret_key, timeout=timeout)

        if not assistant_text:
            logger.warning("  -> [OPENHANDS] Conversation %s returned empty or timed out", conv_id)
            return _run_local_subgraph(state)

    # -- Parse results --
    parsed = _parse_assistant_text(assistant_text)
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
) -> callable:
    """
    Factory for LangGraph integration.

    Returns openhands_build_wrapper (aliased as openhands_build_node for
    backward compatibility) wrapped for use with the existing
    build_proxy_node interface.
    """
    return openhands_build_wrapper
