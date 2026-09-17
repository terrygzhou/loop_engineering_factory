"""D2: UAT skip must not report uat_pass_rate = 1.0."""
import graph.nodes.build_subgraph_legacy as bg

# run_command is imported into the module namespace via
# `from .build_helpers import run_command`, so monkeypatch it on bg.


def _substate_at_deploy_gate(tmp_path, **over):
    base = {
        "sub_phase": "DEPLOY_GATE",
        "project_path": str(tmp_path),
        "docker_proj": str(tmp_path),
        "impl_plan": "plan",
        "backlog": [{"id": "1", "status": "completed", "description": "t1"}],
        "all_generated_code": ["code"],
        "errors": [],
        "parent_artifacts": {},
        "int_test_result": "pass",
        "uat_result": "",
        "uat_output": "",
        "uat_pass_rate": 0.5,
    }
    base.update(over)
    return bg.BuildSubState(**base)


def _child(tmp_path, **over):
    base = {
        "parent_artifacts": {},
        "backlog": [{"id": "1", "status": "completed", "description": "t1"}],
        "all_generated_code": ["code"],
        "errors": [],
        "uat_result": "pass",
        "uat_pass_rate": 1.0,
        "uat_output": "ok",
        "project_path": str(tmp_path),  # mapping writes backlog.md under <project>/build/
        "int_test_result": "pass",
    }
    base.update(over)
    return bg.BuildSubState(**base)


def test_deploy_gate_container_down_writes_zero_rate(monkeypatch, tmp_path):
    # Stub the docker/health commands so deploy_gate hits the skip path.
    monkeypatch.setattr(bg, "run_command", lambda *a, **k: (1, "not up", ""))
    state = _substate_at_deploy_gate(tmp_path)
    out = bg.deploy_gate_node(state)
    assert out["uat_result"] == "skip"
    assert out["uat_pass_rate"] == 0.0


def test_deploy_gate_health_fail_writes_zero_rate(monkeypatch, tmp_path):
    # Container is up, but the health endpoint returns a non-2xx/3xx code.
    def fake_run_command(*a, **k):
        cmd = a[0] if a else ""
        if "compose ps" in cmd:
            return (0, "Up 5 minutes", "")
        if "logs" in cmd:
            return (0, "all good", "")
        return (0, "503", "")  # health endpoint

    monkeypatch.setattr(bg, "run_command", fake_run_command)
    state = _substate_at_deploy_gate(tmp_path)
    out = bg.deploy_gate_node(state)
    assert out["uat_result"] == "skip"
    assert out["uat_pass_rate"] == 0.0


def test_mapping_skip_surfaces_warning_in_errors(tmp_path):
    child = _child(tmp_path, uat_result="skip", uat_pass_rate=0.0)
    out = bg.build_output_mapping(child)
    # The skip warning must surface in the returned payload's error channel
    err = out.get("error") or ""
    assert "UAT skipped" in err or any(
        "UAT skipped" in e for e in (out.get("errors") or [])
    )
    assert out["metrics"].uat_pass_rate == 0.0
    # Skip is surfaced, not fatal: the gate still forwards to SHIP.
    assert out["next_phase"] == "SHIP"
    assert out["artifacts"]["build_status"] == "pass"
