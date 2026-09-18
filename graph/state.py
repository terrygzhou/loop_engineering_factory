"""
WorkflowState definition for the self-improving AI loop.
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel


def _dict_merge(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
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
    """LangGraph state for the self-improving AI loop.

    P0-A1 (2026-09-18): trimmed to keys that are either (a) returned by an
    active node / the HIL runner, or (b) input-only keys set at initial-state
    seeding time. See tests/test_state_contract.py (structural guard) and
    INPUT_ONLY_KEYS below.
    """

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
    # ── DISCOVER: explicit ArcKit artefact list (EYW-171 input, Option 1+2) ──
    arckit_artifacts: list[str]
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
    artifacts: Annotated[Dict[str, Any], _dict_merge]
    # Contract artefact keys (merged into `artifacts` by nodes):
    #   achg_context           — ACHG context for ARCH_REVIEW (EYW-171 §8.3,
    #                            written by graph/nodes/review.py)
    #   discover_artifact_audit— ArcKit ingestion audit (EYW-171 §6.4,
    #                            written by DISCOVER)
    #   oaal_sprint_map        — OAAL sprint map handoff to PLAN/BUILD
    #                            (EYW-171 §7, written by DISCOVER)
    #   arckit_product_backlog — OAPR §3 backlog rows handoff (Tier-2,
    #                            written by DISCOVER when a valid OAPR exists)
    #   arckit_open_questions  — OAPR D1–D10 TBD open questions (Tier-2,
    #                            written by DISCOVER when TBD rows exist)
    #   arckit_strategy_waves  — OASTR/TRANS transformation waves (Tier-2 P1,
    #                            written by DISCOVER when waves exist; OASTR wins)
    #   arch_review_answers    — ARCH_REVIEW HIL answers to missing build
    #                            inputs (written by graph/nodes/review.py on resume)
    #   arckit_data_model        — DATA entities/relationships/classification
    #                               (W3, written by DISCOVER when a valid DATA
    #                               artefact exists; unset otherwise)
    #   arckit_integration_standards — TECH API-standards / messaging-patterns /
    #                            integration-security tables (W3, DISCOVER)
    #   arckit_security_controls — OASEC pillars/threats/guardrails/risks (W3,
    #                            DISCOVER)
    #   arckit_nfr_constraints   — OAA-ADM-lite use_cases + NFR fields (W3,
    #                            DISCOVER)
    #   skill_review             — REFLECT skill-performance review: the
    #                            review dict (cycle_id, ts, verdicts,
    #                            recommendations, status) as a JSON string,
    #                            matching the proposed_diffs convention
    #                            (written by graph/nodes/reflect.py)

    user_review_comments: str


# P0-A1: top-level keys set ONLY at initial-state seeding time
# (build_executor_state / WorkflowBridge._build_executor_state) — never
# returned by a node. The schema contract test
# (tests/test_state_contract.py) asserts every WorkflowState key is either
# node-returned or listed here, and every entry here is declared in the
# TypedDict. Overlap with node-returned keys is allowed (e.g.
# ``config_version`` is returned by SHIP as a forward-compat seed;
# ``cycle_id`` / ``trace_id`` are audit inputs).
INPUT_ONLY_KEYS: frozenset[str] = frozenset({
    "skip_discover",
    "improve_mode",
    "force_hil",
    "auto_approve_override",
    "arckit_artifacts",
    "trace_id",
    "cycle_id",
    "config_version",
})
