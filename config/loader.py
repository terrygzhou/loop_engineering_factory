"""
Configuration loader for Loop Engineering.

Resolution order for every setting:
  1. Environment variable (highest priority)
  2. config/config.yaml
  3. Built-in default (lowest priority)

Usage:
    from config.loader import config
    llm_base = config.services.llm.base_url
    chroma_url = config.services.chroma.url
"""
import os
from pathlib import Path
from typing import Any, Dict

import yaml


# ── Base directory: loop engineering codebase root (current folder) ──
_codebase_root = str(Path(__file__).resolve().parent.parent)


def _load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML config file. Returns {} on missing/invalid."""
    p = Path(path)
    if p.exists():
        try:
            return yaml.safe_load(p.read_text()) or {}
        except Exception:
            pass
    return {}


def _resolve(env_var: str | None, config: Dict[str, Any], key_path: str, default: str) -> str:
    """Resolve a setting: env var > config dict (nested key) > default."""
    if env_var:
        env_val = os.getenv(env_var)
        if env_val:
            return env_val
    # Walk nested keys
    val = config
    for k in key_path.split("."):
        if isinstance(val, dict):
            val = val.get(k)
        else:
            val = None
            break
    if val is not None:
        return str(val)
    return default


def _save_yaml(path: str, data: Dict[str, Any]):
    """Write config dict back to YAML file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# ── Load config file ──────────────────────────────────────────────
_config_path = Path(__file__).resolve().parent / "config.yaml"
if not _config_path.exists():
    _config_path = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
_config = _load_yaml(str(_config_path))


# ── Resolved values ───────────────────────────────────────────────
class Config:
    """Config object. Read attributes directly."""

    class Paths:
        project_name: str = _resolve(None, _config, "paths.project_name", "loop_project")
        project_path_template: str = _resolve(None, _config, "paths.project_path", "{{project_name}}")
        skills_dir: str = _resolve("SKILLS_DIR", _config, "paths.skills_dir", "skills")
        storage_dir: str = _resolve("STORAGE_DIR", _config, "paths.storage_dir", "./storage")
        guardrails_path: str = _resolve("GUARDRAILS_PATH", _config, "paths.guardrails_path", "./config/guardrails.yaml")
        build_dir: str = _resolve("BUILD_DIR", _config, "paths.build_dir", "/app/build")
        workspace_dir: str = _resolve("WORKSPACE_DIR", _config, "paths.workspace_dir", "./output")
        output_subdir: str = _resolve("OUTPUT_SUBDIR", _config, "paths.output_subdir", "output")
        output_dir: str = _resolve("OUTPUT_DIR", _config, "paths.output_dir", "/app/output")
        prompt_log_dir: str = _resolve("PROMPT_LOG_DIR", _config, "paths.prompt_log_dir", "build/prompt_logs")

        @property
        def project_path(self) -> str:
            env_override = os.getenv("PROJECT_PATH")
            if env_override:
                return env_override
            template = self.project_path_template
            if "{{project_name}}" in template:
                return os.path.join(os.path.expanduser(self.workspace_dir), self.project_name)
            return template

    class Services:
        class LLM:
            base_url: str = _resolve("LLM_BASE_URL", _config, "services.llm.base_url", "http://pop-os:8080/v1")
            model: str = _resolve("LLM_MODEL", _config, "services.llm.model", "Qwen3.6-27B")
            api_key: str = _resolve("OPENAI_API_KEY", _config, "services.llm.api_key", "not-needed")
            temperature: float = float(_resolve("LLM_TEMPERATURE", _config, "services.llm.temperature", "0.1"))
            max_tokens: int = int(_resolve("LLM_MAX_TOKENS", _config, "services.llm.max_tokens", "32768"))

        class Chroma:
            url: str = _resolve("CHROMA_URL", _config, "services.chroma.url", "http://chromadb:8000")
            port: int = int(_resolve(None, _config, "services.chroma.port", "8000"))

        class OTEL:
            endpoint: str = _resolve("OTEL_EXPORTER_OTLP_ENDPOINT", _config, "services.otel.endpoint", "http://otel-collector:4318/v1/traces")
            service_name: str = _resolve("OTEL_SERVICE_NAME", _config, "services.otel.service_name", "loop-orchestrator")
            exporter_port: int = int(_resolve(None, _config, "services.otel.exporter_port", "4318"))

        class Phoenix:
            host: str = _resolve(None, _config, "services.phoenix.host", "0.0.0.0")
            port: int = int(_resolve(None, _config, "services.phoenix.port", "6006"))
            database_uri: str = _resolve(None, _config, "services.phoenix.database_uri", "/var/lib/phoenix/phoenix.db")

        class Postgres:
            user: str = _resolve("POSTGRES_USER", _config, "services.postgres.user", "postgres")
            password: str = _resolve("POSTGRES_PASSWORD", _config, "services.postgres.password", "postgres")
            database: str = _resolve("POSTGRES_DB", _config, "services.postgres.database", "crm_dev")
            port: int = int(_resolve(None, _config, "services.postgres.port", "5432"))
            host: str = _resolve("POSTGRES_HOST", _config, "services.postgres.host", "localhost")

        class Grafana:
            host: str = _resolve(None, _config, "services.grafana.host", "0.0.0.0")
            port: int = int(_resolve(None, _config, "services.grafana.port", "3000"))

        class LoopAPI:
            url: str = _resolve("LOOP_API_URL", _config, "services.loop_api.url", "http://localhost:8011")
            port: int = int(_resolve(None, _config, "services.loop_api.port", "8011"))

        class Product:
            url: str = _resolve("PRODUCT_URL", _config, "services.product.url", "http://localhost:8010")
            port: int = int(_resolve(None, _config, "services.product.port", "8010"))

        class Observability:
            port: int = int(_resolve("OBSERVABILITY_PORT", _config, "observability.port", "8081"))

        class OpenHands:
            url: str = _resolve("OH_URL", _config, "openhands.url", "http://openhands:8000")
            secret_key: str = _resolve("OH_SECRET_KEY", _config, "openhands.secret_key", "changeme")
            workspace_path: str = _resolve("OH_WORKSPACE", _config, "openhands.workspace_path", "/opt/workspace_base/output")
            timeout: int = int(_resolve("OH_TIMEOUT", _config, "openhands.timeout", "3600"))
            poll_interval: int = int(_resolve(None, _config, "openhands.poll_interval", "5"))
            prompt_char_limit: int = int(_resolve(None, _config, "openhands.prompt_char_limit", "16000"))
            profile_name: str = _resolve(None, _config, "openhands.profile_name", "build_agent")

        llm = LLM()
        chroma = Chroma()
        otel = OTEL()
        phoenix = Phoenix()
        postgres = Postgres()
        grafana = Grafana()
        loop_api = LoopAPI()
        product = Product()
        observability = Observability()
        openhands = OpenHands()

    class Observability:
        prometheus_port: int = int(_resolve(None, _config, "observability.prometheus_port", "9090"))
        loki_port: int = int(_resolve(None, _config, "observability.loki_port", "3100"))
        port: int = int(_resolve("OBSERVABILITY_PORT", _config, "observability.port", "8081"))
        log_level: str = _resolve("LOG_LEVEL", _config, "observability.log_level", "INFO")

    class Workflow:
        hil_mode: str = _resolve("HIL_MODE", _config, "workflow.hil_mode", "auto")
        max_retries: int = int(_resolve(None, _config, "workflow.max_retries", "2"))
        auto_approve: bool = _resolve("AUTO_APPROVE", _config, "workflow.auto_approve", "false").lower() in ("true", "1", "yes")
        skill_registry_path: str = _resolve("SKILLS_DIR", _config, "workflow.skill_registry_path", "~/.hermes/skills")

    paths = Paths()
    services = Services()
    observability = Observability()
    workflow = Workflow()

    def set_project_name(self, name: str):
        """Update project name and persist to config.yaml."""
        import re
        if not name or not re.match(r'^[a-zA-Z0-9_-]+$', name):
            raise ValueError(f"Invalid project name: {name!r}")
        if name.startswith(("/var/lib/docker", "/app", "/container")):
            raise ValueError(f"Rejected container path in project name: {name!r}")

        self.paths.project_name = name
        self.paths.project_path_template = "{{project_name}}"
        workspace = _config.get("paths", {}).get("workspace_dir", "./output")
        _config["paths"] = {"project_name": name, "workspace_dir": workspace,
                            "project_path": "{{project_name}}",
                            "skills_dir": self.paths.skills_dir, "storage_dir": self.paths.storage_dir,
                            "guardrails_path": self.paths.guardrails_path}
        _config.setdefault("workflow", {})["hil_mode"] = self.workflow.hil_mode
        _config["workflow"]["max_retries"] = self.workflow.max_retries
        _config["workflow"]["auto_approve"] = self.workflow.auto_approve
        try:
            _save_yaml(str(_config_path), _config)
        except OSError:
            pass
        print(f"  ✓ config.yaml updated: project_name={name}, project_path={self.paths.project_path}")

    @staticmethod
    def reload():
        """Reload from disk."""
        global _config
        _config = _load_yaml(str(_config_path))


config = Config()
