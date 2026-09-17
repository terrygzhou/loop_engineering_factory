"""D1: build_output_mapping persists security_review / code_review to artifacts."""
import graph.nodes.build_subgraph_legacy as bg


def _child(tmp_path, **over):
    base = {
        "parent_artifacts": {},
        "backlog": [{"id": "1", "status": "completed", "description": "t1"}],
        "all_generated_code": ["code"],
        "errors": [],
        "uat_result": "pass",
        "uat_pass_rate": 1.0,
        "uat_output": "ok",
        "project_path": str(tmp_path),  # mapping writes backlog.md under <project>/build/
        "int_test_result": "pass",
    }
    base.update(over)
    return bg.BuildSubState(**base)


def test_both_reviews_populated(tmp_path):
    child = _child(tmp_path, security_review="sec findings", code_review="code findings")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["security_review"] == "sec findings"
    assert out["artifacts"]["code_review"] == "code findings"


def test_only_security_populated(tmp_path):
    child = _child(tmp_path, security_review="sec findings", code_review="")
    out = bg.build_output_mapping(child)
    assert out["artifacts"]["security_review"] == "sec findings"
    assert "code_review" not in out["artifacts"]


def test_both_empty_no_sentinel(tmp_path):
    child = _child(tmp_path, security_review="", code_review="")
    out = bg.build_output_mapping(child)
    assert "security_review" not in out["artifacts"]
    assert "code_review" not in out["artifacts"]
