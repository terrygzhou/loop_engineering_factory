"""W3 arckit-build-context (tasks 4.1-4.2): DEFINE's parallel LLM prompts
(source-driven + api-design) receive the ArcKit build-context advisory
blocks — ``arckit_integration_standards`` + ``arckit_nfr_constraints`` —
capped per the engineering-conventions prompt-capping limits; absent keys
keep the prompts byte-identical to today (no advisory markers, no
sentinels)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _state(tmp_path, **artifacts) -> dict:
    from tests.test_llm_failure_robustness import _base_state

    s = _base_state("DEFINE", **artifacts)
    s["project_folder"] = str(tmp_path)
    return s


def _patch_define(monkeypatch, recorded: list, parallel_result: str = "PARALLEL-OK"):
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
    monkeypatch.setattr(define_mod, "invoke_skill", lambda *a, **k: "SPEC-OK")

    async def _recorder(*a, **k):
        recorded.append(a[2] if len(a) > 2 else (k.get("context") or ""))
        return parallel_result

    monkeypatch.setattr(define_mod, "invoke_skill_async", _recorder)
    monkeypatch.setattr(define_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(define_mod, "get_chroma_client", lambda *a, **k: None)
    monkeypatch.setattr(_cfg, "set_project_name", MagicMock())


ISTD = '{"api_standards": [{"standard": "REST", "version": "3.0"}]}'
NFR = '{"use_cases": ["Check out"], "latency_requirement_ms": 300}'


def test_keys_present_appear_in_both_prompts(tmp_path, monkeypatch):
    import graph.nodes.define as define_mod

    recorded: list = []
    s = _state(tmp_path)
    s["artifacts"]["arckit_integration_standards"] = ISTD
    s["artifacts"]["arckit_nfr_constraints"] = NFR
    _patch_define(monkeypatch, recorded)

    out = define_mod.define_node(s)
    assert out["phase"] == "DEFINE"
    assert len(recorded) == 2  # source-driven + api-design contexts captured
    for ctx in recorded:
        assert "REST" in ctx
        assert "Check out" in ctx
        assert "INTEGRATION STANDARDS" in ctx
        assert "NFR CONSTRAINTS" in ctx


def test_partial_key_set_only_that_block(tmp_path, monkeypatch):
    import graph.nodes.define as define_mod

    recorded: list = []
    s = _state(tmp_path)
    s["artifacts"]["arckit_nfr_constraints"] = NFR
    _patch_define(monkeypatch, recorded)

    define_mod.define_node(s)
    for ctx in recorded:
        assert "Check out" in ctx
        assert "INTEGRATION STANDARDS" not in ctx


def test_keys_absent_prompts_identical_to_today(tmp_path, monkeypatch):
    """4.2: with no ArcKit build-context keys the advisory section is
    entirely absent — no markers, no sentinels."""
    import graph.nodes.define as define_mod

    recorded: list = []
    s = _state(tmp_path)
    _patch_define(monkeypatch, recorded)

    define_mod.define_node(s)
    assert recorded, "both parallel calls must still run"
    for ctx in recorded:
        assert "ArcKit" not in ctx
        assert "INTEGRATION STANDARDS" not in ctx
        assert "NFR CONSTRAINTS" not in ctx


def test_advisory_blocks_are_capped(tmp_path, monkeypatch):
    """4.1: advisory content is capped by bounds
    (context.arckit_advisory_max_chars) — no unbounded prompt growth."""
    import graph.nodes.define as define_mod
    from config.bounds_loader import bounds

    cap = bounds.context.arckit_advisory_max_chars
    big = NFR[:10] + "x" * (cap * 4)
    recorded: list = []
    s = _state(tmp_path)
    s["artifacts"]["arckit_nfr_constraints"] = big
    _patch_define(monkeypatch, recorded)

    define_mod.define_node(s)
    assert recorded
    for ctx in recorded:
        # the raw (uncapped) blob must NOT survive into the prompt: the
        # advisory block is truncated to the cap
        assert ctx.count("x") <= cap


def test_llm_none_robustness_unchanged(tmp_path, monkeypatch):
    """4.2 (Decision 3): parallel calls returning None must not crash —
    the advisory section does not change the fatal-LLM contract."""
    import graph.nodes.define as define_mod

    s = _state(tmp_path)
    s["artifacts"]["arckit_integration_standards"] = ISTD
    s["artifacts"]["arckit_nfr_constraints"] = NFR
    _patch_define(monkeypatch, [], parallel_result=None)

    out = define_mod.define_node(s)
    assert out["phase"] == "DEFINE"
    assert out.get("next_phase") == "PLAN"
