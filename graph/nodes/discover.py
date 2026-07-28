"""
DISCOVER nodes: Accept project description, collect user input via interview,
generate discovery artifact for DEFINE phase.

Split into two nodes, each with ONE interrupt:
  1. discover_setup_node — project setup (name + description + context folder)
  2. discover_interview_node — interview questions + requirement.md generation

On resume, only the paused node re-runs (~30 lines vs ~100 lines in the old
single-node design).
"""
import json
import os
import re
import subprocess
import httpx
from pathlib import Path
from langgraph.types import interrupt
from config.loader import config as _cfg
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog
from graph.ui_bridge import SkillTimer


def discover_setup_node(state: dict) -> dict:
    """
    DISCOVER phase — Setup node.

    Purpose: Collect project name, description, context folder.
    Interrupt: Project setup form (once).
    """
    # State override wins if explicitly set; None = use config fallback
    override = state.get("auto_approve_override")
    auto_approve = override if override is not None else _cfg.workflow.auto_approve

    # ── Auto-approve: generate defaults ──
    if auto_approve:
        project_name = state.get("project_name") or "Untitled"
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    else:
        # ── Check if already collected (resume skip) ──
        if state.get("project_name"):
            project_name = state["project_name"]
            project_description = state.get("project_description", "")
            context_folder = state.get("context_folder", "")
        else:
            # ── Pause: Project setup ──
            setup = interrupt({
                "type": "project_setup",
                "fields": [
                    {"key": "project_name", "label": "Project name", "required": True},
                    {"key": "project_description", "label": "Project description", "required": True},
                    {"key": "context_folder", "label": "Existing codebase path (leave empty for greenfield)", "required": False},
                ],
            })
            project_name = setup.get("project_name", "")
            project_description = setup.get("project_description", "")
            context_folder = setup.get("context_folder", "")

    # ── Derive project_folder ──
    project_folder = state.get("project_folder", "")
    if not project_folder:
        workspace = _cfg.paths.workspace_dir
        project_folder = os.path.join(workspace, project_name)

    # ── Improve mode: override with live deployment ──
    if state.get("improve_mode"):
        telemetry = _load_improve_telemetry(state, project_name)
        if telemetry:
            deployed_path = telemetry["project_path"]
            context_folder = deployed_path
            project_folder = deployed_path
            # Create project dirs for improve mode
            project_dir = Path(project_folder)
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "specs").mkdir(parents=True, exist_ok=True)
            (project_dir / "build").mkdir(parents=True, exist_ok=True)
            (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)
            return {
                "project_name": project_name,
                "project_description": project_description,
                "context_folder": context_folder,
                "project_folder": project_folder,
                "project_path": project_folder,
                "phase": "DISCOVER",
                "next_phase": "DEFINE",
                "artifacts": {"improve_telemetry": json.dumps(telemetry, indent=2)},
            }

    # ── Create project directories ──
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "specs").mkdir(parents=True, exist_ok=True)
    (project_dir / "build").mkdir(parents=True, exist_ok=True)
    (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)

    return {
        "project_name": project_name,
        "project_description": project_description,
        "context_folder": context_folder,
        "project_folder": project_folder,
        "project_path": project_folder,
        "phase": "DISCOVER",
        "next_phase": "DEFINE",
        # Clear top-level diagram state from previous cycles
        "diagrams": {},
        "diagram_status": "pending",
    }


def discover_interview_node(state: dict) -> dict:
    """
    DISCOVER phase — Interview node.

    Purpose: Ask interview questions, generate requirement.md.
    Interrupt: Interview questions (once).
    """
    # State override wins if explicitly set; None = use config fallback
    override = state.get("auto_approve_override")
    auto_approve = override if override is not None else _cfg.workflow.auto_approve

    project_name = state.get("project_name", "Untitled")
    project_description = state.get("project_description", "")
    context_folder = state.get("context_folder", "")
    project_folder = state.get("project_folder", "")
    project_dir = Path(project_folder)

    # ── Auto-approve: skip interview, generate defaults ──
    if auto_approve:
        interview_notes = (
            f"Auto-generated interview for '{project_name}':\n"
            f"Description: {project_description}\n"
            f"Core behavior: Standard CRUD operations\n"
            f"API surface: RESTful endpoints\n"
        )
    # ── Check if interview already completed (resume skip) ──
    elif state.get("discover_interview_done") or state.get("interview_notes"):
        interview_notes = state.get("interview_notes", "")
    else:
        # ── Pause: Interview questions ──
        skills = build_skill_registry(_cfg.workflow.skill_registry_path)
        interview_skill = skills.get("interview-me", {})

        interview_prompts = (
            "Ask the following questions one at a time. Wait for each answer before moving on.\n"
            "If a question is not applicable, skip it.\n\n"
            "Questions:\n"
            "1. core_behavior — What does this feature do?\n"
            "2. data_model — What entities and fields are involved?\n"
            "3. api_surface — What HTTP methods, paths, and auth requirements?\n"
            "4. validation — What input validation rules?\n"
            "5. ui_template — Any Jinja2 templates or UI requirements?\n"
            "6. integration — External services, databases, or APIs?\n"
            "7. deployment — Docker or infrastructure implications?\n"
            "8. edge_cases — Known edge cases?\n"
            "9. non_functional — Performance, security, or monitoring needs?\n"
        )

        answers = interrupt({
            "type": "interview",
            "phase": "DISCOVER",
            "instructions": interview_prompts if interview_skill else None,
            "questions": [
                {"key": "core_behavior", "prompt": "What does this feature do?"},
                {"key": "data_model", "prompt": "What entities and fields are involved?"},
                {"key": "api_surface", "prompt": "What HTTP methods, paths, and auth requirements?"},
                {"key": "validation", "prompt": "What input validation rules?"},
                {"key": "ui_template", "prompt": "Any Jinja2 templates or UI requirements?"},
                {"key": "integration", "prompt": "External services, databases, or APIs?"},
                {"key": "deployment", "prompt": "Docker or infrastructure implications?"},
                {"key": "edge_cases", "prompt": "Known edge cases?"},
                {"key": "non_functional", "prompt": "Performance, security, or monitoring needs?"},
            ],
        })
        interview_notes = answers.get("interview_notes", "")

    # ── Scan existing codebase ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    context = _scan_codebase(context_folder, project_name, project_folder)

    # ── Idea refinement: sharpen interview notes into actionable concept ──
    idea_refinement = _refine_idea(interview_notes, project_name, project_description, context, state)

    # ── Context engineering: build focused project context ──
    engineered_context = _build_context(interview_notes, project_name, project_description, context, state)

    # ── Generate discovery artifact ──
    requirement_md = _generate_requirement_via_fabric(
        project_name=project_name,
        project_description=project_description,
        interview_notes=interview_notes,
        context=context,
        project_folder=project_folder,
        state=state,
    )

    req_path = project_dir / "requirement.md"
    req_path.write_text(requirement_md)

    # ── Return partial updates (reducers merge via _dict_merge) ──
    artifacts = {
        "idea_refinement": idea_refinement,
        "engineered_context": engineered_context,
        "project_context": json.dumps(context, indent=2, default=str),
        "requirement_md": requirement_md,
        "requirement_path": str(req_path),
        "interview_notes": interview_notes,
        # Clear stale artifact paths from previous cycles
        "diagrams": {},
        "diagram_pngs": {},
    }

    audit.log_node_output("DISCOVER", {
        "requirement_path": str(req_path),
        "project_context_size": len(artifacts["project_context"]),
        "idea_refinement_size": len(idea_refinement),
        "engineered_context_size": len(engineered_context),
        "interview_notes_collected": bool(interview_notes),
    })

    return {
        "interview_notes": interview_notes,
        "discover_interview_done": True,
        "artifacts": artifacts,
        "phase": "DISCOVER",
        "next_phase": "DEFINE",
        # Clear top-level diagram state from previous cycles
        "diagrams": {},
        "diagram_status": "pending",
    }


# ── Backward compatibility: alias to old single-node function ──

def discover_node(state: dict) -> dict:
    """Backward-compatible wrapper — delegates to setup then interview."""
    result = discover_setup_node(state)
    merged = {**state, **result}
    return discover_interview_node(merged)


def _discover_auto_approve(state: dict) -> dict:
    """Backward-compatible: auto-approve via the two-node pipeline."""
    state = {
        **state,
        "phase": "DISCOVER",
        "next_phase": "DEFINE",
    }
    if not state.get("project_name"):
        state = {**state, "project_name": "Untitled"}
    if not state.get("project_description"):
        state = {**state, "project_description": ""}
    result = discover_setup_node(state)
    merged = {**state, **result}
    return discover_interview_node(merged)


# ── Helpers (unchanged) ──

def _scan_codebase(context_folder: str, project_name: str, project_folder: str) -> dict:
    if context_folder and Path(context_folder).is_dir():
        project_type = _detect_project_type(context_folder)
        return {
            "project_path": project_folder, "project_name": project_name, "project_type": project_type,
            "tree": _inventory_tree(context_folder),
            "routes": _discover_routes(context_folder, project_type),
            "models": _discover_models(context_folder, project_type),
            "templates": _discover_templates(context_folder, project_type),
            "dependencies": _discover_dependencies(context_folder),
            "git": _get_git_status(context_folder),
            "docker": _get_docker_status(context_folder),
            "specs": _discover_specs(context_folder),
        }
    return {
        "project_path": project_folder, "project_name": project_name, "project_type": "greenfield",
        "tree": {}, "routes": [], "models": [], "templates": [], "dependencies": {},
        "git": {"branch": "greenfield"}, "docker": {"services": []}, "specs": {},
    }

def _generate_requirement_via_fabric(project_name, project_description, interview_notes, context, project_folder, state: dict = None):
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
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
        timer = SkillTimer(state, "coding-principles")
        principles_context = invoke_skill(principles_skill["content"], principles_prompt, "", llm=None)
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
        fabric_timer = SkillTimer(state, "fabric-prompts")
        result = invoke_skill(fabric_skill["content"], fabric_prompt, "", llm=None)
        fabric_timer.complete()
        md = result.strip()
        if md.startswith("```"):
            md = re.sub(r'^```[a-z]*\n', '', md).rstrip('`')
            if md.endswith('\n```'):
                md = md[:-4]
        return md
    return _generate_requirement_template(project_name, project_description, interview_notes, context, project_folder)

def _generate_requirement_template(project_name, project_description, interview_notes, context, project_folder):
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
        from config.loader import config as _cfg
        _live_path = Path(_cfg.paths.storage_dir) / "live.json"
        if not _live_path.exists():
            return None
        telemetry = json.loads(_live_path.read_text())
        from config.loader import config as _cfg
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

def _detect_project_type(project_path: str) -> str:
    p = Path(project_path)
    if (p / "pyproject.toml").exists(): return "python-pyproject"
    if (p / "requirements.txt").exists(): return "python-requirements"
    if (p / "package.json").exists(): return "node"
    if (p / "Cargo.toml").exists(): return "rust"
    if (p / "go.mod").exists(): return "go"
    for pyfile in p.rglob("main.py"):
        text = pyfile.read_text(errors="replace")
        if "fastapi" in text.lower() or "FastAPI" in text:
            return "python-fastapi"
    return "unknown"

def _inventory_tree(project_path: str) -> dict:
    p = Path(project_path)
    dirs = [{"name": d.name, "file_count": len(list(d.rglob("*")))} for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
    return {"directories": dirs, "total_top_level": len(dirs)}

def _discover_routes(project_path, project_type):
    if project_type in ("python-fastapi", "python-pyproject", "python-requirements"):
        return _discover_fastapi_routes(project_path)
    elif project_type == "node":
        return _discover_express_routes(project_path)
    return []

def _discover_fastapi_routes(project_path):
    routes = []
    p = Path(project_path)
    for rd in list(p.rglob("routers")) + list(p.rglob("api")) + list(p.rglob("routes")):
        if not rd.is_dir(): continue
        for pyfile in rd.glob("*.py"):
            if pyfile.name.startswith("_"): continue
            try:
                for method, path in re.findall(r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', pyfile.read_text(errors="replace")):
                    routes.append({"method": method.upper(), "path": path, "file": str(pyfile.relative_to(p))})
            except Exception: pass
    for mainfile in list(p.glob("*/main.py")) + [p / "main.py"]:
        try:
            for method, path in re.findall(r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', mainfile.read_text(errors="replace")):
                routes.append({"method": method.upper(), "path": path, "file": str(mainfile.relative_to(p))})
        except Exception: pass
    return routes

def _discover_express_routes(project_path):
    routes = []
    p = Path(project_path)
    for jsfile in list(p.rglob("*.js")) + list(p.rglob("*.ts")):
        try:
            for method, path in re.findall(r'\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', jsfile.read_text(errors="replace")):
                routes.append({"method": method.upper(), "path": path, "file": str(jsfile.relative_to(p))})
        except Exception: pass
    return routes

def _discover_models(project_path, project_type):
    models = []
    if project_type.startswith("python"):
        p = Path(project_path)
        for md in p.rglob("models"):
            if not md.is_dir(): continue
            for pyfile in md.glob("*.py"):
                if pyfile.name.startswith("_"): continue
                try:
                    for cls in re.findall(r'class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase)[^)]*\)', pyfile.read_text(errors="replace")):
                        models.append({"name": cls, "file": str(pyfile.relative_to(p))})
                except Exception: pass
    return models

def _discover_templates(project_path, project_type):
    templates = []
    p = Path(project_path)
    for d in p.rglob("templates"):
        if d.is_dir():
            for f in d.glob("*.html"):
                templates.append({"name": f.stem, "file": str(f.relative_to(p))})
    return templates

def _discover_dependencies(project_path):
    deps = {}
    p = Path(project_path)
    for f in [p / "requirements.txt", p / "package.json", p / "Cargo.toml", p / "go.mod"]:
        if f.exists():
            try:
                deps[f.name] = f.read_text(errors="replace")[:bounds.feedback.max_context_query_chars]
            except Exception: pass
    return deps

def _get_git_status(project_path):
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=project_path, timeout=5)
        return {"status": result.stdout.strip()[:bounds.feedback.max_context_query_chars], "clean": not result.stdout.strip()}
    except Exception:
        return {"status": "unknown"}

def _get_docker_status(project_path):
    p = Path(project_path)
    services = [str(f) for f in [p / "docker-compose.yml", p / "docker-compose.yaml"] if f.exists()]
    return {"services": services}

def _discover_specs(project_path):
    specs = []
    p = Path(project_path)
    for f in p.rglob("*.md"):
        if f.name in ("requirement.md", "README.md", "spec.md") or "spec" in f.name.lower():
            try:
                specs.append({"name": f.stem, "file": str(f.relative_to(p))})
            except Exception: pass
    return {"specs": specs}


def _refine_idea(interview_notes: str, project_name: str, project_description: str, context: dict, state: dict) -> str:
    """Use idea-refine skill to sharpen raw interview notes into a crisp, actionable concept."""
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    refine_skill = skills.get("idea-refine", {})
    if not refine_skill:
        return f"## Idea Refinement\n(Interview notes used as-is)\n\n{interview_notes[:800]}"
    prompt = (
        f"Refine the following project idea into a sharp, actionable concept.\n\n"
        f"Project: {project_name}\n"
        f"Description: {project_description}\n"
        f"Interview notes:\n{interview_notes}\n\n"
        f"Produce a concise one-pager with: Problem Statement, Recommended Direction, "
        f"Key Assumptions, MVP Scope, Not Doing list, Open Questions."
    )
    result = invoke_skill(refine_skill["content"], prompt, "", llm=None,
                          workflow_id=state.get("project_name", ""), phase="DISCOVER")
    timer = SkillTimer(state, "idea-refine")
    timer.complete()
    print(f"  → idea-refine produced {len(result)} chars")
    return result


def _build_context(interview_notes: str, project_name: str, project_description: str, context: dict, state: dict) -> str:
    """Use context-engineering skill to build comprehensive, focused project context."""
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    ctx_skill = skills.get("context-engineering", {})
    if not ctx_skill:
        return f"## Project Context\n{json.dumps(context, indent=2, default=str)[:1200]}"
    prompt = (
        f"Build a focused project context for AI-assisted development.\n\n"
        f"Project: {project_name}\n"
        f"Description: {project_description}\n"
        f"Type: {context.get('project_type', 'greenfield')}\n"
        f"Interview notes:\n{interview_notes[:600]}\n\n"
        f"Output a structured context block with: tech stack, commands, code conventions, "
        f"boundaries, and key files to reference. Keep it under 2000 chars."
    )
    result = invoke_skill(ctx_skill["content"], prompt, "", llm=None,
                          workflow_id=state.get("project_name", ""), phase="DISCOVER")
    ctx_timer = SkillTimer(state, "context-engineering")
    ctx_timer.complete()
    print(f"  → context-engineering produced {len(result)} chars")
    return result

