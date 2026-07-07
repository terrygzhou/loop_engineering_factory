"""
PLAN node: Generate implementation plan, tasks, analysis, and architecture diagrams.
Outputs: $project_folder/build/solution.md — complete solution design with diagrams.

Skills: writing-plans → speckit-tasks → speckit-analyze → doubt-driven-development → 
         speckit-checklist → architecture-diagram-generator
"""
import json
import os
import re
from pathlib import Path
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
        results = query_patterns(client, {"project": project_name, "context": query_text}, top_k=3)
        if not results:
            return ""
        parts = ["== Historical Planning Lessons =="]
        for i, pat in enumerate(results, 1):
            doc = pat.get("document", "")
            parts.append(f"\n[Past Cycle {i}] (distance: {pat.get('distance', '?'):.3f})\n{doc[:400]}")
        parts.append("\n== End Historical Lessons ==")
        return "\n".join(parts)
    except Exception as e:
        import os
        if os.environ.get("CHROMA_URL"):
            print(f"  ⚠ Could not load historical feedback: {e}")
        return ""


def _estimate_arch_uncertainty(artifacts: dict) -> float:
    """
    Derive architectural uncertainty from actual plan artifacts.
    Lower = more confident. Scoring starts at 0.6 and reduces:
    - Has plan with >200 chars: -0.15
    - Has tasks with >5 items: -0.15
    - Has analysis: -0.1
    - Has doubt_resolution: -0.1
    - Has checklist: -0.05
    - Has diagrams: -0.1
    Range: [0.0, 1.0]
    """
    score = 0.6
    plan_text = artifacts.get("plan", "")
    tasks_text = artifacts.get("tasks", "")
    analysis_text = artifacts.get("analysis", "")
    doubt_text = artifacts.get("doubt_resolution", "")
    checklist_text = artifacts.get("checklist", "")

    if len(plan_text) > 200:
        score -= 0.15
    task_items = len(re.findall(r'^\s*[-*]\s*[\-\[]', tasks_text, re.MULTILINE)) + len(re.findall(r'^\s*\d+\.\s', tasks_text, re.MULTILINE))
    if task_items >= 5:
        score -= 0.15
    elif task_items >= 1:
        score -= 0.1
    if len(analysis_text) > 50:
        score -= 0.1
    if len(doubt_text) > 50:
        score -= 0.1
    if len(checklist_text) > 50:
        score -= 0.05
    diagrams = artifacts.get("diagrams", {})
    if diagrams:
        score -= 0.1
    analysis_lower = analysis_text.lower()
    if any(kw in analysis_lower for kw in ["low risk", "solid", "clear path", "straightforward"]):
        score -= 0.05
    if any(kw in analysis_lower for kw in ["unclear", "unknown", "high risk", "major concern"]):
        score += 0.15
    return max(0.0, min(1.0, score))


def _generate_diagram(skills: dict, diagram_type: str, state: dict) -> str:
    """Generate a specific diagram type from workflow artifacts."""
    arch_skill = skills.get("architecture-diagram-generator", {})
    if not arch_skill:
        return f"# {diagram_type} - skill not available"
    spec = state.get("artifacts", {}).get("spec_refined", "")
    plan = state.get("artifacts", {}).get("plan", "")
    tasks = state.get("artifacts", {}).get("tasks", "")
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")
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
    """Convert .mmd diagrams to PNG for UI rendering (single browser session)."""
    import asyncio
    import os
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))
    from tools.convert_diagrams import extract_mermaid, make_html

    # Collect all (type, html_path, png_path) tuples first
    conversions = []
    for dtype, mmd_path_str in diagrams.items():
        mmd_path = Path(mmd_path_str)
        if not mmd_path.exists():
            continue
        png_path = _Path(str(mmd_path.parent) + "/" + mmd_path.stem + ".png")
        try:
            content = mmd_path.read_text()
            mermaid_content = extract_mermaid(content)
            tmp_html_path = make_html(mermaid_content)
            conversions.append((dtype, mmd_path, _Path(tmp_html_path), png_path))
        except Exception as e:
            print(f"  ⚠ Failed to prepare {dtype}: {e}")

    if not conversions:
        return {}

    async def _batch_convert(convs):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1400, "height": 1000})
            results = {}
            for dtype, mmd_path, tmp_html, png_path in convs:
                try:
                    await page.goto(f"file://{tmp_html.resolve()}")
                    await page.wait_for_timeout(5000)
                    await page.screenshot(path=str(png_path), full_page=False)
                    results[dtype] = str(png_path)
                    print(f"  ✓ {mmd_path.name} → {png_path.name}")
                except Exception as e:
                    print(f"  ⚠ Failed to convert {dtype}: {e}")
            await browser.close()
            return results

    png_paths = asyncio.run(_batch_convert(conversions))

    # Clean up temp HTML files
    for _, _, tmp_html, _ in conversions:
        try:
            os.unlink(str(tmp_html))
        except OSError:
            pass
    return png_paths


def plan_node(state: dict) -> dict:
    """
    PLAN phase: Generate implementation plan, tasks, analysis, and architecture diagrams.

    Input:
      - spec_refined: Specification from DEFINE phase
      - interview_notes: Interview results
      - feedback_context: Historical patterns
      - project_folder: Target directory

    Output:
      - $project_folder/build/solution.md: Complete solution design with diagrams
      - $project_folder/build/diagrams/: Mermaid diagram files
      - state["artifacts"]["plan"], "tasks", "analysis", "doubt_resolution", "checklist", "diagrams"
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
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    # ── Load historical feedback context ──
    feedback_context = _load_feedback_context(state)
    state["feedback_context"] = feedback_context

    # ── Step 1: Generate plan ──
    plan_skill = skills.get("writing-plans", {})
    if plan_skill:
        print("  → Running writing-plans...")
        spec = state.get("artifacts", {}).get("spec_refined", "")
        context = spec
        if feedback_context:
            context += f"\n\n{feedback_context}\n"
        # Context optimization
        optimized = prepare_context_for_llm({"context": context}, max_tokens=16000)
        task = f"Create implementation plan for: {state.get('spec_path', '')}"
        result = invoke_skill(plan_skill["content"], task, optimized["context"], llm=None)
        state["artifacts"]["plan"] = result
        feedback.append({"skill": "writing-plans", "output": result[:300]})

    # ── Step 2: Break into tasks ──
    tasks_skill = skills.get("speckit-tasks", {})
    if tasks_skill:
        print("  → Running speckit-tasks...")
        task = "Break the plan into actionable, dependency-ordered tasks"
        result = invoke_skill(tasks_skill["content"], task,
                             state.get("artifacts", {}).get("plan", ""),
                             llm=None)
        state["artifacts"]["tasks"] = result
        task_count = result.count("- [") + result.count("1.") + result.count("2.") + result.count("3.")
        state["metrics"] = state["metrics"].model_copy(update={
            "task_count": max(task_count, 1),
        })
        feedback.append({"skill": "speckit-tasks", "output": result[:300]})

    # ── Step 3: Analyze cross-artifact consistency ──
    analyze_skill = skills.get("speckit-analyze", {})
    if analyze_skill:
        print("  → Running speckit-analyze...")
        task = "Analyze consistency between spec, plan, and tasks"
        result = invoke_skill(analyze_skill["content"], task,
                             state.get("artifacts", {}).get("plan", ""),
                             llm=None)
        state["artifacts"]["analysis"] = result
        feedback.append({"skill": "speckit-analyze", "output": result[:300]})

    # ── Step 4: Doubt-driven development (challenge assumptions) ──
    doubt_skill = skills.get("doubt-driven-development", {})
    if doubt_skill:
        print("  → Running doubt-driven-development...")
        task = "Challenge the architectural assumptions in the plan"
        result = invoke_skill(doubt_skill["content"], task,
                             state.get("artifacts", {}).get("plan", ""),
                             llm=None)
        state["artifacts"]["doubt_resolution"] = result
        feedback.append({"skill": "doubt-driven-development", "output": result[:300]})

    # ── Step 5: Generate checklist ──
    checklist_skill = skills.get("speckit-checklist", {})
    if checklist_skill:
        print("  → Running speckit-checklist...")
        task = "Generate a custom checklist for this feature"
        result = invoke_skill(checklist_skill["content"], task,
                             state.get("artifacts", {}).get("spec_refined", ""),
                             llm=None)
        state["artifacts"]["checklist"] = result
        feedback.append({"skill": "speckit-checklist", "output": result[:300]})

    # ── Step 6: Generate architecture diagrams ──
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

    # ── Audit output ──
    audit.log_node_output("PLAN", {
        "solution_path": str(solution_path),
        "diagram_count": diagram_count,
        "task_count": state["metrics"].task_count,
        "arch_uncertainty": arch_uncertainty,
    })
    audit.log_node_transition("PLAN", "BUILD", "plan generation complete")

    state["phase"] = "PLAN"
    state["feedback"] = state.get("feedback", []) + feedback
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
