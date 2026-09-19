"""Confidence / feedback / solution-assembly concern for the PLAN node (seam split S8).

Pure helpers moved here so `plan.py` keeps only the LLM-orchestration core
(`_generate_diagram`, `_generate_all_diagrams`, the `asyncio.gather` LLM-call
site). Re-exported from `graph/nodes/plan.py` so existing test imports keep
resolving.
"""

from pathlib import Path

from config.bounds_loader import bounds
from feedback.chroma_client import get_chroma_client, query_patterns


def _load_feedback_context(state: dict) -> str:
    """Query ChromaDB for historical patterns relevant to this project type."""
    try:
        client = get_chroma_client()
        if client is None:
            return ""
        project_name = state.get("project_name", "unknown")
        query_text = f"project: {project_name} phase: plan"
        results = query_patterns(
            client,
            {"project": project_name, "context": query_text},
            top_k=bounds.feedback.max_chroma_patterns,
        )
        if not results:
            return ""
        parts = ["== Historical Planning Lessons =="]
        for i, pat in enumerate(results, 1):
            doc = pat.get("document", "")
            parts.append(
                f"\n[Past Cycle {i}] (distance: {pat.get('distance', '?'):.3f})\n{doc[: bounds.feedback.max_pattern_doc_chars]}"
            )
        parts.append("\n== End Historical Lessons ==")
        return "\n".join(parts)
    except Exception:
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


def _generate_solution_md(state: dict, artifacts_delta: dict) -> str:
    """Generate comprehensive solution.md from all PLAN artifacts.

    Always produces meaningful output — falls back to state-level data
    (project_description, project_context, interview_notes, requirement_md)
    when LLM-generated artifacts are missing or empty.
    """
    merged = {**state.get("artifacts", {}), **artifacts_delta}

    # ── Diagnostic logging ──
    artifact_keys = [
        "spec_refined",
        "plan",
        "tasks",
        "analysis",
        "doubt_resolution",
        "checklist",
    ]
    available = [k for k in artifact_keys if merged.get(k)]
    missing = [k for k in artifact_keys if not merged.get(k)]
    if missing:
        from tools.stream_writer import safe_stream_writer
        import time

        w = safe_stream_writer()
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "solution",
                "detail": f"Solution.md: missing artifacts: {', '.join(missing)}",
                "ts": time.time(),
            }
        )
    if available:
        from tools.stream_writer import safe_stream_writer
        import time

        w = safe_stream_writer()
        w(
            {
                "type": "progress",
                "phase": "PLAN",
                "step": "solution",
                "detail": f"Solution.md: has artifacts: {', '.join(available)}",
                "ts": time.time(),
            }
        )

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
            lines.extend(
                [
                    "> **Note:** Architecture diagrams could not be generated — insufficient project context from DISCOVER/DEFINE phases.",
                    "",
                ]
            )

    # ── Metrics (safe formatting — handles non-numeric values) ──
    lines.extend(["## Metrics", ""])
    metrics = state.get("metrics")
    if metrics is not None and hasattr(metrics, "model_dump"):
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
        lines.extend(
            [
                "## Notes",
                f"*Artifacts not generated (may need LLM connection or skill configuration):* {', '.join(missing)}",
                "",
            ]
        )

    lines.append("---")
    lines.append("*Generated by Loop Engineering PLAN phase*")

    return "\n".join(lines)
