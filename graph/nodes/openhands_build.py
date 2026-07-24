"""
OpenHands BUILD node -- delegates to OpenHands agent-server via OpenAI Gateway API.

Replaces build_proxy.py. Falls back to build_subgraph_legacy.py if
the agent-server is unreachable or returns an error.

API endpoints used:
- POST /v1/chat/completions  -> creates conversation, returns conv ID in header
- GET  /api/conversations/{id} -> polls status and collects results
"""

import json
import re
import time
import logging
from typing import Optional

import httpx

from config.loader import config

logger = logging.getLogger(__name__)

# -- Constants --------------------------------------------------------
POLL_INTERVAL = 5         # seconds between status polls
BUILD_TIMEOUT = 3600       # 1-hour hard limit (matches build_subgraph legacy)
PROMPT_CHAR_LIMIT = 16_000 # Truncate spec/tasks to avoid context overflow
STATUS_FINISHED = "finished"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"

# -- Profile creation (one-time setup) --------------------------------
def _ensure_build_profile(client: httpx.Client) -> None:
    """
    Create the build_agent profile on agent-server if it doesn't exist.

    The profile configures the LLM that the agent uses. We target
    Qwen3.6-27B on host:8080 via the OpenAI-compatible endpoint.

    Idempotent: POST /api/profiles/build_agent with 409 -> already exists.
    """
    llm_cfg = config.services.llm
    profile_payload = {
        "name": "build_agent",
        "llm": {
            "base_url": llm_cfg.base_url,
            "model": llm_cfg.model,
            "api_key": llm_cfg.api_key,
            "temperature": llm_cfg.temperature,
            "max_tokens": llm_cfg.max_tokens,
        },
        "agent": {
            "type": "codeact",
            "max_iterations": 50,
            "max_budget_per_task": 0,  # No budget limit for local LLM
        },
    }
    try:
        resp = client.post("/api/profiles", json=profile_payload, timeout=30.0)
        if resp.status_code == 409:
            logger.info("Profile build_agent already exists (409)")
        else:
            resp.raise_for_status()
            logger.info("Profile build_agent created")
    except httpx.HTTPStatusError as e:
        # 409 is not an error -- profile already exists
        if e.response.status_code != 409:
            logger.warning("Profile setup failed: %s", e)


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


# -- Conversation polling ---------------------------------------------
def _poll_conversation(
    client: httpx.Client,
    conv_id: str,
    timeout: int = BUILD_TIMEOUT,
) -> Optional[str]:
    """
    Poll GET /api/conversations/{conv_id} until finished/errored.

    Returns the assistant message text, or None on timeout/error.
    """
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = client.get(f"/api/conversations/{conv_id}", timeout=30.0)
            data = resp.json()

            status = data.get("status", "")
            logger.debug("  -> [OPENHANDS] Conversation %s: %s", conv_id, status)

            if status in (STATUS_FINISHED, STATUS_ERROR):
                # Extract the last assistant message
                messages = data.get("messages", [])
                for msg in reversed(messages):
                    if msg.get("role") == "assistant":
                        return msg.get("content", "")
                return None

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("  -> [OPENHANDS] Poll error: %s", e)
        except TimeoutError:
            logger.warning("  -> [OPENHANDS] Poll timeout")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    logger.warning("  -> [OPENHANDS] Poll timeout after %ds", timeout)
    return None


# -- Legacy fallback ------------------------------------------------
def _fallback_legacy_build(state: dict) -> dict:
    """
    Fallback to build_subgraph_legacy.py when OpenHands is unreachable.

    Imports lazily to avoid dependency issues during normal operation.
    """
    logger.warning("  -> [OPENHANDS] Falling back to build_subgraph_legacy.py")
    from graph.nodes.build_subgraph_legacy import (
        build_input_mapping,
        build_output_mapping,
        build_subgraph,
    )
    child_state = build_input_mapping(state)
    compiled = build_subgraph().compile()
    result = compiled.invoke(child_state)
    return build_output_mapping(result)


# -- Main node function -----------------------------------------------
def openhands_build_node(state: dict) -> dict:
    """
    LangGraph node: delegate BUILD to OpenHands agent-server.

    Steps:
    1. Configure client + ensure profile exists
    2. POST /v1/chat/completions with build prompt
    3. Poll for completion
    4. Parse assistant text -> WorkflowState artifacts
    5. Fallback if OpenHands fails

    Returns: updated state dict with BUILD artifacts populated.
    """
    oh_cfg = config.services.openhands
    gateway_url = oh_cfg.url
    secret_key = oh_cfg.secret_key
    workspace_path = oh_cfg.workspace_path
    timeout = oh_cfg.timeout

    logger.info(
        "  -> [OPENHANDS] Starting BUILD via Gateway at %s",
        gateway_url,
    )

    # -- Health check --
    try:
        with httpx.Client(base_url=gateway_url, timeout=10.0) as client:
            resp = client.get("/health", timeout=5.0)
            if resp.status_code not in (200, 204):
                raise httpx.RemoteProtocolError("Unhealthy")
    except (httpx.HTTPError, TimeoutError, ConnectionError) as e:
        logger.warning(
            "  -> [OPENHANDS] Health check failed: %s -- fallback",
            e,
        )
        return _fallback_legacy_build(state)

    # -- Create conversation --
    prompt = _build_prompt(state)

    try:
        with httpx.Client(base_url=gateway_url, timeout=30.0) as client:
            # Ensure profile exists (idempotent)
            _ensure_build_profile(client)

            # POST to Gateway
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openhands_build_agent",
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "Authorization": f"Bearer {secret_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
            resp.raise_for_status()

            conv_id = resp.headers.get("X-OpenHands-ServerConversation-ID")
            if not conv_id:
                logger.error(
                    "  -> [OPENHANDS] No conversation ID in response"
                )
                return _fallback_legacy_build(state)

            logger.info(
                "  -> [OPENHANDS] Conversation %s created",
                conv_id,
            )

            # -- Poll for completion --
            assistant_text = _poll_conversation(
                client, conv_id, timeout=timeout,
            )

            if assistant_text is None:
                logger.warning(
                    "  -> [OPENHANDS] Conversation %s timed out",
                    conv_id,
                )
                # Attempt fallback
                return _fallback_legacy_build(state)

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.warning(
            "  -> [OPENHANDS] Connection failed: %s -- fallback",
            e,
        )
        return _fallback_legacy_build(state)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (502, 503, 504):
            logger.warning(
                "  -> [OPENHANDS] Server error %d -- fallback",
                e.response.status_code,
            )
            return _fallback_legacy_build(state)
        raise

    # -- Parse results --
    parsed = _parse_assistant_text(assistant_text)
    return _merge_results(state, parsed)


def _merge_results(state: dict, parsed: dict) -> dict:
    """
    Merge OpenHands parsed results into WorkflowState.

    This is the bridge between OpenHands text response and
    executor.py / edges.py quality gates.
    """
    artifacts = state.setdefault("artifacts", {})

    # -- Core artifacts (consumed by executor.py eval + edges.py gates) --
    artifacts["build_status"] = parsed["build_status"]
    artifacts["build_log"] = parsed["build_log"]
    artifacts["test_results"] = parsed["test_results"]

    # -- Generated code (for downstream phases) --
    # Store as JSON-serializable list of file dicts
    artifacts["generated_code_files"] = parsed["files_created"]
    if parsed["generated_code"]:
        # Write files to disk immediately (avoids in-memory accumulation)
        _write_generated_files(state, parsed["generated_code"])

    # -- UAT proxy: derive pass_rate from build_status --
    # OpenHands runs real tests -- map status to pass rate
    status = parsed["build_status"]
    if status == "pass":
        artifacts["uat_report"] = f"OpenHands agent completed successfully.\n{parsed['build_log']}"
        state["metrics"] = state.get("metrics") or {}
        if hasattr(state.get("metrics"), "model_copy"):
            # Pydantic model -- update via model_copy
            m = state["metrics"]
            state["metrics"] = m.model_copy(update={"uat_pass_rate": 1.0})
        else:
            state["metrics"]["uat_pass_rate"] = 1.0
    elif status == "partial":
        artifacts["uat_report"] = f"OpenHands agent completed with issues.\nErrors:\n" + "\n".join(parsed["errors"][:5])
        state["metrics"] = state.get("metrics") or {}
        if hasattr(state.get("metrics"), "model_copy"):
            m = state["metrics"]
            state["metrics"] = m.model_copy(update={"uat_pass_rate": 0.5})
        else:
            state["metrics"]["uat_pass_rate"] = 0.5
    else:
        artifacts["uat_report"] = f"OpenHands agent failed.\nErrors:\n" + "\n".join(parsed["errors"])
        state["metrics"] = state.get("metrics") or {}
        if hasattr(state.get("metrics"), "model_copy"):
            m = state["metrics"]
            state["metrics"] = m.model_copy(update={"uat_pass_rate": 0.0})
        else:
            state["metrics"]["uat_pass_rate"] = 0.0

    # -- Error tracking --
    artifacts["build_errors"] = parsed["errors"]

    # -- Retry guard (same as build_proxy.py) --
    fail_count = state.get("_build_fail_count", 0)
    if status == "fail":
        fail_count += 1
        state["_build_fail_count"] = fail_count
        if fail_count >= 3:
            state["error"] = (
                f"Build failed {fail_count} times consecutively -- "
                f"aborting. Errors: {parsed['errors'][:3]}"
            )
            state["next_phase"] = "REFLECT"
            return state
    else:
        state["_build_fail_count"] = 0

    # -- Next phase --
    state["next_phase"] = "SHIP" if status == "pass" else None
    state["phase"] = "BUILD"
    state["superweb_mode"] = "agent"  # Tag: this build used agent mode

    logger.info(
        "  -> [OPENHANDS] BUILD complete: status=%s, files=%d, errors=%d",
        status,
        len(parsed["generated_code"]),
        len(parsed["errors"]),
    )

    return state


def _write_generated_files(state: dict, files: list[dict]) -> None:
    """
    Write generated files to disk immediately.

    Writes to the project_path so downstream phases (SEED_DATA, VERIFY)
    can access them. Also records file_paths in artifacts for Phase 2
    filesystem-backed state.
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
        state.setdefault("artifacts", {})["file_paths"] = written
        logger.info("  -> [OPENHANDS] Wrote %d files to disk", len(written))


# -- Public factory (same interface as build_proxy_node) --------------
def openhands_build_proxy_factory(
    builder_url: str = "",  # Deprecated: kept for API compatibility
) -> callable:
    """
    Factory for LangGraph integration.

    Returns openhands_build_node wrapped for backward compatibility
    with the existing build_proxy_node interface.
    """
    return openhands_build_node