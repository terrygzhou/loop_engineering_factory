"""
Centralized audit logging for all node I/O, LLM interactions, and user interactions.
Every node input/output is persisted as structured JSON in build/audit_logs/.
Every LLM prompt/response passes through prompt skills + context optimization.
Every user interaction (CLI/Web/API) is logged with trace IDs.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from log.logging import setup_logger, log_event

logger = setup_logger("audit")

AUDIT_DIR = Path(os.getenv("AUDIT_LOG_DIR", "build/audit_logs"))
INTERACTION_LOG = AUDIT_DIR / "interactions.jsonl"


def ensure_audit_dir() -> Path:
    """Create audit log directory structure."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIT_DIR


def generate_trace_id() -> str:
    """Generate a unique trace ID for correlation across logs."""
    return str(uuid.uuid4())


class AuditLog:
    """
    Centralized audit logger that captures:
    1. Node inputs/outputs (phase transitions, artifacts, state changes)
    2. LLM interactions (prompts, responses, context optimization)
    3. User interactions (CLI input, API calls, WebSocket messages)

    All logs are written to build/audit_logs/ as structured JSON.
    """

    def __init__(self, workflow_id: str, trace_id: Optional[str] = None):
        self.workflow_id = workflow_id
        self.trace_id = trace_id or generate_trace_id()
        self._entries: list[dict] = []
        ensure_audit_dir()

    def _log(self, event_type: str, data: dict) -> dict:
        """Write an audit entry to both memory and disk."""
        entry = {
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        self._entries.append(entry)
        # Append to JSONL for streaming consumption
        try:
            with open(INTERACTION_LOG, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            print(f"  ⚠ Audit log write failed: {e}")
        # Log to structured logger
        log_kwargs = {k: v for k, v in entry.items() if k not in ("event", "ts")}
        log_event(logger, f"audit.{event_type}", **log_kwargs)
        return entry

    # ── Node I/O ──

    def log_node_input(self, phase: str, inputs: dict) -> dict:
        """Log node input before processing."""
        return self._log("node.input", {
            "phase": phase,
            "inputs": {k: str(v)[:200] for k, v in inputs.items()},
            "input_keys": list(inputs.keys()),
        })

    def log_node_output(self, phase: str, outputs: dict) -> dict:
        """Log node output after processing."""
        return self._log("node.output", {
            "phase": phase,
            "output_keys": list(outputs.keys()),
            "output_summary": {k: f"{type(v).__name__}({len(str(v))})" for k, v in outputs.items()},
        })

    def log_node_transition(self, from_phase: str, to_phase: str, reason: str = "") -> dict:
        """Log phase transition with reason."""
        return self._log("node.transition", {
            "from": from_phase,
            "to": to_phase,
            "reason": reason,
        })

    def log_artifact_written(self, artifact_name: str, file_path: str, size_bytes: int) -> dict:
        """Log artifact persistence to disk."""
        return self._log("artifact.written", {
            "artifact": artifact_name,
            "path": file_path,
            "size_bytes": size_bytes,
        })

    # ── LLM Interactions ──

    def log_llm_prompt(self, skill: str, phase: str, system_prompt: str, user_prompt: str,
                       context_optimized: bool = False, context_tokens: int = 0) -> dict:
        """Log LLM prompt before sending."""
        return self._log("llm.prompt", {
            "skill": skill,
            "phase": phase,
            "system_prompt_len": len(system_prompt),
            "user_prompt_len": len(user_prompt),
            "context_optimized": context_optimized,
            "context_tokens": context_tokens,
        })

    def log_llm_response(self, skill: str, phase: str, response: str, duration_s: float,
                        success: bool = True) -> dict:
        """Log LLM response after receiving."""
        return self._log("llm.response", {
            "skill": skill,
            "phase": phase,
            "response_len": len(response),
            "duration_s": round(duration_s, 3),
            "success": success,
        })

    # ── User Interactions ──

    def log_user_input(self, interaction_type: str, phase: str, question: str,
                       source: str = "api") -> dict:
        """Log a request for user input."""
        return self._log("user.input_requested", {
            "type": interaction_type,
            "phase": phase,
            "question": question,
            "source": source,
        })

    def log_user_response(self, interaction_type: str, phase: str, response: dict,
                         source: str = "api") -> dict:
        """Log a user's response."""
        return self._log("user.response", {
            "type": interaction_type,
            "phase": phase,
            "response_keys": list(response.keys()) if isinstance(response, dict) else "scalar",
            "source": source,
        })

    def log_api_call(self, endpoint: str, method: str, workflow_id: str,
                    status: int = 200) -> dict:
        """Log an API call."""
        return self._log("api.call", {
            "endpoint": endpoint,
            "method": method,
            "workflow_id": workflow_id,
            "status": status,
        })

    def log_file_write(self, phase: str, file_path: str, content_type: str, size_bytes: int) -> dict:
        """Log any file written to disk."""
        return self._log("file.write", {
            "phase": phase,
            "path": file_path,
            "content_type": content_type,
            "size_bytes": size_bytes,
        })

    def get_entries(self) -> list[dict]:
        """Return all audit entries for this workflow."""
        return self._entries.copy()
