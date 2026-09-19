"""
PLAN node: Generate implementation plan, tasks, analysis, and architecture diagrams.
Outputs: $project_folder/build/solution.md — complete solution design with diagrams.

Skill chain:
  planning-and-task-breakdown → doubt-driven-development → architecture-diagram-generator
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any


from config.bounds_loader import bounds
from config.loader import config as _cfg
from graph.ui_bridge import SkillTimer
from tools.arckit_context import arckit_advisory_block
from tools.audit_logger import AuditLog
from tools.context_manager import prepare_context_for_llm
from tools.llm import invoke_skill, invoke_skill_async
from tools.loader import build_skill_registry
from tools.stream_writer import safe_stream_writer

# Re-exports for the seam-split sibling modules (node-module-seams spec S8).
from graph.nodes.plan_diagrams import (  # noqa: F401
    _DIAGRAM_SKILL_INSTRUCTIONS,
    _build_diagram_context,
    _extract_use_cases,
    _get_diagram_skill,
    _load_local_diagram_skill,
    _slugify,
)
from graph.nodes.plan_confidence import (  # noqa: F401
    _estimate_arch_uncertainty,
    _generate_solution_md,
    _load_feedback_context,
)

# get_chroma_client / query_patterns are now called inside plan_confidence._load_feedback_context,
# but the test suite monkeypatches plan_mod.get_chroma_client directly.
from feedback.chroma_client import get_chroma_client, query_patterns  # noqa: F401


def plan_node(state: dict) -> dict:
    """
    PLAN phase: Generate implementation plan using framework skill chain.

    Flow:
      planning-and-task-breakdown → doubt-driven-development → architecture-diagram-generator

    Returns partial update dict (LangGraph reducer merges).
    """
    w = safe_stream_writer()
    w(
        {
            "type": "progress",
            "phase": "PLAN",
            "step": "start",
            "detail": "PLAN PHASE",
            "ts": time.time(),
        }
    )

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input(
        "PLAN",
        {
            "has_spec": bool(state.get("artifacts", {}).get("spec_refined")),
            "has_interview": bool(state.get("artifacts", {}).get("interview_notes")),
        },
    )

    # ── Load skills (lazy-load via cached registry) ──
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    feedback_entries: list[dict] = []

    # ── Load historical feedback context ──
    feedback_context = _load_feedback_context(state)

    # ── ARCH_REVIEW rejection feedback (EYW-184 reject-loop) ──
    # When PLAN re-runs after a rejection, the reviewer's comments must lead
    # the planning context so the regenerated plan addresses them.
    review_comments = (state.get("user_review_comments") or "").strip()
    if review_comments:
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "replan",
                "detail": "  → Re-planning with ARCH_REVIEW rejection feedback",
                "ts": time.time(),
            }
        )

    # Build context for all skill invocations
    spec = state.get("artifacts", {}).get("spec_refined", "")
    interview = state.get("artifacts", {}).get("interview_notes", "")
    context_parts: list[str] = []
    if review_comments:
        context_parts.append(
            "## ARCH_REVIEW Rejection Feedback (must be addressed in the regenerated plan)\n"
            + review_comments
        )
    context_parts.append(spec)
    if interview:
        context_parts.append(f"Interview notes:\n{interview}")
    if feedback_context:
        context_parts.append(f"\n\n{feedback_context}\n")
    # ArcKit advisory block (shared helper, skill-map-arckit-fit task 2):
    # carries arckit_product_backlog + other set ArcKit advisory keys into
    # the planning context. Byte-identical when no ArcKit keys are set.
    advisory = arckit_advisory_block(state.get("artifacts", {}))
    if advisory:
        context_parts.append(advisory)
    base_context = "\n\n".join(context_parts)

    artifacts_delta: dict[str, Any] = {}

    # ── Step 1: Generate structured task breakdown with milestones and dependencies ──
    plan_skill = skills.get("planning-and-task-breakdown", {})
    plan_result = None
    if plan_skill:
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "planning",
                "detail": "Running planning-and-task-breakdown...",
                "ts": time.time(),
            }
        )
        plan_timer = SkillTimer("planning-and-task-breakdown")
        optimized = prepare_context_for_llm(
            {"context": base_context}, max_tokens=bounds.context.plan_max_tokens
        )
        plan_result = invoke_skill(
            plan_skill["content"],
            "Break down the implementation into structured tasks with milestones, dependencies, effort estimates, and acceptance criteria. Use vertical slicing. Output phases (Foundation, Core Features, Polish) with checkpoints between them. Include a dependency graph, risk table, and parallelization notes.",
            optimized["context"],
            llm=None,
        )
        plan_timer.complete()
        if plan_result is None:
            w(
                {
                    "type": "progress",
                    "phase": "PLAN",
                    "step": "warning",
                    "detail": "  ⚠ plan LLM call failed fatally (None) — continuing with empty plan",
                    "ts": time.time(),
                }
            )
            plan_result = ""
        artifacts_delta["plan"] = plan_result[: bounds.artifacts.max_plan_chars]
        # Store structured task breakdown as separate artifact for downstream phases
        # "task_breakdown" = detailed structure, "tasks" = compat key for solution.md + BUILD
        artifacts_delta["task_breakdown"] = plan_result[
            : bounds.artifacts.max_plan_chars
        ]
        artifacts_delta["tasks"] = plan_result[: bounds.artifacts.max_plan_chars]
        feedback_entries.append(
            {
                "skill": "planning-and-task-breakdown",
                "output": plan_result[: bounds.feedback.max_feedback_entry_chars],
            }
        )

    # ── Step 2: Doubt-driven development (challenge assumptions) ──
    doubt_skill = skills.get("doubt-driven-development", {})
    doubt_result = None
    if doubt_skill:
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "doubt",
                "detail": "Running doubt-driven-development...",
                "ts": time.time(),
            }
        )
        doubt_timer = SkillTimer("doubt-driven-development")
        doubt_result = invoke_skill(
            doubt_skill["content"],
            "Challenge the architectural assumptions in the plan. Be concise — focus on top 3 risks only.",
            artifacts_delta.get("plan", state.get("artifacts", {}).get("plan", ""))[
                : bounds.artifacts.max_analysis_chars
            ],
            llm=None,
        )
        doubt_timer.complete()
        if doubt_result is None:
            w(
                {
                    "type": "progress",
                    "phase": "PLAN",
                    "step": "warning",
                    "detail": "  ⚠ doubt LLM call failed fatally (None) — continuing with empty doubt resolution",
                    "ts": time.time(),
                }
            )
            doubt_result = ""
        artifacts_delta["doubt_resolution"] = doubt_result[
            : bounds.artifacts.max_doubt_chars
        ]
        feedback_entries.append(
            {
                "skill": "doubt-driven-development",
                "output": doubt_result[: bounds.feedback.max_feedback_entry_chars],
            }
        )

    # ── Step 9: Generate architecture diagrams ──
    w(
        {
            "type": "progress",
            "phase": "PLAN",
            "step": "diagrams",
            "detail": "Running architecture-diagram-generator...",
            "ts": time.time(),
        }
    )
    diagrams = _generate_all_diagrams(skills, state)

    # ── Convert diagrams to PNG ──
    png_paths = _convert_diagrams_to_png(diagrams)
    artifacts_delta["diagram_pngs"] = png_paths

    # ── Persist solution.md to $project_folder/build/ ──
    project_folder = state.get("project_folder", state.get("project_path", ""))
    build_dir = Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    solution_md = _generate_solution_md(state, artifacts_delta)
    solution_path = build_dir / "solution.md"
    solution_path.write_text(solution_md)
    audit.log_file_write("PLAN", str(solution_path), "markdown", len(solution_md))
    w(
        {
            "type": "progress",
            "phase": "PLAN",
            "step": "solution",
            "detail": f"solution.md written: {solution_path} ({len(solution_md)} chars)",
            "ts": time.time(),
        }
    )

    # Store in artifacts for openhands_build to pick up
    artifacts_delta["solution_md"] = solution_md
    artifacts_delta["solution_path"] = str(solution_path)
    artifacts_delta["diagrams"] = diagrams

    diagram_count = len(diagrams)
    # Extract task count
    task_count = 1
    if plan_result:
        task_count = (
            plan_result.count("- [")
            + plan_result.count("1.")
            + plan_result.count("2.")
            + plan_result.count("3.")
        )

    # ── Derive architectural uncertainty ──
    merged_artifacts = {**state.get("artifacts", {}), **artifacts_delta}
    arch_uncertainty = _estimate_arch_uncertainty(merged_artifacts)

    # ── Audit output ──
    audit.log_node_output(
        "PLAN",
        {
            "solution_path": str(solution_path),
            "diagram_count": diagram_count,
            "task_count": task_count,
            "arch_uncertainty": arch_uncertainty,
        },
    )
    audit.log_node_transition("PLAN", "BUILD", "plan generation complete")

    # Update metrics
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(
            update={
                "task_count": max(task_count, 1),
                "diagram_count": diagram_count,
                "arch_uncertainty": arch_uncertainty,
            }
        )

    w(
        {
            "type": "progress",
            "phase": "PLAN",
            "step": "metrics",
            "detail": f"task_count={task_count}, arch_uncertainty={arch_uncertainty:.2f}, diagrams={diagram_count}",
            "ts": time.time(),
        }
    )

    # Build partial update
    update: dict = {
        "phase": "PLAN",
        "feedback_context": feedback_context,
        "diagrams": diagrams,
        "diagram_status": "pending",
        "feedback": feedback_entries,
        "next_phase": "BUILD",
        "human_approval_required": False,
    }
    if artifacts_delta:
        update["artifacts"] = artifacts_delta
    if metrics_update:
        update["metrics"] = metrics_update

    return update


def _generate_diagram(skills: dict, diagram_type: str, state: dict) -> str:
    _DIAGRAM_PLACEHOLDER = (
        'flowchart TD\n    NOTE["⚠ Insufficient context for diagram generation."]'
    )

    spec = state.get("artifacts", {}).get("spec_refined", "")
    plan = state.get("artifacts", {}).get("plan", "")
    tasks = state.get("artifacts", {}).get("tasks", "")
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")
    combined = f"{spec}{plan}{tasks}{doubt}".strip()

    # Guard: if no real context, return placeholder instead of feeding empty input to LLM
    if not combined:
        w = safe_stream_writer()
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "diagram",
                "detail": f"Empty context for {diagram_type} diagram; using placeholder",
                "ts": time.time(),
            }
        )
        return _DIAGRAM_PLACEHOLDER

    # 1) Try the registered skill first
    arch_skill = skills.get("architecture-diagram-generator", {})
    skill_content = arch_skill.get("content", "") if arch_skill else ""

    # 2) Fall back to local project skill
    if not skill_content:
        local = _load_local_diagram_skill()
        if local:
            w = safe_stream_writer()
            w(
                {
                    "type": "progress",
                    "phase": "PLAN",
                    "step": "diagram",
                    "detail": "Using local architecture-diagram-generator skill",
                    "ts": time.time(),
                }
            )
            skill_content = local

    # 3) Fall back to inline instructions + LLM
    if not skill_content:
        w = safe_stream_writer()
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "diagram",
                "detail": "No diagram skill found; using inline LLM generation",
                "ts": time.time(),
            }
        )
        skill_content = _DIAGRAM_SKILL_INSTRUCTIONS

    spec = spec[: bounds.context.diagram_spec_chars]
    plan = plan[: bounds.context.diagram_plan_chars]
    tasks = tasks[: bounds.context.diagram_tasks_chars]
    doubt = doubt[: bounds.context.diagram_doubt_chars]
    context = f"Spec:\n{spec}\n\nPlan:\n{plan}\n\nTasks:\n{tasks}\n\nDoubt Resolution:\n{doubt}"
    task = f"Generate a {diagram_type} diagram as a Mermaid graph. Include all components, relationships, and data flows. Use the spec and plan as the primary source of truth."
    diagram = invoke_skill(
        skill_content,
        task,
        context,
        llm=None,
        workflow_id=state.get("project_name", ""),
        phase="PLAN",
    )
    return diagram


def _generate_all_diagrams(skills: dict, state: dict) -> dict[str, str]:
    project_folder = state.get("project_folder", state.get("project_path", ""))
    diagrams_dir = Path(project_folder) / "build" / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    # ── Guard: skip LLM calls if context is too thin ──
    spec = state.get("artifacts", {}).get("spec_refined", "")
    plan = state.get("artifacts", {}).get("plan", "")
    interview = state.get("artifacts", {}).get("interview_notes", "")
    context_length = len(f"{spec}{plan}{interview}".strip())
    _DIAGRAM_PLACEHOLDER = (
        'flowchart TD\n    NOTE["⚠ Insufficient context for diagram generation."]'
    )

    # W4: per-use-case sequence views replace the generic "sequence" view
    # only when use cases are found; the generic view stays as the fallback
    # (behaviour identical to pre-W4 when no use cases are available).
    use_cases = _extract_use_cases(state.get("artifacts", {}))
    uc_entries: list[tuple[str, str, str]] = []  # (key, use case, filename)
    used_keys: set[str] = set()
    for uc in use_cases:
        base = _slugify(uc)
        slug, n = base, 2
        while f"sequence_{slug}" in used_keys:
            slug = f"{base}-{n}"
            n += 1
        key = f"sequence_{slug}"
        used_keys.add(key)
        uc_entries.append((key, uc, f"{key.replace('_', '-')}.mmd"))

    diagram_types = [
        ("component", "component-diagram.mmd"),
        ("data flow", "data-flow.mmd"),
        ("deployment", "deployment-diagram.mmd"),
    ]
    if not uc_entries:
        # fallback: today's 4-view set including the generic sequence view
        diagram_types.insert(1, ("sequence", "sequence-diagram.mmd"))

    if context_length < 200:
        w = safe_stream_writer()
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "diagram",
                "detail": "Skipping diagram generation — insufficient project context",
                "ts": time.time(),
            }
        )
        diagrams = {}
        for dtype, filename in diagram_types:
            filepath = diagrams_dir / filename
            filepath.write_text(_DIAGRAM_PLACEHOLDER)
            diagrams[dtype] = str(filepath)
        for key, _uc, filename in uc_entries:
            filepath = diagrams_dir / filename
            filepath.write_text(_DIAGRAM_PLACEHOLDER)
            diagrams[key] = str(filepath)
        return diagrams

    diagrams = {}

    # ── Parallel LLM calls: base views + one sequence view per use case ──
    spec_cap = state.get("artifacts", {}).get("spec_refined", "")[
        : bounds.context.diagram_spec_chars
    ]
    plan_cap = state.get("artifacts", {}).get("plan", "")[
        : bounds.context.diagram_plan_chars
    ]

    async def _run_parallel():
        tasks = []
        for dtype, filename in diagram_types:
            w = safe_stream_writer()
            w(
                {
                    "type": "progress",
                    "phase": "PLAN",
                    "step": "diagram",
                    "detail": f"Generating {dtype} diagram (parallel)...",
                    "ts": time.time(),
                }
            )
            tasks.append(
                invoke_skill_async(
                    skill_content=_get_diagram_skill(skills),
                    task=f"Generate a {dtype} diagram as a Mermaid graph. Include all components, relationships, and data flows. Use the spec and plan as the primary source of truth.",
                    context=_build_diagram_context(state),
                    llm=None,
                    workflow_id=state.get("project_name", ""),
                    phase="PLAN",
                )
            )
        for key, uc, filename in uc_entries:
            w = safe_stream_writer()
            w(
                {
                    "type": "progress",
                    "phase": "PLAN",
                    "step": "diagram",
                    "detail": f"Generating sequence diagram for use case '{uc}' (parallel)...",
                    "ts": time.time(),
                }
            )
            tasks.append(
                invoke_skill_async(
                    skill_content=_get_diagram_skill(skills),
                    task=(
                        f"Generate a UML sequence diagram (mermaid `sequenceDiagram`) for the use "
                        f"case: {uc}. Show participant interactions, all components and data "
                        f"flows involved. Use the spec and plan as the primary source of truth."
                    ),
                    context=(
                        f"Spec:\n{spec_cap}\n\nPlan:\n{plan_cap}\n\nUse case:\n{uc}"
                    ),
                    llm=None,
                    workflow_id=state.get("project_name", ""),
                    phase="PLAN",
                )
            )
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(_run_parallel())
    entries = [(k, f) for (k, f) in diagram_types] + [
        (k, f) for (k, _uc, f) in uc_entries
    ]
    for (key, filename), result in zip(entries, results):
        diagram_text: str
        if result is None or isinstance(result, Exception):
            # Decision 3: None = fatal LLM failure → placeholder, never raise.
            detail = (
                f"Diagram {key} LLM call failed"
                if result is None
                else f"Diagram {key} failed: {result}"
            )
            w = safe_stream_writer()
            w(
                {
                    "type": "error" if result is None else "progress",
                    "phase": "PLAN",
                    "step": "diagram",
                    "detail": detail,
                    "ts": time.time(),
                }
            )
            diagram_text = _DIAGRAM_PLACEHOLDER
        else:
            diagram_text = str(result)
        filepath = diagrams_dir / filename
        filepath.write_text(diagram_text)
        diagrams[key] = str(filepath)
    return diagrams


def _convert_diagrams_to_png(diagrams: dict[str, str]) -> dict[str, str]:
    import asyncio
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))
    from tools.convert_diagrams import extract_mermaids, make_html

    conversions: list[tuple[str, _Path, _Path, bool]] = []
    for dtype, mmd_path_str in diagrams.items():
        mmd_path = Path(mmd_path_str)
        if not mmd_path.exists():
            continue
        blocks = extract_mermaids(mmd_path.read_text())
        for idx, block in enumerate(blocks, 1):
            is_primary = idx == 1
            name = (
                f"{mmd_path.stem}.png"
                if len(blocks) <= 1
                else f"{mmd_path.stem}-{idx}.png"
            )
            png_path = _Path(str(mmd_path.parent) + "/" + name)
            try:
                tmp_html_path = make_html(block)
                conversions.append((dtype, _Path(tmp_html_path), png_path, is_primary))
            except Exception as e:
                w = safe_stream_writer()
                w(
                    {
                        "type": "progress",
                        "phase": "PLAN",
                        "step": "diagram_png",
                        "detail": f"Failed to prepare {dtype} block {idx}: {e}",
                        "ts": time.time(),
                    }
                )

    if not conversions:
        return {}

    async def _batch_convert(convs):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1400, "height": 1000})
            results: dict[str, str] = {}
            extra: dict[str, list[str]] = {}
            for dtype, tmp_html, png_path, is_primary in convs:
                try:
                    await page.goto(f"file://{tmp_html.resolve()}")
                    await page.wait_for_timeout(5000)
                    await page.screenshot(path=str(png_path), full_page=False)
                    if is_primary:
                        results[dtype] = str(png_path)
                    else:
                        extra.setdefault(dtype, []).append(str(png_path))
                    w = safe_stream_writer()
                    w(
                        {
                            "type": "progress",
                            "phase": "PLAN",
                            "step": "diagram_png",
                            "detail": f"{tmp_html.name} → {png_path.name}",
                            "ts": time.time(),
                        }
                    )
                except Exception as e:
                    w = safe_stream_writer()
                    w(
                        {
                            "type": "progress",
                            "phase": "PLAN",
                            "step": "diagram_png",
                            "detail": f"Failed to convert {dtype}: {e}",
                            "ts": time.time(),
                        }
                    )
            await browser.close()
            return results, extra

    result, extra_pngs = asyncio.run(_batch_convert(conversions))

    for _, tmp_html, _, _ in conversions:
        try:
            os.unlink(str(tmp_html))
        except OSError:
            pass
    return result
