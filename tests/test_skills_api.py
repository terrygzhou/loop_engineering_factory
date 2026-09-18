"""FastAPI endpoint tests for the skill-management API (/api/skills*).

Uses the existing app module; the skill_manager functions are monkeypatched
so no filesystem or git is touched.
"""

import json
import pytest

from fastapi.testclient import TestClient

import frontend.backend.app as app_module


@pytest.fixture
def client(monkeypatch):
    """TestClient for the FastAPI app with skill_manager functions monkeypatched."""
    monkeypatch.setattr(
        "tools.skill_manager.list_skills",
        lambda: [
            {
                "name": "alpha",
                "version": "1.0.0",
                "path": "/x/skills/alpha/SKILL.md",
                "description": "alpha",
                "triggers": [],
                "category": "",
                "active_in_graph": True,
            }
        ],
    )
    monkeypatch.setattr(
        "tools.skill_manager.register_skill",
        lambda name, content, source="manual": {"name": name, "version": "1.0.0"},
    )
    monkeypatch.setattr("tools.skill_manager.remove_skill", lambda name: True)
    monkeypatch.setattr(
        "tools.skill_manager.update_skill",
        lambda name, source=None, ref=None: {"name": name, "version": "2.0.0"},
    )
    monkeypatch.setattr(
        "tools.skill_manager.sync_from_sources",
        lambda: [
            {
                "name": "alpha",
                "source": "agent-skills",
                "ref": "main",
                "status": "updated (v2.0.0)",
            }
        ],
    )
    return TestClient(app_module.app)


def test_list_skills(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    assert [s["name"] for s in r.json()["skills"]] == ["alpha"]


def test_register_skill(client):
    r = client.post(
        "/api/skills/register",
        json={"name": "gamma", "content": "---\nname: gamma\n---\nbody"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "gamma"


def test_register_skill_malformed_400(monkeypatch):
    """Malformed SKILL.md → 400 (SkillRegistrationError), not 500."""
    from tools.skill_manager import SkillRegistrationError

    monkeypatch.setattr(
        "tools.skill_manager.register_skill",
        lambda name, content, source="manual": (_ for _ in ()).throw(
            SkillRegistrationError("no frontmatter name")
        ),
    )
    r = TestClient(app_module.app).post(
        "/api/skills/register", json={"name": "x", "content": "no fm"}
    )
    assert r.status_code == 400


def test_remove_skill(client):
    r = client.post("/api/skills/remove", json={"name": "alpha"})
    assert r.status_code == 200
    assert r.json()["removed"] is True


def test_update_skill(client):
    r = client.post(
        "/api/skills/update", json={"name": "alpha", "source": "agent-skills"}
    )
    assert r.status_code == 200
    assert r.json()["version"] == "2.0.0"


def test_update_skill_error_400(monkeypatch):
    """SkillUpdateError → 400, not 500."""
    from tools.skill_manager import SkillUpdateError

    monkeypatch.setattr(
        "tools.skill_manager.update_skill",
        lambda name, source=None, ref=None: (_ for _ in ()).throw(
            SkillUpdateError("no source provides skill")
        ),
    )
    r = TestClient(app_module.app).post("/api/skills/update", json={"name": "alpha"})
    assert r.status_code == 400


def test_sync(client):
    r = client.post("/api/skills/sync")
    assert r.status_code == 200
    assert r.json()["results"][0]["status"].startswith("updated")


def test_recommendations_absent_file(client, tmp_path, monkeypatch):
    """GET /api/skills/recommendations returns [] when the file does not exist."""
    import config.loader as cl

    monkeypatch.setattr(cl.config.paths, "storage_dir", str(tmp_path))
    r = client.get("/api/skills/recommendations")
    assert r.status_code == 200
    assert r.json() == {"recommendations": []}


def test_recommendations_present_file(client, tmp_path, monkeypatch):
    """A persisted review file is unwrapped to its top-level dict shape."""
    import config.loader as cl

    monkeypatch.setattr(cl.config.paths, "storage_dir", str(tmp_path))
    (tmp_path / "skill_recommendations.json").write_text(
        json.dumps(
            {
                "cycle_id": "c-1",
                "verdicts": [{"skill": "x", "verdict": "improve"}],
                "recommendations": [{"skill": "x", "action": "rewrite_section"}],
            }
        )
    )
    r = client.get("/api/skills/recommendations")
    assert r.status_code == 200
    assert r.json()["recommendations"][0]["action"] == "rewrite_section"
