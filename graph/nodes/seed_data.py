"""
SEED_DATA node: prepares initial data state for the generated project.

Two branches:
- ``artifacts["arckit_data_model"]`` set (JSON with entities): deterministic
  model-driven branch — writes ``seed_data_model`` (entities + classification
  scheme, no LLM) and ``seed_data_status = "model_driven"``.
- otherwise: legacy pass-through placeholder — ``seed_data_status =
  "skipped_placeholder"``.

Both branches preserve all artifacts and forward to VERIFY.
"""

import json
import time
from tools.audit_logger import AuditLog
from tools.stream_writer import safe_stream_writer


def _data_model(artifacts: dict):
    """Parse ``arckit_data_model`` into a dict, or None when absent/empty/invalid."""
    raw = artifacts.get("arckit_data_model")
    if not raw:
        return None
    try:
        model = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return model if isinstance(model, dict) else None


def seed_data_node(state: dict) -> dict:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """
    SEED_DATA phase: model-driven seeding context (ArcKit data model) or
    pass-through placeholder when no data model is present.

    Returns partial update dict (LangGraph reducer merges).
    """
    artifacts = state.get("artifacts", {}) or {}
    model = _data_model(artifacts)
    model_driven = bool(model and model.get("entities"))

    writer(
        {
            "type": "progress",
            "phase": "SEED_DATA",
            "step": "started",
            "detail": "\n=== SEED_DATA PHASE ==="
            if model_driven
            else "\n=== SEED_DATA PHASE (placeholder) ===",
            "ts": time.time(),
        }
    )
    if model_driven:
        writer(
            {
                "type": "progress",
                "phase": "SEED_DATA",
                "step": "progress",
                "detail": "  -> Seed model derived from ArcKit data model "
                f"({len(model['entities'])} entities) — no LLM",
                "ts": time.time(),
            }
        )
    else:
        writer(
            {
                "type": "progress",
                "phase": "SEED_DATA",
                "step": "progress",
                "detail": "  -> Seed data seeding not yet implemented — pass-through to VERIFY",
                "ts": time.time(),
            }
        )

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("SEED_DATA", {"model_driven": model_driven})
    if model_driven:
        seed_model = json.dumps(
            {
                "entities": model["entities"],
                "classification": model.get("classification") or [],
            },
            indent=2,
        )
        audit.log_node_output(
            "SEED_DATA",
            {
                "status": "model_driven",
                "entity_count": len(model["entities"]),
            },
        )
        return {
            "phase": "SEED_DATA",
            "next_phase": "VERIFY",
            "artifacts": {
                "seed_data_status": "model_driven",
                "seed_data_model": seed_model,
            },
        }

    audit.log_node_output(
        "SEED_DATA",
        {
            "status": "skipped_placeholder",
            "note": "Will be implemented with real seeding logic",
        },
    )

    return {
        "phase": "SEED_DATA",
        "next_phase": "VERIFY",
        "artifacts": {"seed_data_status": "skipped_placeholder"},
    }
