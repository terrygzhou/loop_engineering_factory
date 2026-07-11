"""
DISCOVER node: Accept project description, collect user input via interview,
generate discovery artifact for DEFINE phase.

Uses LangGraph OOTB interrupt() for double-pause:
  1. Project setup (name + description)
  2. Interview questions (requirements gathering)

Output: $project_folder/requirement.md — structured discovery artifact
"""
import json
import os
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from langgraph.types import interrupt
from config.loader import config as _cfg
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog


def discover_node(state: dict) -> dict:
    """
    DISCOVER phase: Double-pause OOTB interrupt() node.

    Pause 1: Project setup (name + description)
    Pause 2: Interview questions (requirements gathering)

    On resume, both values are available and the node completes normally.
    """
    # ── Auto-approve mode (headless Docker) ──
    auto_approve = _cfg.workflow.auto_approve

    if auto_approve:
        return _discover_auto_approve(state)

    # ── Set phase ──
    state["phase"] = "DISCOVER"
    state["next_phase"] = "DEFINE"

    # ── Pause 1: Project setup ──
    # Check if project_name is already in state (from previous resume)
    project_name = state.get("project_name", "") or state.get("project_description", "")
    if project_name:
        # Already collected — skip pause 1, use state values
        project_name = state["project_name"]
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    else:
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

    state["project_name"] = project_name
    state["project_description"] = project_description
    state["context_folder"] = context_folder

    # ── Pause 2: Interview questions ──
    # Check if interview already completed
    if state.get("discover_interview_done") or state.get("interview_notes"):
        # Already collected — skip pause 2
        interview_notes = state.get("interview_notes", "")
    else:
        answers = interrupt({
            "type": "interview",
            "phase": "DISCOVER",
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
        state["discover_interview_done"] = True

    # ── Derive project_folder ──
    project_folder = state.get("project_folder", "")
    if not project_folder:
        workspace = _cfg.paths.workspace_dir
        project_folder = os.path.join(workspace, project_name)
        state["project_folder"] = project_folder
    state["project_path"] = project_folder

    # ── Improve mode
    if state.get("improve_mode"):
        telemetry = _load_improve_telemetry(state, project_name)
        if telemetry:
            deployed_path = telemetry["project_path"]
            context_folder = deployed_path
            project_folder = deployed_path
            state["context_folder"] = deployed_path
            state.setdefault("artifacts", {})["improve_telemetry"] = json.dumps(telemetry, indent=2)

    # ── Create project directories ──
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "specs").mkdir(parents=True, exist_ok=True)
    (project_dir / "build").mkdir(parents=True, exist_ok=True)
    (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)

    # ── Scan existing codebase ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    context = _scan_codebase(context_folder, project_name, project_folder)

    # ── Generate discovery artifact ──
    requirement_md = _generate_requirement_via_fabric(
        project_name=project_name,
        project_description=project_description,
        interview_notes=interview_notes,
        context=context,
        project_folder=project_folder,
    )

    req_path = project_dir / "requirement.md"
    req_path.write_text(requirement_md)

    # Store artifacts
    state["artifacts"]["project_context"] = json.dumps(context, indent=2, default=str)
    state["artifacts"]["requirement_md"] = requirement_md
    state["artifacts"]["requirement_path"] = str(req_path)
    state["interview_notes"] = interview_notes
    state["artifacts"]["interview_notes"] = interview_notes
    state["discover_interview_done"] = True

    audit.log_node_output("DISCOVER", {
        "requirement_path": str(req_path),
        "project_context_size": len(state["artifacts"]["project_context"]),
        "interview_notes_collected": bool(interview_notes),
    })

    state["phase"] = "DISCOVER"
    state["next_phase"] = "DEFINE"
    return state


def _discover_auto_approve(state: dict) -> dict:
    """Auto-approve mode: generate default interview notes from project description."""
    project_name = state.get("project_name", "Untitled")
    project_description = state.get("project_description", "")
    interview_notes = (
        f"Auto-generated interview for '{project_name}':\n"
        f"Description: {project_description}\n"
        f"Core behavior: Standard CRUD operations\n"
        f"API surface: RESTful endpoints\n"
    )
    state["interview_notes"] = interview_notes
    state.setdefault("artifacts", {})["interview_notes"] = interview_notes
    state["discover_interview_done"] = True
    state["phase"] = "DISCOVER"
    state["next_phase"] = "DEFINE"
    from config.loader import config as _cfg
    project_folder = state.get("project_folder", "") or os.path.join(
        os.path.expanduser(_cfg.paths.workspace_dir),
        project_name or "Untitled"
    )
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    req_md = f"# {project_name} — Discovery Report\n\n## Overview\n{project_description}\n\n## Requirements\n{interview_notes}\n"
    req_path = project_dir / "requirement.md"
    req_path.write_text(req_md)
    state["artifacts"]["requirement_md"] = req_md
    state["artifacts"]["requirement_path"] = str(req_path)
    return state


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


def _generate_requirement_via_fabric(project_name, project_description, interview_notes, context, project_folder):
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    fabric_skill = skills.get("Fabric Prompt Engineering", {}) or skills.get("fabric-prompt-engineering", {})
    if fabric_skill:
        fabric_prompt = (
            f"Generate a structured discovery report for DEFINE phase.\n\n"
            f"Project: {project_name}\nDescription: {project_description}\n"
            f"Interview notes:\n{interview_notes}\n\n"
            f"Output: Markdown with sections: Project Overview, Core Behavior, "
            f"Data Model, API Surface, Integration Requirements, Non-Functional, Edge Cases, Constraints"
        )
        result = invoke_skill(fabric_skill["content"], fabric_prompt, "", llm=None)
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
            req = urllib.request.Request(f"{url.rstrip('/')}/{health.lstrip('/')}", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                telemetry["health_status"] = resp.status
                telemetry["healthy"] = 200 <= resp.status < 400
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
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
