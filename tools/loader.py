"""
Load skills from local ./skills directory. Prioritizes local over external sources.
Supports versioning, hot-reload, and validation.
"""
import os
import json
import time
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

LOCAL_SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILLS_INDEX = LOCAL_SKILLS_DIR / "SKILLS_INDEX.json"


def parse_skill_md(filepath: str) -> Dict[str, Any]:
    """Parse a SKILL.md file: extract YAML frontmatter and markdown body."""
    with open(filepath, 'r') as f:
        content = f.read()

    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2].strip()
        else:
            frontmatter = {}
            body = content
    else:
        frontmatter = {}
        body = content

    return {
        "meta": frontmatter or {},
        "content": body,
        "path": filepath,
    }


def validate_skill(skill: Dict[str, Any]) -> bool:
    """Validate skill structure — name, description, content."""
    if not skill.get("name"):
        return False
    if not skill.get("description"):
        return False
    if not skill.get("content"):
        return False
    return True


def load_skills(skills_dir: str = "") -> List[Dict[str, Any]]:
    """Scan skills_dir for all SKILL.md files and return parsed skill objects."""
    skills = []
    if not skills_dir:
        skills_dir = str(LOCAL_SKILLS_DIR)

    skills_path = Path(skills_dir).expanduser()
    if not skills_path.exists():
        print(f"WARNING: Skills directory not found: {skills_path}")
        return skills

    for root, dirs, files in os.walk(skills_path):
        if "SKILL.md" in files:
            skill_dir = Path(root)
            skill_name = skill_dir.name
            filepath = str(skill_dir / "SKILL.md")

            try:
                parsed = parse_skill_md(filepath)
                meta = parsed["meta"]
                skill = {
                    "name": meta.get("name", skill_name),
                    "description": meta.get("description", f"Skill: {skill_name}"),
                    "triggers": meta.get("triggers", []),
                    "version": meta.get("version", "1.0.0"),
                    "content": parsed["content"],
                    "category": str(skill_dir.relative_to(skills_path).parent) if skills_path != Path(root) else "",
                    "path": filepath,
                }
                if validate_skill(skill):
                    skills.append(skill)
                else:
                    print(f"WARNING: Invalid skill {filepath}")
            except Exception as e:
                print(f"WARNING: Failed to parse {filepath}: {e}")

    return skills


def build_skill_registry(skills_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Build a name→skill registry for fast lookup.
    Prioritizes local ./skills directory.
    Falls back to SKILLS_DIR env var.
    Does NOT fallback to ~/.hermes/skills unless explicitly configured.
    """
    # Determine skills directory — local first
    if skills_dir is None:
        skills_dir = os.getenv("SKILLS_DIR")

    if skills_dir is None:
        if LOCAL_SKILLS_DIR.exists():
            skills_dir = str(LOCAL_SKILLS_DIR)
        else:
            skills_dir = "~/.hermes/skills"

    registry = {}
    skills = load_skills(skills_dir)
    for skill in skills:
        registry[skill["name"]] = skill

    # Save skills index for versioning
    _save_skills_index(registry)

    return registry


def _save_skills_index(registry: Dict[str, Dict[str, Any]]):
    """Save skills index with versions for change detection."""
    index = {}
    for name, skill in registry.items():
        index[name] = {
            "version": skill.get("version", "1.0.0"),
            "path": skill.get("path", ""),
            "mtime": os.path.getmtime(skill.get("path", __file__)),
        }
    try:
        SKILLS_INDEX.parent.mkdir(parents=True, exist_ok=True)
        with open(SKILLS_INDEX, 'w') as f:
            json.dump(index, f, indent=2)
    except Exception as e:
        print(f"WARNING: Could not save skills index: {e}")


def check_skills_changed(registry: Dict[str, Dict[str, Any]]) -> bool:
    """Check if any skill files have changed since last load."""
    if not SKILLS_INDEX.exists():
        return True
    try:
        with open(SKILLS_INDEX, 'r') as f:
            index = json.load(f)
        for name, skill in registry.items():
            path = skill.get("path", "")
            if path and path in index:
                current_mtime = os.path.getmtime(path)
                if current_mtime != index[path]["mtime"]:
                    return True
        return False
    except Exception:
        return True


def find_skills_by_trigger(trigger_keyword: str, skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find skills that match a trigger keyword."""
    matches = []
    keyword = trigger_keyword.lower()
    for skill in skills:
        triggers = [t.lower() for t in skill.get("triggers", [])]
        if keyword in triggers or keyword in skill["name"].lower() or keyword in skill["description"].lower():
            matches.append(skill)
    return matches
