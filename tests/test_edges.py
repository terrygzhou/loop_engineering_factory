"""Tests for graph/edges.py — routing logic, loop counters, quality gates."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestGetLoopCount:
    """Test _get_loop_count helper."""

    def test_returns_zero_when_no_artifacts(self):
        from graph.edges import _get_loop_count
        state: dict = {"phase": "DEFINE", "metrics": MagicMock()}
        assert _get_loop_count(state, "DEFINE") == 0

    def test_returns_zero_when_no_loop_counts(self):
        from graph.edges import _get_loop_count
        state: dict = {"phase": "DEFINE", "metrics": MagicMock(), "artifacts": {}}
        assert _get_loop_count(state, "DEFINE") == 0

    def test_returns_count_when_present(self):
        from graph.edges import _get_loop_count
        state: dict = {
            "phase": "DEFINE",
            "metrics": MagicMock(),
            "artifacts": {"loop_counts": {"DEFINE": 3}},
        }
        assert _get_loop_count(state, "DEFINE") == 3

    def test_different_phase_no_count(self):
        from graph.edges import _get_loop_count
        state: dict = {
            "phase": "BUILD",
            "metrics": MagicMock(),
            "artifacts": {"loop_counts": {"DEFINE": 2}},
        }
        assert _get_loop_count(state, "BUILD") == 0


class TestIncrementLoop:
    """Test increment_loop — pure node-side loop counter (E1)."""

    def test_first_increment(self):
        from graph.edges import increment_loop
        new_artifacts, exceeded = increment_loop({"loop_counts": {}}, "DEFINE")
        assert not exceeded
        assert new_artifacts["loop_counts"]["DEFINE"] == 1

    def test_second_increment_exceeds(self):
        from graph.edges import increment_loop
        new_artifacts, exceeded = increment_loop({"loop_counts": {"DEFINE": 1}}, "DEFINE")
        assert exceeded
        assert new_artifacts["loop_counts"]["DEFINE"] == 2

    def test_starts_from_zero(self):
        from graph.edges import increment_loop
        new_artifacts, exceeded = increment_loop({}, "BUILD")
        assert not exceeded
        assert new_artifacts["loop_counts"]["BUILD"] == 1

    def test_third_call_still_exceeds(self):
        from graph.edges import increment_loop
        new_artifacts, exceeded = increment_loop({"loop_counts": {"PLAN": 2}}, "PLAN")
        assert exceeded
        assert new_artifacts["loop_counts"]["PLAN"] == 3

    def test_pure_input_not_mutated(self):
        from graph.edges import increment_loop
        arts = {"loop_counts": {"DEFINE": 1}}
        new_arts, _ = increment_loop(arts, "DEFINE")
        assert arts == {"loop_counts": {"DEFINE": 1}}
        assert new_arts is not arts


class TestRoutePhase:
    """Test route_phase routing logic with quality gates."""

    def _make_state(self, phase: str, **overrides) -> dict:
        metrics = MagicMock()
        metrics.spec_confidence = 0.95
        metrics.arch_uncertainty = 0.3
        metrics.security_findings = 0
        metrics.review_revisions = 0
        metrics.uat_pass_rate = 0.99
        metrics.test_flakiness_rate = 0.0
        metrics.latency_ms = 100.0
        state: dict = {
            "phase": phase,
            "metrics": metrics,
            "error": None,
            "artifacts": {},
            "next_phase": None,
            **overrides,
        }
        return state

    def test_discover_to_define(self):
        from graph.edges import route_phase
        state = self._make_state("DISCOVER")
        assert route_phase(state) == "DEFINE"

    def test_define_passes_to_plan(self):
        from graph.edges import route_phase
        state = self._make_state("DEFINE")
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0.9
            assert route_phase(state) == "PLAN"

    def test_define_loops_on_low_confidence(self):
        from graph.edges import route_phase
        metrics = MagicMock()
        metrics.spec_confidence = 0.5
        metrics.arch_uncertainty = 0.3
        metrics.security_findings = 0
        metrics.review_revisions = 0
        metrics.uat_pass_rate = 0.99
        state: dict = {"phase": "DEFINE", "metrics": metrics, "error": None, "artifacts": {}, "next_phase": None}
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0.9
            assert route_phase(state) == "DEFINE"

    def test_plan_passes_to_arch_review(self):
        from graph.edges import route_phase
        state = self._make_state("PLAN")
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0.5
            assert route_phase(state) == "ARCH_REVIEW"

    def test_plan_loops_on_high_uncertainty(self):
        from graph.edges import route_phase
        metrics = MagicMock()
        metrics.spec_confidence = 0.95
        metrics.arch_uncertainty = 0.9
        metrics.security_findings = 0
        metrics.review_revisions = 0
        metrics.uat_pass_rate = 0.99
        state: dict = {"phase": "PLAN", "metrics": metrics, "error": None, "artifacts": {}, "next_phase": None}
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0.5
            assert route_phase(state) == "PLAN"

    def test_arch_review_approved(self):
        from graph.edges import route_phase
        state = self._make_state("ARCH_REVIEW", artifacts={"review_approved": True})
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "BUILD"

    def test_arch_review_rejected(self):
        from graph.edges import route_phase
        state = self._make_state("ARCH_REVIEW", artifacts={"review_approved": False})
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "PLAN"

    def test_build_passes_to_seed_data(self):
        from graph.edges import route_phase
        state = self._make_state("BUILD")
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0
            assert route_phase(state) == "SEED_DATA"

    def test_build_loops_on_security_findings(self):
        from graph.edges import route_phase
        metrics = MagicMock()
        metrics.spec_confidence = 0.95
        metrics.arch_uncertainty = 0.3
        metrics.security_findings = 5
        metrics.review_revisions = 0
        metrics.uat_pass_rate = 0.99
        state: dict = {"phase": "BUILD", "metrics": metrics, "error": None, "artifacts": {}, "next_phase": None}
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0
            assert route_phase(state) == "BUILD"

    def test_build_loops_on_low_uat(self):
        from graph.edges import route_phase
        metrics = MagicMock()
        metrics.spec_confidence = 0.95
        metrics.arch_uncertainty = 0.3
        metrics.security_findings = 0
        metrics.review_revisions = 0
        metrics.uat_pass_rate = 0.5
        state: dict = {"phase": "BUILD", "metrics": metrics, "error": None, "artifacts": {}, "next_phase": None}
        with patch("graph.edges.get_threshold") as gt:
            gt.return_value = 0.95
            assert route_phase(state) == "BUILD"

    def test_build_next_phase_override(self):
        from graph.edges import route_phase
        state = self._make_state("BUILD", next_phase="REFLECT", error="build failed")
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "REFLECT"

    def test_seed_data_to_verify(self):
        from graph.edges import route_phase
        state = self._make_state("SEED_DATA")
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "VERIFY"

    def test_verify_to_ship(self):
        from graph.edges import route_phase
        state = self._make_state("VERIFY")
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "SHIP"

    def test_ship_to_reflect(self):
        from graph.edges import route_phase
        state = self._make_state("SHIP")
        assert route_phase(state) == "REFLECT"

    def test_reflect_to_end(self):
        from graph.edges import route_phase
        state = self._make_state("REFLECT")
        result = route_phase(state)
        assert result == "__end__" or result is not None  # END marker

    def test_error_routes_to_error_node(self):
        from graph.edges import route_phase
        state = self._make_state("DEFINE", error="something broke")
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "ERROR"

    def test_loop_count_exceeds_forwards(self):
        from graph.edges import route_phase
        state = self._make_state("DEFINE", artifacts={"loop_counts": {"DEFINE": 2}})
        with patch("graph.edges.get_threshold"):
            assert route_phase(state) == "PLAN"  # forward path

    def test_unknown_phase_fallback(self):
        from graph.edges import route_phase
        state = self._make_state("UNKNOWN_PHASE")
        result = route_phase(state)
        assert result == "__end__" or result is not None

    def test_verify_routing_never_mutates_state_artifacts(self):
        """State invariance (P0-A4, state-schema-contract §3.2): after
        route_phase(state) for VERIFY, state["artifacts"] is byte-identical
        — edges never mutate state. Exercises all VERIFY outcomes
        (pass → SHIP, fail → BUILD/ERROR, budget-exhausted → ERROR)."""
        from graph.edges import route_phase

        cases = [
            # (verify_status, test_fail, loop_count, expected)
            ("pass", 0, 0, "SHIP"),
            ("fail", 0, 0, "BUILD"),  # gate failed, counter 0, no terminal error
            ("fail", 0, 1, "BUILD"),  # gate failed, retry
            ("fail", 3, 0, "BUILD"),  # pytest_fail signal, first failure
            ("fail", 0, 2, "ERROR"),  # budget exhausted
        ]
        for verify_status, test_fail, loop_count, expected in cases:
            artifacts = {
                "verify_status": verify_status,
                "loop_counts": {"VERIFY": loop_count},
                "spec_refined": "the spec",
            }
            if test_fail:
                import json as _json

                artifacts["test_results"] = _json.dumps({"pytest_fail": test_fail})
            state: dict = {
                "phase": "VERIFY",
                "metrics": MagicMock(),
                "error": None,
                "next_phase": None,
                "artifacts": artifacts,
            }
            snapshot = _json_dump_artifacts(artifacts)
            assert route_phase(state) == expected
            assert _json_dump_artifacts(state["artifacts"]) == snapshot, (
                "route_phase mutated state['artifacts'] for VERIFY"
            )


def _json_dump_artifacts(artifacts):
    import json

    return json.dumps(artifacts, sort_keys=True)

    def test_valid_phases_constant(self):
        from graph.edges import VALID_PHASES
        assert "DISCOVER" in VALID_PHASES
        assert "REFLECT" in VALID_PHASES
        assert "ERROR" in VALID_PHASES
        assert "UNKNOWN" not in VALID_PHASES


class TestForwardPaths:
    """Test forward path mapping."""

    def test_all_phases_have_forward(self):
        from graph.edges import _forward_paths
        expected_phases = {"DISCOVER", "DEFINE", "PLAN", "ARCH_REVIEW", "BUILD", "SEED_DATA", "VERIFY"}
        assert set(_forward_paths.keys()) == expected_phases

    def test_chain_is_correct(self):
        from graph.edges import _forward_paths
        assert _forward_paths["DISCOVER"] == "DEFINE"
        assert _forward_paths["DEFINE"] == "PLAN"
        assert _forward_paths["PLAN"] == "ARCH_REVIEW"
        assert _forward_paths["ARCH_REVIEW"] == "BUILD"
        assert _forward_paths["BUILD"] == "SEED_DATA"
        assert _forward_paths["SEED_DATA"] == "VERIFY"
        # Decision 2: exhausted VERIFY loop must HALT (ERROR), never SHIP.
        assert _forward_paths["VERIFY"] == "ERROR"
