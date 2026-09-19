"""OpenHands gateway client helpers (seam split, node-module-seams spec)."""

import json
import logging
import tempfile
import time
from pathlib import Path

import httpx

from config.loader import config

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

    Returns the agent's final response text, or None on timeout, error, or a lost conversation (404).
    """
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = client.get(
                f"/api/conversations/{conv_id}",
                headers={"X-Api-Key": secret_key},
                timeout=30.0,
            )
            if resp.status_code == 404:
                # Terminal: the conversation was lost — most likely the agent-server
                # restarted mid-build and wiped its in-memory store. Retrying would
                # loop until BUILD_TIMEOUT, so fall back to the local subgraph now
                # (the caller treats a None poll result as terminal).
                logger.warning(
                    "  -> [OPENHANDS] Conversation %s no longer exists (404) — "
                    "gateway likely restarted mid-build; falling back",
                    conv_id,
                )
                return None
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
