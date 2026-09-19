"""
BUILD subgraph — structured sub-workflow for the BUILD phase.

Sub-nodes:
  IMPL_PLAN → CREATE_BACKLOG → IMPLEMENT → UNIT_TEST → INT_TEST → SEED → DEPLOY_GATE → UAT → SECURITY_GATE → END

Internal routing:
  UNIT_TEST pass → next backlog item (IMPLEMENT) or INT_TEST (if all done)
  UNIT_TEST fail → retry IMPLEMENT (max 3) or skip
  INT_TEST bugs → append to backlog → IMPLEMENT
  UAT fail → route back to BUILD parent (outer graph handles retry)
  SECURITY_GATE → runs security-and-hardening + pre-commit-review aggregate passes

Seam split S10: the 11 sub-node functions + BuildSubState live in
`build_legacy_nodes.py`; the 3 SuperApp runners live in
`build_legacy_superapp.py`. This module keeps the wiring:
build_input_mapping, build_output_mapping, route_build, build_subgraph,
get_compiled_subgraph, build_subgraph_node.

All moved names are re-exported below so existing test imports
(`import graph.nodes.build_subgraph_legacy as bg`) keep resolving.
`run_command` and `invoke_skill` are re-exported as module-level names
because the test files monkeypatch them on this module
(`bg.run_command`, `bg.invoke_skill`); the moved node functions in
`build_legacy_nodes.py` resolve those names lazily through this module
at call time so the patches reach the call sites.
"""

import time

from langgraph.graph import END, START, StateGraph

from config.bounds_loader import bounds
from tools.audit_logger import AuditLog
from tools.llm import invoke_skill  # noqa: F401 — monkeypatch target (bg.invoke_skill)
from tools.loader import build_skill_registry

from .build_helpers import (
    find_docker_project,
    generate_backlog_md,
    run_command,  # noqa: F401 — monkeypatch target (bg.run_command)
)
from tools.stream_writer import safe_stream_writer

# Re-export moved names (S10 seam split) — monkeypatch targets stay here.
from .build_legacy_nodes import (  # noqa: F401
    MAX_ITEM_RETRIES,
    BuildSubState,
    code_review_node,
    create_backlog_node,
    deploy_gate_node,
    implement_node,
    impl_plan_node,
    int_test_node,
    security_gate_node,
    security_review_node,
    seed_node,
    uat_node,
    unit_test_node,
)
from .build_legacy_superapp import (  # noqa: F401
    _run_llm_uat_fallback,
    _run_superApp_agent,
    _run_superApp_scripted,
)


# ── Conditional routing ────────────────────────────────────────────


def route_build(state: BuildSubState) -> str:
    """Route within the BUILD subgraph."""
    sub_phase = state["sub_phase"]

    if sub_phase == "ALL_ITEMS_DONE":
        return "INT_TEST"

    if sub_phase == "NO_MORE_ITEMS":
        return "INT_TEST"

    if sub_phase == "IMPL_PLAN":
        return "CREATE_BACKLOG"

    if sub_phase == "CREATE_BACKLOG":
        return "IMPLEMENT"

    if sub_phase == "IMPLEMENT":
        return "UNIT_TEST"

    if sub_phase == "UNIT_TEST":
        # unit_test_node already advanced backlog_idx on completion/failure.
        # If backlog_idx >= len(backlog), all items processed → INT_TEST.
        # Otherwise, loop back to IMPLEMENT for the next item.
        if state["backlog_idx"] >= len(state["backlog"]):
            return "INT_TEST"
        return "IMPLEMENT"

    if sub_phase == "INT_TEST":
        return "SEED"

    if sub_phase == "SEED":
        return "DEPLOY_GATE"

    if sub_phase == "DEPLOY_GATE":
        return "UAT"

    if sub_phase == "UAT":
        return END

    return END


# ── State mapping functions (parent ↔ child) ──────────────────────


def build_input_mapping(parent: dict) -> BuildSubState:
    """Map parent WorkflowState → BuildSubState for native subgraph entry.

    Called by LangGraph automatically when entering the BUILD subgraph.
    Replaces the manual BuildSubState construction in build.py.
    """

    project_path = parent.get("project_path", "")
    docker_proj = find_docker_project(project_path)

    from config import loader as config_loader

    skills = build_skill_registry(config_loader.config.workflow.skill_registry_path)

    return BuildSubState(
        {
            "sub_phase": "IMPL_PLAN",
            "project_path": project_path,
            "docker_proj": docker_proj,
            "spec_text": (parent.get("artifacts", {}).get("spec_refined", "") or "")[
                :16_000
            ],
            "tasks_text": (parent.get("artifacts", {}).get("tasks", "") or "")[:8_000],
            "skills": skills,
            "backlog": [],
            "backlog_idx": 0,
            "impl_plan": "",
            "current_code": "",
            "test_code": "",
            "test_result": "",
            "test_output": "",
            "retry_count": 0,
            "int_test_result": "",
            "int_test_output": "",
            "seed_result": "",
            "seed_output": "",
            "uat_result": "",
            "uat_output": "",
            "uat_pass_rate": 0.5,
            "all_generated_code": [],
            "errors": [],
            "build_status": "pending",
            "parent_artifacts": parent.get("artifacts", {}),
            "superApp_mode": "agent",  # Default: agent mode
            "superApp_agent_report": {},
            "security_review": "",
            "code_review": "",
        }
    )


def build_output_mapping(child: BuildSubState) -> dict:
    writer = safe_stream_writer()  # fallback for tests/CLI
    """Map BuildSubState → parent WorkflowState update for native subgraph exit.

    Called by LangGraph automatically when the BUILD subgraph completes.
    Returns a dict that gets shallow-merged into the parent WorkflowState.
    Replaces the manual merge logic in build.py (lines 139-206).
    """
    from pathlib import Path as _Path

    # ── Extract subgraph results ──
    backlog = child.get("backlog", [])
    errors = child.get("errors", [])
    uat_pass_rate = child.get("uat_pass_rate", 0.5)
    uat_result = child.get("uat_result", "pass")
    all_code = child.get("all_generated_code", [])
    uat_output = child.get("uat_output", "")
    project_folder = child.get("project_path", "")

    # ── Write backlog.md ──
    build_dir = _Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = build_dir / "backlog.md"
    backlog_path.write_text(generate_backlog_md(backlog, project_folder))

    # ── Determine pass/fail ──
    all_completed = (
        all(i["status"] == "completed" for i in backlog) if backlog else False
    )
    has_errors = bool(errors) or uat_result == "fail"

    # ── Build updated artifacts dict ──
    artifacts = dict(child.get("parent_artifacts", {}))
    if has_errors and not all_completed:
        # ── FAILURE ──
        error_summary = "\n".join(errors[:10])
        incomplete = sum(1 for i in backlog if i["status"] != "completed")
        writer(
            {
                "type": "error",
                "phase": "BUILD",
                "step": "error",
                "detail": f"\n  ✗ BUILD: {incomplete} items incomplete, UAT={uat_result}",
                "ts": time.time(),
            }
        )
        artifacts["build_status"] = "fail"

        from graph.state import CycleMetrics

        metrics = CycleMetrics(
            uat_pass_rate=uat_pass_rate,
        )

        return {
            "phase": "BUILD",
            "error": error_summary,
            "next_phase": "BUILD",  # Loop back
            "artifacts": artifacts,
            "metrics": metrics,
        }

    # ── SUCCESS ──
    items_completed = sum(1 for i in backlog if i["status"] == "completed")
    artifacts["build_status"] = "pass"
    artifacts["implementation"] = "\n".join(all_code)
    artifacts["uat_results"] = uat_output
    if uat_result == "skip":
        # D2: skip is surfaced, not fatal — VERIFY (Decision 2) owns the verdict.
        skip_errors = list(errors)
        skip_errors.append(
            "UAT skipped — deployment not verified; VERIFY gate owns the pass/fail verdict"
        )
        skip_errors = skip_errors[-bounds.feedback.max_error_entries :]
        error_summary = "\n".join(skip_errors)
        writer(
            {
                "type": "error",
                "phase": "BUILD",
                "step": "error",
                "detail": f"\n  ⚠ BUILD: {error_summary}",
                "ts": time.time(),
            }
        )
    else:
        error_summary = None
    artifacts["uat_pass_rate"] = uat_pass_rate
    for key in ("security_review", "code_review"):
        val = child.get(key, "")
        if val:  # Decision 3: omit empty/None, never a sentinel
            artifacts[key] = val

    from graph.state import CycleMetrics

    metrics = CycleMetrics(
        uat_pass_rate=uat_pass_rate,
        test_flakiness_rate=0.0,
        latency_ms=0.0,
    )

    writer(
        {
            "type": "progress",
            "phase": "BUILD",
            "step": "success",
            "detail": f"\n  ✓ BUILD passed: {items_completed}/{len(backlog)} items, UAT rate={uat_pass_rate}",
            "ts": time.time(),
        }
    )

    return {
        "phase": "BUILD",
        "error": error_summary,
        "next_phase": "SHIP",
        "artifacts": artifacts,
        "metrics": metrics,
    }


# ── Build subgraph ─────────────────────────────────────────────────


def build_subgraph() -> StateGraph:
    """Build the BUILD subgraph (returns the StateGraph, not compiled)."""
    sub = StateGraph(BuildSubState)

    sub.add_node("IMPL_PLAN", impl_plan_node)
    sub.add_node("CREATE_BACKLOG", create_backlog_node)
    sub.add_node("IMPLEMENT", implement_node)
    sub.add_node("UNIT_TEST", unit_test_node)
    sub.add_node("INT_TEST", int_test_node)
    sub.add_node("SEED", seed_node)
    sub.add_node("DEPLOY_GATE", deploy_gate_node)
    sub.add_node("UAT", uat_node)
    sub.add_node("SECURITY_GATE", security_gate_node)

    sub.add_edge(START, "IMPL_PLAN")
    sub.add_edge("IMPL_PLAN", "CREATE_BACKLOG")
    sub.add_edge("CREATE_BACKLOG", "IMPLEMENT")
    sub.add_edge("IMPLEMENT", "UNIT_TEST")
    sub.add_conditional_edges("UNIT_TEST", route_build)
    sub.add_edge("INT_TEST", "SEED")
    sub.add_edge("SEED", "DEPLOY_GATE")
    sub.add_edge("DEPLOY_GATE", "UAT")
    sub.add_edge("UAT", "SECURITY_GATE")
    sub.add_edge("SECURITY_GATE", END)

    return sub


def get_compiled_subgraph():
    """Return the compiled BUILD subgraph for native parent integration."""
    return build_subgraph().compile()


def build_subgraph_node(state: dict) -> dict:
    """Wrapper node that bridges WorkflowState ↔ BuildSubState.

    Maps parent state to subgraph input, invokes the subgraph,
    then maps the result back to a parent state update.
    """
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input(
        "BUILD_LEGACY", {"project_path": state.get("project_path", "")}
    )
    child_state = build_input_mapping(state)
    compiled = get_compiled_subgraph()
    result = compiled.invoke(child_state)
    result = build_output_mapping(result)
    audit.log_node_output(
        "BUILD_LEGACY",
        {"status": (result.get("artifacts") or {}).get("build_status", "pass")},
    )
    return result
