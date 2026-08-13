"""
WorkflowState definition for the self-improving AI loop.
"""
import operator
from typing import Annotated, Dict, List, Optional, TypedDict
from pydantic import BaseModel


def _dict_merge(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """Reducer: merge two dicts (right wins on conflict). Empty right is NO-OP."""
    if not right:
        return left
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
    project_description: str
    skip_discover: bool
    context_folder: str
    error: Optional[str]

    # ── B-010: Architecture diagrams ──
    diagrams: Annotated[Dict[str, str], _dict_merge]
    diagram_status: str
    diagram_feedback: str

    # ── Improve mode ──
    improve_mode: bool

    # ── HIL control ──
    auto_approve_override: Optional[bool]
    force_hil: bool

    # ── DISCOVER: interview notes ──
    interview_notes: str
    discover_setup_done: bool
    discover_interview_done: bool

    # ── Audit trail ──
    trace_id: str

    # ── BUILD subgraph state (carried through for merge) ──
    superweb_mode: str
    superweb_agent_report: Optional[dict]
    artifacts: Annotated[Dict[str, str], _dict_merge]

    # ── Parent graph runtime keys (S-001: schema enforcement) ──
    project_context: str
    spec_text: str
    spec_refined: str
    plan: str
    tasks: str
    backlog: Annotated[List[dict], operator.add]
    diagram_pngs: Annotated[Dict[str, str], _dict_merge]
    user_review_comments: str
    status: str
    retry_count: int
    # NOTE: loop_counts is in artifacts (not top-level) — deduplicated S-003
    # NOTE: spec_confidence is in metrics.spec_confidence (CycleMetrics) — deduplicated S-003
    tasks_text: str
    solution_md: str