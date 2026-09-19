"""OpenHands result merge + local subgraph fallback (seam split S7)."""

import logging
from pathlib import Path
from typing import cast

from graph.nodes.build_subgraph_legacy import (
    BuildSubState,
    build_input_mapping,
    build_output_mapping,
    get_compiled_subgraph,
)

logger = logging.getLogger(__name__)


# -- Local subgraph fallback ------------------------------------------
def _run_local_subgraph(state: dict) -> dict:
    """
    Run the compiled BUILD subgraph as local fallback.

    Uses proper LangGraph subgraph invocation with clean parent↔child
    state mapping — no internal state keys leak into WorkflowState.
    """
    logger.warning("  -> [OPENHANDS] Running local BUILD subgraph")
    child_state = build_input_mapping(state)
    compiled = get_compiled_subgraph()
    result = compiled.invoke(child_state)
    return build_output_mapping(cast(BuildSubState, result))


# -- OpenHands delegation helpers -------------------------------------
def _write_generated_files(state: dict, files: list[dict]) -> list[str]:
    """
    Write generated files to disk immediately.

    Writes to the project_path so downstream phases (SEED_DATA, VERIFY)
    can access them. Returns list of written paths.
    """
    project_path = state.get("project_path", "")
    root = Path(project_path)
    written = []
    for file_entry in files:
        rel_path = file_entry["path"]
        content = file_entry["content"]
        # Decision 1 (safety): reject absolute paths and any path that escapes
        # the project root (e.g. "../../etc/passwd") before writing.
        rel = Path(rel_path)
        if rel.is_absolute():
            logger.warning("Rejected absolute generated path: %s", rel_path)
            continue
        target = (root / rel).resolve() if root.exists() else (root / rel)
        try:
            target.relative_to(root.resolve() if root.exists() else root)
        except ValueError:
            logger.warning("Rejected path-traversal generated file: %s", rel_path)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(rel_path)
        except Exception as e:
            logger.warning("Failed to write %s: %s", rel_path, e)

    if written:
        logger.info("  -> [OPENHANDS] Wrote %d files to disk", len(written))
    return written


# -- Retry guard constants --------------------------------------------
BUILD_MAX_RETRIES = 2  # max BUILD->BUILD loops before halting (Decision 2/5)


def _merge_results(state: dict, parsed: dict) -> dict:
    """
    Merge OpenHands parsed results into WorkflowState as a partial update.

    This is the bridge between OpenHands text response and
    executor.py / edges.py quality gates.

    Retry counter (Decision 5): the BUILD retry count is persisted in
    `artifacts.loop_counts["BUILD"]` so LangGraph persists it across
    checkpoints. The edge router (route_phase) is a pure reader — it no
    longer mutates state. The node owns the increment, matching the
    pattern used by DEFINE/PLAN/VERIFY.
    """
    # -- Write files to disk immediately --
    _write_generated_files(state, parsed.get("generated_code", []))

    # -- Core artifacts delta --
    artifacts_delta: dict[str, str] = {
        "build_status": parsed["build_status"],
        "build_log": parsed["build_log"],
        "test_results": parsed["test_results"],
        "generated_code_files": parsed["files_created"],
        "build_errors": parsed["errors"],
    }

    # -- UAT proxy: derive pass_rate from build_status --
    status = parsed["build_status"]
    if status == "pass":
        artifacts_delta["uat_report"] = (
            f"OpenHands agent completed successfully.\n{parsed['build_log']}"
        )
        uat_pass_rate = 1.0
    elif status == "partial":
        artifacts_delta["uat_report"] = (
            "OpenHands agent completed with issues.\nErrors:\n"
            + "\n".join(parsed["errors"][:5])
        )
        uat_pass_rate = 0.5
    else:
        artifacts_delta["uat_report"] = (
            "OpenHands agent failed.\nErrors:\n" + "\n".join(parsed["errors"])
        )
        uat_pass_rate = 0.0

    # -- UAT pass rate via metrics update --
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(
            update={"uat_pass_rate": uat_pass_rate}
        )

    # -- Retry guard (Decision 5): single canonical counter in artifacts --
    # The previous top-level `_build_fail_count` was not persisted by
    # LangGraph and could reset on resume; this counter lives in
    # artifacts.loop_counts which the _dict_merge reducer persists.
    loop_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))
    fail_count = int(loop_counts.get("BUILD", 0))
    if status == "fail":
        fail_count += 1
        loop_counts["BUILD"] = fail_count
        if fail_count > BUILD_MAX_RETRIES:
            # Exceeded retry budget — halt the cycle (route to ERROR).
            logger.error(
                "  -> [OPENHANDS] Build failed %d times consecutively -- halting",
                fail_count,
            )
            # Keep error/next_phase/verify_status consistent with the BUILD
            # gate in edges.route_phase: a terminal BUILD failure halts the
            # cycle (route -> ERROR) instead of silently shipping a broken
            # project via the next_phase override.
            return {
                "phase": "BUILD",
                "error": (
                    f"Build failed {fail_count} times consecutively -- "
                    f"aborting. Errors: {parsed['errors'][:3]}"
                ),
                "next_phase": None,
                "artifacts": {**artifacts_delta, "loop_counts": loop_counts},
                "metrics": metrics_update,
            }

    # Reset counter on success (pass / partial) so a later failure starts
    # fresh; the BUILD->BUILD retry path will re-increment.
    if status != "fail":
        loop_counts["BUILD"] = 0

    # -- Next phase --
    next_phase = "SEED_DATA" if status == "pass" else None

    update: dict = {
        "phase": "BUILD",
        "artifacts": {**artifacts_delta, "loop_counts": loop_counts},
        "superApp_mode": "agent",
    }
    if next_phase:
        update["next_phase"] = next_phase
    if metrics_update:
        update["metrics"] = metrics_update

    logger.info(
        "  -> [OPENHANDS] BUILD complete: status=%s, files=%d, errors=%d, retry=%d",
        status,
        len(parsed["generated_code"]),
        len(parsed["errors"]),
        loop_counts.get("BUILD", 0),
    )

    return update
