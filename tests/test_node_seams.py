"""Seam tests for graph/nodes sibling modules: pure helpers importable without LLM/network/checkpointer monkeypatching."""


def test_node_seams_module_importable():
    """The seam-test module is collected."""
    assert True


def test_review_parse_json_artifact():
    from graph.nodes.review_payload import _parse_json_artifact
    assert _parse_json_artifact('{"a": 1}') == {"a": 1}
    assert _parse_json_artifact("not json") is None
    assert _parse_json_artifact("") is None
    assert _parse_json_artifact(None) is None


def test_review_spec_summary_truncation():
    from graph.nodes.review_payload import _spec_summary
    assert _spec_summary("short") == "short"
    assert _spec_summary("") == ""
    out = _spec_summary("x" * 600, 500)
    assert len(out) <= 504 and out.endswith(" ...")


def test_review_extract_task_breakdown():
    from graph.nodes.review_payload import _extract_task_breakdown
    plan = "- [ ] task one\n- [x] task two\n1. task three\nsome milestone line\n"
    tasks = _extract_task_breakdown(plan)
    assert "task one" in tasks and "task two" in tasks
    assert _extract_task_breakdown("") == []
