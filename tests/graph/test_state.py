"""Tests for graph.state — WorkflowState and CycleMetrics.

Covers:
  - CycleMetrics defaults (all zeros / False)
  - build_executor_state returns valid state with all required keys
  - project_name / project_path resolution
  - skip_discover logic (no context_folder → True, improve_mode → False)
  - improve_mode flag passthrough
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Mock heavy dependencies so we can import graph.state ────────
# graph.state has no heavy deps — it's pure TypedDict + Pydantic.

from graph.state import CycleMetrics, WorkflowState


# ── Tests: CycleMetrics ──────────────────────────────────────────

class TestCycleMetrics:
    def test_defaults_all_zero(self):
        m = CycleMetrics()
        assert m.review_revisions == 0
        assert m.security_findings == 0
        assert m.test_flakiness_rate == 0.0
        assert m.latency_ms == 0.0
        assert m.uat_pass_rate == 0.0
        assert m.spec_confidence == 0.0
        assert m.task_count == 0
        assert m.arch_uncertainty == 0.0
        assert m.launch_success is False

    def test_custom_values(self):
        m = CycleMetrics(spec_confidence=0.95, security_findings=3)
        assert m.spec_confidence == 0.95
        assert m.security_findings == 3
        # Unspecified fields remain at defaults
        assert m.arch_uncertainty == 0.0
        assert m.uat_pass_rate == 0.0

    def test_model_dump(self):
        """CycleMetrics can be serialized (needed for JSON / checkpoint)."""
        m = CycleMetrics(spec_confidence=0.8, task_count=10)
        dump = m.model_dump()
        assert dump["spec_confidence"] == 0.8
        assert dump["task_count"] == 10


# ── Tests: build_executor_state ──────────────────────────────────
# We mock graph.executor because it imports heavy services (otel, etc.)
# We import build_executor_state through the mocked path.

# Mock the heavy modules before importing executor
_mock_heavy_modules = {
    "service.otel_instrumentor": MagicMock(),
    "service.evaluator": MagicMock(),
    "service.health": MagicMock(),
    "log.logging": MagicMock(),
    "graph.sqlite_saver": MagicMock(),
    "tools.loader": MagicMock(),
    "graph.main": MagicMock(),
}


@pytest.fixture
def mock_executor_deps():
    """Patch heavy deps so graph.executor can be imported."""
    patches = []
    for mod_name, mock in _mock_heavy_modules.items():
        patches.append(patch(mod_name, create=True, new=mock))
        sys.modules.setdefault(mod_name, mock)
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


class TestBuildExecutorState:
    @pytest.fixture(autouse=True)
    def setup(self, mock_executor_deps):
        # Import build_executor_state after mocks are in place
        from graph.executor import build_executor_state, get_project_path
        self.build_executor_state = build_executor_state
        self.get_project_path = get_project_path

    def test_returns_dict_with_required_keys(self):
        state = self.build_executor_state(
            cycle_id="test-1",
            project_name="test_proj",
        )
        required_keys = {
            "cycle_id", "phase", "artifacts", "metrics", "feedback",
            "config_version", "human_approval_required", "next_phase",
            "project_name", "project_path", "project_folder",
            "project_description", "skip_discover",
            "context_folder", "error",
            "diagrams", "diagram_status", "diagram_feedback",
            "improve_mode", "interview_notes", "discover_interview_done",
            "trace_id",
            "superweb_mode", "superweb_agent_report",
            "feedback_context",
            # S-001: parent graph runtime keys
            "spec_text", "project_context", "spec_refined", "plan",
            "tasks", "backlog", "diagram_pngs", "user_review_comments",
            "status", "retry_count", "loop_counts", "spec_confidence",
            "tasks_text", "solution_md",
        }
        missing = required_keys - set(state.keys())
        assert not missing, f"Missing keys in state: {missing}"

    def test_initial_phase_is_discover(self):
        state = self.build_executor_state(
            cycle_id="1", project_name="x",
        )
        assert state["phase"] == "DISCOVER"
        assert state["next_phase"] == "DEFINE"

    def test_project_name_passes_through(self):
        state = self.build_executor_state(
            cycle_id="1", project_name="my_app",
        )
        assert state["project_name"] == "my_app"

    def test_empty_project_name_allowed(self):
        """Empty project name is allowed (defaults to placeholder)."""
        state = self.build_executor_state(cycle_id="1")
        assert state["project_name"] == ""

    def test_skip_discover_no_context(self):
        """No context_folder and not improve_mode → skip_discover=True."""
        state = self.build_executor_state(
            cycle_id="1", project_name="greenfield",
            context_folder="",
        )
        assert state["skip_discover"] is True

    def test_skip_discover_with_context(self):
        """context_folder provided → skip_discover=False."""
        state = self.build_executor_state(
            cycle_id="1", project_name="brownfield",
            context_folder="/tmp/existing",
        )
        assert state["skip_discover"] is False

    def test_improve_mode_bypasses_skip(self):
        """improve_mode=True → skip_discover=False even without context."""
        state = self.build_executor_state(
            cycle_id="1", project_name="improve_test",
            improve_mode=True,
        )
        assert state["skip_discover"] is False
        assert state["improve_mode"] is True

    def test_metrics_are_cycle_metrics(self):
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert isinstance(state["metrics"], CycleMetrics)
        assert state["metrics"].spec_confidence == 0.0

    def test_artifacts_contain_loop_counts(self):
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert "loop_counts" in state["artifacts"]
        assert state["artifacts"]["loop_counts"] == {}

    def test_error_is_none_initially(self):
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert state["error"] is None

    def test_diagram_defaults(self):
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert state["diagrams"] == {}
        assert state["diagram_status"] == "pending"
        assert state["diagram_feedback"] == ""

    def test_trace_id_only(self):
        """Trace ID defaults to empty string; audit_entries removed (OOM risk)."""
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert state["trace_id"] == ""  # default empty
        assert "audit_entries" not in state  # removed

    def test_build_subgraph_defaults(self):
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert state["superweb_mode"] == ""
        assert state["superweb_agent_report"] is None

    def test_new_parent_graph_keys(self):
        """S-001: parent graph runtime keys are initialized."""
        state = self.build_executor_state(cycle_id="1", project_name="m")
        assert state["spec_text"] == ""
        assert state["project_context"] == ""
        assert state["spec_refined"] == ""
        assert state["plan"] == ""
        assert state["tasks"] == ""
        assert state["backlog"] == []
        assert state["diagram_pngs"] == {}
        assert state["user_review_comments"] == ""
        assert state["status"] == ""
        assert state["retry_count"] == 0
        assert state["loop_counts"] == {}
        assert state["spec_confidence"] == 0.0
        assert state["tasks_text"] == ""
        assert state["solution_md"] == ""


class TestProjectPathResolution:
    @pytest.fixture(autouse=True)
    def setup(self, mock_executor_deps):
        from graph.executor import build_executor_state
        self.build_executor_state = build_executor_state

    def test_project_path_resolved(self):
        """project_path comes from config.paths.project_path."""
        state = self.build_executor_state(cycle_id="1", project_name="test")
        # project_path should be a non-empty string from config
        assert isinstance(state["project_path"], str)
        assert len(state["project_path"]) > 0


class TestWorkflowStateTypedDict:
    """WorkflowState is a TypedDict — verify it accepts the right keys."""

    def test_state_creation(self):
        state: WorkflowState = {
            "cycle_id": "1",
            "phase": "DISCOVER",
            "artifacts": {},
            "metrics": CycleMetrics(),
            "feedback": [],
            "feedback_context": "",
            "config_version": "1",
            "human_approval_required": False,
            "next_phase": "DEFINE",
            "project_name": "test",
            "project_path": "/tmp/test",
            "project_folder": "/tmp/test",
            "project_description": "",
            "skip_discover": True,
            "context_folder": "",
            "error": None,
            "diagrams": {},
            "diagram_status": "pending",
            "diagram_feedback": "",
            "improve_mode": False,
            "interview_notes": "",
            "discover_interview_done": False,
            "trace_id": "",
            "auto_approve_override": None,
            "superweb_mode": "",
            "superweb_agent_report": None,
            # S-001: parent graph runtime keys
            "project_context": "",
            "spec_text": "",
            "spec_refined": "",
            "plan": "",
            "tasks": "",
            "backlog": [],
            "diagram_pngs": {},
            "user_review_comments": "",
            "status": "",
            "retry_count": 0,
            "loop_counts": {},
            "spec_confidence": 0.0,
            "tasks_text": "",
            "solution_md": "",
        }
        assert state["phase"] == "DISCOVER"