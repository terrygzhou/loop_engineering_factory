"""
Tests for the W1/W2 "way forward" decisions (post codebase-audit):

- Decision 1: build_report.json manifest parsing + rel_path sanitization
- Decision 2: VERIFY conditional gate (never ships a failing build)
- Decision 3: LLM failure contract (typed errors, bounded retry, None-on-fatal)
- Decision 5: unified BUILD retry counter in artifacts.loop_counts
"""

import json

import pytest

from graph.edges import route_phase
from graph.main import build_graph
from graph.nodes import openhands_build as ob
from tools.llm import LLMError, _invoke_with_retry, _is_retryable


# ── Decision 1: build_report.json manifest ─────────────────────────


def test_parse_build_report_valid(tmp_path):
    p = tmp_path / "build_report.json"
    p.write_text(
        json.dumps(
            {
                "status": "pass",
                "test_results": "12 passed",
                "files": ["a.py", "tests/test_a.py"],
                "errors": [],
            }
        )
    )
    parsed = ob._parse_build_report(str(tmp_path))
    assert parsed is not None
    assert parsed["build_status"] == "pass"
    assert parsed["files_created"] == ["a.py", "tests/test_a.py"]
    assert parsed["test_results"] == "12 passed"
    assert parsed["errors"] == []
    assert "pass" in parsed["build_log"]


def test_parse_build_report_fail_status(tmp_path):
    p = tmp_path / "build_report.json"
    p.write_text(
        json.dumps(
            {"status": "fail", "test_results": "", "files": [], "errors": ["boom"]}
        )
    )
    parsed = ob._parse_build_report(str(tmp_path))
    assert parsed is not None
    assert parsed["build_status"] == "fail"
    assert parsed["errors"] == ["boom"]


def test_parse_build_report_bad_status_normalized(tmp_path):
    p = tmp_path / "build_report.json"
    p.write_text(json.dumps({"status": "weird", "files": ["x.py"], "errors": []}))
    parsed = ob._parse_build_report(str(tmp_path))
    assert parsed is not None
    assert parsed["build_status"] == "partial"


def test_parse_build_report_missing():
    assert ob._parse_build_report("/nonexistent/project/xyz") is None


def test_parse_build_report_invalid_json(tmp_path):
    (tmp_path / "build_report.json").write_text("{not json")
    assert ob._parse_build_report(str(tmp_path)) is None


def test_parse_build_report_malformed_shape(tmp_path):
    (tmp_path / "build_report.json").write_text(json.dumps([1, 2, 3]))
    assert ob._parse_build_report(str(tmp_path)) is None


def test_parse_build_report_coerces_types(tmp_path):
    p = tmp_path / "build_report.json"
    p.write_text(json.dumps({"status": "pass", "files": ["a.py", 7], "errors": None}))
    parsed = ob._parse_build_report(str(tmp_path))  # type: ignore[assignment]
    # test_results is a top-level key in the schema (str | absent); an absent
    # key normalizes to ""
    assert parsed["test_results"] == ""
    assert parsed["files_created"] == ["a.py"]
    assert parsed["errors"] == []


def test_prompt_includes_mandatory_manifest():
    prompt = ob._build_prompt(
        {
            "artifacts": {"spec_refined": "spec", "tasks": "tasks"},
            "project_path": "/tmp/proj",
            "project_name": "demo",
        }
    )
    assert "build_report.json" in prompt
    assert "MANDATORY MACHINE-READABLE RESULT" in prompt


# ── Decision 1 (safety): rel_path sanitization ─────────────────────


def test_write_generated_files_rejects_traversal(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    written = ob._write_generated_files(
        {"project_path": str(project)},
        [
            {"path": "../../evil.py", "content": "x"},
            {"path": "ok.py", "content": "y"},
        ],
    )
    assert written == ["ok.py"]
    assert (project / "ok.py").exists()
    assert not (tmp_path / "evil.py").exists()
    assert not (project / ".." / "evil.py").exists()


def test_write_generated_files_rejects_absolute(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    written = ob._write_generated_files(
        {"project_path": str(project)},
        [{"path": "/etc/evil.py", "content": "x"}],
    )
    assert written == []


# ── Decision 2: VERIFY conditional gate ────────────────────────────


def test_main_graph_uses_conditional_verify_edge():
    """A static VERIFY->SHIP add_edge would make SHIP trigger on VERIFY alone;
    a conditional edge triggers it via the router. Assert SHIP is NOT
    triggered by VERIFY (so the gate actually gates)."""
    g = build_graph()
    assert "SHIP" not in g.trigger_to_nodes.get("VERIFY", set()), (
        "VERIFY must not statically trigger SHIP — the gate must route it"
    )


def _verify_state(verify_status=None, test_fail=0, error=None, loop_counts=None):
    from graph.state import CycleMetrics

    artifacts = {
        "verify_status": verify_status or "pass",
        "loop_counts": loop_counts or {},
    }
    if test_fail:
        artifacts["test_results"] = json.dumps({"pytest_fail": test_fail})
    s = {
        "phase": "VERIFY",
        "metrics": CycleMetrics(),
        "artifacts": artifacts,
    }
    if error:
        s["error"] = error
        s["next_phase"] = None
    return s


def test_route_verify_pass_goes_to_ship():
    assert route_phase(_verify_state(verify_status="pass")) == "SHIP"


def test_route_verify_fail_loops_back_to_build():
    assert route_phase(_verify_state(verify_status="fail")) == "BUILD"


def test_route_verify_test_failures_loop_back_to_build():
    # verify_status omitted (older runs) but deterministic pytest_fail present
    assert route_phase(_verify_state(verify_status=None, test_fail=3)) == "BUILD"


def test_route_verify_error_terminal_routes_to_error():
    # LLM-fatal escape hatch from verify_node: error set, no next_phase.
    # Terminal failures go to the ERROR sink BEFORE the retry loop (this is
    # the documented behavior: a terminal error never gets a build retry).
    assert route_phase(_verify_state(verify_status="fail", error="boom")) == "ERROR"


def test_route_verify_halt_after_budget_exhausted():
    """When the VERIFY retry counter is exhausted AND verify_status is
    "fail", route to the ERROR terminal instead of looping back to BUILD.
    """
    s = _verify_state(
        verify_status="fail",
        loop_counts={"VERIFY": 2},  # max_loops = 2
    )
    assert route_phase(s) == "ERROR"


# ── Decision 3: LLM failure contract ───────────────────────────────


class _FakeLLM:
    """Configurable fake: fail N times then succeed (or always fail)."""

    def __init__(self, fail_times=0, exc=None):
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("transient 500")
        self.calls = 0

    def invoke(self, messages, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        class _R:
            content = "ok"
        return _R()


def test_invoke_with_retry_succeeds_after_transient():
    llm = _FakeLLM(fail_times=2, exc=RuntimeError("connect timeout"))
    out = _invoke_with_retry(llm, [], max_retries=3, timeout_s=5)
    assert out.content == "ok"
    assert llm.calls == 3


def test_invoke_with_retry_raises_llmerror_on_exhaustion(monkeypatch):
    import tools.llm as mod

    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)
    llm = _FakeLLM(fail_times=99, exc=RuntimeError("connect timeout"))
    with pytest.raises(LLMError):
        _invoke_with_retry(llm, [], max_retries=2, timeout_s=5)
    assert llm.calls == 3  # 1 + 2 retries


def test_invoke_with_retry_no_retry_on_fatal():
    monkeypatch = pytest.MonkeyPatch()
    import tools.llm as mod

    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)
    llm = _FakeLLM(fail_times=99, exc=RuntimeError("401 Unauthorized"))
    with pytest.raises(LLMError):
        _invoke_with_retry(llm, [], max_retries=5, timeout_s=5)
    assert llm.calls == 1  # fatal -> no retries
    monkeypatch.undo()


def test_is_retryable_classification():
    assert _is_retryable(RuntimeError("connect timeout")) is True
    assert _is_retryable(RuntimeError("500 server error")) is True
    assert _is_retryable(RuntimeError("401 Unauthorized")) is False
    assert _is_retryable(RuntimeError("model not found")) is False


def test_invoke_skill_returns_none_on_llm_error(monkeypatch):
    import tools.llm as mod

    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)

    class _FailLLM:
        def invoke(self, *a, **k):
            raise RuntimeError("connect timeout")

    # patch the heavy side-effects to keep the test fast + hermetic.
    # Note: invoke_skill imports tracer/health_module INSIDE the function
    # (`from service.otel_instrumentor import tracer`), so we patch the
    # source modules' attributes, not mod.tracer (mod doesn't have it).
    monkeypatch.setattr(mod, "prepare_context_for_llm", lambda c, max_tokens=None: {
        "context": "ctx",
        "total_tokens": 10,
        "headroom": {"headroom_pct": 100.0},
    })
    monkeypatch.setattr(mod, "log_llm_call", lambda **kw: None)

    from service import health as health_module
    monkeypatch.setattr(health_module, "track_llm", lambda **kw: None)
    from service import otel_instrumentor as otel_mod
    monkeypatch.setattr(
        otel_mod.tracer, "record_llm_call", lambda **kw: None, raising=False
    )

    out = mod.invoke_skill("skill", "task", llm=_FailLLM())
    assert out is None  # None-on-fatal: no sentinel string


# ── Decision 5: unified BUILD retry counter ────────────────────────


def test_merge_results_halt_after_build_budget(tmp_path):
    state = {
        "project_path": str(tmp_path),
        "artifacts": {"loop_counts": {"BUILD": ob.BUILD_MAX_RETRIES}},
        "metrics": None,
    }
    parsed = {
        "build_status": "fail",
        "build_log": "log",
        "test_results": "",
        "files_created": [],
        "errors": ["e1"],
        "generated_code": [],
    }
    out = ob._merge_results(state, parsed)
    # Budget exceeded: error set, NO next_phase override -> route_phase
    # sends it to the ERROR terminal (no silent REFLECT side-door).
    assert out["error"]
    assert out.get("next_phase") is None
    assert out["artifacts"]["loop_counts"]["BUILD"] == ob.BUILD_MAX_RETRIES + 1
    assert out["artifacts"]["build_status"] == "fail"


def test_merge_results_increments_counter_on_fail(tmp_path):
    state = {"project_path": str(tmp_path), "artifacts": {}, "metrics": None}
    parsed = {
        "build_status": "fail",
        "build_log": "log",
        "test_results": "",
        "files_created": [],
        "errors": ["e"],
        "generated_code": [],
    }
    out = ob._merge_results(state, parsed)
    assert out["artifacts"]["loop_counts"]["BUILD"] == 1
    assert out.get("next_phase") is None


def test_merge_results_resets_counter_on_pass(tmp_path):
    state = {
        "project_path": str(tmp_path),
        "artifacts": {"loop_counts": {"BUILD": 2}},
        "metrics": None,
    }
    parsed = {
        "build_status": "pass",
        "build_log": "log",
        "test_results": "ok",
        "files_created": ["a.py"],
        "errors": [],
        "generated_code": [{"path": "a.py", "content": "x"}],
    }
    out = ob._merge_results(state, parsed)
    assert out["artifacts"]["loop_counts"]["BUILD"] == 0
    assert out["next_phase"] == "SEED_DATA"


def test_route_build_respects_node_persisted_counter():
    """The edge no longer mutates: a state with counter>=max routes forward."""
    from graph.state import CycleMetrics

    s = {
        "phase": "BUILD",
        "metrics": CycleMetrics(uat_pass_rate=0.0, security_findings=0),
        "artifacts": {"loop_counts": {"BUILD": 2}},
    }
    # UAT gate would loop, but the budget is exhausted -> forced forward.
    assert route_phase(s) == "SEED_DATA"


def test_route_build_loops_when_uat_fails_and_budget_ok():
    from graph.state import CycleMetrics

    s = {
        "phase": "BUILD",
        "metrics": CycleMetrics(uat_pass_rate=0.0, security_findings=0),
        "artifacts": {"loop_counts": {"BUILD": 0}},
    }
    assert route_phase(s) == "BUILD"


# ── E1: increment_loop pure helper ─────────────────────────────────
# (P0-A4, state-schema-contract §3.1)


def test_increment_loop_increments_from_zero():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({}, "DEFINE")
    assert not exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 1


def test_increment_loop_0_to_1_not_exceeded():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({"loop_counts": {}}, "DEFINE")
    assert not exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 1


def test_increment_loop_halt_at_max():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({"loop_counts": {"DEFINE": 1}}, "DEFINE")
    assert exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 2


def test_increment_loop_stays_exceeded_beyond_max():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({"loop_counts": {"DEFINE": 2}}, "DEFINE")
    assert exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 3


def test_increment_loop_reset_on_success():
    """Caller passes a fresh dict (no counter yet) -> back to 0 semantics."""
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({}, "VERIFY")
    assert not exceeded
    assert new_artifacts["loop_counts"]["VERIFY"] == 1
    assert "loop_counts" in new_artifacts


def test_increment_loop_is_pure_input_unchanged():
    from graph.edges import increment_loop

    arts = {"loop_counts": {"DEFINE": 1}, "spec_text": "keep"}
    new_arts, _ = increment_loop(arts, "DEFINE")
    assert arts == {"loop_counts": {"DEFINE": 1}, "spec_text": "keep"}
    assert new_arts is not arts
    assert new_arts["loop_counts"]["DEFINE"] == 2
    assert new_arts["spec_text"] == "keep"


# ── BUILD mode choice (HIL) ─────────────────────────────────────────


class _NoopAudit:
    def log_node_input(self, *a, **kw):
        pass

    def log_node_output(self, *a, **kw):
        pass

    def log_node_transition(self, *a, **kw):
        pass


def test_wrapper_subgraph_mode_skips_gateway(monkeypatch, tmp_path):
    """build_mode='subgraph' forces local subgraph — no HTTP health check."""

    def _fake_local_subgraph(state):
        return {
            "phase": "BUILD",
            "artifacts": {"build_status": "pass", "loop_counts": {"BUILD": 0}},
            "next_phase": "SEED_DATA",
            "superApp_mode": "agent",
        }

    monkeypatch.setattr(ob, "_run_local_subgraph", _fake_local_subgraph)
    monkeypatch.setattr(ob, "AuditLog", lambda *a, **kw: _NoopAudit())

    state = {
        "project_path": str(tmp_path),
        "cycle_id": "1",
        "artifacts": {"build_mode": "subgraph"},
    }
    out = ob.openhands_build_wrapper(state)
    assert out["artifacts"]["build_status"] == "pass"
    assert out["next_phase"] == "SEED_DATA"


def test_wrapper_openhands_mode_default_when_no_build_mode(monkeypatch, tmp_path):
    """Absent build_mode defaults to openhands — health check is attempted,
    then falls back to local subgraph on connection failure."""
    import httpx

    called = {"local": False}

    def _fake_local_subgraph(state):
        called["local"] = True
        return {
            "phase": "BUILD",
            "artifacts": {"build_status": "pass", "loop_counts": {"BUILD": 0}},
            "next_phase": "SEED_DATA",
        }

    monkeypatch.setattr(ob, "_run_local_subgraph", _fake_local_subgraph)
    monkeypatch.setattr(ob, "AuditLog", lambda *a, **kw: _NoopAudit())

    # Simulate unreachable gateway: httpx.Client(...) context manager's .get()
    # raises ConnectError → wrapper catches it → falls back to local subgraph
    class _FakeHttpModule:
        ConnectError = httpx.ConnectError
        ConnectTimeout = httpx.ConnectTimeout
        HTTPError = httpx.HTTPError
        HTTPStatusError = httpx.HTTPStatusError
        RemoteProtocolError = httpx.RemoteProtocolError

        class Client:
            def __init__(self, *a, **kw):
                pass

            def get(self, *a, **kw):
                raise httpx.ConnectError("refused")

            def post(self, *a, **kw):
                raise httpx.ConnectError("refused")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

    monkeypatch.setattr(ob, "httpx", _FakeHttpModule)

    state = {
        "project_path": str(tmp_path),
        "cycle_id": "1",
        "artifacts": {},
    }
    out = ob.openhands_build_wrapper(state)
    # Gateway unreachable → local subgraph fallback was used
    assert called["local"] is True
    assert out["artifacts"]["build_status"] == "pass"


def test_review_interrupt_payload_includes_build_mode(monkeypatch):
    """The ARCH_REVIEW interrupt payload carries build_mode options."""
    from graph.nodes import review as review_module

    # Capture the interrupt payload via monkeypatch
    captured = {}

    def _fake_interrupt(payload):
        captured["payload"] = payload
        return {"approved": True}

    monkeypatch.setattr(review_module, "interrupt", _fake_interrupt)
    monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {})
    monkeypatch.setattr(review_module, "PxGate", _FakePxGate)
    monkeypatch.setattr(review_module, "scan_achg_context", lambda root: {})
    monkeypatch.setattr(review_module, "pending_achg_ids", lambda ctx: [])
    monkeypatch.setattr(
        review_module, "AuditLog", lambda *a, **kw: _NoopAudit()
    )

    state = {
        "cycle_id": "1",
        "trace_id": "t1",
        "artifacts": {"plan": "p", "spec_refined": "s"},
    }
    review_module.review_node(state)

    payload = captured["payload"]
    assert payload.get("build_mode") == {
        "default": "openhands",
        "options": ["openhands", "subgraph"],
    }


def test_review_resume_writes_build_mode_to_artifacts(monkeypatch):
    """Resume with build_mode='subgraph' writes it into artifacts."""
    from graph.nodes import review as review_module

    captured = {}

    def _fake_interrupt(payload):
        captured["payload"] = payload
        return {"approved": True, "build_mode": "subgraph"}

    monkeypatch.setattr(review_module, "interrupt", _fake_interrupt)
    monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {})
    monkeypatch.setattr(review_module, "PxGate", _FakePxGate)
    monkeypatch.setattr(review_module, "scan_achg_context", lambda root: {})
    monkeypatch.setattr(review_module, "pending_achg_ids", lambda ctx: [])
    monkeypatch.setattr(review_module, "AuditLog", lambda *a, **kw: _NoopAudit())

    state = {
        "cycle_id": "1",
        "trace_id": "t1",
        "artifacts": {"plan": "p", "spec_refined": "s"},
    }
    out = review_module.review_node(state)
    assert out["artifacts"]["build_mode"] == "subgraph"


def test_review_resume_default_build_mode_openhands(monkeypatch):
    """Resume without build_mode defaults to 'openhands'."""
    from graph.nodes import review as review_module

    def _fake_interrupt(payload):
        return {"approved": True}  # no build_mode key

    monkeypatch.setattr(review_module, "interrupt", _fake_interrupt)
    monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {})
    monkeypatch.setattr(review_module, "PxGate", _FakePxGate)
    monkeypatch.setattr(review_module, "scan_achg_context", lambda root: {})
    monkeypatch.setattr(review_module, "pending_achg_ids", lambda ctx: [])
    monkeypatch.setattr(review_module, "AuditLog", lambda *a, **kw: _NoopAudit())

    state = {
        "cycle_id": "1",
        "trace_id": "t1",
        "artifacts": {"plan": "p", "spec_refined": "s"},
    }
    out = review_module.review_node(state)
    assert out["artifacts"]["build_mode"] == "openhands"


class _FakePxGate:
    enabled = False

    def __init__(self, **kw):
        pass

    def evaluate_review_gate(self, spec, plan):
        class _R:
            passed = True
            failures = []
            def to_artifact(self):
                return {"passed": True, "failures": []}
        return _R()
