import pytest
from config.loader import config

from tools.loader import LOCAL_SKILLS_DIR, build_skill_registry


@pytest.fixture()
def fresh_local_registry():
    """Reset the module-level registry cache so a local-dir build never
    returns a registry populated from a different (e.g. tmp) skills dir.
    """
    import tools.loader as loader

    orig_registry, orig_mtime = loader._registry, loader._registry_mtime
    loader._registry, loader._registry_mtime = {}, 0.0
    try:
        yield
    finally:
        loader._registry, loader._registry_mtime = orig_registry, orig_mtime


def test_pre_commit_review_present_and_old_name_absent(fresh_local_registry):
    # Pass the repo's LOCAL_SKILLS_DIR explicitly so the test exercises the
    # actual on-disk skill set, not the configured skill_registry_path
    # (/app/skills in the container, nonexistent on a normal host).
    registry = build_skill_registry(str(LOCAL_SKILLS_DIR))
    assert "pre-commit-review" in registry
    assert "requesting-code-review" not in registry


def test_code_review_and_quality_merged_away(fresh_local_registry):
    registry = build_skill_registry(str(LOCAL_SKILLS_DIR))
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


