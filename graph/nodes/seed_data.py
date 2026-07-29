"""
SEED_DATA placeholder node: seeds database/initial data for the generated project.

Currently a pass-through placeholder — does minimal validation and forwards to
VERIFY. Will be expanded with real seeding logic (SQL inserts, fixture loads,
initial data generation) in a future iteration.

Output: marks seed phase as complete, preserves all artifacts.
"""

from langgraph.config import get_stream_writer

import time
from tools.audit_logger import AuditLog


def seed_data_node(state: dict) -> dict:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """
    SEED_DATA phase: Placeholder for data seeding.

    Currently passes through. Future: generate and insert seed data,
    fixtures, and initial database state based on project models.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer({"type": "progress", "phase": "SEED_DATA", "step": "started", "detail": "\n=== SEED_DATA PHASE (placeholder) ===", "ts": time.time()})
    writer({"type": "progress", "phase": "SEED_DATA", "step": "progress", "detail": "  -> Seed data seeding not yet implemented — pass-through to VERIFY", "ts": time.time()})

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("SEED_DATA", {"is_placeholder": True})
    audit.log_node_output("SEED_DATA", {
        "status": "skipped_placeholder",
        "note": "Will be implemented with real seeding logic",
    })

    return {
        "phase": "SEED_DATA",
        "next_phase": "VERIFY",
        "artifacts": {"seed_data_status": "skipped_placeholder"},
    }
