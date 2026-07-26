# Loop Engineering — Pydantic Schemas for Workflow

from pydantic import BaseModel, Field
from typing import Optional


class SkillProgress(BaseModel):
    """Progress for a single skill invocation."""
    name: str
    status: str  # "running" | "completed" | "failed"
    duration_s: Optional[float] = None
    output_path: Optional[str] = None


class HilContext(BaseModel):
    """Context for a HIL pause."""
    phase: str
    pause_type: str
    skill_names: Optional[list[str]] = None
    artifact_keys: Optional[list[str]] = None


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

    # Skill tracking
    skills_completed: list[str] = Field(default_factory=list)
    skill_progress: list[SkillProgress] = Field(default_factory=list)

    # Artifacts summary (keys only — use /artifacts for content)
    artifact_keys: list[str] = Field(default_factory=list)

    # HIL context
    hil_context: Optional[HilContext] = None

    @classmethod
    def from_state(cls, state: dict):
        artifacts = state.get("artifacts", {}) or {}
        skills_completed = []
        skill_progress = []
        for key, val in artifacts.items():
            if key.endswith("_skill") or key.endswith("_result"):
                skills_completed.append(key)

        return cls(
            workflow_id=state.get("project_name", "unknown"),
            phase=state.get("phase", "UNKNOWN"),
            status=state.get("status", "active"),
            started_at=state.get("started_at"),
            duration_s=state.get("duration_s"),
            skills_completed=skills_completed,
            skill_progress=skill_progress,
            artifact_keys=list(artifacts.keys()),
        )
