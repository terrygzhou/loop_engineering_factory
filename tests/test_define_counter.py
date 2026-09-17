"""E1 — DEFINE loop-counter persistence (the livelock bug).

``_maybe_increment_loop`` mutated ``state["artifacts"]`` in place, which
LangGraph's ``_dict_merge`` reducer never sees (it only persists node
return values) — so the DEFINE counter was never persisted and a
chronically-low-confidence spec looped DEFINE→DEFINE without bound.

These tests pin the fix: on low confidence the node persists
``artifacts.loop_counts["DEFINE"]`` in its returned delta; the pure
``graph.edges.increment_loop`` helper does the counting; a high-confidence
run never touches the counter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ── graph.edges.increment_loop (pure helper) ────────────────────────


def test_increment_loop_first_call_not_exceeded():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({}, "DEFINE")
    assert not exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 1


def test_increment_loop_second_call_exceeds():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({"loop_counts": {"DEFINE": 1}}, "DEFINE")
    assert exceeded
    assert new_artifacts["loop_counts"]["DEFINE"] == 2


def test_increment_loop_pure_does_not_mutate_input():
    from graph.edges import increment_loop

    artifacts = {"loop_counts": {"DEFINE": 1, "BUILD": 3}}
    new_artifacts, _ = increment_loop(artifacts, "DEFINE")
    # The input dict must be untouched (no in-place mutation anywhere).
    assert artifacts == {"loop_counts": {"DEFINE": 1, "BUILD": 3}}
    assert new_artifacts is not artifacts
    assert new_artifacts["loop_counts"]["DEFINE"] == 2
    # Other phases carried through.
    assert new_artifacts["loop_counts"]["BUILD"] == 3


def test_increment_loop_missing_counts_key_defaults_to_zero():
    from graph.edges import increment_loop

    new_artifacts, exceeded = increment_loop({"other_key": 1}, "BUILD")
    assert not exceeded
    assert new_artifacts["loop_counts"]["BUILD"] == 1
    assert new_artifacts["other_key"] == 1


def test_maybe_increment_loop_is_gone():
    """E1 1.3: the in-place-mutation helper is deleted, not kept."""
    import graph.edges as edges_mod

    assert not hasattr(edges_mod, "_maybe_increment_loop")


# ── define_node persistence (the livelock regression) ──────────────


def _state(tmp_path, **artifacts) -> dict:
    from tests.test_llm_failure_robustness import _base_state

    s = _base_state("DEFINE", **artifacts)
    s["project_folder"] = str(tmp_path)
    return s


def _patch_define(monkeypatch, recorded: list):
    import graph.nodes.define as define_mod
    from config.loader import config as _cfg

    monkeypatch.setattr(define_mod, "safe_stream_writer", lambda: lambda x: None)
    monkeypatch.setattr(
        define_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "spec-driven-development": {"content": "c"},
            "source-driven-development": {"content": "c"},
            "api-and-interface-design": {"content": "c"},
        },
    )
    monkeypatch.setattr(define_mod, "invoke_skill", lambda *a, **k: None)

    async def _noop_async(*a, **k):
        return None

    monkeypatch.setattr(define_mod, "invoke_skill_async", _noop_async)
    monkeypatch.setattr(define_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(define_mod, "get_chroma_client", lambda *a, **k: None)
    monkeypatch.setattr(_cfg, "set_project_name", MagicMock())


def test_low_confidence_define_persists_counter(tmp_path, monkeypatch):
    """1.1a: a low-confidence DEFINE run persists loop_counts["DEFINE"] == 1."""
    import graph.nodes.define as define_mod

    s = _state(tmp_path, interview_notes="notes")
    _patch_define(monkeypatch, [])
    # Force a low confidence: spec/api/interview all empty or short.
    monkeypatch.setattr(define_mod, "_estimate_spec_confidence", lambda a: 0.5)

    out = define_mod.define_node(s)

    assert out["artifacts"]["loop_counts"]["DEFINE"] == 1
    # The node must not mutate the incoming state's artifacts in place.
    assert "loop_counts" not in s["artifacts"]


def test_second_low_confidence_run_persists_counter_two_and_logs(tmp_path, monkeypatch):
    """1.1b: seeding loop_counts["DEFINE"]=1 yields == 2 and the
    "loop limit reached, forcing forward" progress event is logged."""
    import graph.nodes.define as define_mod

    events: list = []

    def _writer_factory():
        def _w(event: dict):
            events.append(event)
        return _w

    monkeypatch.setattr(define_mod, "safe_stream_writer", _writer_factory)
    monkeypatch.setattr(
        define_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "spec-driven-development": {"content": "c"},
            "source-driven-development": {"content": "c"},
            "api-and-interface-design": {"content": "c"},
        },
    )
    monkeypatch.setattr(define_mod, "invoke_skill", lambda *a, **k: None)

    async def _noop_async2(*a, **k):
        return None

    monkeypatch.setattr(define_mod, "invoke_skill_async", _noop_async2)
    monkeypatch.setattr(define_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(define_mod, "get_chroma_client", lambda *a, **k: None)
    from config.loader import config as _cfg

    monkeypatch.setattr(_cfg, "set_project_name", MagicMock())

    s = _state(tmp_path, interview_notes="notes", loop_counts={"DEFINE": 1})
    monkeypatch.setattr(define_mod, "_estimate_spec_confidence", lambda a: 0.5)

    out = define_mod.define_node(s)

    assert out["artifacts"]["loop_counts"]["DEFINE"] == 2
    forcing = [e for e in events if "forcing forward" in str(e.get("detail", ""))]
    assert forcing, "the 'forcing forward' progress event must be emitted"
    assert "loop limit reached" in forcing[0]["detail"]


def test_high_confidence_run_does_not_touch_loop_counts(tmp_path, monkeypatch):
    """1.1c: a high-confidence run must NOT persist a DEFINE counter."""
    import graph.nodes.define as define_mod

    s = _state(tmp_path, interview_notes="notes")
    _patch_define(monkeypatch, [])
    monkeypatch.setattr(define_mod, "_estimate_spec_confidence", lambda a: 0.95)

    out = define_mod.define_node(s)

    assert "loop_counts" not in out.get("artifacts", {})


def test_low_confidence_does_not_mutate_incoming_state_in_place(tmp_path, monkeypatch):
    """Spec scenario: no function in graph/ or tools/ mutates
    state["artifacts"] in place — the incoming state stays pristine."""
    import graph.nodes.define as define_mod

    s = _state(tmp_path, interview_notes="notes")
    incoming = dict(s["artifacts"])  # pre-existing keys only (no loop_counts)
    _patch_define(monkeypatch, [])
    monkeypatch.setattr(define_mod, "_estimate_spec_confidence", lambda a: 0.5)

    define_mod.define_node(s)

    assert s["artifacts"] == incoming  # nothing new, no in-place mutation
    assert "loop_counts" not in s["artifacts"]
