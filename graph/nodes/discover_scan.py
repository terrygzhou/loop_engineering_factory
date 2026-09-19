"""Pure scanning helpers for the DISCOVER node (seam split, node-module-seams spec)."""

import re
import subprocess
from pathlib import Path


def _collect_plain_docs(context_folder: str) -> list:
    """Collect plain (non-ArcKit) document files under `context_folder`.

    Returns up to 20 files, each truncated to a total budget, so the
    extraction prompt stays bounded. Excludes files whose names match the
    ArcKit canonical pattern (those belong to the auto-populate path) and
    common code/build directories.
    """
    import re as _re

    base = Path(context_folder)
    if not base.is_dir():
        return []
    arckit_re = _re.compile(r"^ARC-\d{3}-")
    skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
    out: list[Path] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {
            ".md",
            ".txt",
            ".adoc",
            ".yaml",
            ".yml",
        }:
            continue
        if arckit_re.match(p.name):
            continue
        if skip_dirs & set(p.parts):
            continue
        out.append(p)
        if len(out) >= 20:
            break
    return out


def _scan_codebase(context_folder: str, project_name: str, project_folder: str) -> dict:
    if context_folder and Path(context_folder).is_dir():
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
    tree: dict = {}
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
                        sub[sub_entry.name] = {
                            "type": "dir" if sub_entry.is_dir() else "file"
                        }
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
    routes: list = []
    if not context_folder or not Path(context_folder).is_dir():
        return routes
    if project_type == "fastapi":
        for f in Path(context_folder).rglob("*.py"):
            text = f.read_text()
            for m in re.finditer(
                r'@(?:router|app)\.(?:get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)',
                text,
            ):
                routes.append(
                    {
                        "method": "auto",
                        "path": m.group(1),
                        "file": str(f.relative_to(context_folder)),
                    }
                )
    elif project_type == "django":
        for f in Path(context_folder).rglob("urls.py"):
            text = f.read_text()
            for m in re.finditer(r"path\s*\(\s*['\"]?([^'\",)]+)", text):
                routes.append(
                    {
                        "method": "auto",
                        "path": m.group(1),
                        "file": str(f.relative_to(context_folder)),
                    }
                )
    elif project_type in ("nextjs", "react"):
        for f in Path(context_folder).rglob("page.tsx"):
            routes.append(
                {
                    "method": "GET",
                    "path": f"/{f.relative_to(context_folder).parent}",
                    "file": str(f.relative_to(context_folder)),
                }
            )
    return routes


def _discover_models(context_folder: str, project_type: str) -> list:
    """Extract model definitions from backends."""
    models: list = []
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
    templates: list = []
    if not context_folder or not Path(context_folder).is_dir():
        return templates
    ext = (
        ".html"
        if project_type in ("django", "flask")
        else (".tsx" if project_type in ("nextjs", "react") else ".jinja2")
    )
    for f in Path(context_folder).rglob(f"*{ext}"):
        templates.append(str(f.relative_to(context_folder)))
    return templates


def _discover_dependencies(context_folder: str) -> dict:
    """Return known dependencies from lock/config files."""
    deps = {}
    base = Path(context_folder)
    if (base / "requirements.txt").exists():
        deps["requirements"] = [
            dep.strip()
            for dep in base.joinpath("requirements.txt").read_text().splitlines()
            if dep.strip() and not dep.startswith("#")
        ]
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
            deps["npm"] = list(
                {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}.keys()
            )
        except Exception:
            pass
    return deps


def _get_git_status(context_folder: str) -> dict:
    """Return git branch and dirty status."""
    try:
        result = subprocess.run(
            ["git", "-C", context_folder, "status", "--porcelain", "--branch"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        branch = lines[0].replace("## ", "").split("...")[0] if lines else "unknown"
        dirty = len([line for line in lines if line.strip()]) > 1
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
            if (
                "spec" in f.stem.lower()
                or "requirement" in f.stem.lower()
                or "readme" in f.stem.lower()
            ):
                specs[f.name] = {
                    "size": f.stat().st_size,
                    "path": str(f.relative_to(context_folder)),
                }
    return specs
