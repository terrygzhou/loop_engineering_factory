"""
DISCOVER node: Accept project description, collect user input via interview,
generate discovery artifact for DEFINE phase.

Single async node with TWO sequential interrupt() calls:
  1. project_setup — project name + description + context folder
  2. interview — detailed requirements questions

Both interrupts fire from the same node context, avoiding LangGraph's
post-resume interrupt suppression (LangGraph 1.x: interrupt() in a
downstream node after resume does not yield __interrupt__).
"""
from langgraph.config import get_stream_writer

import json
import os
import re
import subprocess
import time
import httpx
from pathlib import Path
from langgraph.types import interrupt
from config.loader import config as _cfg
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog
from graph.ui_bridge import SkillTimer


async def discover_node(state: dict) -> dict:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI

    # ── State override wins if explicitly set; None = use config fallback ──
    override = state.get("auto_approve_override")
    auto_approve = override if override is not None else _cfg.workflow.auto_approve
    force_hil = bool(state.get("force_hil"))

    # ── 1. Project setup (interrupt #1) ──
    if auto_approve:
        project_name = state.get("project_name") or "Untitled"
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    elif state.get("discover_setup_done"):
        # Already collected on a previous run — skip setup interrupt
        project_name = state["project_name"]
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    elif force_hil or not state.get("project_name"):
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
    else:
        project_name = state.get("project_name", "Untitled")
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")

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
                "discover_setup_done": True,
                "artifacts": {"improve_telemetry": json.dumps(telemetry, indent=2)},
            }

    # ── Create project directories ──
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "specs").mkdir(parents=True, exist_ok=True)
    (project_dir / "build").mkdir(parents=True, exist_ok=True)
    (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)

    # ── 2. Interview (interrupt #2) — same node, same checkpoint context ──
    if auto_approve:
        interview_notes = (
            f"Auto-generated interview for '{project_name}':\n"
            f"Description: {project_description}\n"
            f"Core behavior: Standard CRUD operations\n"
            f"API surface: RESTful endpoints\n"
        )
    elif state.get("discover_interview_done") or state.get("interview_notes"):
        interview_notes = state.get("interview_notes", "")
    else:
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
        "project_name": project_name,
        "project_description": project_description,
        "context_folder": context_folder,
        "project_folder": project_folder,
        "project_path": project_folder,
        "interview_notes": interview_notes,
        "discover_setup_done": True,
        "discover_interview_done": True,
        "artifacts": artifacts,
        "phase": "DISCOVER",
        "next_phase": "DEFINE",
        "diagrams": {},
        "diagram_status": "pending",
    }


# ── Helpers ──

def _scan_codebase(context_folder: str, project_name: str, project_folder: str) -> dict:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    """Detect framework type from package dependencies."""
    if not project_path:
        return "unknown"
    pm = Path(project_path)
    if (pm / "pyproject.toml").exists():
        return "python"
    if (pm / "package.json").exists():
        return "node"
    if (pm / "Cargo.toml").exists():
        return "rust"
    if (pm / "go.mod").exists():
        return "go"
    if (pm / "Gemfile").exists():
        return "ruby"
    return "unknown"

def _inventory_tree(context_folder: str, max_depth: int = 3):
    """Walk the project tree up to max_depth."""
    base = Path(context_folder)
    tree = {}
    if not base.is_dir():
        return tree
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_dir():
            sub = {}
            if max_depth > 1:
                for sub_entry in sorted(entry.iterdir())[:20]:
                    if not sub_entry.name.startswith("."):
                        sub[sub_entry.name] = {"type": "dir" if sub_entry.is_dir() else "file"}
            tree[entry.name] = {"type": "dir", "children": sub}
        else:
            tree[entry.name] = {"type": "file"}
    return tree

def _detect_framework(project_path: str):
    """Detect framework from pyproject.toml or package.json deps."""
    base = Path(project_path)
    if (base / "pyproject.toml").exists():
        import toml
        try:
            data = toml.loads((base / "pyproject.toml").read_text())
            deps = data.get("project", {}).get("dependencies", [])
            dd = " ".join(deps).lower()
            if "django" in dd:
                return "django"
            if "fastapi" in dd:
                return "fastapi"
            if "flask" in dd:
                return "flask"
            if "httpx" in dd:
                return "fastapi"
            return "python"
        except Exception:
            return "python"
    if (base / "package.json").exists():
        import json
        try:
            pkg = json.loads((base / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            dd = " ".join(deps.keys()).lower()
            if "next" in dd:
                return "nextjs"
            if "react" in dd:
                return "react"
            return "node"
        except Exception:
            return "node"
    return "unknown"

def _discover_routes(context_folder: str, project_type: str) -> list:
    """Extract route definitions from backends."""
    routes = []
    if not context_folder or not Path(context_folder).is_dir():
        return routes
    if project_type == "fastapi":
        for f in Path(context_folder).rglob("*.py"):
            text = f.read_text()
            for m in re.finditer(r'@(?:router|app)\.(?:get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)', text):
                routes.append({"method": "auto", "path": m.group(1), "file": str(f.relative_to(context_folder))})
    elif project_type == "django":
        for f in Path(context_folder).rglob("urls.py"):
            text = f.read_text()
            for m in re.finditer(r"path\s*\(\s*['\"]?([^'\",)]+)", text):
                routes.append({"method": "auto", "path": m.group(1), "file": str(f.relative_to(context_folder))})
    elif project_type in ("nextjs", "react"):
        for f in Path(context_folder).rglob("page.tsx"):
            routes.append({"method": "GET", "path": f"/{f.relative_to(context_folder).parent}", "file": str(f.relative_to(context_folder))})
    return routes

def _discover_models(context_folder: str, project_type: str) -> list:
    """Extract model definitions from backends."""
    models = []
    if not context_folder or not Path(context_folder).is_dir():
        return models
    if project_type == "django":
        for f in Path(context_folder).rglob("models.py"):
            for m in re.finditer(r"class\s+(\w+)\(models\.", f.read_text()):
                models.append(m.group(1))
    elif project_type == "fastapi":
        for f in Path(context_folder).rglob("*.py"):
            for m in re.finditer(r"class\s+(\w+)\(BaseModel\)", f.read_text()):
                models.append(m.group(1))
    return models

def _discover_templates(context_folder: str, project_type: str) -> list:
    """List Jinja2 or JSX template paths."""
    templates = []
    if not context_folder or not Path(context_folder).is_dir():
        return templates
    ext = ".html" if project_type in ("django", "flask") else (".tsx" if project_type in ("nextjs", "react") else ".jinja2")
    for f in Path(context_folder).rglob(f"*{ext}"):
        templates.append(str(f.relative_to(context_folder)))
    return templates

def _discover_dependencies(context_folder: str) -> dict:
    """Return known dependencies from lock/config files."""
    deps = {}
    base = Path(context_folder)
    if (base / "requirements.txt").exists():
        deps["requirements"] = [l.strip() for l in base.joinpath("requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    if (base / "pyproject.toml").exists():
        import toml
        try:
            data = toml.loads((base / "pyproject.toml").read_text())
            deps["pyproject"] = data.get("project", {}).get("dependencies", [])
        except Exception:
            pass
    if (base / "package.json").exists():
        import json
        try:
            pkg = json.loads((base / "package.json").read_text())
            deps["npm"] = list({**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}.keys())
        except Exception:
            pass
    return deps

def _get_git_status(context_folder: str) -> dict:
    """Return git branch and dirty status."""
    try:
        result = subprocess.run(
            ["git", "-C", context_folder, "status", "--porcelain", "--branch"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        branch = lines[0].replace("## ", "").split("...")[0] if lines else "unknown"
        dirty = len([l for l in lines if l.strip()]) > 1
        return {"branch": branch, "dirty": dirty}
    except (subprocess.SubprocessError, FileNotFoundError):
        return {"branch": "unknown", "dirty": False}

def _get_docker_status(context_folder: str) -> dict:
    """Check for docker-compose.yaml or Dockerfile."""
    base = Path(context_folder)
    return {
        "services": ["app"],
        "has_dockerfile": any(base.glob("Dockerfile*")),
        "has_compose": any(base.glob("docker-compose.*")),
    }

def _discover_specs(context_folder: str) -> dict:
    """Find specification documents."""
    base = Path(context_folder)
    specs = {}
    for pattern in ["**/*.md", "**/*.yaml", "**/*.yml", "**/*.json"]:
        for f in base.glob(pattern):
            if "spec" in f.stem.lower() or "requirement" in f.stem.lower() or "readme" in f.stem.lower():
                specs[f.name] = {"size": f.stat().st_size, "path": str(f.relative_to(context_folder))}
    return specs

def _refine_idea(interview_notes, project_name, project_description, context, state=None):
    """Sharpen interview notes into a focused concept for DEFINE."""
    writer = get_stream_writer() or (lambda **kw: None)
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    refine_skill = skills.get("creative-ideation", {})
    if not refine_skill or not interview_notes:
        return "No refinement available (missing interview notes or skill)."

    prompt = (
        f"Refine these interview notes into a sharp, actionable concept for the DEFINE phase.\n\n"
        f"Project: {project_name}\nDescription: {project_description}\n"
        f"Interview Notes:\n{interview_notes}\n\n"
        f"Output: A concise tech + UX concept (2-3 sentences) highlighting core innovation,"
        f" key trade-offs, and the most important design decision."
    )
    timer = SkillTimer(state, "creative-ideation") if state else None
    result = invoke_skill(refine_skill["content"], prompt, "", llm=None)
    if timer:
        timer.complete()
    return result

def _build_context(interview_notes, project_name, project_description, context, state=None):
    """Engineer focused project context for DEFINE phase."""
    writer = get_stream_writer() or (lambda **kw: None)
    return json.dumps({
        "project_name": project_name,
        "description": project_description[:500],
        "type": context.get("project_type", "greenfield"),
        "interview_focus": interview_notes[:1000] if interview_notes else "",
        "tree_summary": {k: v["type"] for k, v in context.get("tree", {}).items()},
        "dependencies": context.get("dependencies", {}),
        "specs": context.get("specs", {}),
    }, indent=2)
