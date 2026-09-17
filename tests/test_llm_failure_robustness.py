"""
LLM-failure robustness (Decision 3 follow-up)
==============================================

``invoke_skill`` returns ``None`` on fatal LLM failure (Decision 3:
None-on-fatal, no sentinel strings). Every active-path node must therefore
degrade gracefully instead of raising ``TypeError`` — the 2026-09-15 Web
smoke test showed DEFINE's spec call timing out → None → ``TypeError``
killing the run at ``workflow_bridge.on_error``.

These tests pin the contract: with every LLM call returning None, the node
completes (or its helper falls back) without raising.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _base_state(phase: str, **artifacts) -> dict:
    """Build a minimal valid WorkflowState dict for node tests."""
    from graph.state import CycleMetrics

    return {
        "phase": phase,
        "project_name": "test-project",
        "project_path": "/tmp/test-project",
        "auto_approve_override": True,
        "force_hil": False,
        "metrics": CycleMetrics(),
        "artifacts": dict(artifacts),
        "error": None,
        "next_phase": None,
        "cycle_id": "test-cycle-001",
        "trace_id": "test-trace-001",
    }


# ── DEFINE ──────────────────────────────────────────────────────────


def test_define_node_survives_llm_fatal(tmp_path, monkeypatch):
    """spec/parallel LLM calls all returning None must not crash DEFINE."""
    import graph.nodes.define as define_mod
    from config.loader import config as _cfg

    s = _base_state("DEFINE", interview_notes="notes")
    s["project_folder"] = str(tmp_path)

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

    out = define_mod.define_node(s)

    assert out["phase"] == "DEFINE"
    assert out.get("next_phase") == "PLAN"
    # No spec/api artifacts recorded when the LLM is fatal
    assert "spec_refined" not in out.get("artifacts", {})
    assert "api_contract" not in out.get("artifacts", {})


# ── PLAN ────────────────────────────────────────────────────────────


def test_plan_node_survives_llm_fatal(tmp_path, monkeypatch):
    """plan/doubt LLM calls returning None must not crash PLAN."""
    import graph.nodes.plan as plan_mod

    s = _base_state(
        "PLAN",
        spec_refined="S" * 250,  # >200 chars → LLM diagram path is exercised
        interview_notes="notes",
    )
    s["project_path"] = str(tmp_path)
    s["project_folder"] = str(tmp_path)

    monkeypatch.setattr(plan_mod, "safe_stream_writer", lambda: lambda x: None)
    monkeypatch.setattr(
        plan_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "planning-and-task-breakdown": {"content": "c"},
            "doubt-driven-development": {"content": "c"},
        },
    )
    monkeypatch.setattr(plan_mod, "invoke_skill", lambda *a, **k: None)

    async def _noop_async(*a, **k):
        return None

    monkeypatch.setattr(plan_mod, "invoke_skill_async", _noop_async)
    monkeypatch.setattr(plan_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(plan_mod, "get_chroma_client", lambda *a, **k: None)

    out = plan_mod.plan_node(s)

    assert out["phase"] == "PLAN"
    assert out.get("next_phase") == "BUILD"
    # solution.md still written with fallback content
    assert (tmp_path / "build" / "solution.md").exists()
    # plan/doubt artifacts degrade to empty, never None
    assert out.get("artifacts", {}).get("plan") in (None, "")
    assert out.get("artifacts", {}).get("doubt_resolution") in (None, "")


# ── SHIP ────────────────────────────────────────────────────────────


def test_ship_node_survives_llm_fatal(tmp_path, monkeypatch):
    """All four SHIP LLM calls returning None must not crash SHIP."""
    import graph.nodes.ship as ship_mod
    from config.loader import config as _cfg

    s = _base_state("SHIP", build_log="log")
    s["project_path"] = str(tmp_path)
    s["artifacts"]["project_context"] = json.dumps({"project_type": "python-fastapi"})

    monkeypatch.setattr(ship_mod, "safe_stream_writer", lambda: lambda x: None)
    monkeypatch.setattr(
        ship_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "observability-and-instrumentation": {"content": "c"},
            "shipping-and-launch": {"content": "c"},
            "production-deployment": {"content": "c"},
            "git-workflow": {"content": "c"},
        },
    )
    monkeypatch.setattr(ship_mod, "invoke_skill", lambda *a, **k: None)
    monkeypatch.setattr(_cfg.paths, "storage_dir", str(tmp_path / "storage"))

    out = ship_mod.ship_node(s)

    assert out["phase"] == "SHIP"
    assert out.get("next_phase") == "REFLECT"
    # live.json still written
    assert (tmp_path / "storage" / "live.json").exists()


# ── REFLECT ─────────────────────────────────────────────────────────


def test_reflect_node_survives_llm_fatal_with_changes(tmp_path, monkeypatch):
    """git-workflow commit LLM call returning None (with approved config
    diffs present) must not crash REFLECT."""
    import feedback.diff_engine as diff_mod
    import graph.nodes.reflect as reflect_mod
    from config.loader import config as _cfg

    guardrails_file = tmp_path / "guardrails.yaml"
    guardrails_file.write_text("min_spec_confidence: 0.8\nmax_arch_uncertainty: 0.5\n")

    s = _base_state("REFLECT", build_log="log", test_results="3 passed")

    mock_aggregator = MagicMock()
    mock_aggregator.get_historical_patterns.return_value = []
    mock_aggregator.get_cycle.return_value = []

    monkeypatch.setattr(reflect_mod, "safe_stream_writer", lambda: lambda x: None)
    monkeypatch.setattr(
        reflect_mod,
        "build_skill_registry",
        lambda *a, **k: {"git-workflow": {"content": "c"}},
    )
    monkeypatch.setattr(reflect_mod, "invoke_skill", lambda *a, **k: None)
    monkeypatch.setattr(reflect_mod, "get_llm", lambda *a, **k: None)
    monkeypatch.setattr(reflect_mod, "get_chroma_client", lambda *a, **k: None)
    monkeypatch.setattr(
        reflect_mod, "FeedbackAggregator", lambda *a, **k: mock_aggregator
    )
    monkeypatch.setattr(
        reflect_mod,
        "generate_config_diffs",
        lambda *a, **k: {
            "changes": [
                {
                    "skill": "code-review",
                    "change": "lower threshold",
                    "risk_level": "low",
                }
            ],
            "summary": "1 change",
        },
    )
    monkeypatch.setattr(reflect_mod, "dry_run_validation", lambda *a, **k: True)
    monkeypatch.setattr(diff_mod, "apply_yaml_diff", MagicMock())
    monkeypatch.setattr(_cfg.paths, "guardrails_path", str(guardrails_file))
    monkeypatch.setattr(_cfg.paths, "storage_dir", str(tmp_path))

    out = reflect_mod.reflect_node(s)

    assert out["phase"] == "REFLECT"
    assert out.get("next_phase") == "END"
    assert out.get("error") is None


# ── DISCOVER helpers ───────────────────────────────────────────────


def test_discover_fabric_requirement_falls_back_on_llm_fatal(monkeypatch):
    """_generate_requirement_via_fabric must fall back to the deterministic
    template (never raise) when the LLM is fatal."""
    import graph.nodes.discover as discover_mod

    monkeypatch.setattr(
        discover_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "fabric-prompts": {"content": "f"},
            "coding-principles": {"content": "p"},
        },
    )
    monkeypatch.setattr(discover_mod, "invoke_skill", lambda *a, **k: None)

    md = discover_mod._generate_requirement_via_fabric(
        "proj",
        "a description",
        "notes",
        {"project_type": "greenfield"},
        "/tmp/proj",
        {"cycle_id": "c"},
    )

    assert isinstance(md, str)
    assert "proj" in md  # template content, not an LLM crash


def test_discover_refine_idea_returns_empty_on_llm_fatal(monkeypatch):
    """_refine_idea must return a string (""), never None — the caller does
    len() on the result for audit logging."""
    import graph.nodes.discover as discover_mod

    monkeypatch.setattr(
        discover_mod,
        "build_skill_registry",
        lambda *a, **k: {"idea-refine": {"content": "c"}},
    )
    monkeypatch.setattr(discover_mod, "invoke_skill", lambda *a, **k: None)

    out = discover_mod._refine_idea("notes", "proj", "desc", {}, None)

    assert out == ""


def test_discover_refine_idea_is_live_with_idea_refine_skill(monkeypatch):
    """_refine_idea must be live for the real idea-refine skill: with a
    registry providing idea-refine content and a non-None invoke_skill,
    the result is the LLM output, not the placeholder string. (The lookup
    was previously for a skill that does not exist, so the refine step
    silently no-op'd.)"""
    import graph.nodes.discover as discover_mod

    monkeypatch.setattr(
        discover_mod,
        "build_skill_registry",
        lambda *a, **k: {"idea-refine": {"content": "c"}},
    )
    monkeypatch.setattr(discover_mod, "invoke_skill", lambda *a, **k: "REFINED")

    out = discover_mod._refine_idea("notes", "proj", "desc", {}, None)

    assert out == "REFINED"
    assert "No refinement available" not in out
