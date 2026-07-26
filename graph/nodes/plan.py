"""
PLAN node: Generate implementation plan, tasks, analysis, and architecture diagrams.
Outputs: $project_folder/build/solution.md — complete solution design with diagrams.

Skill chain:
  planning-and-task-breakdown → doubt-driven-development → architecture-diagram-generator
"""
import os
import re
from pathlib import Path
from config.loader import config as _cfg
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.context_manager import prepare_context_for_llm
from tools.audit_logger import AuditLog
from feedback.chroma_client import get_chroma_client, query_patterns
from graph.ui_bridge import SkillTimer


def plan_node(state: dict) -> dict:
    """
    PLAN phase: Generate implementation plan using framework skill chain.

    Flow:
      planning-and-task-breakdown → doubt-driven-development → architecture-diagram-generator

    Returns partial update dict (LangGraph reducer merges).
    """
    print("\n=== PLAN PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("PLAN", {
        "has_spec": bool(state.get("artifacts", {}).get("spec_refined")),
        "has_interview": bool(state.get("artifacts", {}).get("interview_notes")),
    })

    # ── Load skills (lazy-load via cached registry) ──
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    feedback_entries: list[dict] = []

    # ── Load historical feedback context ──
    feedback_context = _load_feedback_context(state)

    # Build context for all skill invocations
    spec = state.get("artifacts", {}).get("spec_refined", "")
    interview = state.get("artifacts", {}).get("interview_notes", "")
    context_parts = [spec]
    if interview:
        context_parts.append(f"Interview notes:\n{interview}")
    if feedback_context:
        context_parts.append(f"\n\n{feedback_context}\n")
    base_context = "\n\n".join(context_parts)

    artifacts_delta: dict[str, str] = {}

    # ── Step 1: Generate structured task breakdown with milestones and dependencies ──
    plan_skill = skills.get("planning-and-task-breakdown", {})
    plan_result = None
    if plan_skill:
        print("  → Running planning-and-task-breakdown...")
        optimized = prepare_context_for_llm({"context": base_context}, max_tokens=bounds.context.plan_max_tokens)
        plan_result = invoke_skill(
            plan_skill["content"],
            "Break down the implementation into structured tasks with milestones, dependencies, effort estimates, and acceptance criteria. Use vertical slicing. Output phases (Foundation, Core Features, Polish) with checkpoints between them. Include a dependency graph, risk table, and parallelization notes.",
            optimized["context"],
            llm=None
        )
        artifacts_delta["plan"] = plan_result[:bounds.artifacts.max_plan_chars]
        # Store structured task breakdown as separate artifact for downstream phases
        # "task_breakdown" = detailed structure, "tasks" = compat key for solution.md + BUILD
        artifacts_delta["task_breakdown"] = plan_result[:bounds.artifacts.max_plan_chars]
        artifacts_delta["tasks"] = plan_result[:bounds.artifacts.max_plan_chars]
        feedback_entries.append({"skill": "planning-and-task-breakdown", "output": plan_result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 2: Doubt-driven development (challenge assumptions) ──
    doubt_skill = skills.get("doubt-driven-development", {})
    doubt_result = None
    if doubt_skill:
        print("  → Running doubt-driven-development...")
        doubt_result = invoke_skill(
            doubt_skill["content"],
            "Challenge the architectural assumptions in the plan. Be concise — focus on top 3 risks only.",
            artifacts_delta.get("plan", state.get("artifacts", {}).get("plan", ""))[:bounds.artifacts.max_analysis_chars],
            llm=None
        )
        artifacts_delta["doubt_resolution"] = doubt_result[:bounds.artifacts.max_doubt_chars]
        feedback_entries.append({"skill": "doubt-driven-development", "output": doubt_result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 9: Generate architecture diagrams ──
    print("  → Running architecture-diagram-generator...")
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
    print(f"  → solution.md written: {solution_path} ({len(solution_md)} chars)")

    # Store in artifacts for openhands_build to pick up
    artifacts_delta["solution_md"] = solution_md
    artifacts_delta["solution_path"] = str(solution_path)
    artifacts_delta["diagrams"] = diagrams

    diagram_count = len(diagrams)
    # Extract task count
    task_count = 1
    if plan_result:
        task_count = plan_result.count("- [") + plan_result.count("1.") + plan_result.count("2.") + plan_result.count("3.")

    # ── Derive architectural uncertainty ──
    merged_artifacts = {**state.get("artifacts", {}), **artifacts_delta}
    arch_uncertainty = _estimate_arch_uncertainty(merged_artifacts)

    # ── Audit output ──
    audit.log_node_output("PLAN", {
        "solution_path": str(solution_path),
        "diagram_count": diagram_count,
        "task_count": task_count,
        "arch_uncertainty": arch_uncertainty,
    })
    audit.log_node_transition("PLAN", "BUILD", "plan generation complete")

    # Update metrics
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(update={
            "task_count": max(task_count, 1),
            "diagram_count": diagram_count,
            "arch_uncertainty": arch_uncertainty,
        })

    print(f"  ✓ task_count={task_count}, arch_uncertainty={arch_uncertainty:.2f}, diagrams={diagram_count}")

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


def _load_feedback_context(state: dict) -> str:
    """Query ChromaDB for historical patterns relevant to this project type."""
    try:
        client = get_chroma_client()
        if client is None:
            return ""
        project_name = state.get("project_name", "unknown")
        query_text = f"project: {project_name} phase: plan"
        results = query_patterns(client, {"project": project_name, "context": query_text}, top_k=bounds.feedback.max_chroma_patterns)
        if not results:
            return ""
        parts = ["== Historical Planning Lessons =="]
        for i, pat in enumerate(results, 1):
            doc = pat.get("document", "")
            parts.append(f"\n[Past Cycle {i}] (distance: {pat.get('distance', '?'):.3f})\n{doc[:bounds.feedback.max_pattern_doc_chars]}")
        parts.append("\n== End Historical Lessons ==")
        return "\n".join(parts)
    except Exception as e:
        return ""


def _estimate_arch_uncertainty(artifacts: dict) -> float:
    score = 0.6
    plan_text = artifacts.get("plan", "")
    doubt_text = artifacts.get("doubt_resolution", "")
    diagrams = artifacts.get("diagrams", {})

    if len(plan_text) > 200:
        score -= 0.15
    if len(doubt_text) > 50:
        score -= 0.1
    if diagrams:
        score -= 0.1
    return max(0.0, min(1.0, score))


# ── Inline skill instructions for diagram generation (fallback) ──
_DIAGRAM_SKILL_INSTRUCTIONS = """You are an architecture diagram generator. Your job is to produce valid Mermaid syntax diagrams.

Rules:
- Output ONLY a Mermaid code block, nothing else.
- Use the appropriate Mermaid diagram type for the request.
- Include all components, relationships, and data flows mentioned in the context.
- Mark assumed components with a note.

Diagram type mappings:
- "component" → use `graph TD` with subgraphs for modules/boundaries
- "sequence" → use `sequenceDiagram` with participant interactions
- "data flow" → use `graph LR` or `graph TD` showing entity relationships and data movement
- "deployment" → use `graph TD` with infrastructure nodes (servers, containers, networks)"""

def _load_local_diagram_skill() -> str | None:
    """Load architecture-diagram-generator skill from local project skills dir."""
    local_path = Path(__file__).resolve().parent.parent.parent / "skills" / "architecture-diagram-generator" / "SKILL.md"
    if local_path.exists():
        return local_path.read_text().split("---", 2)[-1].strip()
    return None

def _generate_diagram(skills: dict, diagram_type: str, state: dict) -> str:
    _DIAGRAM_PLACEHOLDER = 'flowchart TD\n    NOTE["⚠ Insufficient context for diagram generation."]'

    spec = state.get("artifacts", {}).get("spec_refined", "")
    plan = state.get("artifacts", {}).get("plan", "")
    tasks = state.get("artifacts", {}).get("tasks", "")
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")
    combined = f"{spec}{plan}{tasks}{doubt}".strip()

    # Guard: if no real context, return placeholder instead of feeding empty input to LLM
    if not combined:
        print(f"  ⚠ Empty context for {diagram_type} diagram; using placeholder")
        return _DIAGRAM_PLACEHOLDER

    # 1) Try the registered skill first
    arch_skill = skills.get("architecture-diagram-generator", {})
    skill_content = arch_skill.get("content", "") if arch_skill else ""

    # 2) Fall back to local project skill
    if not skill_content:
        local = _load_local_diagram_skill()
        if local:
            print(f"  → Using local architecture-diagram-generator skill")
            skill_content = local

    # 3) Fall back to inline instructions + LLM
    if not skill_content:
        print(f"  → No diagram skill found; using inline LLM generation")
        skill_content = _DIAGRAM_SKILL_INSTRUCTIONS

    spec = spec[:bounds.context.diagram_spec_chars]
    plan = plan[:bounds.context.diagram_plan_chars]
    tasks = tasks[:bounds.context.diagram_tasks_chars]
    doubt = doubt[:bounds.context.diagram_doubt_chars]
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
    _DIAGRAM_PLACEHOLDER = 'flowchart TD\n    NOTE["⚠ Insufficient context for diagram generation."]'

    if context_length < 200:
        print("  ⚠ Skipping diagram generation — insufficient project context")
        diagrams = {}
        diagram_types = [
            ("component", "component-diagram.mmd"),
            ("sequence", "sequence-diagram.mmd"),
            ("data flow", "data-flow.mmd"),
            ("deployment", "deployment-diagram.mmd"),
        ]
        for dtype, filename in diagram_types:
            filepath = diagrams_dir / filename
            filepath.write_text(_DIAGRAM_PLACEHOLDER)
            diagrams[dtype] = str(filepath)
        return diagrams

    diagrams = {}
    diagram_types = [
        ("component", "component-diagram.mmd"),
        ("sequence", "sequence-diagram.mmd"),
        ("data flow", "data-flow.mmd"),
        ("deployment", "deployment-diagram.mmd"),
    ]
    for dtype, filename in diagram_types:
        print(f"  → Generating {dtype} diagram...")
        diagram = _generate_diagram(skills, dtype, state)
        filepath = diagrams_dir / filename
        filepath.write_text(diagram)
        diagrams[dtype] = str(filepath)
    return diagrams


def _convert_diagrams_to_png(diagrams: dict[str, str]) -> dict[str, str]:
    import asyncio
    import os
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))
    from tools.convert_diagrams import extract_mermaid, extract_mermaids, make_html

    conversions: list[tuple[str, _Path, _Path, bool]] = []
    for dtype, mmd_path_str in diagrams.items():
        mmd_path = Path(mmd_path_str)
        if not mmd_path.exists():
            continue
        blocks = extract_mermaids(mmd_path.read_text())
        for idx, block in enumerate(blocks, 1):
            is_primary = (idx == 1)
            name = f"{mmd_path.stem}.png" if len(blocks) <= 1 else f"{mmd_path.stem}-{idx}.png"
            png_path = _Path(str(mmd_path.parent) + "/" + name)
            try:
                tmp_html_path = make_html(block)
                conversions.append((dtype, _Path(tmp_html_path), png_path, is_primary))
            except Exception as e:
                print(f"  ⚠ Failed to prepare {dtype} block {idx}: {e}")

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
                    print(f"  ✓ {tmp_html.name} → {png_path.name}")
                except Exception as e:
                    print(f"  ⚠ Failed to convert {dtype}: {e}")
            await browser.close()
            return results, extra

    result, extra_pngs = asyncio.run(_batch_convert(conversions))

    for _, tmp_html, _, _ in conversions:
        try:
            os.unlink(str(tmp_html))
        except OSError:
            pass
    return result


def _generate_solution_md(state: dict, artifacts_delta: dict) -> str:
    """Generate comprehensive solution.md from all PLAN artifacts.

    Always produces meaningful output — falls back to state-level data
    (project_description, project_context, interview_notes, requirement_md)
    when LLM-generated artifacts are missing or empty.
    """
    merged = {**state.get("artifacts", {}), **artifacts_delta}

    # ── Diagnostic logging ──
    artifact_keys = ["spec_refined", "plan", "tasks", "analysis", "doubt_resolution", "checklist"]
    available = [k for k in artifact_keys if merged.get(k)]
    missing = [k for k in artifact_keys if not merged.get(k)]
    if missing:
        print(f"  ⚠ Solution.md: missing artifacts: {', '.join(missing)}")
    if available:
        print(f"  ✓ Solution.md: has artifacts: {', '.join(available)}")

    lines = ["# Solution Design", ""]

    project_name = state.get("project_name", "Project")
    lines.append(f"## {project_name} — Solution Design")
    lines.append("")

    # ── Always include project description ──
    project_desc = state.get("project_description", "")
    if project_desc:
        lines.extend(["## Project Description", project_desc, ""])

    # ── Always include interview notes (source requirements from DISCOVER) ──
    interview = merged.get("interview_notes", "")
    if interview:
        lines.extend(["## Interview Notes", interview, ""])

    # ── Always include project context from DISCOVER (if spec not generated) ──
    project_context = merged.get("project_context", "")
    if project_context and not merged.get("spec_refined"):
        lines.extend(["## Project Context (from DISCOVER)", project_context, ""])

    # ── Always include requirement_md (if spec not generated) ──
    requirement_md = merged.get("requirement_md", "")
    if requirement_md and not merged.get("spec_refined"):
        lines.extend(["## Requirements", requirement_md, ""])

    # ── LLM-generated artifacts (spec, plan, tasks, etc.) ──
    spec = merged.get("spec_refined", "")
    if spec:
        lines.extend(["## Specification", spec, ""])

    plan = merged.get("plan", "")
    if plan:
        lines.extend(["## Implementation Plan", plan, ""])

    tasks = merged.get("tasks", "")
    if tasks:
        lines.extend(["## Task Breakdown", tasks, ""])

    analysis = merged.get("analysis", "")
    if analysis:
        lines.extend(["## Cross-Artifact Analysis", analysis, ""])

    doubt = merged.get("doubt_resolution", "")
    if doubt:
        lines.extend(["## Doubt Resolution", doubt, ""])

    checklist = merged.get("checklist", "")
    if checklist:
        lines.extend(["## Implementation Checklist", checklist, ""])

    # ── API contract (from DEFINE phase) ──
    api_contract = merged.get("api_contract", "")
    if api_contract:
        lines.extend(["## API Contract", api_contract, ""])

    # ── Architecture diagrams ──
    diagrams = merged.get("diagrams", {})
    if diagrams:
        lines.extend(["## Architecture Diagrams", ""])
        _DIAGRAM_PLACEHOLDER_MARKER = "Insufficient context for diagram generation"
        has_placeholder = False
        for dtype, filepath in diagrams.items():
            lines.append(f"### {dtype.replace('-', ' ').title()}")
            lines.append("```mermaid")
            try:
                diagram_content = Path(filepath).read_text()
                if _DIAGRAM_PLACEHOLDER_MARKER in diagram_content:
                    has_placeholder = True
                lines.append(diagram_content)
            except Exception:
                lines.append(f"(diagram file: {filepath})")
            lines.append("```")
            lines.append("")
        if has_placeholder:
            lines.extend([
                "> **Note:** Architecture diagrams could not be generated — insufficient project context from DISCOVER/DEFINE phases.",
                "",
            ])

    # ── Metrics (safe formatting — handles non-numeric values) ──
    lines.extend(["## Metrics", ""])
    metrics = state.get("metrics")
    if hasattr(metrics, "model_dump"):
        md = metrics.model_dump()
    else:
        md = metrics or {}

    arch_unc = md.get("arch_uncertainty", "N/A")
    if isinstance(arch_unc, (int, float)):
        lines.append(f"- **Architectural Uncertainty**: {arch_unc:.2f}")
    else:
        lines.append(f"- **Architectural Uncertainty**: {arch_unc}")

    task_count = md.get("task_count", "N/A")
    lines.append(f"- **Task Count**: {task_count}")
    diagram_count = md.get("diagram_count", "N/A")
    lines.append(f"- **Diagram Count**: {diagram_count}")
    lines.append("")

    # ── Note about missing artifacts ──
    if missing:
        lines.extend([
            "## Notes",
            f"*Artifacts not generated (may need LLM connection or skill configuration):* {', '.join(missing)}",
            "",
        ])

    lines.append("---")
    lines.append("*Generated by Loop Engineering PLAN phase*")

    return "\n".join(lines)