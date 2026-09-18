# tests/test_audit_coverage.py
"""Spec conformance: observability › Distributed tracing › Audit completeness.

Every phase node module MUST emit both AuditLog.log_node_input and
log_node_output (openspec/specs/observability/spec.md).
"""

import json
import pathlib
import uuid

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE_MODULES = [
    "graph/nodes/discover.py",
    "graph/nodes/define.py",
    "graph/nodes/plan.py",
    "graph/nodes/review.py",
    "graph/nodes/openhands_build.py",
    "graph/nodes/build_subgraph_legacy.py",
    "graph/nodes/seed_data.py",
    "graph/nodes/verify.py",
    "graph/nodes/ship.py",
    "graph/nodes/reflect.py",
]


@pytest.mark.parametrize("rel", NODE_MODULES)
def test_node_module_emits_audit_input_and_output(rel):
    src = (REPO_ROOT / rel).read_text()
    assert "log_node_input(" in src, f"{rel} missing log_node_input"
    assert "log_node_output(" in src, f"{rel} missing log_node_output"


def test_ship_node_writes_audit_entries(tmp_path, monkeypatch):
    """Behavioural: SHIP audit records land in interactions.jsonl."""
    from tools import audit_logger
    from graph.nodes.ship import ship_node
    from graph.state import CycleMetrics

    trace_id = str(uuid.uuid4())
    log_path = tmp_path / "interactions.jsonl"
    monkeypatch.setattr(audit_logger, "INTERACTION_LOG", log_path)
    # ensure_audit_dir() only touches AUDIT_DIR (repo build/audit_logs) — fine.

    state = {
        "cycle_id": "audit-test-cycle",
        "trace_id": trace_id,
        "project_path": "",
        "artifacts": {},
        "metrics": CycleMetrics(),
    }
    ship_node(state)

    lines = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    mine = [e for e in lines if e["trace_id"] == trace_id]
    events = {(e["event"], e.get("phase")) for e in mine}
    assert ("node.input", "SHIP") in events
    assert ("node.output", "SHIP") in events
