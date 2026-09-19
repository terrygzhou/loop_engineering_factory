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


def test_verify_parse_review_result_counts():
    from graph.nodes.verify_review import _parse_review_result
    r = _parse_review_result(
        "Critical: broken import at a.py:3\nRequired: missing error handling\n"
        "- [x] item\n**Nit: style thing here**\n"
    )
    assert r["critical"] == 1 and r["verdict"] == "changes"
    r2 = _parse_review_result("All good, no issues found at all here")
    assert r2["verdict"] in ("approve", "changes")


def test_verify_find_venv_python(tmp_path):
    from graph.nodes.verify_tooling import _find_venv_python
    assert _find_venv_python(str(tmp_path)) is None
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python3").write_text("#!/usr/bin/env python3")
    assert _find_venv_python(str(tmp_path)) == str(tmp_path / ".venv" / "bin" / "python3")


def test_verify_collect_source_files(tmp_path):
    from graph.nodes.verify_review import _collect_source_files
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "b.py").write_text("y = 2\n")
    files = _collect_source_files(str(tmp_path))
    assert [f["path"] for f in files] == ["a.py"]


def test_verify_build_review_context():
    from graph.nodes.verify_review import _build_review_context
    ctx = _build_review_context([{"path": "a.py", "content": "x"}], "SPEC")
    assert "a.py" in ctx and "SPEC" in ctx
