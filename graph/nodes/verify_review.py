"""Pure helpers for the VERIFY node review pipeline (seam split, node-module-seams spec)."""

import json
from pathlib import Path


# ── Source-file collectors ─────────────────────────────────────────


def _collect_source_files(
    project_path: str, max_files: int = 30, max_file_bytes: int = 80_000
) -> list[dict]:
    """Walk *project_path* and return a list of {path, content} dicts for
    reviewable source files (skipping __pycache__, .git, build/, node_modules)."""
    root = Path(project_path)
    if not root.exists():
        return []
    exclude = {"__pycache__", ".git", "node_modules", ".venv", "build", ".pytest_cache"}
    suffixes = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
    }
    files: list[dict] = []
    for fpath in sorted(root.rglob("*")):
        if (
            fpath.is_file()
            and fpath.suffix in suffixes
            and not any(p in fpath.parts for p in exclude)
        ):
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if len(text.encode("utf-8")) > max_file_bytes:
                text = text[:max_file_bytes]
            files.append({"path": str(fpath.relative_to(root)), "content": text})
            if len(files) >= max_files:
                break
    return files


def _build_review_context(files: list[dict], spec_text: str) -> str:
    """Assemble a context string for the code review LLM call."""
    parts: list[str] = []
    if spec_text:
        parts.append(f"## Project Spec\n{spec_text[:3000]}\n")
    parts.append("## Source Files\n")
    for f in files:
        parts.append(f"\n--- {f['path']} ---\n{f['content']}\n")
    return "\n".join(parts)


# ── Review-result parser ────────────────────────────────────────────


def _parse_review_result(review_text: str) -> dict:
    """Extract structured findings from LLM review text.

    Returns dict with keys:
      issues (list[str]), critical (int), required (int), optional (int),
      nit (int), verdict ("approve" | "changes")
    """
    issues: list[str] = []
    critical = 0
    required = 0
    optional = 0
    nit = 0

    for line in review_text.splitlines():
        line_lower = line.strip().lower()
        if "critical:" in line_lower:
            critical += 1
            issues.append(line.strip())
        elif line_lower.startswith("- [x]") or line_lower.startswith("- [ ]"):
            continue  # checklist lines
        elif any(
            line.strip().startswith(prefix)
            for prefix in ("**Nit:", "**Optional:", "**Consider:", "**FYI")
        ):
            if "nit:" in line_lower:
                nit += 1
            elif "optional:" in line_lower or "consider:" in line_lower:
                optional += 1
            issues.append(line.strip())
        elif line.strip() and not line.strip().startswith(("##", "---", "---", "#")):
            # Treat non-empty non-heading lines as findings
            if len(line.strip()) > 10:
                required += 1
                issues.append(line.strip())

    # Verdict: if critical issues exist, changes required; otherwise approve
    verdict = "changes" if critical > 0 else "approve"

    return {
        "issues": issues,
        "critical": critical,
        "required": required,
        "optional": optional,
        "nit_count": nit,
        "total": critical + required + optional + nit,
        "verdict": verdict,
    }


# ── Report writer ───────────────────────────────────────────────────


def _write_review_report(project_path: str, review_text: str, findings: dict) -> str:
    """Write code_review.md to the project's build/ directory."""
    build_dir = Path(project_path) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    report_path = build_dir / "code_review.md"

    summary = json.dumps({k: v for k, v in findings.items() if k != "issues"}, indent=2)
    md = [
        "# Code Review Report",
        "",
        "## Summary",
        f"- Verdict: **{findings['verdict']}**",
        f"- Critical: {findings['critical']}  |  Required: {findings['required']}  |  "
        f"Optional: {findings['optional']}  |  Nit: {findings.get('nit_count', 0)}",
        f"- Total findings: {findings['total']}",
        "",
        "## Metadata",
        f"```\n{summary}\n```",
        "",
        "## Full Review",
        "",
        review_text,
    ]
    content = "\n".join(md)
    report_path.write_text(content, encoding="utf-8")
    return str(report_path)
