"""DISCOVER/DEFINE inject skill recommendations as advisory context.

Contract: absent file → byte-identical prompt (no advisory block);
present file → advisory block appended.
"""

from pathlib import Path


import graph.nodes.discover as discover
import graph.nodes.define as define
from feedback.skill_review import store_skill_review
from tools import skill_recommendations as rec_mod


def _write_recs(storage_dir: Path, recs, cycle_id="c-prev"):
    store_skill_review({
        "cycle_id": cycle_id, "ts": 0,
        "verdicts": [{"skill": "x", "verdict": "improve", "signal": "s", "rationale": "r"}],
        "recommendations": recs,
        "status": "ok",
    }, str(storage_dir))


RECS = [{
    "skill": "doubt-driven-development", "action": "add_substep",
    "target": "challenges", "suggestion": "add a contrarian pass", "priority": "high",
}]


class TestBlockHelper:
    """The shared helper is the unit under test; the nodes just call it."""

    def test_absent_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path / "nope")})(),
        })())
        assert rec_mod.skill_recommendations_block() == ""

    def test_present_recs_returns_block(self, tmp_path, monkeypatch):
        _write_recs(tmp_path, RECS)
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path)})(),
        })())
        block = rec_mod.skill_recommendations_block()
        assert "SKILL RECOMMENDATIONS" in block
        assert "doubt-driven-development" in block
        assert "contrarian pass" in block


class TestDiscoverInjection:
    """_generate_requirement_via_fabric appends the block to fabric_prompt."""

    def _capture(self, monkeypatch):
        captured = {}

        def fake_invoke_skill(content, task, context, llm=None, **kw):
            captured["task"] = task
            return "# Report\nbody"

        monkeypatch.setattr(discover, "invoke_skill", fake_invoke_skill)
        monkeypatch.setattr(discover, "build_skill_registry", lambda *a, **k: {
            "fabric-prompts": {"content": "fabric skill body"},
            "coding-principles": {},  # skip the principles sub-call
        })
        return captured

    def test_prompt_carries_block_when_recs_present(self, tmp_path, monkeypatch):
        _write_recs(tmp_path, RECS)
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path)})(),
        })())
        captured = self._capture(monkeypatch)
        discover._generate_requirement_via_fabric(
            "p", "d", "interview notes", {}, "folder", state={},
        )
        assert "SKILL RECOMMENDATIONS" in captured["task"]
        assert "doubt-driven-development" in captured["task"]

    def test_prompt_byte_identical_when_absent(self, tmp_path, monkeypatch):
        """No file → no SKILL RECOMMENDATIONS marker in the prompt."""
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path / "empty")})(),
        })())
        captured = self._capture(monkeypatch)
        discover._generate_requirement_via_fabric(
            "p", "d", "interview notes", {}, "folder", state={},
        )
        assert "SKILL RECOMMENDATIONS" not in captured["task"]


class TestDefineInjection:
    """_arckit_advisory_context appends the block (covers both parallel prompts)."""

    def _state(self):
        return {"artifacts": {}}

    def test_block_present_when_recs_exist(self, tmp_path, monkeypatch):
        _write_recs(tmp_path, RECS)
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path)})(),
        })())
        out = define._arckit_advisory_context(self._state())
        assert "SKILL RECOMMENDATIONS" in out
        assert "doubt-driven-development" in out

    def test_byte_identical_when_absent(self, tmp_path, monkeypatch):
        """No ArcKit keys + no recs file → helper returns '' (pre-feature behavior)."""
        monkeypatch.setattr(rec_mod, "config", type("C", (), {
            "paths": type("P", (), {"storage_dir": str(tmp_path / "empty")})(),
        })())
        out = define._arckit_advisory_context(self._state())
        assert out == ""
