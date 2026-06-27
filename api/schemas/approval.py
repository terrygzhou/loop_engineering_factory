# Loop Engineering — Pydantic Schemas for Approvals

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class ApprovalRequest(BaseModel):
    workflow_id: str
    approved: bool
    feedback: Optional[str] = Field(default=None, max_length=5000)
    section_feedback: Optional[Dict[str, Any]] = None
    input_data: Optional[Dict[str, str]] = None


class ApprovalResponse(BaseModel):
    workflow_id: str
    approved: bool
    status: str = "accepted"

    @classmethod
    def from_result(cls, result: dict):
        return cls(
            workflow_id=result.get("workflow_id", "unknown"),
            approved=result.get("approved", False),
        )
