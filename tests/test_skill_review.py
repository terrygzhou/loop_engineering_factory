"""Unit tests for feedback/skill_review.py."""

import json
from pathlib import Path

from feedback.skill_review import (
    build_skill_review_context,
    render_skill_review_prompt,
    store_skill_review,
    load_skill_recommendations,
    run_skill_review,
)


def _state(**over):
    base = {
        "cycle_id": "c-1",
        "metrics": {
            "review_revisions": 2,
            "security_findings": 1,
            "spec_confidence": 0.8,
            "arch_uncertainty": 0.7,
        },
        "feedback": [
            {
                "type": "skill_progress",
                "skill": "doubt-driven-development",
                "event": "completed",
            },
            {
                "type": "skill_progress",
                "skill": "planning-and-task-breakdown",
                "event": "completed",
            },
            {
                "type": "skill_progress",
                "skill": "planning-and-task-breakdown",
                "event": "failed",
            },
            {
                "type": "skill_progress",
                "skill": "planning-and-task-breakdown",
                "event": "running",
            },
            {
                "type": "skill_progress",
                "skill": "planning-and-task-breakdown",
                "event": "completed",
            },
            # Non-skill feedback entries must be ignored.
            {"type": "note", "text": "human note"},
        ],
        "artifacts": {
            "loop_counts": {"BUILD": 1, "VERIFY": 1},
            "test_errors": 3,
            "verify_status": "fail",
            "acceptance_results": json.dumps(
                [
                    {
                        "id": "a1",
                        "check": "pytest -x",
                        "passed": False,
                        "expect": "0 failed",
                    }
                ]
            ),
            "proposed_diffs": json.dumps(
                {
                    "changes": [
                        {
                            "skill": "doubt-driven-development",
                            "change": "add contrarian pass",
                            "risk_level": "medium",
                        }
                    ]
                }
            ),
        },
    }
    base.update(over)
    return base


def test_build_context_collects_skill_usage():
    ctx = build_skill_review_context(_state())
    assert ctx["skill_usage"]["doubt-driven-development"] == {
        "completed": 1,
        "failed": 0,
    }
    assert ctx["skill_usage"]["planning-and-task-breakdown"] == {
        "completed": 2,
        "failed": 1,
    }
    assert ctx["loop_counts"] == {"BUILD": 1, "VERIFY": 1}
    assert ctx["test_errors"] == 3
    assert ctx["verify_status"] == "fail"


def test_build_context_empty_state():
    ctx = build_skill_review_context({})
    assert ctx["skill_usage"] == {}
    assert ctx["loop_counts"] == {}
    assert ctx["test_errors"] == 0


def test_render_prompt_contains_signals():
    ctx = build_skill_review_context(_state())
    prompt = render_skill_review_prompt(ctx)
    assert "doubt-driven-development" in prompt
    assert "arch_uncertainty" in prompt
    assert "acceptance" in prompt.lower()


def test_store_and_load_roundtrip(tmp_path):
    review = {
        "cycle_id": "c-1",
        "ts": 1,
        "verdicts": [
            {"skill": "x", "verdict": "keep", "signal": "s", "rationale": "r"}
        ],
        "recommendations": [
            {
                "skill": "x",
                "action": "keep",
                "target": None,
                "suggestion": "none",
                "priority": "low",
            }
        ],
    }
    p = store_skill_review(review, str(tmp_path))
    assert p.exists()
    loaded = load_skill_recommendations(str(tmp_path))
    assert loaded["cycle_id"] == "c-1"
    assert loaded["verdicts"][0]["skill"] == "x"


def test_load_absent_returns_empty(tmp_path):
    assert load_skill_recommendations(str(tmp_path)) == {}


def test_run_review_degrades_when_llm_none(tmp_path, monkeypatch):
    """Decision 3: LLM None -> review is recorded as unavailable, no raise."""
    monkeypatch.setattr(
        "feedback.skill_review._recommendations_path",
        lambda d: Path(d) / "skill_recommendations.json",
    )
    out = run_skill_review(_state(), llm=None, storage_dir=str(tmp_path))
    assert out["status"] == "unavailable"
    assert "reason" in out
    # Still persisted, so the next cycle sees a stable shape.
    assert load_skill_recommendations(str(tmp_path))["status"] == "unavailable"


def test_run_review_parses_llm_json(tmp_path, monkeypatch):
    """A well-formed LLM response is stored and returned."""
    monkeypatch.setattr(
        "feedback.skill_review._recommendations_path",
        lambda d: Path(d) / "skill_recommendations.json",
    )

    class FakeMsg:
        content = json.dumps(
            {
                "verdicts": [
                    {
                        "skill": "x",
                        "verdict": "improve",
                        "signal": "s",
                        "rationale": "r",
                    }
                ],
                "recommendations": [
                    {
                        "skill": "x",
                        "action": "rewrite_section",
                        "target": "challenges",
                        "suggestion": "add substep",
                        "priority": "high",
                    }
                ],
            }
        )

    class FakeLLM:
        def invoke(self, messages):
            return FakeMsg()

    out = run_skill_review(_state(), llm=FakeLLM(), storage_dir=str(tmp_path))
    assert out["status"] == "ok"
    assert out["verdicts"][0]["verdict"] == "improve"
    # Persisted file has the same shape.
    assert (
        load_skill_recommendations(str(tmp_path))["verdicts"][0]["verdict"] == "improve"
    )


def test_run_review_degrades_when_llm_fails(tmp_path, monkeypatch):
    """Decision 3: a raising LLM is caught, degraded, never raises."""
    monkeypatch.setattr(
        "feedback.skill_review._recommendations_path",
        lambda d: Path(d) / "skill_recommendations.json",
    )

    class BadLLM:
        def invoke(self, messages):
            raise RuntimeError("500 boom")

    out = run_skill_review(_state(), llm=BadLLM(), storage_dir=str(tmp_path))
    assert out["status"] == "unavailable"
    assert "LLM review failed" in out["reason"]
