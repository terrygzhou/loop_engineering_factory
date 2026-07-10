"""
Prompt and response logger — persists LLM interactions for debugging.
Logs system prompts, user prompts, responses, and metadata to build/prompt_logs/.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from log.logging import setup_logger, log_event

logger = setup_logger("prompt_logger")
from config.loader import config

PROMPT_LOG_DIR = Path(config.paths.prompt_log_dir)


def log_llm_call(
    workflow_id: str,
    phase: str,
    skill: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response: str,
    duration_s: float,
    error: Optional[str] = None,
):
    """Log an LLM call with full context for debugging."""
    PROMPT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "workflow_id": workflow_id,
        "phase": phase,
        "skill": skill,
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "response": response,
        "duration_s": round(duration_s, 3),
        "error": error,
    }

    # Write per-call log
    log_file = PROMPT_LOG_DIR / f"{workflow_id}_{ts}.json"
    try:
        with open(log_file, 'w') as f:
            json.dump(entry, f, indent=2)
    except Exception as e:
        print(f"WARNING: Could not write prompt log: {e}")

    # Also log to structured logger
    log_event(logger, "llm.prompt_logged", workflow_id=workflow_id, phase=phase,
              skill=skill, model=model, duration_s=round(duration_s, 3),
              system_prompt_len=len(system_prompt), user_prompt_len=len(user_prompt),
              response_len=len(response))


def get_logs(workflow_id: str = "", phase: str = "") -> list[dict]:
    """Retrieve prompt logs, optionally filtered by workflow or phase."""
    logs = []
    if not PROMPT_LOG_DIR.exists():
        return logs

    for log_file in sorted(PROMPT_LOG_DIR.glob("*.json")):
        try:
            with open(log_file, 'r') as f:
                entry = json.load(f)
            if workflow_id and entry.get("workflow_id") != workflow_id:
                continue
            if phase and entry.get("phase") != phase:
                continue
            # Strip large fields for listing
            light = {
                "ts": entry.get("ts"),
                "workflow_id": entry.get("workflow_id"),
                "phase": entry.get("phase"),
                "skill": entry.get("skill"),
                "model": entry.get("model"),
                "duration_s": entry.get("duration_s"),
                "error": entry.get("error"),
                "system_prompt_len": len(entry.get("system_prompt", "")),
                "user_prompt_len": len(entry.get("user_prompt", "")),
                "response_len": len(entry.get("response", "")),
            }
            logs.append(light)
        except Exception:
            continue
    return logs
