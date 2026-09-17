"""D5: partial build status for incomplete-backlog + green UAT/INT_TEST."""
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
