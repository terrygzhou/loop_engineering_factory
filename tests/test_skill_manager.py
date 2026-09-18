"""Unit tests for tools/skill_manager.py.

Git is monkeypatched so tests never hit the network.
"""

import pytest

from config.loader import config

from tools import skill_manager


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    """Point the manager at an isolated skills dir and seed a fake skill."""
    d = tmp_path / "skills"
    (d / "alpha" / "SKILL.md").parent.mkdir(parents=True)
    (d / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: 'alpha skill'\nversion: 1.0.0\n---\n\n# Alpha\n"
    )
    (d / "beta" / "SKILL.md").parent.mkdir(parents=True)
    (d / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: 'beta skill'\nversion: 1.0.0\n---\n\n# Beta\n"
    )
    monkeypatch.setattr(config.workflow, "skill_registry_path", str(d))
    return d


def test_list_skills_returns_all(skills_dir):
    skills = skill_manager.list_skills()
    names = {s["name"] for s in skills}
    assert "alpha" in names
    assert "beta" in names
    for s in skills:
        assert s["path"].endswith("SKILL.md")
    assert all("active_in_graph" in s for s in skills)
    assert all("triggers" in s for s in skills)
    assert all("category" in s for s in skills)


def test_register_skill_creates_file(skills_dir, monkeypatch):
    entry = skill_manager.register_skill(
        "gamma",
        "---\nname: gamma\ndescription: 'gamma skill'\nversion: 1.0.0\n---\n\n# Gamma\n",
    )
    assert entry["name"] == "gamma"
    assert (skills_dir / "gamma" / "SKILL.md").exists()
    # A fresh build_skill_registry call MUST include the new skill — the
    # refresh must defeat the loader's non-empty-cache short-circuit.
    import tools.loader as loader
    loader.build_skill_registry(str(skills_dir))  # populate cache
    monkeypatch.setattr(loader, "load_skills", lambda *a, **k: [])
    rebuilt = loader.build_skill_registry(str(skills_dir))
    assert "gamma" in rebuilt


def test_register_skill_rejects_missing_frontmatter_name(skills_dir):
    with pytest.raises(skill_manager.SkillRegistrationError):
        skill_manager.register_skill("gamma", "# No frontmatter\n")
    assert not (skills_dir / "gamma").exists()


def test_register_skill_rejects_blank_content(skills_dir):
    with pytest.raises(skill_manager.SkillRegistrationError):
        skill_manager.register_skill("gamma", "")
    assert not (skills_dir / "gamma").exists()


def test_remove_skill_removes_directory(skills_dir, monkeypatch):
    import tools.loader as loader

    loader.build_skill_registry(str(skills_dir))  # populate cache
    assert skill_manager.remove_skill("alpha") is True
    assert not (skills_dir / "alpha").exists()
    # A fresh build_skill_registry call must no longer see "alpha".
    monkeypatch.setattr(loader, "load_skills", lambda *a, **k: [])
    rebuilt = loader.build_skill_registry(str(skills_dir))
    assert "alpha" not in rebuilt


def test_remove_skill_missing_returns_false(skills_dir):
    assert skill_manager.remove_skill("nope") is False


def test_update_skill_pulls_from_source(skills_dir, monkeypatch):
    """update_skill clones/pulls from a configured source and overwrites the SKILL.md.

    Uses an inline source listing "alpha" (the real config/skill_sources.yaml
    lists the 22 agent-skills upstream skills, not the fixture skill "alpha"),
    and a tmp cache dir so .skill_cache/ is never created inside the repo.
    """
    monkeypatch.setattr(skill_manager, "_load_sources", lambda: [
        {
            "name": "agent-skills",
            "repo": "https://github.com/addyosmani/agent-skills.git",
            "ref": "main",
            "skills": ["alpha", "beta"],
        }
    ])
    monkeypatch.setattr(skill_manager, "_cache_dir", lambda: skills_dir.parent / "cache")

    def fake_git(repo, ref, dest):
        # Simulate the effect of a successful clone/pull: the skill is present
        # under dest/skills/<name>/SKILL.md.
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "skills" / "alpha" / "SKILL.md").parent.mkdir(parents=True)
        (dest / "skills" / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: 'updated alpha'\nversion: 2.0.0\n---\n\n# Alpha v2\n"
        )

    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)
    entry = skill_manager.update_skill("alpha", source="agent-skills", ref="main")
    assert entry["version"] == "2.0.0"
    assert (skills_dir / "alpha" / "SKILL.md").read_text().startswith(
        "---\nname: alpha\ndescription: 'updated alpha'"
    )
    # The cache dir is the sibling of the skills dir (never inside it).
    assert not (skills_dir / ".skill_cache").exists()


def test_update_skill_unknown_skill_raises(skills_dir, monkeypatch):
    """No configured source provides the skill -> SkillUpdateError."""
    monkeypatch.setattr(skill_manager, "_load_sources", lambda: [
        {"name": "agent-skills", "repo": "https://github.com/addyosmani/agent-skills.git",
         "ref": "main", "skills": ["alpha", "beta"]},
    ])
    monkeypatch.setattr(
        skill_manager, "_git_clone_or_pull", lambda repo, ref, dest: dest.mkdir(parents=True, exist_ok=True)
    )
    with pytest.raises(skill_manager.SkillUpdateError, match="No source provides skill 'ghost'"):
        skill_manager.update_skill("ghost", source="agent-skills")


def test_sync_isolated_failure(skills_dir, monkeypatch):
    """A failure on one skill never aborts the remaining skills."""
    # Simulate the effect of a successful clone: the repo's skills/ subtree
    # holds alpha and beta but not ghost.
    def fake_git(repo, ref, dest):
        dest.mkdir(parents=True, exist_ok=True)
        for skill_name in ("alpha", "beta"):
            (dest / "skills" / skill_name / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
            (dest / "skills" / skill_name / "SKILL.md").write_text(
                f"---\nname: {skill_name}\ndescription: 'updated {skill_name}'\n"
                f"version: 2.0.0\n---\n\n# {skill_name} v2\n"
            )

    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)
    monkeypatch.setattr(
        skill_manager,
        "_load_sources",
        lambda: [
            {
                "name": "agent-skills",
                "repo": "https://github.com/addyosmani/agent-skills.git",
                "ref": "main",
                "skills": ["alpha", "beta", "ghost"],
            }
        ],
    )
    results = skill_manager.sync_from_sources()
    by_name = {r["name"]: r for r in results}
    assert by_name["alpha"]["status"].startswith("updated")
    assert by_name["beta"]["status"].startswith("updated")
    assert by_name["ghost"]["status"].startswith("error:")
    assert all(set(r) == {"name", "source", "ref", "status"} for r in results)
