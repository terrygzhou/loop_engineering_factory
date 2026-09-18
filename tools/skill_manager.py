"""
Skill lifecycle manager for the loop factory.

Provides register / remove / update / list / sync for skills under
``config.workflow.skill_registry_path``. Git is invoked via ``subprocess``
and is the *only* external dependency; it is monkeypatched in tests.

Design:
- All filesystem paths resolve through ``config.workflow.skill_registry_path``
  so the module works identically on host (./skills) and in-container
  (/app/skills).
- The git clone cache lives in a sibling ``.skill_cache/`` directory next to
  the skills dir (host: .skill_cache/, container: /app/.skill_cache/).
- ``update_skill`` / ``sync_from_sources`` read configured GitHub sources
  from ``config/skill_sources.yaml`` (the Feature 1 config-driven source).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config.loader import config
from tools.loader import build_skill_registry, parse_skill_md

__all__ = [
    "SkillUpdateError",
    "SkillRegistrationError",
    "list_skills",
    "register_skill",
    "remove_skill",
    "update_skill",
    "sync_from_sources",
    "_git_clone_or_pull",
    "_skills_dir",
    "_cache_dir",
]


class SkillUpdateError(Exception):
    """Raised when a skill update from a source fails (bad repo, missing skill, git error)."""


class SkillRegistrationError(Exception):
    """Raised when registering a skill whose SKILL.md is malformed (no frontmatter name)."""


def _skills_dir() -> Path:
    """Resolve the skills root from config (host ./skills or container /app/skills)."""
    return Path(config.workflow.skill_registry_path).expanduser()


def _cache_dir() -> Path:
    """Git clone cache, sibling to the skills dir (never inside it)."""
    return _skills_dir().resolve().parent / ".skill_cache"


def _refresh_registry() -> None:
    """Force the loader's mtime-cached registry to rebuild from disk.

    The loader caches on the newest SKILL.md mtime, so a file written in the
    same second can be skipped; clearing the cache (``_registry = {}``)
    guarantees the next ``build_skill_registry`` call re-scans. (Setting
    ``_registry_mtime`` alone is not enough — the ``if _registry and ...``
    guard short-circuits on a non-empty cache.)
    """
    import tools.loader as loader

    loader._registry = {}
    loader.build_skill_registry(str(_skills_dir()))


def list_skills() -> List[Dict[str, Any]]:
    """Return every skill under the skills dir as a flat list of registry entries.

    Each entry: ``{name, version, path, description, triggers, category, active_in_graph}``.
    ``active_in_graph`` is True when the skill name is in the module-level
    active set (kept in sync with ``skills/PHASE_SKILL_MAP.md``) — the Web UI
    only needs the flag for display.
    """
    # Names the graph actively loads (PHASE_SKILL_MAP: all ✅ rows, plus the
    # local custom skills wired into VERIFY/SHIP/PLAN).
    active = {
        "interview-me", "fabric-prompts", "coding-principles", "idea-refine",
        "spec-driven-development", "source-driven-development", "api-and-interface-design",
        "planning-and-task-breakdown", "doubt-driven-development", "architecture-diagram-generator",
        "incremental-implementation", "frontend-ui-engineering", "test-driven-development",
        "ai-workflow-data-seeding", "uat-workflow", "security-and-hardening",
        "pre-commit-review", "observability-and-instrumentation", "shipping-and-launch",
        "production-deployment", "git-workflow",
    }
    registry = build_skill_registry(str(_skills_dir()))
    out: List[Dict[str, Any]] = []
    for name, skill in sorted(registry.items()):
        out.append({
            "name": skill.get("name", name),
            "version": skill.get("version", "1.0.0"),
            "path": skill.get("path", ""),
            "description": skill.get("description", ""),
            "triggers": skill.get("triggers", []),
            "category": skill.get("category", ""),
            "active_in_graph": name in active,
        })
    return out


def register_skill(name: str, content: str, *, source: str = "manual") -> Dict[str, Any]:
    """Write a new skill from raw SKILL.md text and return the registry entry.

    ``content`` must contain valid YAML frontmatter with a ``name`` field.
    Raises SkillRegistrationError on malformed input; any partial write is
    rolled back before the raise.
    """
    # A skill name must start with an ASCII letter, end with a letter or
    # digit, and contain only ASCII letters, digits, '-' or '_' (UAT
    # Finding 5: '7bad', '-leading', 'trailing-' and 'UPPER' previously
    # slipped through the isalnum check).
    if not name or not re.fullmatch(r"[a-z][a-z0-9_-]*[a-z0-9]|[a-z]", name):
        raise SkillRegistrationError(f"Invalid skill name: {name!r}")

    target_dir = _skills_dir() / name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "SKILL.md"
    target_file.write_text(content)

    parsed = parse_skill_md(str(target_file))
    meta = parsed.get("meta") or {}
    if not meta.get("name"):
        target_file.unlink(missing_ok=True)
        target_dir.rmdir()
        raise SkillRegistrationError(
            f"SKILL.md for '{name}' has no frontmatter 'name' field — rolled back"
        )
    # Refresh the registry index so the new skill is immediately visible.
    _refresh_registry()
    return {
        "name": meta.get("name", name),
        "version": str(meta.get("version", "1.0.0")),
        "path": str(target_file),
        "description": meta.get("description", ""),
        "source": source,
    }


def remove_skill(name: str) -> bool:
    """Delete skills/<name>/. Returns True if a directory was removed."""
    target = _skills_dir() / name
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    _refresh_registry()
    return True


def _git_clone_or_pull(repo: str, ref: str, dest: Path) -> None:
    """Clone ``repo`` at ``ref`` into ``dest``; if present, fetch + checkout ref.

    Subprocess ``git``. Bounded timeout from ``config.Skills.update_timeout_s``.
    Raises SkillUpdateError on any failure.
    """
    timeout = getattr(config.Skills, "update_timeout_s", 120)
    if not dest.exists():
        cmd = ["git", "clone", "--depth", "1", "--branch", ref, repo, str(dest)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError) as e:
            raise SkillUpdateError(f"git clone failed for {repo}@{ref}: {e}") from e
        return

    try:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
        # fetch --depth 1 rewrites origin/<ref> (forced update), leaving the
        # local <ref> branch diverged — `checkout <ref>` is then a no-op and
        # the working tree silently keeps stale content. reset --hard to the
        # ref we just fetched instead (works whether or not a local branch
        # exists under that name).
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", f"origin/{ref}"],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        raise SkillUpdateError(f"git pull failed for {repo}@{ref}: {e}") from e


def _load_sources() -> List[Dict[str, Any]]:
    """Read the configured GitHub sources from config/skill_sources.yaml."""
    path = Path(config.Skills.skill_sources_path).expanduser()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("sources", [])


def update_skill(
    name: str, *, source: Optional[str] = None, ref: Optional[str] = None
) -> Dict[str, Any]:
    """Pull skill ``name`` from a configured GitHub source and overwrite skills/<name>/SKILL.md.

    ``source`` is a key into config/skill_sources.yaml ``sources[].name``. If
    omitted, the first source listing ``name`` is used. ``ref`` overrides the
    source's ref. Raises SkillUpdateError if the skill is not present in the
    cloned repo.
    """
    sources = _load_sources()
    if not sources:
        raise SkillUpdateError("No skill sources configured (config/skill_sources.yaml empty)")

    chosen = None
    for src in sources:
        if source is not None and src.get("name") != source:
            continue
        skills_list = src.get("skills")
        if skills_list is None or name in skills_list:
            chosen = src
            break
    if chosen is None:
        raise SkillUpdateError(f"No source provides skill '{name}'")

    eff_ref = ref or chosen.get("ref", "main")
    dest = _cache_dir() / chosen.get("name", "cache")
    _git_clone_or_pull(chosen["repo"], eff_ref, dest)

    src_skill = dest / "skills" / name / "SKILL.md"
    if not src_skill.exists():
        raise SkillUpdateError(
            f"Skill '{name}' not found in {chosen['repo']}@{eff_ref} under skills/{name}/"
        )
    content = src_skill.read_text()
    return register_skill(name, content, source=chosen.get("name", "github"))


def sync_from_sources() -> List[Dict[str, Any]]:
    """Iterate every configured source and update every skill it lists.

    Returns ``[{name, source, ref, status}]`` where status is
    ``updated (v<ver>)`` or ``error: <msg>``. A failure on one skill never
    aborts the remaining skills.
    """
    results: List[Dict[str, Any]] = []
    for src in _load_sources():
        src_name = src.get("name", "?")
        ref = src.get("ref", "main")
        skills_list = src.get("skills") or []
        if not skills_list:
            # null = pull every skill under the repo's skills/ subtree
            dest = _cache_dir() / src_name
            _git_clone_or_pull(src.get("repo", ""), ref, dest)
            skills_dir_in_repo = dest / "skills"
            if skills_dir_in_repo.is_dir():
                skills_list = [p.name for p in skills_dir_in_repo.iterdir() if p.is_dir()]
        for skill_name in skills_list:
            try:
                entry = update_skill(skill_name, source=src_name, ref=ref)
                results.append({"name": skill_name, "source": src_name, "ref": ref,
                               "status": f"updated (v{entry.get('version', '?')})"})
            except SkillUpdateError as e:
                results.append({"name": skill_name, "source": src_name, "ref": ref,
                               "status": f"error: {e}"})
    return results
