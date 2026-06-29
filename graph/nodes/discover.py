"""
DISCOVER node: Accept project description, collect user input via interview,
generate discovery artifact for DEFINE phase.

Flow:
  1. Ask user input (GraphInterrupt — pause for user)
  2. Trigger interview-me skill (parse user answers into structured notes)
  3. Use Fabric prompt skill to generate requirement.md for DEFINE

Output: $project_folder/requirement.md — structured discovery artifact
"""
import os
import json
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from langgraph.errors import GraphInterrupt
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog


def discover_node(state: dict) -> dict:
    """
    DISCOVER phase: Collect user requirements and generate discovery artifact.

    Input:
      - project_name: User-provided project name
      - project_description: Initial description from user
      - context_folder: Optional path to existing codebase

    Output:
      - $project_folder/requirement.md: Structured discovery artifact for DEFINE
      - state["artifacts"]["requirement_md"]: Markdown content
      - state["artifacts"]["project_context"]: JSON context
      - state["interview_notes"]: Collected interview answers
    """
    print("\n=== DISCOVER PHASE ===")

    # ── Step 0: Extract inputs ──
    project_name = state.get("project_name", "project")
    project_description = state.get("project_description", "")
    context_folder = state.get("context_folder", "")
    project_folder = state.get("project_folder", "")

    # Derive project_folder from project_name if not set
    if not project_folder:
        workspace = os.getenv("WORKSPACE_DIR", os.path.expanduser("~/workspace/projects"))
        project_folder = os.path.join(workspace, project_name)
        state["project_folder"] = project_folder

    state["project_path"] = project_folder
    state["project_name"] = project_name

    # ── Step 0.5: Improve mode — connect to a previously deployed product ──
    # When --improve is set, load storage/live.json, health-check the product,
    # and use its project path as context. This bridges factory → product.
    improve_mode = state.get("improve_mode", False)
    if improve_mode:
        telemetry = _load_improve_telemetry(state, project_name)
        if telemetry:
            print(f"  → Improve mode: connected to {telemetry.get('product_url', '?')}")
            # Point both context_folder and project_folder at the deployed project
            deployed_path = telemetry["project_path"]
            state["context_folder"] = deployed_path
            state["project_folder"] = deployed_path
            state["project_path"] = deployed_path
            project_folder = deployed_path
            # Store telemetry for downstream nodes
            state.setdefault("artifacts", {})["improve_telemetry"] = json.dumps(telemetry, indent=2)
            # Bypass interview — generate notes from existing deployment
            interview_notes = _generate_improve_interview_notes(state, telemetry)
            state["interview_notes"] = interview_notes
            state.setdefault("artifacts", {})["interview_notes"] = interview_notes
        else:
            print("  ⚠ improve_mode: live.json not found or product unreachable — falling back to standard DISCOVER")

    # ── Step 1: Check if we've already collected interview (resume detection) ──
    # When auto_approve=True: skip GraphInterrupt entirely (executor loops forever on it)
    # On resume from interrupt: discover_interview_done flag is set by executor
    auto = os.getenv("AUTO_APPROVE", "").lower() in ("true", "1", "yes")
    interrupted = state.get("artifacts", {}).get("discover_interview_done", False)
    existing_notes = state.get("interview_notes") or state.get("artifacts", {}).get("interview_notes")
    # BUG-FIX: Check auto-approve via state flag as fallback (env var may not persist)
    auto_approved = state.get("arch_review_approved", False) or state.get("auto_approve", False)
    if not auto and not interrupted and not existing_notes and not auto_approved:
        # First run, interactive mode — pause for user input
        raise GraphInterrupt(
            interrupts=[
                {
                    "type": "discover_interview",
                    "phase": "DISCOVER",
                    "message": "Interview: answer requirements questions for this project",
                }
            ]
        )

    # If no interview notes yet (auto_approve path), generate defaults
    if not existing_notes:
        interview_notes = _auto_generate_interview_notes(project_name, project_description)
    else:
        interview_notes = existing_notes
    state["interview_notes"] = interview_notes
    state.setdefault("artifacts", {})["interview_notes"] = interview_notes

    # ── Step 2: Scan existing codebase (if context provided) ──
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "specs").mkdir(parents=True, exist_ok=True)
    (project_dir / "build").mkdir(parents=True, exist_ok=True)
    (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("DISCOVER", {
        "project_name": project_name,
        "project_description": project_description[:200] or "(none)",
        "context_folder": context_folder or "(none)",
        "project_folder": project_folder,
    })

    context = _scan_codebase(context_folder, project_name, project_folder)

    # ── Step 3: Generate discovery artifact via Fabric prompt ──
    requirement_md = _generate_requirement_via_fabric(
        project_name=project_name,
        project_description=project_description,
        interview_notes=interview_notes,
        context=context,
        project_folder=project_folder,
        state=state,
    )

    # Write requirement.md
    req_path = project_dir / "requirement.md"
    req_path.write_text(requirement_md)
    audit.log_file_write("DISCOVER", str(req_path), "markdown", len(requirement_md))
    print(f"  ✓ requirement.md written: {req_path} ({len(requirement_md)} chars)")

    # Store artifacts for DEFINE phase
    state["artifacts"]["project_context"] = json.dumps(context, indent=2, default=str)
    state["artifacts"]["requirement_md"] = requirement_md
    state["artifacts"]["requirement_path"] = str(req_path)

    # ── Audit output ──
    audit.log_node_output("DISCOVER", {
        "requirement_path": str(req_path),
        "project_context_size": len(state["artifacts"]["project_context"]),
        "interview_notes_collected": bool(interview_notes),
    })
    audit.log_node_transition("DISCOVER", "DEFINE", "discovery complete")

    state["phase"] = "DISCOVER"
    state["next_phase"] = "DEFINE"

    print(f"  → Project folder: {project_folder}")
    print(f"  → Requirement: {req_path}")
    return state


def _scan_codebase(context_folder: str, project_name: str, project_folder: str) -> dict:
    """Scan existing codebase or return greenfield context."""
    if context_folder and Path(context_folder).is_dir():
        print(f"  → Scanning existing codebase: {context_folder}")
        project_type = _detect_project_type(context_folder)
        return {
            "project_path": project_folder,
            "project_name": project_name,
            "project_type": project_type,
            "tree": _inventory_tree(context_folder),
            "routes": _discover_routes(context_folder, project_type),
            "models": _discover_models(context_folder, project_type),
            "templates": _discover_templates(context_folder, project_type),
            "dependencies": _discover_dependencies(context_folder),
            "git": _get_git_status(context_folder),
            "docker": _get_docker_status(context_folder),
            "specs": _discover_specs(context_folder),
        }
    else:
        print("  → No context_folder — greenfield mode")
        return {
            "project_path": project_folder,
            "project_name": project_name,
            "project_type": "greenfield",
            "tree": {},
            "routes": [],
            "models": [],
            "templates": [],
            "dependencies": {},
            "git": {"branch": "greenfield"},
            "docker": {"services": []},
            "specs": {},
        }


def _generate_requirement_via_fabric(project_name: str, project_description: str,
                                     interview_notes: str, context: dict,
                                     project_folder: str, state: dict) -> str:
    """
    Use Fabric prompt skill to generate structured requirement.md.
    If Fabric skill is not available, fall back to template generation.
    """
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills

    fabric_skill = skills.get("Fabric Prompt Engineering", {}) or skills.get("fabric-prompt-engineering", {})

    if fabric_skill:
        print("  → Using Fabric prompt skill to generate requirement.md...")
        fabric_prompt = (
            f"Generate a structured discovery report for DEFINE phase.\n\n"
            f"Project: {project_name}\n"
            f"Description: {project_description}\n"
            f"Interview notes:\n{interview_notes}\n"
            f"Context: {json.dumps(context, default=str, indent=2)[:2000]}\n\n"
            f"Output format: Markdown with sections:\n"
            f"  # {project_name} — Discovery Report\n"
            f"  ## Project Overview\n"
            f"  ## Core Behavior\n"
            f"  ## Data Model\n"
            f"  ## API Surface\n"
            f"  ## Integration Requirements\n"
            f"  ## Non-Functional Requirements\n"
            f"  ## Edge Cases\n"
            f"  ## Constraints"
        )
        result = invoke_skill(fabric_skill["content"], fabric_prompt, "", llm=None)
        # Extract markdown from LLM output (strip code fences if present)
        md = result.strip()
        if md.startswith("```"):
            md = re.sub(r'^```[a-z]*\n', '', md).rstrip('`')
            if md.endswith('\n```'):
                md = md[:-4]
        return md

    # Fallback: template-based generation
    print("  → Fabric skill not available — using template generation...")
    return _generate_requirement_template(
        project_name=project_name,
        project_description=project_description,
        interview_notes=interview_notes,
        context=context,
        project_folder=project_folder,
    )


def _generate_requirement_template(project_name: str, project_description: str,
                                   interview_notes: str, context: dict,
                                   project_folder: str) -> str:
    """Fallback template-based requirement generation."""
    lines = [
        f"# {project_name} — Discovery Report",
        "",
        "## Project Overview",
        project_description or "(no description provided)",
        "",
        "## Core Behavior",
        interview_notes.split("\n")[0] if interview_notes else "(interview not completed)",
        "",
        "## Data Model",
        "",
    ]
    if context.get("models"):
        for model in context["models"][:20]:
            lines.append(f"- `{model.get('name', '?')}` (`{model.get('file', '?')}`)")
    else:
        lines.append("- (to be determined from interview)")
    lines.append("")

    lines.append("## API Surface")
    if context.get("routes"):
        for route in context["routes"][:20]:
            lines.append(f"- {route.get('method', '?')} `{route.get('path', '/')} (`{route.get('file', '?')}`)")
    else:
        lines.append("- (to be determined from interview)")
    lines.append("")

    lines.append("## Integration Requirements")
    if context.get("dependencies"):
        for dep_file, dep_list in context["dependencies"].items():
            lines.append(f"### {dep_file}")
            if isinstance(dep_list, list):
                for dep in dep_list[:30]:
                    lines.append(f"- {dep}")
            else:
                lines.append(str(dep_list))
    lines.append("")

    lines.append("## Non-Functional Requirements")
    lines.append("- (from interview notes)")
    lines.append("")

    lines.append("## Edge Cases")
    lines.append("- (to be determined from interview)")
    lines.append("")

    lines.append("## Constraints")
    lines.append(f"- Project folder: `{project_folder}`")
    lines.append(f"- Type: {context.get('project_type', 'greenfield')}")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by Loop Engineering DISCOVER phase*")

    return "\n".join(lines)


def _load_improve_telemetry(state: dict, project_name: str) -> dict | None:
    """
    Load storage/live.json from a previous SHIP cycle and health-check the product.
    Returns telemetry dict on success, None if live.json is missing or product unreachable.
    """
    try:
        from config.loader import config as _cfg
        _live_path = Path(_cfg.paths.storage_dir) / "live.json"
        if not _live_path.exists():
            print(f"  → No live.json at {_live_path} — first cycle, nothing to improve yet")
            return None

        telemetry = json.loads(_live_path.read_text())
        print(f"  → Found live.json from cycle {telemetry.get('cycle_id', '?')}")

        # Health-check the product
        url = telemetry.get("product_url", "http://localhost:8010")
        health = telemetry.get("health_endpoint", "/health")
        health_url = f"{url.rstrip('/')}/{health.lstrip('/')}"
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")[:500]
            print(f"  → Product health check: HTTP {status}")
            telemetry["health_status"] = status
            telemetry["health_body"] = body
            telemetry["healthy"] = 200 <= status < 400
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"  ⚠ Product unreachable at {health_url}: {e}")
            telemetry["healthy"] = False
            telemetry["health_error"] = str(e)

        # Validate project_path exists
        deployed_path = telemetry.get("project_path", "")
        if deployed_path and Path(deployed_path).is_dir():
            print(f"  → Deployed project path: {deployed_path}")
            return telemetry
        else:
            print(f"  ⚠ Deployed project path missing or not a directory: {deployed_path}")
            return None

    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"  ⚠ Could not load improve telemetry: {e}")
        return None


def _generate_improve_interview_notes(state: dict, telemetry: dict) -> str:
    """Generate interview notes from a running product's telemetry."""
    project_name = state.get("project_name", telemetry.get("project_name", "project"))
    health_body = telemetry.get("health_body", "")
    prev_cycle = telemetry.get("cycle_id", "?")
    spec_from_artifacts = state.get("spec_path", "")

    lines = [
        f"Improvement cycle for '{project_name}' (previously deployed in cycle {prev_cycle}):",
        f"Core behavior: Existing deployed application at {telemetry.get('product_url', '?')}",
        f"Health endpoint: {telemetry.get('product_url', '')}{telemetry.get('health_endpoint', '')}",
    ]
    if health_body:
        lines.append(f"Health response: {health_body[:200]}")
    if spec_from_artifacts:
        lines.append(f"Previous spec: {spec_from_artifacts[:200]}")
    lines.extend([
        f"Data model: Modify existing schema (from deployed project)",
        f"API surface: Extend existing RESTful endpoints",
        f"Validation: Existing validation + new requirements",
        f"Integration: As currently deployed in project",
        f"Deployment: Docker Compose (rolling update preferred)",
        f"Edge cases: Precedent from deployed behavior",
        f"Non-functional: Current performance baseline + targets",
    ])
    return "\n".join(lines)


def _auto_generate_interview_notes(project_name: str, project_description: str) -> str:
    """Generate default interview notes for auto-approve mode."""
    return (
        f"Auto-generated interview for '{project_name}':\n"
        f"Description: {project_description}\n"
        f"Core behavior: Standard CRUD operations\n"
        f"Data model: To be determined from spec\n"
        f"API surface: RESTful endpoints\n"
        f"Validation: Standard input validation\n"
        f"Integration: As specified in project description\n"
        f"Deployment: Docker Compose\n"
        f"Edge cases: Standard error handling\n"
        f"Non-functional: Standard performance targets\n"
    )


# ── Helper functions (unchanged) ──

def _detect_project_type(project_path: str) -> str:
    p = Path(project_path)
    if (p / "pyproject.toml").exists():
        return "python-pyproject"
    if (p / "requirements.txt").exists():
        return "python-requirements"
    if (p / "package.json").exists():
        return "node"
    if (p / "Cargo.toml").exists():
        return "rust"
    if (p / "go.mod").exists():
        return "go"
    for pyfile in p.rglob("main.py"):
        text = pyfile.read_text(errors="replace")
        if "fastapi" in text.lower() or "FastAPI" in text:
            return "python-fastapi"
    return "unknown"


def _inventory_tree(project_path: str) -> dict:
    p = Path(project_path)
    dirs = []
    for d in p.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            count = len(list(d.rglob("*")))
            dirs.append({"name": d.name, "file_count": count})
    return {"directories": dirs, "total_top_level": len(dirs)}


def _discover_routes(project_path: str, project_type: str) -> list:
    routes = []
    if project_type in ("python-fastapi", "python-pyproject", "python-requirements"):
        routes = _discover_fastapi_routes(project_path)
    elif project_type == "node":
        routes = _discover_express_routes(project_path)
    return routes


def _discover_fastapi_routes(project_path: str) -> list:
    routes = []
    p = Path(project_path)
    router_dirs = list(p.rglob("routers")) + list(p.rglob("api")) + list(p.rglob("routes"))
    for rd in router_dirs:
        if not rd.is_dir():
            continue
        for pyfile in rd.glob("*.py"):
            if pyfile.name.startswith("_"):
                continue
            try:
                text = pyfile.read_text(errors="replace")
                patterns = re.findall(
                    r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                    text
                )
                for method, path in patterns:
                    routes.append({"method": method.upper(), "path": path, "file": str(pyfile.relative_to(p))})
            except Exception:
                pass
    mainfiles = list(p.glob("*/main.py")) + [p / "main.py"]
    for mainfile in mainfiles:
        try:
            text = mainfile.read_text(errors="replace")
            matches = re.findall(
                r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                text
            )
            for method, path in matches:
                routes.append({"method": method.upper(), "path": path, "file": str(mainfile.relative_to(p))})
        except Exception:
            pass
    return routes


def _discover_express_routes(project_path: str) -> list:
    routes = []
    p = Path(project_path)
    for jsfile in list(p.rglob("*.js")) + list(p.rglob("*.ts")):
        try:
            text = jsfile.read_text(errors="replace")
            matches = re.findall(r'\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', text)
            for method, path in matches:
                routes.append({"method": method.upper(), "path": path, "file": str(jsfile.relative_to(p))})
        except Exception:
            pass
    return routes


def _discover_models(project_path: str, project_type: str) -> list:
    models = []
    p = Path(project_path)
    if project_type.startswith("python"):
        for md in p.rglob("models"):
            if not md.is_dir():
                continue
            for pyfile in md.glob("*.py"):
                if pyfile.name.startswith("_"):
                    continue
                try:
                    text = pyfile.read_text(errors="replace")
                    class_matches = re.findall(
                        r'class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase)[^)]*\)',
                        text
                    )
                    for cls in class_matches:
                        models.append({"name": cls, "file": str(pyfile.relative_to(p))})
                except Exception:
                    pass
    return models


def _discover_templates(project_path: str, project_type: str) -> list:
    templates = []
    p = Path(project_path)
    if project_type.startswith("python"):
        for html in p.rglob("*.html"):
            templates.append({"name": html.name, "file": str(html.relative_to(p))})
    elif project_type == "node":
        for tpl in list(p.rglob("*.ejs")) + list(p.rglob("*.pug")) + list(p.rglob("*.hbs")):
            templates.append({"name": tpl.name, "file": str(tpl.relative_to(p))})
    return templates


def _discover_dependencies(project_path: str) -> dict:
    deps = {}
    p = Path(project_path)
    if (p / "requirements.txt").exists():
        lines = (p / "requirements.txt").read_text(errors="replace").strip().splitlines()
        deps["requirements.txt"] = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    if (p / "pyproject.toml").exists():
        deps["pyproject.toml"] = "present"
    if (p / "package.json").exists():
        try:
            pkg = json.loads((p / "package.json").read_text())
            deps["package.json"] = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        except Exception:
            deps["package.json"] = "present"
    return deps


def _get_git_status(project_path: str) -> dict:
    info = {"branch": "unknown", "modified": 0, "untracked": 0, "ahead": 0, "behind": 0}
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5, cwd=project_path,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip() or "detached"
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, cwd=project_path,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line.startswith("??"):
                    info["untracked"] += 1
                elif line.startswith(" M") or line.startswith("M "):
                    info["modified"] += 1
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h|%s"],
            capture_output=True, text=True, timeout=5, cwd=project_path,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 1)
            info["last_commit"] = parts[0]
            info["last_message"] = parts[1] if len(parts) > 1 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        info["error"] = "git not available or timed out"
    return info


def _get_docker_status(project_path: str) -> dict:
    info = {"services": [], "healthy": 0, "unhealthy": 0}
    p = Path(project_path)
    compose_file = None
    for candidate in [p / "docker-compose.yml", p / "docker-compose.yaml", p / "mvp_output" / "docker-compose.yml"]:
        if candidate.exists():
            compose_file = candidate
            break
    if not compose_file:
        info["error"] = "no docker-compose.yml found"
        return info
    info["compose_file"] = str(compose_file.relative_to(p))
    info["project_dir"] = str(compose_file.parent)
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "ps", "--format", "json"],
            capture_output=True, text=True, timeout=15,
            cwd=str(compose_file.parent),
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                try:
                    container = json.loads(line)
                    svc = {"name": container.get("Name", "unknown"), "state": container.get("State", "unknown"),
                           "ports": container.get("Ports", "")}
                    info["services"].append(svc)
                    if "running" in svc["state"].lower():
                        info["healthy"] += 1
                    else:
                        info["unhealthy"] += 1
                except json.JSONDecodeError:
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        info["error"] = "docker compose not available or timed out"
    return info


def _discover_specs(project_path: str) -> dict:
    specs = {}
    p = Path(project_path)
    spec_dir = p / "specs"
    if not spec_dir.exists():
        return specs
    for spec_subdir in sorted(spec_dir.iterdir()):
        if not spec_subdir.is_dir():
            continue
        entries = {f.name: str(f.relative_to(spec_dir)) for f in spec_subdir.iterdir() if f.is_file()}
        specs[spec_subdir.name] = entries
    return specs
