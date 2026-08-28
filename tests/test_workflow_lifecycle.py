"""Integration test: full workflow lifecycle (DISCOVER → REFLECT).

Validates that the edge router can carry a state object through all 9 phases
and that quality gates, loop counters, and forward paths work correctly
across the complete lifecycle.

Marked @pytest.mark.integration so it can be skipped with `-m "not integration"`.
"""

import pytest
from unittest.mock import patch, MagicMock

from graph.edges import route_phase, _forward_paths, VALID_PHASES, END_MARKER
from graph.state import CycleMetrics

# Threshold guard values used by route_phase
_MOCK_THRESHOLDS = {
    "min_spec_confidence": 0.7,
    "max_arch_uncertainty": 0.3,
    "max_security_findings": 3,
    "max_review_revisions": 5,
    "uat_pass_rate": 0.95,
}


def _make_state(phase: str, **overrides) -> dict:
    """Build a dict that satisfies WorkflowState for testing."""
    base: dict = {  # type: ignore[typeddict-item]
        "cycle_id": "test-1",
        "phase": phase,
        "metrics": CycleMetrics(
            spec_confidence=0.9,
            arch_uncertainty=0.1,
            security_findings=0,
            review_revisions=0,
            uat_pass_rate=0.99,
        ),
        "feedback": [],
        "feedback_context": "",
        "config_version": "1.0",
        "human_approval_required": False,
        "next_phase": None,
        "project_name": "TestProject",
        "project_path": "/tmp/test-project",
        "project_folder": "/tmp/test-project",
        "project_description": "Test project",
        "skip_discover": False,
        "context_folder": "/tmp/test-project",
        "error": None,
        "diagrams": {},
        "diagram_status": "",
        "diagram_feedback": "",
        "improve_mode": False,
        "auto_approve_override": None,
        "force_hil": False,
        "interview_notes": "",
        "discover_setup_done": False,
        "discover_interview_done": False,
        "trace_id": "test-trace",
        "superweb_mode": "",
        "superweb_agent_report": None,
        "artifacts": {},
        "project_context": "",
        "spec_text": "",
        "spec_refined": "",
        "plan": "",
        "tasks": "",
        "backlog": [],
        "diagram_pngs": {},
        "user_review_comments": "",
        "status": "running",
        "retry_count": 0,
        "loop_counts": {},
        "spec_confidence": 0.9,
        "tasks_text": "",
        "solution_md": "",
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


@pytest.fixture(autouse=True)
def mock_thresholds():
    """Patch get_threshold so all tests use deterministic guard values."""
    with patch("graph.edges.get_threshold") as mock_gt:
        mock_gt.side_effect = lambda k: _MOCK_THRESHOLDS[k]
        yield mock_gt


@pytest.mark.integration
class TestWorkflowLifecycle:
    """Walk a state object through DISCOVER → REFLECT via route_phase."""

    # ── Forward chain (all gates pass) ──

    def test_discover_to_define(self):
        state = _make_state("DISCOVER")
        assert route_phase(state) == "DEFINE"

    def test_define_to_plan(self):
        # spec_confidence=0.9 >= 0.7 threshold
        state = _make_state("DEFINE")
        assert route_phase(state) == "PLAN"

    def test_plan_to_arch_review(self):
        # arch_uncertainty=0.1 <= 0.3 threshold
        state = _make_state("PLAN")
        assert route_phase(state) == "ARCH_REVIEW"

    def test_arch_review_to_build(self):
        # review_approved=True in artifacts
        state = _make_state("ARCH_REVIEW", artifacts={"review_approved": True})
        assert route_phase(state) == "BUILD"

    def test_build_to_seed_data(self):
        # All BUILD gates pass: security=0, revisions=0, uat=0.99
        state = _make_state("BUILD")
        assert route_phase(state) == "SEED_DATA"

    def test_seed_data_to_verify(self):
        state = _make_state("SEED_DATA")
        assert route_phase(state) == "VERIFY"

    def test_verify_to_ship(self):
        state = _make_state("VERIFY")
        assert route_phase(state) == "SHIP"

    def test_ship_to_reflect(self):
        state = _make_state("SHIP")
        assert route_phase(state) == "REFLECT"

    def test_reflect_to_end(self):
        state = _make_state("REFLECT")
        assert route_phase(state) == END_MARKER

    # ── Quality gate loops ──

    def test_define_loop_on_low_confidence(self):
        state = _make_state(
            "DEFINE",
            metrics=CycleMetrics(spec_confidence=0.3),
        )
        assert route_phase(state) == "DEFINE"

    def test_define_forwards_on_high_confidence(self):
        state = _make_state(
            "DEFINE",
            metrics=CycleMetrics(spec_confidence=0.85),
        )
        assert route_phase(state) == "PLAN"

    def test_plan_loop_on_high_uncertainty(self):
        state = _make_state(
            "PLAN",
            metrics=CycleMetrics(arch_uncertainty=0.6),
        )
        assert route_phase(state) == "PLAN"

    def test_arch_review_rejected(self):
        state = _make_state("ARCH_REVIEW", artifacts={"review_approved": False})
        assert route_phase(state) == "PLAN"

    def test_build_loops_on_security_findings(self):
        state = _make_state(
            "BUILD",
            metrics=CycleMetrics(security_findings=5),
        )
        assert route_phase(state) == "BUILD"

    def test_build_loops_on_low_uat(self):
        state = _make_state(
            "BUILD",
            metrics=CycleMetrics(uat_pass_rate=0.6),
        )
        assert route_phase(state) == "BUILD"

    def test_build_loops_on_excessive_revisions(self):
        state = _make_state(
            "BUILD",
            metrics=CycleMetrics(review_revisions=8),
        )
        assert route_phase(state) == "BUILD"

    # ── Loop exhaustion (forward paths) ──

    def test_loop_exceeded_forwards_define(self):
        state = _make_state(
            "DEFINE",
            metrics=CycleMetrics(spec_confidence=0.3),
            artifacts={"loop_counts": {"DEFINE": 2}},
        )
        assert route_phase(state) == "PLAN"

    def test_loop_exceeded_forwards_build(self):
        state = _make_state(
            "BUILD",
            metrics=CycleMetrics(security_findings=5),
            artifacts={"loop_counts": {"BUILD": 2}},
        )
        assert route_phase(state) == "SEED_DATA"

    def test_loop_exceeded_forwards_plan(self):
        state = _make_state(
            "PLAN",
            metrics=CycleMetrics(arch_uncertainty=0.6),
            artifacts={"loop_counts": {"PLAN": 2}},
        )
        assert route_phase(state) == "ARCH_REVIEW"

    # ── Build next_phase override ──

    def test_build_next_phase_override(self):
        state = _make_state(
            "BUILD",
            next_phase="REFLECT",
            error="Build guard triggered",
            metrics=CycleMetrics(review_revisions=10),
        )
        assert route_phase(state) == "REFLECT"

    # ── Error handling ──

    def test_error_routes_to_error_node(self):
        state = _make_state("ERROR")
        assert route_phase(state) == END_MARKER

    def test_error_in_state_routes_to_error(self):
        state = _make_state("DEFINE", error="Something broke", metrics=CycleMetrics(spec_confidence=0.9))
        # Even with passing metrics, error state forces ERROR routing
        assert route_phase(state) == "ERROR"

    def test_unknown_phase_fallback(self):
        state = _make_state("UNKNOWN_PHASE")
        assert route_phase(state) == END_MARKER

    # ── Structural invariants ──

    def test_all_forward_paths_valid(self):
        for phase, target in _forward_paths.items():
            assert target in VALID_PHASES, f"{phase} → {target} target not valid"
            assert phase in VALID_PHASES

    def test_valid_phases_complete(self):
        expected = {"DISCOVER", "DEFINE", "PLAN", "ARCH_REVIEW", "BUILD",
                    "SEED_DATA", "VERIFY", "SHIP", "REFLECT", "ERROR"}
        assert expected.issubset(VALID_PHASES)

    def test_full_chain_coverage(self):
        """Every forward-path phase has a corresponding route_phase branch.

        Decision 2: VERIFY with a passing verify_status routes to SHIP;
        the _forward_paths["VERIFY"] target is "ERROR" (halt) which is
        only reached when the retry budget is exhausted. This test uses
        a clean passing state, so the expected target for VERIFY is "SHIP".
        """
        verify_expected = "SHIP"  # clean passing VERIFY -> SHIP
        for phase in _forward_paths:
            state = _make_state(phase)
            state["metrics"] = CycleMetrics(
                spec_confidence=0.9,
                arch_uncertainty=0.1,
                security_findings=0,
                review_revisions=0,
                uat_pass_rate=0.99,
            )
            state["artifacts"] = {"review_approved": True}
            if phase == "VERIFY":
                state["artifacts"]["verify_status"] = "pass"
                expected = verify_expected
            else:
                expected = _forward_paths[phase]
            result = route_phase(state)
            assert result == expected, f"{phase} → expected {expected}, got {result}"
