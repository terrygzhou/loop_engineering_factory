"""
PLAN node: Generate implementation plan, tasks, analysis, and architecture diagrams.
Outputs: $project_folder/build/solution.md — complete solution design with diagrams.

Skill chain:
  writing-plans → doubt-driven-development → architecture-diagram-generator
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
    """
    Derive architectural uncertainty from actual plan artifacts.
    Lower = more confident. Scoring starts at 0.6 and reduces:
    - Has plan with >200 chars: -0.15
    - Has doubt_resolution: -0.1
    - Has diagrams: -0.1
    Range: [0.0, 1.0]
    """
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

def _generate_diagram(skills: dict, diagram_type: str, state: dict) -> str:
    """Generate a specific diagram type from workflow artifacts."""
    arch_skill = skills.get("architecture-diagram-generator", {})
    if not arch_skill:
        return f"# {diagram_type} - skill not available"
    spec = state.get("artifacts", {}).get("spec_refined", "")[:bounds.context.diagram_spec_chars]
    plan = state.get("artifacts", {}).get("plan", "")[:bounds.context.diagram_plan_chars]
    tasks = state.get("artifacts", {}).get("tasks", "")[:bounds.context.diagram_tasks_chars]
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")[:bounds.context.diagram_doubt_chars]
    context = f"Spec:\n{spec}\n\nPlan:\n{plan}\n\nTasks:\n{tasks}\n\nDoubt Resolution:\n{doubt}"
    task = f"Generate a {diagram_type} diagram as a Mermaid graph. Include all components, relationships, and data flows. Use the spec and plan as the primary source of truth."
    diagram = invoke_skill(
        arch_skill["content"],
        task,
        context,
        llm=None,
        workflow_id=state.get("project_name", ""),
        phase="PLAN",
    )
    return diagram

def _generate_all_diagrams(skills: dict, state: dict) -> dict[str, str]:
    """Generate all architecture diagrams and save to build/diagrams/."""
    project_folder = state.get("project_folder", state.get("project_path", ""))
    diagrams_dir = Path(project_folder) / "build" / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

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
    """Convert .mmd diagrams to PNG for UI rendering (single browser session).

    Returns dict[str, str] mapping dtype → first PNG path (backward-compatible).
    If a .mmd file contains multiple mermaid blocks, only the first block is rendered.
    Additional PNGs are stored in state["diagram_extra_pngs"] as dict[str, list[str]].
    """
    import asyncio
    import os
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))
    from tools.convert_diagrams import extract_mermaid, extract_mermaids, make_html

    # Collect all (type, html_path, png_path, is_primary) tuples
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

    # Clean up temp HTML files
    for _, tmp_html, _, _ in conversions:
        try:
            os.unlink(str(tmp_html))
        except OSError:
            pass
    return result

def plan_node(state: dict) -> dict:
    """
    PLAN phase: Generate implementation plan using framework skill chain.

    Flow:
      writing-plans → doubt-driven-development → architecture-diagram-generator

    Input:
      - spec_refined: Specification from DEFINE phase
      - interview_notes: Interview results
      - feedback_context: Historical patterns
      - project_folder: Target directory

    Output:
      - $project_folder/build/solution.md: Complete solution design with diagrams
      - $project_folder/build/diagrams/: Mermaid diagram files
      - state["artifacts"]["plan"], "tasks", "analysis", "checklist", "diagrams"
      - state["artifacts"]["conformance"]: Spec↔plan alignment report
    """
    print("\n=== PLAN PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("PLAN", {
        "has_spec": bool(state.get("artifacts", {}).get("spec_refined")),
        "has_interview": bool(state.get("artifacts", {}).get("interview_notes")),
    })

    # ── Load skills ──
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(_cfg.workflow.skill_registry_path)
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    # ── Load historical feedback context ──
    feedback_context = _load_feedback_context(state)
    state["feedback_context"] = feedback_context

    # Build context for all skill invocations
    spec = state.get("artifacts", {}).get("spec_refined", "")
    interview = state.get("artifacts", {}).get("interview_notes", "")
    context_parts = [spec]
    if interview:
        context_parts.append(f"Interview notes:\n{interview}")
    if feedback_context:
        context_parts.append(f"\n\n{feedback_context}\n")
    base_context = "\n\n".join(context_parts)

    # ── Step 1: Generate architecture/implementation plan ──
    plan_skill = skills.get("writing-plans", {})
    if plan_skill:
        print("  → Running writing-plans...")
        optimized = prepare_context_for_llm({"context": base_context}, max_tokens=bounds.context.plan_max_tokens)
        result = invoke_skill(
            plan_skill["content"],
            "Create implementation plan with architecture, file structure, milestones, and task breakdown. Keep it concise — max 3000 words.",
            optimized["context"],
            llm=None
        )
        state["artifacts"]["plan"] = result[:bounds.artifacts.max_plan_chars]
        # Extract task count from the plan
        task_count = result.count("- [") + result.count("1.") + result.count("2.") + result.count("3.")
        state["metrics"] = state["metrics"].model_copy(update={
            "task_count": max(task_count, 1),
        })
        feedback.append({"skill": "writing-plans", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 2: Doubt-driven development (challenge assumptions) ──
    doubt_skill = skills.get("doubt-driven-development", {})
    if doubt_skill:
        print("  → Running doubt-driven-development...")
        result = invoke_skill(
            doubt_skill["content"],
            "Challenge the architectural assumptions in the plan. Be concise — focus on top 3 risks only.",
            state.get("artifacts", {}).get("plan", "")[:bounds.artifacts.max_analysis_chars],
            llm=None
        )
        state["artifacts"]["doubt_resolution"] = result[:bounds.artifacts.max_doubt_chars]
        feedback.append({"skill": "doubt-driven-development", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 9: Generate architecture diagrams ──
    print("  → Running architecture-diagram-generator...")
    diagrams = _generate_all_diagrams(skills, state)

    # ── Convert diagrams to PNG ──
    png_paths = _convert_diagrams_to_png(diagrams)
    state["artifacts"]["diagram_pngs"] = png_paths

    state["artifacts"]["diagrams"] = diagrams
    state["diagrams"] = diagrams
    state["diagram_status"] = "pending"
    diagram_count = len(diagrams)
    state["metrics"] = state["metrics"].model_copy(update={
        "diagram_count": diagram_count,
    })
    feedback.append({"skill": "architecture-diagram-generator", "output": f"Generated {diagram_count} diagrams + {len(png_paths)} PNGs"})

    # ── Derive architectural uncertainty ──
    arch_uncertainty = _estimate_arch_uncertainty(state["artifacts"])
    state["metrics"] = state["metrics"].model_copy(update={
        "arch_uncertainty": arch_uncertainty,
    })

    # ── Persist solution.md to $project_folder/build/ ──
    project_folder = state.get("project_folder", state.get("project_path", ""))
    build_dir = Path(project_folder) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    solution_md = _generate_solution_md(state)
    solution_path = build_dir / "solution.md"
    solution_path.write_text(solution_md)
    audit.log_file_write("PLAN", str(solution_path), "markdown", len(solution_md))
    print(f"  → solution.md written: {solution_path} ({len(solution_md)} chars)")

    # Store in artifacts for build_proxy to pick up
    state["artifacts"]["solution_md"] = solution_md
    state["artifacts"]["solution_path"] = str(solution_path)

    # ── Audit output ──
    audit.log_node_output("PLAN", {
        "solution_path": str(solution_path),
        "diagram_count": diagram_count,
        "task_count": state["metrics"].task_count,
        "arch_uncertainty": arch_uncertainty,
    })
    audit.log_node_transition("PLAN", "BUILD", "plan generation complete")

    state["phase"] = "PLAN"
    state["feedback"] = state.get("feedback", [])[-bounds.artifacts.max_feedback_entries:] + feedback
    state["next_phase"] = "BUILD"
    state["human_approval_required"] = False

    print(f"  ✓ task_count={state['metrics'].task_count}, arch_uncertainty={arch_uncertainty:.2f}, diagrams={diagram_count}")
    return state

def _generate_solution_md(state: dict) -> str:
    """Generate comprehensive solution.md from all PLAN artifacts."""
    lines = ["# Solution Design", ""]

    # Title
    project_name = state.get("project_name", "Project")
    lines.append(f"## {project_name} — Solution Design")
    lines.append("")

    # Specification summary
    spec = state.get("artifacts", {}).get("spec_refined", "")
    if spec:
        lines.append("## Specification")
        lines.append(spec)
        lines.append("")

    # Implementation plan
    plan = state.get("artifacts", {}).get("plan", "")
    if plan:
        lines.append("## Implementation Plan")
        lines.append(plan)
        lines.append("")

    # Task breakdown
    tasks = state.get("artifacts", {}).get("tasks", "")
    if tasks:
        lines.append("## Task Breakdown")
        lines.append(tasks)
        lines.append("")

    # Analysis
    analysis = state.get("artifacts", {}).get("analysis", "")
    if analysis:
        lines.append("## Cross-Artifact Analysis")
        lines.append(analysis)
        lines.append("")

    # Doubt resolution
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")
    if doubt:
        lines.append("## Doubt Resolution")
        lines.append(doubt)
        lines.append("")

    # Checklist
    checklist = state.get("artifacts", {}).get("checklist", "")
    if checklist:
        lines.append("## Implementation Checklist")
        lines.append(checklist)
        lines.append("")

    # Architecture diagrams (embedded as mermaid)
    diagrams = state.get("artifacts", {}).get("diagrams", {})
    if diagrams:
        lines.append("## Architecture Diagrams")
        lines.append("")
        for dtype, filepath in diagrams.items():
            lines.append(f"### {dtype.replace('-', ' ').title()}")
            lines.append(f"``````mermaid")
            try:
                diagram_content = Path(filepath).read_text()
                lines.append(diagram_content)
            except Exception:
                lines.append(f"(diagram file: {filepath})")
            lines.append("``````")
            lines.append("")

    # Metrics
    lines.append("## Metrics")
    metrics = state.get("metrics", {})
    if hasattr(metrics, "model_dump"):
        md = metrics.model_dump()
    else:
        md = metrics
    lines.append(f"- **Architectural Uncertainty**: {md.get('arch_uncertainty', 'N/A'):.2f}")
    lines.append(f"- **Task Count**: {md.get('task_count', 'N/A')}")
    lines.append(f"- **Diagram Count**: {md.get('diagram_count', 'N/A')}")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by Loop Engineering PLAN phase*")

    return "\n".join(lines)
