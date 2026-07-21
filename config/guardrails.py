"""
Guardrails loader — load quality thresholds from YAML at runtime.

Used by edges.py, verify.py, and reflect.py to read thresholds that REFLECT
can update between cycles. Falls back to built-in defaults if YAML missing.
"""
from pathlib import Path
from typing import Any, Dict

import yaml


# ── Built-in defaults (used when YAML missing or key absent) ──
_DEFAULTS: Dict[str, Any] = {
    # DEFINE gates
    "min_spec_confidence": 0.9,
    # PLAN gates
    "max_arch_uncertainty": 0.8,
    # BUILD gates
    "max_security_findings": 0,
    "max_review_revisions": 2,
    # VERIFY gates
    "uat_pass_rate": 0.95,
    "max_latency_ms": 500,
    "max_test_flakiness_rate": 0.1,
}


def _resolve_path() -> str:
    """Resolve guardrails path: config.yaml > default."""
    from config.loader import config
    _guardrails_path = config.paths.guardrails_path
    # Try alongside this module
    mod_path = Path(__file__).resolve().parent / "guardrails.yaml"
    if mod_path.exists():
        return str(mod_path)
    return _guardrails_path


def load_guardrails() -> Dict[str, Any]:
    """
    Load guardrails YAML. Returns a dict with at least quality_thresholds.
    Falls back to built-in defaults for any missing key.
    """
    path = _resolve_path()
    try:
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}

    thresholds = raw.get("quality_thresholds", {})
    # Merge: YAML wins, then defaults
    merged = dict(_DEFAULTS)
    merged.update(thresholds)

    return {
        "quality_thresholds": merged,
        "security_sensitive": raw.get("security_sensitive", []),
        "feedback": raw.get("feedback", {}),
        "reflection": raw.get("reflection", {}),
        "llm": raw.get("llm", {}),
        # Preserve any extra top-level keys (e.g. code_review, spec_generation)
        **{k: v for k, v in raw.items() if k not in ("quality_thresholds", "security_sensitive", "feedback", "reflection", "llm")},
    }


# ── Cached config (reloaded only when file changes) ──
_cache: Dict[str, Any] = {}
_cache_mtime: float = 0.0


def _get_cache() -> Dict[str, Any]:
    """Return cached guardrails, reloading from disk only when the file changed."""
    global _cache, _cache_mtime
    path = _resolve_path()
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        mtime = 0.0
    if not _cache or mtime != _cache_mtime:
        _cache = load_guardrails()
        _cache_mtime = mtime
    return _cache


def get_threshold(name: str, default=None) -> Any:
    """Get a single quality threshold, falling back to built-in default."""
    if default is None:
        default = _DEFAULTS.get(name)
    if default is None:
        raise KeyError(f"Unknown threshold: {name!r}")
    return _get_cache()["quality_thresholds"].get(name, default)
