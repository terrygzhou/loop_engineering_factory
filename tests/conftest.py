"""Shared test fixtures — mock only external/unavailable deps.

INTERNAL modules (graph/*, config/*, service/*, tools/*, feedback/*)
are NOT pre-mocked. Tests import real code and patch specific calls
as needed.

Only mock what cannot be installed: phoenix, chromadb, and LLM endpoints.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Mock external deps that are not installed in test env ──

# Phoenix SDK — optional for evals
_mock_phoenix = MagicMock()
sys.modules["phoenix"] = _mock_phoenix
sys.modules["phoenix.trace_eval"] = MagicMock()

# ChromaDB — external vector DB
_mock_chroma = MagicMock()
sys.modules["chromadb"] = _mock_chroma
sys.modules["chromadb.ClientAPI"] = MagicMock()
sys.modules["chromadb.config"] = MagicMock()

# ── Pytest fixtures ──

@pytest.fixture(autouse=True)
def mock_langgraph_stream_writer():
    """Patch get_stream_writer so node helpers work standalone."""
    with patch("langgraph.config.get_stream_writer", return_value=lambda *a, **kw: None):
        yield


@pytest.fixture(autouse=True)
def mock_time():
    """Fix time.time() for deterministic testing."""
    with patch("time.time", return_value=1000000000.0):
        yield


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with a sample file."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hello')")
    return tmp_path


@pytest.fixture
def mock_skill_registry(monkeypatch):
    """Provide a mock skill registry."""
    registry = {
        "fabric-prompts": {"content": "# fabric\nGenerate spec"},
        "coding-principles": {"content": "# principles"},
        "spec-driven-development": {"content": "# spec"},
        "api-and-interface-design": {"content": "# api"},
        "observability-and-instrumentation": {"content": "# observability"},
        "shipping-and-launch": {"content": "# shipping"},
    }
    monkeypatch.setattr("tools.loader.build_skill_registry", lambda *a, **kw: registry)
    return registry


@pytest.fixture
def mock_invoke_skill(monkeypatch):
    """Mock invoke_skill to return structured output."""
    def _invoke(skill_content, prompt, ctx, llm=None):
        project_name = "TestProject"
        for part in [prompt, ctx, skill_content]:
            if part and "Project:" in part:
                project_name = part.split("Project:")[1].split("\n")[0].strip()
                break
        return f"# {project_name}\n\n## Spec\nGenerated.\n\n## API\n- GET /api/items\n"
    monkeypatch.setattr("tools.llm.invoke_skill", _invoke)
    return _invoke


@pytest.fixture
def mock_project_path(monkeypatch, tmp_path):
    """Make config paths point to tmp_path."""
    monkeypatch.setattr(
        "config.loader.config.paths",
        type("Paths", (), {
            "project_path": str(tmp_path / "projects"),
            "build_dir": str(tmp_path / "builds"),
            "storage_dir": str(tmp_path / "storage"),
            "project_name": "test-project",
            "project_path_template": "{{project_name}}",
            "workspace_dir": str(tmp_path),
            "skills_dir": "skills",
            "guardrails_path": str(Path(__file__).parent.parent / "config/guardrails.yaml"),
            "prompt_log_dir": str(tmp_path / "prompt_logs"),
        })(),
    )
    return tmp_path
