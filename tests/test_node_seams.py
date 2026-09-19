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
    # NB: the cleanup regex in _extract_task_breakdown is
    # r"^\s*[-*]\s*\[[ xX?\]]\s*" — the character class [ xX?]
    # swallows the closing bracket on "- [ ]" and "- [x]", so the
    # extracted lines keep a leading "]" prefix. This is the
    # pre-existing (verbatim-moved) behavior; we assert it as-is.
    assert "] task one" in tasks and "] task two" in tasks
    assert "task three" in tasks and "some milestone line" in tasks
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
    assert _find_venv_python(str(tmp_path)) == str(
        tmp_path / ".venv" / "bin" / "python3"
    )


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


def test_discover_detect_project_type(tmp_path):
    from graph.nodes.discover_scan import _detect_project_type

    assert _detect_project_type(str(tmp_path)) == "unknown"
    (tmp_path / "pyproject.toml").write_text("[project]")
    assert _detect_project_type(str(tmp_path)) == "python"
    (tmp_path / "package.json").write_text("{}")
    # pyproject wins (checked first)
    assert _detect_project_type(str(tmp_path)) == "python"


def test_discover_inventory_tree(tmp_path):
    from graph.nodes.discover_scan import _inventory_tree

    (tmp_path / "src" / "a.py").parent.mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / ".git").mkdir()
    tree = _inventory_tree(str(tmp_path))
    assert "src" in tree and ".git" not in tree
    assert tree["src"]["type"] == "dir"


def test_discover_git_status_no_repo(tmp_path):
    from graph.nodes.discover_scan import _get_git_status

    out = _get_git_status(str(tmp_path))
    assert set(out) == {"branch", "dirty"}


def test_discover_collect_plain_docs(tmp_path):
    from graph.nodes.discover_scan import _collect_plain_docs

    (tmp_path / "notes.md").write_text("hello")
    (tmp_path / "ARC-001-REQ.md").write_text("arckit")
    out = _collect_plain_docs(str(tmp_path))
    assert [p.name for p in out] == ["notes.md"]


def test_define_build_spec_context_pure():
    from graph.nodes.define_prompts import _build_spec_context

    state = {"spec_path": "/x", "artifacts": {"project_context": "ctx"}}
    out = _build_spec_context(state, "notes", "", "")
    assert "Existing project context" in out and "ctx" in out
    # byte-identical: NFR block only when artifact set
    state2 = {"spec_path": "/x", "artifacts": {"arckit_nfr_constraints": "NFR-1"}}
    assert "NFR constraints" in _build_spec_context(state2, "n", "", "")
    assert "NFR constraints" not in _build_spec_context(state, "n", "", "")


def test_define_estimate_spec_confidence_pure():
    from graph.nodes.define_confidence import _estimate_spec_confidence

    assert _estimate_spec_confidence({}) == 0.0
    assert (
        0
        < _estimate_spec_confidence(
            {
                "spec_refined": "x" * 200,
                "api_contract": "y" * 100,
                "interview_notes": "z" * 100,
            }
        )
        <= 1.0
    )


# ── S7 openhands siblings ─────────────────────────────────────────────


def test_openhands_parse_build_report_valid(tmp_path):
    import json as _json

    from graph.nodes.openhands_report import _parse_build_report

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "build_report.json").write_text(
        _json.dumps(
            {"status": "pass", "test_results": "12/12", "files": ["a.py"], "errors": []}
        )
    )
    r = _parse_build_report(str(proj))
    assert r is not None
    assert r["build_status"] == "pass"
    assert r["files_created"] == ["a.py"]
    assert r["test_results"] == "12/12"


def test_openhands_parse_build_report_invalid(tmp_path):
    from graph.nodes.openhands_report import _parse_build_report

    proj = tmp_path / "proj"
    proj.mkdir()
    # No file at all → None
    assert _parse_build_report(str(proj)) is None
    # Invalid JSON → None
    (proj / "build_report.json").write_text("{not json")
    assert _parse_build_report(str(proj)) is None
    # Missing "status" key → None
    (proj / "build_report.json").write_text('{"files": ["a.py"]}')
    assert _parse_build_report(str(proj)) is None


def test_openhands_write_generated_files_traversal_rejected(tmp_path):
    from graph.nodes.openhands_merge import _write_generated_files

    state = {"project_path": str(tmp_path)}
    files = [
        {"path": "a.py", "content": "print('ok')"},
        {"path": "../../etc/passwd", "content": "evil"},
        {"path": "/abs/path.py", "content": "abs"},
    ]
    written = _write_generated_files(state, files)
    assert written == ["a.py"]
    assert not (tmp_path.parent / "etc" / "passwd").exists()


def test_openhands_merge_results_halt_on_exhausted_budget():
    from graph.nodes.openhands_merge import _merge_results

    state = {
        "phase": "BUILD",
        "project_path": "/tmp/never",
        "artifacts": {"loop_counts": {"BUILD": 2}},  # already at max
    }
    parsed = {
        "build_status": "fail",
        "build_log": "log",
        "test_results": "0/10",
        "files_created": [],
        "errors": ["boom"],
        "generated_code": [],
    }
    result = _merge_results(state, parsed)
    assert result["next_phase"] is None
    assert "error" in result and "3 times" in result["error"]
    assert result["artifacts"]["loop_counts"]["BUILD"] == 3


# ── S9 discover siblings ──────────────────────────────────────────────


def test_discover_extract_doc_prefill_no_docs(tmp_path):
    from graph.nodes.discover_prefill import _extract_doc_prefill

    assert _extract_doc_prefill(str(tmp_path), "P", "d", [], "") == (None, None)


def test_discover_extract_doc_prefill_no_files(tmp_path):
    # Empty dir → no plain docs → (None, None)
    from graph.nodes.discover_prefill import _extract_doc_prefill

    assert _extract_doc_prefill(str(tmp_path), "P", "d", [], "") == (None, None)


def test_discover_build_context_json_shape():
    from graph.nodes.discover_interview import _build_context

    import json

    ctx = _build_context(
        "notes here",
        "Proj",
        "desc",
        {"project_type": "python", "tree": {"src": {"type": "dir"}}, "dependencies": {"x": "1"}, "specs": {}},
        None,
    )
    parsed = json.loads(ctx)
    assert parsed["project_name"] == "Proj"
    assert parsed["type"] == "python"
    assert "interview_focus" in parsed

