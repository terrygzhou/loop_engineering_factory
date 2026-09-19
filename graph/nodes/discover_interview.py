"""Interview / requirement-generation concern for the DISCOVER node (seam split S9).

Moved here per the OpenSpec S9 task. Ruling: `_generate_interview_questions`
contains an `invoke_skill` LLM call; the seam rule nominally excludes it,
but the spec lists it explicitly as a move target and it is a self-contained
concern (no interrupt, no owned stream-writer/audit, stateless signature),
so it moves. Recorded in the S9 commit.

Re-exported from `graph/nodes/discover.py` so existing test imports keep
resolving.
"""

import json
import logging
import re
from pathlib import Path

import httpx
from config.loader import config as _cfg

# `invoke_skill`, `build_skill_registry`, and `SkillTimer` are resolved via
# `graph.nodes.discover` at call time so that test monkeypatch targets
# ("graph.nodes.discover.invoke_skill", etc.) keep working even though the
# LLM call sites now live in this sibling module.
logger = logging.getLogger("discover")


def _invoke(*args, **kwargs):
    """Lazy resolve of `invoke_skill` through the discover node module."""
    import graph.nodes.discover as _disc_mod

    return _disc_mod.invoke_skill(*args, **kwargs)


def _build_registry(path):
    """Lazy resolve of `build_skill_registry` through the discover node module."""
    import graph.nodes.discover as _disc_mod

    return _disc_mod.build_skill_registry(path)


def _skill_timer(name):
    """Lazy resolve of `SkillTimer` through the discover node module."""
    import graph.nodes.discover as _disc_mod

    return _disc_mod.SkillTimer(name)


def _generate_interview_questions(
    project_name: str, project_description: str, skill_content: str = ""
) -> list:
    """Generate domain-specific interview questions from the project description.

    Uses the interview-me skill (when available) as the structured question
    framework, then tailors each category to the project domain via LLM.
    Falls back to generic questions if description is too short or LLM fails.
    """
    generic_questions = [
        {
            "key": "core_behavior",
            "label": "Core Behavior",
            "prompt": "What does this feature do? What are the primary user actions?",
        },
        {
            "key": "data_model",
            "label": "Data Model",
            "prompt": "What entities and fields are involved? Any relationships between them?",
        },
        {
            "key": "api_surface",
            "label": "API Surface",
            "prompt": "What endpoints, HTTP methods, and auth requirements do you need?",
        },
        {
            "key": "integration",
            "label": "Integration",
            "prompt": "Does this integrate with external services, databases, or third-party APIs?",
        },
        {
            "key": "ui_template",
            "label": "UI",
            "prompt": "Any specific UI requirements, templates, or styling preferences?",
        },
        {
            "key": "validation",
            "label": "Validation",
            "prompt": "What input validation rules or data integrity constraints apply?",
        },
        {
            "key": "edge_cases",
            "label": "Edge Cases",
            "prompt": "Are there known edge cases, error paths, or failure modes to handle?",
        },
        {
            "key": "non_functional",
            "label": "Non-Functional",
            "prompt": "Any performance, security, or monitoring requirements?",
        },
    ]

    # If description is too short, just use generic questions
    if len(project_description.strip()) < 20:
        return generic_questions

    # Build LLM prompt — grounded in the skill's interview framework
    skill_framework = ""
    if skill_content:
        skill_framework = (
            f"The following skill defines the interview framework. Use its "
            f"categories (Core Behavior, Data Model, API Surface, Integration, "
            f"Validation, UI/Template, Deployment, Edge Cases, Non-Functional) "
            f"as the structure, then tailor each question to this project's domain.\n\n"
            f"Interview framework:\n{skill_content}\n\n"
        )

    prompt = (
        f"You are designing an interview for a new software project.\n\n"
        f"{skill_framework}"
        f"Project: {project_name}\n"
        f"Description: {project_description}\n\n"
        f"Generate 6-8 interview questions that cover the key categories above, "
        f"but make each question specific to this project's domain.\n"
        f"For example, if the project mentions Google Calendar integration,\n"
        f"ask about OAuth scopes, sync direction, conflict resolution, etc.\n\n"
        f"Output ONLY a JSON array of question objects with this structure:\n"
        f'[{{"key": "area_name", "label": "Display Label", "prompt": "The specific question?"}}, ...]\n\n'
        f"Rules:\n"
        f"- Use the 'key' field as a short snake_case identifier (e.g. calendar_sync)\n"
        f"- Map each question to one of the framework categories above\n"
        f"- Make each question specific to the project, not generic\n"
        f"- Include at least one question about data model, integration/APIs, and user workflow\n"
        f"- Keep labels to 2-4 words\n"
        f"- Output only the JSON array, nothing else"
    )

    try:
        result = _invoke(
            "You are an expert software requirements interviewer.",
            prompt,
            "",
            llm=None,
        )
        # Parse the JSON array from LLM output
        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, list) and len(parsed) >= 3:
                # Ensure each question has required fields
                cleaned = []
                for q in parsed:
                    if isinstance(q, dict) and q.get("key") and q.get("prompt"):
                        cleaned.append(
                            {
                                "key": q["key"],
                                "label": q.get(
                                    "label", q["key"].replace("_", " ").title()
                                ),
                                "prompt": q["prompt"],
                            }
                        )
                if cleaned:
                    return cleaned
    except Exception as e:
        logger.warning("Interview question generation failed: %s", e)

    # Fall back to generic questions with project context
    return [
        {
            "key": "core_behavior",
            "label": "Core Behavior",
            "prompt": f"For '{project_name}', what are the primary user actions and workflows?",
        },
        {
            "key": "data_model",
            "label": "Data Model",
            "prompt": "What entities does this project manage? What fields and relationships?",
        },
        {
            "key": "integration",
            "label": "Integration",
            "prompt": "The description mentions specific services — which external APIs or databases need integration?",
        },
        {
            "key": "api_surface",
            "label": "API Surface",
            "prompt": "What REST endpoints or GraphQL queries should this expose?",
        },
        {
            "key": "auth_security",
            "label": "Auth & Security",
            "prompt": "Does this require authentication, authorization, or data encryption?",
        },
        {
            "key": "ui_template",
            "label": "UI",
            "prompt": "What does the user interface look like? Any existing design system or templates?",
        },
        {
            "key": "edge_cases",
            "label": "Edge Cases",
            "prompt": "What are the trickiest scenarios or failure modes for this project?",
        },
        {
            "key": "deployment",
            "label": "Deployment",
            "prompt": "Any Docker, infrastructure, or hosting requirements?",
        },
    ]


def _generate_requirement_via_fabric(
    project_name,
    project_description,
    interview_notes,
    context,
    project_folder,
    state: dict | None = None,
):
    skills = _build_registry(_cfg.workflow.skill_registry_path)
    fabric_skill = skills.get("fabric-prompts", {})

    # Wire coding-principles as context-aware refinement
    principles_skill = skills.get("coding-principles", {})
    principles_context = ""
    if principles_skill and project_description and state:
        principles_prompt = (
            f"Given this project context, extract relevant coding principles:\n"
            f"Project: {project_name}\n"
            f"Description: {project_description}\n"
            f"Type: {context.get('project_type', 'greenfield')}\n\n"
            "Output key technical principles and conventions that should guide implementation."
        )
        timer = _skill_timer("coding-principles")
        principles_context = (
            _invoke(principles_skill["content"], principles_prompt, "", llm=None) or ""
        )
        timer.complete()
        principles_context = f"\n\n## Coding Principles\n{principles_context[:1000]}\n"

    if fabric_skill:
        fabric_prompt = (
            f"Generate a structured discovery report for DEFINE phase.\n\n"
            f"Project: {project_name}\nDescription: {project_description}\n"
            f"Interview notes:\n{interview_notes}\n"
            f"{principles_context}\n\n"
            f"Output: Markdown with sections: Project Overview, Core Behavior, "
            f"Data Model, API Surface, Integration Requirements, Non-Functional, Edge Cases, Constraints"
        )
        # Feature 2: prior REFLECT skill recommendations (advisory; "" when
        # absent so the prompt stays byte-identical to the pre-feature one).
        from tools.skill_recommendations import skill_recommendations_block

        fabric_prompt += skill_recommendations_block()
        fabric_timer = _skill_timer("fabric-prompts")
        result = _invoke(fabric_skill["content"], fabric_prompt, "", llm=None)
        fabric_timer.complete()
        if not result:
            # LLM fatal (None) — degrade to the deterministic template
            return _generate_requirement_template(
                project_name,
                project_description,
                interview_notes,
                context,
                project_folder,
            )
        md = result.strip()
        if md.startswith("```"):
            md = re.sub(r"^```[a-z]*\n", "", md).rstrip("`")
            if md.endswith("\n```"):
                md = md[:-4]
        return md
    return _generate_requirement_template(
        project_name, project_description, interview_notes, context, project_folder
    )


def _generate_requirement_template(
    project_name, project_description, interview_notes, context, project_folder
):
    return (
        f"# {project_name} — Discovery Report\n\n"
        f"## Project Overview\n{project_description or '(none)'}\n\n"
        f"## Core Behavior\n{interview_notes.split(chr(10))[0] if interview_notes else '(none)'}\n\n"
        f"## Data Model\n- (from context or interview)\n\n"
        f"## API Surface\n- (to be determined)\n\n"
        f"## Non-Functional\n- (from interview)\n\n"
        f"## Edge Cases\n- (to be determined)\n\n"
        f"## Constraints\n- `{project_folder}`\n- {context.get('project_type', 'greenfield')}\n"
    )


def _load_improve_telemetry(state, project_name):
    try:
        _live_path = Path(_cfg.paths.storage_dir) / "live.json"
        if not _live_path.exists():
            return None
        telemetry = json.loads(_live_path.read_text())

        url = telemetry.get("product_url", _cfg.services.product.url)
        health = telemetry.get("health_endpoint", "/health")
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{url.rstrip('/')}/{health.lstrip('/')}")
                telemetry["health_status"] = resp.status_code
                telemetry["healthy"] = 200 <= resp.status_code < 400
        except (httpx.RequestError, OSError):
            telemetry["healthy"] = False
        deployed = telemetry.get("project_path", "")
        if deployed and Path(deployed).is_dir():
            return telemetry
        return None
    except Exception:
        return None


def _refine_idea(
    interview_notes, project_name, project_description, context, state=None
):
    """Sharpen interview notes into a focused concept for DEFINE."""
    skills = _build_registry(_cfg.workflow.skill_registry_path)
    refine_skill = skills.get("idea-refine", {})
    if not refine_skill or not interview_notes:
        return "No refinement available (missing interview notes or idea-refine skill)."

    prompt = (
        f"Refine these interview notes into a sharp, actionable concept for the DEFINE phase.\n\n"
        f"Project: {project_name}\nDescription: {project_description}\n"
        f"Interview Notes:\n{interview_notes}\n\n"
        f"Output: A concise tech + UX concept (2-3 sentences) highlighting core innovation,"
        f" key trade-offs, and the most important design decision."
    )
    timer = _skill_timer("idea-refine")
    result = _invoke(refine_skill["content"], prompt, "", llm=None)
    timer.complete()
    return result or ""


def _build_context(
    interview_notes, project_name, project_description, context, state=None
):
    """Engineer focused project context for DEFINE phase."""
    return json.dumps(
        {
            "project_name": project_name,
            "description": project_description[:500],
            "type": context.get("project_type", "greenfield"),
            "interview_focus": interview_notes[:1000] if interview_notes else "",
            "tree_summary": {k: v["type"] for k, v in context.get("tree", {}).items()},
            "dependencies": context.get("dependencies", {}),
            "specs": context.get("specs", {}),
        },
        indent=2,
    )
