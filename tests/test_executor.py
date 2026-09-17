"""Tests for graph/executor.py — dead spec_text parameter removal (review finding I-1)."""

import inspect

from graph.executor import build_executor_state


def test_build_executor_state_has_no_spec_text():
    """spec_text was dead after P0-A1 removed it from WorkflowState; assert it is gone."""
    assert "spec_text" not in inspect.signature(build_executor_state).parameters

    # Calling without spec_text must work without error
    state = build_executor_state(cycle_id="1", project_name="x")
    assert state["cycle_id"] == "1"
    assert state["project_name"] == "x"
