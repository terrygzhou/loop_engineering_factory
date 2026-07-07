"""
WorkflowState definition for the self-improving AI loop.
"""
from typing import TypedDict, List, Optional
from pydantic import BaseModel


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
    seed_executed: bool = False
    diagram_count: int = 0
    diagram_quality_score: float = 0.0


class WorkflowState(TypedDict):
    """LangGraph state for the self-improving AI loop."""
    cycle_id: str                          # Unique ID for this cycle
    phase: str                             # Current phase: DISCOVER/DEFINE/PLAN/BUILD/SEED_DATA/VERIFY/SHIP/REFLECT
    artifacts: dict[str, str]              # spec.yaml, tasks.md, code diffs, logs, etc.
    metrics: CycleMetrics                  # Collected metrics
    feedback: List[dict]                   # LLM review comments, debug traces, etc.
    feedback_context: str                  # Historical patterns from past cycles (populated by ChromaDB)
    config_version: str                    # Git commit hash of skill configs
    human_approval_required: bool          # True if next action needs human approval
    next_phase: Optional[str]              # Suggested next phase (edges can override)
    project_name: str                      # User-provided project name (captured in DISCOVER)
    project_path: str                      # Path to the target project ($project_folder)
    project_folder: str                   # Canonical project directory (e.g., ~/workspace/projects/xyz)
    spec_path: str                         # Path to the spec directory
    project_description: str                # User's project description (input to DISCOVER)
    skip_discover: bool                    # True if no context folder (greenfield mode)
    context_folder: str                    # Path to existing codebase for discovery
    error: Optional[str]                   # Error message if phase failed

    # ── B-009: Non-blocking input ──
    pending_inputs: List[dict]              # Active input requests waiting for user response
    input_responses: dict[str, dict]       # Collected responses keyed by request_id
    input_timeout_s: int                   # Per-request timeout (default 300s)
    auto_approve_timeout: bool              # Auto-approve on timeout

    # ── B-010: Architecture diagrams ──
    diagrams: dict[str, str]               # Generated diagram file paths
    diagram_status: str                    # "pending" / "approved" / "rejected"
    diagram_feedback: str                  # User feedback on rejection

    # ── Improve mode: connect factory to running product ──
    improve_mode: bool                       # True when --improve: load live.json, skip interview, use running product as context

    # ── DISCOVER: interview notes ──
    interview_notes: str                     # Collected interview answers (persists across GraphInterrupt resume)
    discover_interview_done: bool            # Top-level flag: survives LangGraph shallow merge on resume

    # ── Audit trail ──
    trace_id: str                            # Correlation ID for all logs in this workflow
    audit_entries: List[dict]               # Accumulated audit log entries
