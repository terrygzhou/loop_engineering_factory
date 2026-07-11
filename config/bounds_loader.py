"""
Bounds loader — configurable context & memory limits.

Resolution: config/bounds.yaml > built-in defaults.

Usage:
    from config.bounds_loader import bounds
    max_tokens = bounds.context.define_max_tokens
    max_items  = bounds.build.max_item_retries
"""
from pathlib import Path

import yaml


def _load_yaml(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return yaml.safe_load(p.read_text()) or {}
        except Exception:
            pass
    return {}


def _resolve(data: dict, key_path: str, default):
    """Resolve: config dict (nested key) > default."""
    val = data
    for k in key_path.split("."):
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
    if val is not None:
        return type(default)(val)
    return default


# ── Load bounds config ─────────────────────────────────────────────
_bounds_path = Path(__file__).resolve().parent / "bounds.yaml"
_bounds_data = _load_yaml(str(_bounds_path))


class Bounds:
    """Configurable bounds for context, artifacts, and build pipeline."""

    class Context:
        # Max tokens per LLM call by phase
        define_max_tokens: int = _resolve(_bounds_data, "context.define_max_tokens", 16000)
        plan_max_tokens: int = _resolve(_bounds_data, "context.plan_max_tokens", 10000)
        build_max_tokens: int = _resolve(_bounds_data, "context.build_max_tokens", 12000)

        # Diagram context char limits
        diagram_spec_chars: int = _resolve(_bounds_data, "context.diagram_context.spec_chars", 3000)
        diagram_plan_chars: int = _resolve(_bounds_data, "context.diagram_context.plan_chars", 8000)
        diagram_tasks_chars: int = _resolve(_bounds_data, "context.diagram_context.tasks_chars", 5000)
        diagram_doubt_chars: int = _resolve(_bounds_data, "context.diagram_context.doubt_chars", 3000)

    class Artifacts:
        # Accumulation caps
        max_generated_code_entries: int = _resolve(_bounds_data, "artifacts.max_generated_code_entries", 3)
        max_feedback_entries: int = _resolve(_bounds_data, "artifacts.max_feedback_entries", 20)
        max_plan_chars: int = _resolve(_bounds_data, "artifacts.max_plan_chars", 40000)
        max_tasks_chars: int = _resolve(_bounds_data, "artifacts.max_tasks_chars", 20000)
        max_analysis_chars: int = _resolve(_bounds_data, "artifacts.max_analysis_chars", 15000)
        max_doubt_chars: int = _resolve(_bounds_data, "artifacts.max_doubt_chars", 15000)
        max_spec_subgraph_chars: int = _resolve(_bounds_data, "artifacts.max_spec_subgraph_chars", 30000)
        max_tasks_subgraph_chars: int = _resolve(_bounds_data, "artifacts.max_tasks_subgraph_chars", 15000)

    class Build:
        # Retry & failure limits
        max_item_retries: int = _resolve(_bounds_data, "build.max_item_retries", 3)
        max_build_failures: int = _resolve(_bounds_data, "build.max_build_failures", 3)
        max_test_output_chars: int = _resolve(_bounds_data, "build.max_test_output_chars", 500)
        max_seed_output_chars: int = _resolve(_bounds_data, "build.max_seed_output_chars", 500)
        recent_code_snippets: int = _resolve(_bounds_data, "build.recent_code_snippets", 2)
        recent_code_chars: int = _resolve(_bounds_data, "build.recent_code_chars", 2000)

    class Feedback:
        # Logging & historical context limits
        max_feedback_entry_chars: int = _resolve(_bounds_data, "feedback.max_feedback_entry_chars", 300)
        max_pattern_doc_chars: int = _resolve(_bounds_data, "feedback.max_pattern_doc_chars", 400)
        max_context_query_chars: int = _resolve(_bounds_data, "feedback.max_context_query_chars", 500)
        max_review_comments_chars: int = _resolve(_bounds_data, "feedback.max_review_comments_chars", 500)
        max_error_entries: int = _resolve(_bounds_data, "feedback.max_error_entries", 10)
        max_chroma_patterns: int = _resolve(_bounds_data, "feedback.max_chroma_patterns", 3)

    class MemoryBudget:
        orchestrator_limit_bytes: int = _resolve(_bounds_data, "memory_budget.orchestrator_limit_bytes", 1073741824)
        builder_limit_bytes: int = _resolve(_bounds_data, "memory_budget.builder_limit_bytes", 6442450944)
        warning_threshold_pct: int = _resolve(_bounds_data, "memory_budget.warning_threshold_pct", 75)
        critical_threshold_pct: int = _resolve(_bounds_data, "memory_budget.critical_threshold_pct", 90)

    context = Context()
    artifacts = Artifacts()
    build = Build()
    feedback = Feedback()
    memory_budget = MemoryBudget()


bounds = Bounds()