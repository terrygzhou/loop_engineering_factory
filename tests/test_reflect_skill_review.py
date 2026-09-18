"""Integration: reflect_node runs the skill review and persists the artifact.

The LLM and the ChromaDB client are monkeypatched; the node itself runs for
real so the new wiring is exercised end-to-end.
"""

import json

import pytest

from config.loader import config
from feedback.skill_review import load_skill_recommendations
from graph.nodes.reflect import reflect_node


@pytest.fixture
def fake_llm():
    """A stub LLM that returns valid skill-review JSON for any prompt."""

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
                        "action": "add_substep",
                        "target": "t",
                        "suggestion": "s",
                        "priority": "high",
                    }
                ],
            }
        )

    class FakeLLM:
        def invoke(self, messages):
            return FakeMsg()

    return FakeLLM()


def _patch_node(monkeypatch, storage_dir):
    """Stub out the external dependencies of reflect_node (idiom matches
    tests/test_llm_failure_robustness.py::test_reflect_node_survives_llm_fatal_with_changes)."""
    from unittest.mock import MagicMock

    import feedback.diff_engine as diff_mod
    import graph.nodes.reflect as reflect_mod

    guardrails_file = storage_dir / "guardrails.yaml"
    guardrails_file.write_text("min_spec_confidence: 0.8\nmax_arch_uncertainty: 0.5\n")

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
    monkeypatch.setattr(reflect_mod, "get_chroma_client", lambda *a, **k: None)
    monkeypatch.setattr(
        reflect_mod, "FeedbackAggregator", lambda *a, **k: mock_aggregator
    )
    monkeypatch.setattr(
        reflect_mod,
        "generate_config_diffs",
        lambda *a, **k: {"changes": [], "summary": "no changes"},
    )
    monkeypatch.setattr(diff_mod, "apply_yaml_diff", MagicMock())
    monkeypatch.setattr(config.paths, "guardrails_path", str(guardrails_file))
    monkeypatch.setattr(config.paths, "storage_dir", str(storage_dir))


def _state(**over):
    from graph.state import CycleMetrics

    base = {
        "cycle_id": "c-int",
        "phase": "REFLECT",
        "metrics": CycleMetrics(),
        "feedback": [{"type": "skill_progress", "skill": "x", "event": "completed"}],
        "artifacts": {"loop_counts": {}},
        "auto_approve_override": True,
    }
    base.update(over)
    return base


def test_reflect_writes_skill_review_artifact(tmp_path, monkeypatch, fake_llm):
    """After reflect_node, artifacts.skill_review is set and the file is written."""
    import graph.nodes.reflect as reflect_mod

    _patch_node(monkeypatch, tmp_path)
    monkeypatch.setattr(reflect_mod, "get_llm", lambda *a, **k: fake_llm)

    out = reflect_node(_state())

    # The review landed in artifacts (JSON string, like proposed_diffs).
    assert "skill_review" in out.get("artifacts", {}), (
        f"artifacts={out.get('artifacts')}"
    )
    review = json.loads(out["artifacts"]["skill_review"])
    assert review["status"] == "ok"
    assert review["verdicts"][0]["skill"] == "x"

    # And the persistent file was written.
    persisted = load_skill_recommendations(str(tmp_path))
    assert persisted["cycle_id"] == "c-int"
    assert persisted["verdicts"][0]["verdict"] == "improve"

    # A skill_reviewed feedback entry was recorded.
    assert any(e.get("action") == "skill_reviewed" for e in out.get("feedback", []))


def test_reflect_skill_review_degrades_without_llm(tmp_path, monkeypatch):
    """Decision 3: with no LLM the review is 'unavailable' but the node completes."""
    import graph.nodes.reflect as reflect_mod

    _patch_node(monkeypatch, tmp_path)
    monkeypatch.setattr(reflect_mod, "get_llm", lambda *a, **k: None)

    out = reflect_node(_state(cycle_id="c-no-llm"))
    review = json.loads(out["artifacts"]["skill_review"])
    assert review["status"] == "unavailable"
