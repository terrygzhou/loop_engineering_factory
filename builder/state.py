"""
Build request/response/status models for the standalone builder service.
"""
from pydantic import BaseModel
from typing import Optional


class BuildRequest(BaseModel):
    build_id: str
    project_name: str
    project_path: str
    spec_text: str
    tasks_text: str
    backlog: list[dict]
    skills: dict


class BuildStatus(BaseModel):
    build_id: str
    status: str  # "running" | "pass" | "fail" | "partial"
    sub_phase: str
    progress: list[dict]
    artifacts: dict
    errors: list[str]
    completed_at: Optional[str] = None


class BuildResponse(BaseModel):
    build_id: str
    status: str  # "accepted"