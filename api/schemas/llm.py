# Loop Engineering — Pydantic Schemas for LLM
#
# DEPRECATED: This module is not used by any active code path.
# The LLM logging is handled directly in tools/llm.py and graph/executor.py
# without these schema classes. Kept for historical reference — import is
# blocked to prevent accidental usage.

# ── DISABLED: Import guard to prevent accidental usage ──────────────
raise ImportError(
    "api.schemas.llm is DEPRECATED. "
    "This module was disabled in the code cleanup audit. "
    "LLM logging is handled directly in tools/llm.py without Pydantic schemas."
)
# ── End guard — original code below (preserved for reference) ──────

from pydantic import BaseModel
from typing import Optional


class LLMResponse(BaseModel):
    prompt: str
    response: str
    model: str
    duration_s: float
    tokens: Optional[dict] = None
    error: Optional[str] = None


class LLMLogEntry(BaseModel):
    workflow_id: str
    phase: str
    skill: str
    model: str
    system_prompt: str
    user_prompt: str
    response: str
    duration_s: float
    timestamp: str