"""
arckit-web-ingestion: Web API explicit ArcKit artefact list.

- `StartRequest` accepts an optional `arckit_artifacts` array
- the bridge seeds `state["arckit_artifacts"]` in `_build_executor_state`
  only when a non-empty list was posted (empty/absent → key absent,
  glob discovery remains the default)
- the list is persisted with the rest of the start inputs so HIL
  recovery re-applies it
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _bridge(tmp_path):
    # orchestrator_state_dir is a read-only property backed by config; the
    # persisted-inputs path is an instance attr, so redirect it to tmp_path.
    from frontend.backend.workflow_bridge import WorkflowBridge

    bridge = WorkflowBridge()
    bridge._user_inputs_path = tmp_path / "user_inputs.json"
    return bridge


class TestStartRequestSchema:
    def test_defaults_to_empty_list(self):
        from frontend.backend.app import StartRequest

        assert StartRequest().arckit_artifacts == []

    def test_accepts_explicit_list(self):
        from frontend.backend.app import StartRequest

        req = StartRequest(
            project_name="p",
            arckit_artifacts=["/x/ARC-001-ADMP-v1.0.md", "/x/ARC-001-OAAL-v1.0.md"],
        )
        assert req.arckit_artifacts == [
            "/x/ARC-001-ADMP-v1.0.md",
            "/x/ARC-001-OAAL-v1.0.md",
        ]


class TestBridgeStateSeed:
    def test_non_empty_list_seeds_state(self, tmp_path):
        bridge = _bridge(tmp_path)
        state = bridge._build_executor_state(
            "1", "proj", "spec", "/ctx",
            arckit_artifacts=["/a/ARC-001-ADMP-v1.0.md"],
        )
        assert state["arckit_artifacts"] == ["/a/ARC-001-ADMP-v1.0.md"]

    def test_empty_list_is_unset_equivalent(self, tmp_path):
        bridge = _bridge(tmp_path)
        # explicit empty list == omitted: DISCOVER treats [] the same as an
        # absent key (files = [] or None -> None -> glob default discovery).
        state = bridge._build_executor_state("1", "proj", "spec", "/ctx",
                                             arckit_artifacts=[])
        assert state.get("arckit_artifacts", []) == []

    def test_persisted_inputs_round_trip(self, tmp_path):
        bridge = _bridge(tmp_path)
        bridge._project_name = "p"
        bridge._arckit_artifacts = ["/a/ARC-001-ADMP-v1.0.md"]
        bridge._save_persisted_inputs()
        reloaded = bridge._load_persisted_inputs()
        assert reloaded.get("_arckit_artifacts") == ["/a/ARC-001-ADMP-v1.0.md"]
