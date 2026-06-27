# Loop Engineering — Pydantic Schemas for Workflow

from pydantic import BaseModel, Field
from typing import Optional


class WorkflowStartRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    spec_text: str = Field(default="", max_length=10000)
    context_folder: Optional[str] = Field(default=None)


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    phase: str
    status: str
    started_at: Optional[float] = None
    duration_s: Optional[float] = None

    @classmethod
    def from_state(cls, state: dict):
        return cls(
            workflow_id=state.get("project_name", "unknown"),
            phase=state.get("phase", "UNKNOWN"),
            status=state.get("status", "active"),
            started_at=state.get("started_at"),
            duration_s=state.get("duration_s"),
        )
