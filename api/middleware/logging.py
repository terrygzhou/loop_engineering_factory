# Loop Engineering — Request/Response Logging Middleware

import time
import json
from log.logging import setup_logger, log_event

logger = setup_logger("api")


def log_request(action: str, **kwargs):
    """Log API request/response with correlation ID and metadata."""
    log_event(logger, "api.request", action=action, **kwargs)


def log_llm_call(skill: str, phase: str, system_prompt: str, user_prompt: str, response: str, duration_s: float, model: str = "unknown"):
    """Log LLM prompt/response for debugging and auditing."""
    log_event(logger, "llm.call", skill=skill, phase=phase, model=model, duration_s=round(duration_s, 3),
              system_prompt_preview=system_prompt[:200], user_prompt_preview=user_prompt[:200],
              response_preview=response[:200])
