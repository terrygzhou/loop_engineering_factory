"""Gap tests for tools/skill_manager.py — GitHub source update/sync paths (S2).

Covers the concrete agent-skills source shape from config/skill_sources.yaml:
- update_skill with source=None picks the first source listing the skill
- ref override propagates to _git_clone_or_pull
- unknown skill / missing source name -> SkillUpdateError
- empty / absent sources file -> SkillUpdateError
- _git_clone_or_pull failure (clone and pull paths) -> SkillUpdateError
- sync_from_sources with skills: null enumerates the cloned repo's skills/
- sync with multiple sources: one source's git failure never aborts the others

Git is monkeypatched so tests never hit the network.
"""

from pathlib import Path

import pytest

from config.loader import config

from tools import skill_manager


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(config.workflow, "skill_registry_path", str(d))
    monkeypatch.setattr(config.Skills, "skill_sources_path", str(tmp_path / "skill_sources.yaml"))
    return d


def _git_probe(repo, ref, dest):
    """A _git_clone_or_pull fake that records calls and simulates a clone."""
    calls = []

    def fake_git(repo, ref, dest):
        calls.append((repo, ref, dest))
        dest.mkdir(parents=True, exist_ok=True)
        for skill in ("alpha", "beta"):
            f = dest / "skills" / skill / "SKILL.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(
                f"---\nname: {skill}\ndescription: '{skill}'\nversion: 2.0.0\n---\n\n# {skill}\n"
            )

    return fake_git, calls


SOURCES_YAML = """\
sources:
  - name: agent-skills
    repo: https://github.com/addyosmani/agent-skills.git
    ref: main
    skills:
      - alpha
      - beta
"""


def test_update_skill_source_none_picks_first_listed(skills_dir, monkeypatch):
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(SOURCES_YAML)
    fake_git, calls = _git_probe(None, None, None)
    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)

    entry = skill_manager.update_skill("alpha")
    assert entry["version"] == "2.0.0"
    # Chose the agent-skills source (only one listing the skill) at its ref.
    assert calls[0][:2] == ("https://github.com/addyosmani/agent-skills.git", "main")


def test_update_skill_ref_override(skills_dir, monkeypatch):
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(SOURCES_YAML)
    fake_git, calls = _git_probe(None, None, None)
    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)

    skill_manager.update_skill("alpha", source="agent-skills", ref="v1.4.0")
    assert calls[0][:2] == ("https://github.com/addyosmani/agent-skills.git", "v1.4.0")


def test_update_skill_source_not_in_config_raises(skills_dir, monkeypatch):
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(SOURCES_YAML)
    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", lambda *a: None)
    with pytest.raises(skill_manager.SkillUpdateError, match="No source provides skill"):
        skill_manager.update_skill("alpha", source="nope")


def test_update_skill_skill_not_listed_in_source_raises(skills_dir, monkeypatch):
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(SOURCES_YAML)
    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", lambda *a: None)
    # 'gamma' is not in agent-skills' skills list -> no source provides it.
    with pytest.raises(skill_manager.SkillUpdateError, match="No source provides skill 'gamma'"):
        skill_manager.update_skill("gamma", source="agent-skills")


def test_update_skill_empty_sources_file_raises(skills_dir, monkeypatch):
    (Path(skills_dir).parent / "skill_sources.yaml").write_text("sources: []\n")
    with pytest.raises(skill_manager.SkillUpdateError, match="No skill sources configured"):
        skill_manager.update_skill("alpha")


def test_update_skill_absent_sources_file_raises(skills_dir, monkeypatch):
    # Fixture points at a skill_sources.yaml that was never written.
    with pytest.raises(skill_manager.SkillUpdateError, match="No skill sources configured"):
        skill_manager.update_skill("alpha")


def test_git_clone_failure_raises_skill_update_error(skills_dir, monkeypatch, tmp_path):
    """_git_clone_or_pull: clone path subprocess failure -> SkillUpdateError."""
    import subprocess

    dest = tmp_path / "cache"  # absent -> clone path
    real_run = subprocess.run

    def broken_run(cmd, *a, **k):
        # cmd is a list (subprocess.run is called without shell=True).
        if "clone" in cmd:
            raise subprocess.CalledProcessError(128, cmd)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", broken_run)
    for repo, ref in (("https://github.com/addyosmani/agent-skills.git", "main"),
                      ("https://github.com/addyosmani/agent-skills.git", "v1.4.0")):
        with pytest.raises(skill_manager.SkillUpdateError, match="git clone failed"):
            skill_manager._git_clone_or_pull(repo, ref, dest)


def test_git_clone_or_pull_missing_git_raises(skills_dir, monkeypatch, tmp_path):
    """_git_clone_or_pull: git binary absent (FileNotFoundError) -> SkillUpdateError."""
    import subprocess

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")))
    with pytest.raises(skill_manager.SkillUpdateError, match="git clone failed"):
        skill_manager._git_clone_or_pull(
            "https://github.com/addyosmani/agent-skills.git", "main", tmp_path / "cache"
        )


def test_git_pull_failure_raises_skill_update_error(skills_dir, monkeypatch, tmp_path):
    """_git_clone_or_pull: pull path (fetch on existing dest) -> SkillUpdateError."""
    import subprocess

    dest = tmp_path / "cache"
    dest.mkdir()
    real_run = subprocess.run

    def broken_run(cmd, *a, **k):
        # cmd is a list (subprocess.run is called without shell=True).
        if "fetch" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", broken_run)
    with pytest.raises(skill_manager.SkillUpdateError, match="git pull failed"):
        skill_manager._git_clone_or_pull(
            "https://github.com/addyosmani/agent-skills.git", "main", dest
        )


def test_sync_null_skills_lists_cloned_repo_skills(skills_dir, monkeypatch):
    """skills: null = enumerate the cloned repo's skills/ subtree."""
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(
        "sources:\n"
        "  - name: agent-skills\n"
        "    repo: https://github.com/addyosmani/agent-skills.git\n"
        "    ref: main\n"
        "    skills: null\n"
    )
    # Simulate a clone that yields two skill dirs under dest/skills/.
    def fake_git(repo, ref, dest):
        for skill in ("alpha", "beta"):
            f = dest / "skills" / skill / "SKILL.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(
                f"---\nname: {skill}\ndescription: '{skill}'\nversion: 2.0.0\n---\n\n# {skill}\n"
            )

    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)
    results = skill_manager.sync_from_sources()
    by_name = {r["name"]: r for r in results}
    assert set(by_name) == {"alpha", "beta"}
    for r in results:
        assert r["status"].startswith("updated")
        assert r["source"] == "agent-skills"
        assert r["ref"] == "main"


def test_sync_multi_source_isolated_git_failure(skills_dir, monkeypatch, tmp_path):
    """A source whose git clone fails yields error rows; other sources still sync."""
    (Path(skills_dir).parent / "skill_sources.yaml").write_text(
        "sources:\n"
        "  - name: agent-skills\n"
        "    repo: https://github.com/addyosmani/agent-skills.git\n"
        "    ref: main\n"
        "    skills:\n"
        "      - alpha\n"
        "      - beta\n"
        "  - name: upstream-skill-src\n"
        "    repo: https://example.com/other-skills.git\n"
        "    ref: main\n"
        "    skills:\n"
        "      - gamma\n"
    )

    def fake_git(repo, ref, dest):
        if "addyosmani" in repo:
            for skill in ("alpha", "beta"):
                f = dest / "skills" / skill / "SKILL.md"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(
                    f"---\nname: {skill}\ndescription: '{skill}'\nversion: 2.0.0\n---\n\n# {skill}\n"
                )
        else:
            raise skill_manager.SkillUpdateError(f"git clone failed for {repo}@{ref}")

    monkeypatch.setattr(skill_manager, "_git_clone_or_pull", fake_git)
    results = skill_manager.sync_from_sources()
    by_name = {r["name"]: r for r in results}
    assert by_name["alpha"]["status"].startswith("updated")
    assert by_name["beta"]["status"].startswith("updated")
    assert by_name["gamma"]["status"].startswith("error:")
    # Every row has the documented key set.
    assert all(set(r) == {"name", "source", "ref", "status"} for r in results)
