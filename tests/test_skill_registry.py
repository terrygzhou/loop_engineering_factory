from config.loader import config

from tools.loader import build_skill_registry


def test_pre_commit_review_present_and_old_name_absent():
    registry = build_skill_registry()
    assert "pre-commit-review" in registry
    assert "requesting-code-review" not in registry


def test_code_review_and_quality_merged_away():
    registry = build_skill_registry()
    assert "code-review-and-quality" not in registry
    assert "pre-commit-review" in registry


def test_skills_index_written_under_configured_registry_path(tmp_path, monkeypatch):
    """Regression (UAT Finding 4): SKILLS_INDEX.json must land under the
    *configured* skill_registry_path, not the module-level LOCAL_SKILLS_DIR
    (which is the repo's skills/ on host and /app/skills in the container).
    """
    import json

    d = tmp_path / "alt_skills"
    (d / "alpha" / "SKILL.md").parent.mkdir(parents=True)
    (d / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: 'alpha skill'\nversion: 1.0.0\n---\n\n# Alpha\n"
    )
    monkeypatch.setattr(config.workflow, "skill_registry_path", str(d))

    # Build from the configured dir so _save_skills_index runs; the tmp dir's
    # newer mtimes trigger a natural cache rebuild, no cache reset needed.
    registry = build_skill_registry(str(d))
    assert "alpha" in registry

    idx = d / "SKILLS_INDEX.json"
    assert idx.exists(), "SKILLS_INDEX.json was not written under the configured registry path"
    data = json.loads(idx.read_text())
    assert "alpha" in data
    assert data["alpha"]["version"] == "1.0.0"


