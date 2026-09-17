"""Tests for config/loader.py — env var > config.yaml > default resolution."""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestResolve:
    """Test _resolve function: env var > config > default."""

    def test_env_var_wins(self):
        from config.loader import _resolve
        with patch("os.getenv", return_value="http://env:9999"):
            result = _resolve("MY_VAR", {"key": "yaml_val"}, "key", "default_val")
            assert result == "http://env:9999"

    def test_config_wins_over_default(self):
        from config.loader import _resolve
        with patch("os.getenv", return_value=None):
            result = _resolve(None, {"key": "yaml_val"}, "key", "default_val")
            assert result == "yaml_val"

    def test_default_when_nothing(self):
        from config.loader import _resolve
        with patch("os.getenv", return_value=None):
            result = _resolve("NO_VAR", {}, "key", "default_val")
            assert result == "default_val"

    def test_nested_key_path(self):
        from config.loader import _resolve
        cfg = {"services": {"llm": {"base_url": "http://nested:8080"}}}
        with patch("os.getenv", return_value=None):
            result = _resolve(None, cfg, "services.llm.base_url", "default")
            assert result == "http://nested:8080"

    def test_nested_key_missing(self):
        from config.loader import _resolve
        with patch("os.getenv", return_value=None):
            result = _resolve(None, {}, "services.missing.key", "default")
            assert result == "default"

    def test_empty_env_var_falls_through(self):
        from config.loader import _resolve
        with patch("os.getenv", return_value=""):
            result = _resolve("MY_VAR", {"key": "yaml_val"}, "key", "default_val")
            assert result == "yaml_val"


class TestLoadYaml:
    """Test _load_yaml helper."""

    def test_load_existing_file(self, tmp_path):
        from config.loader import _load_yaml
        f = tmp_path / "test.yaml"
        f.write_text("key: value\nnum: 42\n")
        result = _load_yaml(str(f))
        assert result == {"key": "value", "num": 42}

    def test_missing_file_returns_empty(self):
        from config.loader import _load_yaml
        result = _load_yaml("/nonexistent/file.yaml")
        assert result == {}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        from config.loader import _load_yaml
        f = tmp_path / "bad.yaml"
        f.write_text("{{{{invalid yaml:::\n")
        result = _load_yaml(str(f))
        assert result == {}


class TestSaveYaml:
    """Test _save_yaml helper."""

    def test_save_and_read_back(self, tmp_path):
        from config.loader import _save_yaml, _load_yaml
        path = str(tmp_path / "saved.yaml")
        data = {"key": "value", "nested": {"a": 1}}
        _save_yaml(path, data)
        result = _load_yaml(path)
        assert result == data

    def test_creates_parent_dirs(self, tmp_path):
        from config.loader import _save_yaml
        path = str(tmp_path / "deep" / "nested" / "file.yaml")
        _save_yaml(path, {"x": 1})
        assert Path(path).exists()


class TestConfigObject:
    """Test Config class defaults and methods."""

    def test_defaults(self):
        from config.loader import Config
        cfg = Config()
        assert isinstance(cfg.paths.project_name, str)
        assert isinstance(cfg.services.llm.base_url, str)
        assert isinstance(cfg.workflow.max_retries, int)

    def test_set_project_name_valid(self, tmp_path):
        from config.loader import Config
        cfg = Config()
        cfg.set_project_name("test-proj-123")
        assert cfg.paths.project_name == "test-proj-123"

    def test_set_project_name_invalid(self):
        from config.loader import Config
        cfg = Config()
        try:
            cfg.set_project_name("invalid name with spaces!")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_set_project_name_rejects_container_path(self):
        from config.loader import Config
        cfg = Config()
        try:
            cfg.set_project_name("/var/lib/docker/bad")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_reset_paths(self):
        from config.loader import Config
        cfg = Config()
        cfg.reset_paths("new-proj")
        assert cfg.paths.project_name == "new-proj"
        assert cfg.paths.project_path_template == "{{project_name}}"

    def test_env_var_override_llm(self):
        from config.loader import _resolve
        with patch("os.getenv") as mock_get:
            mock_get.side_effect = lambda k: {"LLM_BASE_URL": "http://custom:9999"}.get(k)
            result = _resolve("LLM_BASE_URL", {}, "services.llm.base_url", "default")
            assert result == "http://custom:9999"


class TestConfigSingleton:
    """Test the module-level config singleton."""

    def test_config_exists(self):
        from config.loader import config
        assert config is not None
        assert hasattr(config, "paths")
        assert hasattr(config, "services")
        assert hasattr(config, "workflow")

    def test_services_llm_attributes(self):
        from config.loader import config
        assert isinstance(config.services.llm.base_url, str)
        assert isinstance(config.services.llm.model, str)
        assert isinstance(config.services.llm.temperature, float)
        assert isinstance(config.services.llm.max_tokens, int)

    def test_services_chroma(self):
        from config.loader import config
        assert isinstance(config.services.chroma.url, str)
        assert isinstance(config.services.chroma.port, int)
