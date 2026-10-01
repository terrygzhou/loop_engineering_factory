"""D5: partial build status for incomplete-backlog + green UAT/INT_TEST.

Includes the Decision-5 retry-counter semantics: D4 hard fails and D5
partials increment artifacts.loop_counts["BUILD"] and halt (error +
next_phase=None) once the counter reaches the max budget, so
route_phase can stop the BUILD livelock.
"""
import graph.nodes.build_subgraph_legacy as bg


def _backlog(completed):
    return [
        {"id": str(i), "status": "completed" if i <= completed else "failed",
         "description": f"t{i}"}
        for i in range(1, 6)
    ]


def _child(tmp_path, **over):
    base = {
        "parent_artifacts": {},
        "backlog": _backlog(5),
        "all_generated_code": ["code"],
        "errors": [],
        "uat_result": "pass",
        "uat_pass_rate": 1.0,
        "uat_output": "ok",
        "project_path": str(tmp_path),
        "int_test_result": "pass",
    }
    base.update(over)
    return bg.BuildSubState(**base)


def test_partial_when_some_incomplete_uat_green(tmp_path):
    child = _child(tmp_path, backlog=_backlog(3),
                   errors=["Item 4: No code generated", "Item 5: No code generated"],
                   uat_result="pass", int_test_result="pass")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "partial"
    assert sorted(out["artifacts"]["incomplete_items"]) == ["4", "5"]


def test_partial_when_uat_skipped(tmp_path):
    child = _child(tmp_path, backlog=_backlog(3),
                   errors=["Item 4: No code generated", "Item 5: No code generated"],
                   uat_result="skip", uat_pass_rate=0.0, int_test_result="pass")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "partial"


def test_pass_when_all_completed(tmp_path):
    child = _child(tmp_path, backlog=_backlog(5), uat_result="pass", int_test_result="pass")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "pass"
    assert "incomplete_items" not in out["artifacts"]


def test_fail_wins_over_partial_when_int_test_fails(tmp_path):
    child = _child(tmp_path, backlog=_backlog(3), uat_result="pass",
                   int_test_result="fail", int_test_output="Health check failed: HTTP 500")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "fail"  # D4 wins over D5


# ── Decision 5: retry counter in artifacts.loop_counts ─────────────


def _partial_child(tmp_path, loop_counts):
    """D5 partial: some items incomplete, UAT + INT_TEST green."""
    return _child(
        tmp_path,
        backlog=_backlog(3),
        errors=["Item 4: No code generated", "Item 5: No code generated"],
        uat_result="pass",
        int_test_result="pass",
        parent_artifacts={"loop_counts": loop_counts},
    )


def test_d5_first_failure_increments_counter_and_retries(tmp_path):
    """First partial failure -> counter 1, next_phase BUILD (retry)."""
    out = bg.build_output_mapping(_partial_child(tmp_path, {}))
    assert out["artifacts"]["build_status"] == "partial"
    assert out["artifacts"]["loop_counts"]["BUILD"] == 1
    assert out["next_phase"] == "BUILD"  # retry while budget remains
    assert out["error"] is None  # non-exhausted partial keeps error=None


def test_d5_second_failure_exhausts_budget_and_halts(tmp_path):
    """Second partial failure -> counter hits budget (2), terminal halt:
    next_phase=None + a real error so the route_phase terminal gate fires."""
    out = bg.build_output_mapping(_partial_child(tmp_path, {"BUILD": 1}))
    assert out["artifacts"]["build_status"] == "partial"
    assert out["artifacts"]["loop_counts"]["BUILD"] == 2
    assert out["next_phase"] is None
    assert out["error"]  # budget-exhausted partial must carry a real error


def test_d4_hard_fail_increments_counter_and_retries(tmp_path):
    """First D4 hard fail -> counter 1, next_phase BUILD (retry)."""
    child = _child(
        tmp_path,
        backlog=_backlog(3),
        errors=["uat boom"],
        uat_result="fail",
        int_test_result="pass",
    )
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "fail"
    assert out["artifacts"]["loop_counts"]["BUILD"] == 1
    assert out["next_phase"] == "BUILD"
    assert out["error"]  # D4 always carries an error summary


def test_d4_second_hard_fail_exhausts_budget_and_halts(tmp_path):
    """Second D4 hard fail -> counter hits budget, next_phase=None."""
    child = _child(
        tmp_path,
        backlog=_backlog(3),
        errors=["uat boom"],
        uat_result="fail",
        int_test_result="pass",
        parent_artifacts={"loop_counts": {"BUILD": 1}},
    )
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["build_status"] == "fail"
    assert out["artifacts"]["loop_counts"]["BUILD"] == 2
    assert out["next_phase"] is None
    assert out["error"]
