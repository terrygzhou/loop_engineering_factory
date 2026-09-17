"""W5 verify-acceptance-criteria: spec acceptance block (DEFINE), VERIFY gate
extension, and BUILD retry prompt.

Specs: openspec/changes/verify-acceptance-criteria/specs/{define-acceptance,
verify-acceptance}/spec.md
"""

import json
from unittest.mock import MagicMock, patch


def _spec_with_block(cases):
    body = "## User stories\n- As a user I want to pay online\n\n"
    block = json.dumps(
        {"acceptance_tests": cases}, indent=2
    )
    return body + "```json\n" + block + "\n```\n"


PASS_CASES = [
    {"id": "AT-01", "check": "true", "expect": "exit code 0"},
]
MIXED_CASES = [
    {"id": "AT-01", "check": "true", "expect": "exit code 0"},
    {"id": "AT-02", "check": "false", "expect": "must not happen"},
]


# ── Task 1.x — tools/acceptance.py parser + DEFINE ─────────────────


def test_parse_well_formed_block():
    from tools.acceptance import parse_acceptance_block

    tests = parse_acceptance_block(_spec_with_block(MIXED_CASES))
    assert tests == MIXED_CASES


def test_parse_absent_block_returns_none():
    from tools.acceptance import parse_acceptance_block

    assert parse_acceptance_block("no block here") is None
    assert parse_acceptance_block("") is None


def test_parse_invalid_json_returns_none():
    from tools.acceptance import parse_acceptance_block

    spec = "text\n```json\n{not json}\n```\n"
    assert parse_acceptance_block(spec) is None


def test_parse_malformed_shape_returns_none():
    from tools.acceptance import parse_acceptance_block

    missing_check = [{"id": "AT-01", "expect": "x"}]
    assert parse_acceptance_block(_spec_with_block(missing_check)) is None
    empty = {"acceptance_tests": []}
    assert parse_acceptance_block("x ```json\n" + json.dumps(empty) + "\n``` y") is None
    not_a_list = {"acceptance_tests": {"AT-01": "..."}}
    assert parse_acceptance_block("x ```json\n" + json.dumps(not_a_list) + "\n``` y") is None


def test_parse_first_valid_block_wins():
    from tools.acceptance import parse_acceptance_block

    good = json.dumps({"acceptance_tests": PASS_CASES})
    bad = json.dumps({"acceptance_tests": "nope"})
    spec = (
        "before\n```json\n" + bad + "\n```\nmiddle\n```json\n" + good + "\n```\n"
    )
    assert parse_acceptance_block(spec) == PASS_CASES


def test_spec_prompt_instruction_covers_acceptance_block():
    from graph.nodes.define import _SPEC_TASK_INSTRUCTION

    assert "acceptance_tests" in _SPEC_TASK_INSTRUCTION
    assert "check" in _SPEC_TASK_INSTRUCTION and "expect" in _SPEC_TASK_INSTRUCTION


def test_confidence_rewards_well_formed_block():
    from graph.nodes.define import _estimate_spec_confidence

    body = "Project spec content. " * 20  # >100 chars
    base = _estimate_spec_confidence({"spec_refined": body})
    richer = _estimate_spec_confidence({"spec_refined": _spec_with_block(PASS_CASES) + body})
    assert richer > base


def test_confidence_unchanged_when_block_invalid():
    from graph.nodes.define import _estimate_spec_confidence

    body = "Project spec content. " * 20
    base = _estimate_spec_confidence({"spec_refined": body})
    invalid = body + "\n```json\n{broken\n```\n"
    assert _estimate_spec_confidence({"spec_refined": invalid}) == base


def test_spec_context_includes_nfr_constraints_when_set():
    from graph.nodes.define import _build_spec_context

    state = {"artifacts": {"arckit_nfr_constraints": json.dumps({"use_cases": ["Pay online"]})}}
    ctx = _build_spec_context(state, "interview notes", "", "")
    assert "NFR constraints" in ctx
    assert "Pay online" in ctx


def test_spec_context_without_nfr_key_unchanged():
    from graph.nodes.define import _build_spec_context

    ctx = _build_spec_context({"artifacts": {}}, "interview notes", "", "")
    assert "NFR constraints" not in ctx


# ── Task 2.x — VERIFY gate extension ───────────────────────────────


def _verify_state(tmp_path, artifacts, extra=None):
    import graph.state

    state = {
        "phase": "VERIFY",
        "project_name": "demo",
        "project_path": str(tmp_path),
        "artifacts": artifacts,
        "metrics": graph.state.CycleMetrics(),
        "cycle_id": "0",
        "trace_id": "t",
        "next_phase": None,
    }
    if extra:
        state.update(extra)
    return state


def _patched_verify(tmp_path):
    """Patch writer/audit/skill-registry/test-infra; yield the infra patcher."""
    stack = patch.multiple(
        "graph.nodes.verify",
        safe_stream_writer=lambda: (lambda x: None),
        AuditLog=MagicMock(),
        build_skill_registry=lambda *a, **k: {},  # no-skill branch: no LLM
    )
    stack.start()
    import pytest

    monkey = pytest.MonkeyPatch()
    monkey.setattr("graph.nodes.verify._run_test_infrastructure", lambda *a: {})
    stack._monkey = monkey
    return stack


def _run_verify(tmp_path, artifacts, infra=None):
    from graph.nodes.verify import verify_node

    stack = _patched_verify(tmp_path)
    try:
        if infra is not None:
            stack._monkey.setattr(
                "graph.nodes.verify._run_test_infrastructure",
                lambda *a: infra,
            )
        return verify_node(_verify_state(tmp_path, artifacts))
    finally:
        stack.stop()
        stack._monkey.undo()


def test_verify_pass_when_all_acceptance_pass(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')\n")
    out = _run_verify(tmp_path, {"spec_refined": _spec_with_block(PASS_CASES)})
    art = out["artifacts"]
    assert art["verify_status"] == "pass"
    assert out["next_phase"] == "SHIP"
    results = json.loads(art["acceptance_results"])
    assert results["AT-01"]["passed"] is True
    assert results["AT-01"]["expect"] == "exit code 0"


def test_verify_fail_on_acceptance_failure_alone(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')\n")
    out = _run_verify(tmp_path, {"spec_refined": _spec_with_block(MIXED_CASES)})
    art = out["artifacts"]
    assert art["verify_status"] == "fail"
    assert art["loop_counts"]["VERIFY"] == 1
    assert out["next_phase"] is None
    assert "VERIFY failed" in out.get("error", "")
    results = json.loads(art["acceptance_results"])
    assert results["AT-01"]["passed"] is True
    assert results["AT-02"]["passed"] is False


def test_verify_fail_when_both_test_and_acceptance_fail(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')\n")
    infra = {"pytest": {"failures": 2, "passed": 4}, "ruff": None, "mypy": None}
    out = _run_verify(tmp_path, {"spec_refined": _spec_with_block(MIXED_CASES)}, infra=infra)
    assert out["artifacts"]["verify_status"] == "fail"


def test_verify_no_block_behaves_like_today(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')\n")
    out = _run_verify(tmp_path, {"spec_refined": "plain spec, no block"})
    art = out["artifacts"]
    assert art["verify_status"] == "pass"
    assert out["next_phase"] == "SHIP"
    assert "acceptance_results" not in art


def test_verify_timed_out_check_counts_as_failure(tmp_path, monkeypatch):
    import config.bounds_loader

    monkeypatch.setattr(
        config.bounds_loader.bounds.verify, "acceptance_timeout_s", 0, raising=False
    )
    (tmp_path / "app.py").write_text("print('hi')\n")
    slow = [{"id": "AT-01", "check": "sleep 0.5", "expect": "done"}]
    out = _run_verify(tmp_path, {"spec_refined": _spec_with_block(slow)})
    results = json.loads(out["artifacts"]["acceptance_results"])
    assert results["AT-01"]["passed"] is False
    assert results["AT-01"]["timed_out"] is True
    assert out["artifacts"]["verify_status"] == "fail"


# ── Task 2.4 — routing (Decision 2 preserved) ──────────────────────


def _route(artifacts, next_phase=None, error=None):
    import graph.state
    from graph.edges import route_phase

    state = {
        "phase": "VERIFY",
        "metrics": graph.state.CycleMetrics(),
        "artifacts": artifacts,
        "next_phase": next_phase,
    }
    if error is not None:
        state["error"] = error
    return route_phase(state)


def test_routing_fail_within_budget_loops_to_build():
    art = {"verify_status": "fail", "loop_counts": {"VERIFY": 1}}
    assert _route(art, next_phase=None, error="VERIFY failed") == "BUILD"


def test_routing_budget_exhausted_goes_to_error_never_ship():
    art = {"verify_status": "fail", "loop_counts": {"VERIFY": 2}}
    assert _route(art, next_phase=None, error="VERIFY failed") == "ERROR"


def test_routing_pass_goes_to_ship():
    art = {"verify_status": "pass", "loop_counts": {"VERIFY": 1}}
    assert _route(art) == "SHIP"


# ── Task 3.x — BUILD retry prompt ──────────────────────────────────


def _prompt(artifacts):
    from graph.nodes.openhands_build import _build_prompt

    return _build_prompt(
        {
            "project_name": "demo",
            "project_path": "/tmp/demo",
            "artifacts": artifacts,
            "cycle_id": "0",
            "trace_id": "t",
        }
    )


def test_retry_prompt_lists_failing_acceptance_tests():
    results = {
        "AT-01": {"id": "AT-01", "check": "true", "expect": "ok", "passed": True, "output": ""},
        "AT-02": {
            "id": "AT-02",
            "check": "pytest -q tests/test_pay.py",
            "expect": "2 passed",
            "passed": False,
            "output": "1 failed",
        },
        "AT-03": {"id": "AT-03", "check": "ruff check .", "expect": "clean", "passed": False, "output": "E501"},
    }
    prompt = _prompt(
        {
            "spec_refined": "spec",
            "tasks": "tasks",
            "acceptance_results": json.dumps(results),
        }
    )
    assert "ACCEPTANCE TEST FAILURES" in prompt
    assert "AT-02" in prompt and "AT-03" in prompt
    assert "2 passed" in prompt  # expect text surfaced
    assert "AT-01" not in prompt  # only failures listed


def test_first_attempt_prompt_unchanged_without_results():
    arts = {"spec_refined": "spec", "tasks": "tasks"}
    prompt = _prompt(arts)
    assert "ACCEPTANCE TEST FAILURES" not in prompt
    assert _prompt(dict(arts, acceptance_results=json.dumps({}))) == prompt
