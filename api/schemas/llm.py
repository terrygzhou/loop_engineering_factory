# Loop Engineering — Pydantic Schemas for LLM

from pydantic import BaseModel, Field
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
