"""
WorkflowState definition for the self-improving AI loop.
"""
import operator
from typing import Annotated, Dict, List, Optional, TypedDict
from pydantic import BaseModel


def _dict_merge(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """Reducer: merge two dicts (right wins on conflict)."""
    return {**left, **right}


class CycleMetrics(BaseModel):
    """Metrics collected during a workflow cycle."""
    review_revisions: int = 0
    security_findings: int = 0
    test_flakiness_rate: float = 0.0
    latency_ms: float = 0.0
    uat_pass_rate: float = 0.0
    spec_confidence: float = 0.0
    task_count: int = 0
    arch_uncertainty: float = 0.0
    launch_success: bool = False


class WorkflowState(TypedDict):
    """LangGraph state for the self-improving AI loop."""
    cycle_id: str
    phase: str
    metrics: CycleMetrics
    feedback: Annotated[List[dict], operator.add]
    feedback_context: str
    config_version: str
    human_approval_required: bool
    next_phase: Optional[str]
    project_name: str
    project_path: str
    project_folder: str
    spec_path: str
    project_description: str
    skip_discover: bool
    context_folder: str
    error: Optional[str]

    # ── B-009: Non-blocking input ──
    pending_inputs: Annotated[List[dict], operator.add]

    # ── B-010: Architecture diagrams ──
    diagrams: Annotated[Dict[str, str], _dict_merge]
    diagram_status: str
    diagram_feedback: str

    # ── Improve mode ──
    improve_mode: bool

    # ── DISCOVER: interview notes ──
    interview_notes: str
    discover_interview_done: bool

    # ── Audit trail ──
    trace_id: str
    # NOTE: audit_entries exists in state but NOT populated by nodes (OOM risk).
    # AuditLog persists to disk (build/audit_logs/interactions.jsonl).
    audit_entries: Annotated[List[dict], operator.add]

    # ── BUILD subgraph state (carried through for merge) ──
    build_backlog: Optional[Annotated[List[dict], operator.add]]
    superweb_mode: str
    superweb_agent_report: Optional[dict]
    artifacts: Annotated[Dict[str, str], _dict_merge]