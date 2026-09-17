"""W3 arckit-build-context (task 7.1-7.2): SEED_DATA is driven by
``arckit_data_model`` when set (deterministic, no LLM), else retains its
existing pass-through behaviour."""

import json
from unittest.mock import MagicMock, patch


def _run(artifacts):
    from graph.nodes.seed_data import seed_data_node

    s = {
        "phase": "SEED_DATA",
        "project_name": "demo",
        "project_path": "/tmp/demo",
        "auto_approve_override": True,
        "metrics": __import__("graph.state", fromlist=["CycleMetrics"]).CycleMetrics(),
        "artifacts": artifacts,
        "cycle_id": "0",
        "trace_id": "t",
    }
    with patch("graph.nodes.seed_data.safe_stream_writer",
               return_value=lambda x: None), \
         patch("graph.nodes.seed_data.AuditLog", MagicMock()):
        return seed_data_node(s)


DATA_MODEL = json.dumps(
    {
        "entities": [
            {"entity": "Policyholder", "domain": "Customer", "classification": "Internal"},
            {"entity": "Claim", "domain": "Claims", "classification": "Internal"},
        ],
        "classification": [
            {"level": "Internal", "handling": "no PII in logs"}
        ],
    }
)


def test_model_driven_when_data_model_set():
    out = _run({"arckit_data_model": DATA_MODEL})
    art = out["artifacts"]
    assert art["seed_data_status"] == "model_driven"
    model = json.loads(art["seed_data_model"])
    names = [e.get("entity") for e in model["entities"]]
    assert names == ["Policyholder", "Claim"]
    # classification scheme carried for the seeding script
    assert model["classification"]
    assert out["next_phase"] == "VERIFY"


def test_pass_through_when_absent():
    out = _run({})
    art = out["artifacts"]
    assert art["seed_data_status"] == "skipped_placeholder"
    assert "seed_data_model" not in art
    assert out["next_phase"] == "VERIFY"


def test_model_driven_ignores_empty_data_model():
    """An empty dict value is not a model — fall back to pass-through."""
    out = _run({"arckit_data_model": json.dumps({})})
    art = out["artifacts"]
    assert art["seed_data_status"] == "skipped_placeholder"
    assert "seed_data_model" not in art
