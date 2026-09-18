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


@pytest.mark.parametrize("bad_name", ["", "7bad", "-leading", "a b", "x/y", "trailing-", "UPPER"])
def test_register_skill_rejects_bad_names(bad_name, skills_dir):
    """UAT Finding 5: skill names must start with an ASCII letter and may
    only contain letters, digits, '-', '_' — so '7bad', '-leading', spaces,
    '/', trailing hyphens and uppercase are all rejected.
    """
    with pytest.raises(skill_manager.SkillRegistrationError, match="Invalid skill name"):
        skill_manager.register_skill(bad_name, "# x\n")


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


def test_update_skill_pull_path_advances_cached_shallow_clone(tmp_path):
    """Regression: a second update (cache already cloned) must pick up new upstream content.

    _git_clone_or_pull's pull path runs ``fetch --depth 1 origin <ref>``; on a
    cached shallow clone fetch rewrites the origin/<ref> ref while the local
    <ref> branch diverges, so any command that only resolves the local branch
    (e.g. `checkout <ref>`) leaves the working tree on stale content (UAT
    Finding 1, 2026-09-18).

    Uses a REAL local git repo (no monkeypatching of the git commands) so the
    test exercises actual shallow-clone semantics.
    """
    import subprocess

    # Upstream source repo at v1.0.0 (a single commit on main).
    srcrepo = tmp_path / "srcrepo"
    skill_md = srcrepo / "skills" / "alpha" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("---\nname: alpha\ndescription: alpha v1\nversion: 1.0.0\n---\n# v1\n")

    def _commit(msg: str) -> None:
        subprocess.run(["git", "add", "skills"], cwd=srcrepo, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", msg],
                       cwd=srcrepo, check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=srcrepo, check=True, capture_output=True)
    _commit("v1")

    # Isolated skills dir + cache dir (never touch the repo's skills/ or /app/.skill_cache).
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    from config.loader import config as cfg
    import tools.skill_manager as sm
    old_registry, old_sources, old_cache = (
        cfg.workflow.skill_registry_path, cfg.Skills.skill_sources_path, sm._cache_dir
    )
    cfg.workflow.skill_registry_path = str(skills_dir)
    cfg.Skills.skill_sources_path = str(tmp_path / "skill_sources.yaml")
    (tmp_path / "skill_sources.yaml").write_text(
        "sources:\n"
        f"  - name: local-upstream\n    repo: {srcrepo}\n    ref: main\n    skills:\n      - alpha\n"
    )
    sm._cache_dir = lambda: tmp_path / "skill_cache"
    try:
        # First update = clone path: sees the only commit (v1.0.0).
        entry1 = sm.update_skill("alpha")
        assert entry1["version"] == "1.0.0"

        # Bump the upstream to v2.0.0 while the cache clone is at v1.
        skill_md.write_text("---\nname: alpha\ndescription: alpha v2\nversion: 2.0.0\n---\n# v2\n")
        _commit("v2")

        # Second update = pull path: must see v2.0.0, not the stale v1.0.0.
        entry2 = sm.update_skill("alpha")
        assert entry2["version"] == "2.0.0", (
            f"pull path served stale content: expected 2.0.0, got {entry2['version']}"
        )
        assert (skills_dir / "alpha" / "SKILL.md").read_text().startswith(
            "---\nname: alpha\ndescription: alpha v2"
        )
    finally:
        cfg.workflow.skill_registry_path = old_registry
        cfg.Skills.skill_sources_path = old_sources
        sm._cache_dir = old_cache


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
