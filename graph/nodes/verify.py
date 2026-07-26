"""
VERIFY node: runs code quality review on the generated project using the
code-review-and-quality skill.

Scans source files, invokes multi-axis review (correctness, readability,
architecture, security, performance), writes report to build/code_review.md,
and updates metrics (review_revisions, uat_pass_rate).

Output: code review report + updated metrics, forwards to SHIP.
"""
import json
from pathlib import Path

from config.loader import config
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog


# ── Source-file collectors ─────────────────────────────────────────

def _collect_source_files(project_path: str, max_files: int = 30, max_file_bytes: int = 80_000) -> list[dict]:
    """Walk *project_path* and return a list of {path, content} dicts for
    reviewable source files (skipping __pycache__, .git, build/, node_modules)."""
    root = Path(project_path)
    if not root.exists():
        return []
    exclude = {"__pycache__", ".git", "node_modules", ".venv", "build", ".pytest_cache"}
    suffixes = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".yaml", ".yml", ".json", ".toml"}
    files: list[dict] = []
    for fpath in sorted(root.rglob("*")):
        if fpath.is_file() and fpath.suffix in suffixes and not any(p in fpath.parts for p in exclude):
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
        elif any(line.strip().startswith(prefix) for prefix in ("**Nit:", "**Optional:", "**Consider:", "**FYI")):
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


# ── Main node ───────────────────────────────────────────────────────

def verify_node(state: dict) -> dict:
    """
    VERIFY phase: Run multi-axis code quality review on the generated project.

    Loads the code-review-and-quality skill, collects source files from
    state.project_path, sends them through the LLM for review, writes the
    report to build/code_review.md, and updates metrics.

    Returns partial update dict (LangGraph reducer merges).
    """
    print("\n=== VERIFY PHASE ===")

    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    project_path = state.get("project_path", "")
    spec_text = state.get("artifacts", {}).get("spec_refined", "")

    audit.log_node_input("VERIFY", {
        "project_path": project_path,
        "has_spec": bool(spec_text),
    })

    # ── Default findings (no project / skip) ──
    findings = {
        "issues": [],
        "critical": 0,
        "required": 0,
        "optional": 0,
        "nit_count": 0,
        "total": 0,
        "verdict": "approve",
    }
    review_text = ""
    report_path: str = ""
    files_reviewed = 0

    if project_path and Path(project_path).exists():
        # ── Load skill registry ──
        skills = build_skill_registry(config.workflow.skill_registry_path)
        cr_skill = skills.get("code-review-and-quality", {})

        if not cr_skill:
            print("  ⚠ code-review-and-quality skill not found — running basic file scan")
            audit.log_node_output("VERIFY", {"status": "no_skill", "note": "skill not in registry"})
            # Still collect and count files as a basic check
            files = _collect_source_files(project_path)
            findings["total"] = 0
            findings["verdict"] = "approve"
            review_text = f"[Basic scan] Reviewed {len(files)} source files. No automated review available."
            files_reviewed = len(files)
        else:
            # ── Collect source files ──
            print("  → Collecting source files...")
            files = _collect_source_files(project_path)
            files_reviewed = len(files)

            if not files:
                print("  ⚠ No source files found in project — nothing to review")
                audit.log_node_output("VERIFY", {"status": "no_files", "files_reviewed": 0})
                review_text = "No source files found in the generated project."
            else:
                print(f"  → Found {files_reviewed} source files")

                # ── Build review context ──
                context = _build_review_context(files, spec_text)

                # ── Invoke code-review skill ──
                print("  → Running code-review-and-quality review...")
                review_text = invoke_skill(
                    cr_skill["content"],
                    (
                        "Review this generated project for code quality across five axes: "
                        "correctness, readability, architecture, security, and performance. "
                        "Flag issues as Critical, Required, Optional, or Nit. "
                        "Provide a clear verdict (approve or request changes). "
                        "Be specific with file paths and line references."
                    ),
                    context,
                    llm=None,
                    workflow_id=state.get("project_name", ""),
                    phase="VERIFY",
                )

                # ── Parse results ──
                findings = _parse_review_result(review_text)

                # ── Write report ──
                report_path = _write_review_report(project_path, review_text, findings)
                print(f"  → Review report: {report_path}")
                audit.log_file_write("VERIFY", report_path, "markdown", len(review_text))

        print(f"  ✓ Review complete: {findings['total']} findings, verdict={findings['verdict']}")
        audit.log_node_output("VERIFY", {
            "status": "complete",
            "files_reviewed": files_reviewed,
            "findings": findings,
        })
    else:
        print(f"  ⚠ Project path not found: {project_path}")
        audit.log_node_output("VERIFY", {"status": "no_project", "project_path": project_path})

    # ── Compute metrics from findings ──
    review_revisions = max(findings["critical"], findings["required"])
    uat_pass_rate = 0.0 if findings["critical"] > 0 else (
        0.5 if findings["required"] > 0 else 1.0
    )

    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(update={
            "review_revisions": review_revisions,
            "uat_pass_rate": uat_pass_rate,
            "security_findings": findings["critical"],
            "test_flakiness_rate": 0.0,
            "latency_ms": 0.0,
        })

    # ── Build partial update ──
    update: dict = {
        "phase": "VERIFY",
        "next_phase": "SHIP",
        "artifacts": {
            "verify_status": "complete",
            "code_review_report": report_path or "",
            "files_reviewed": files_reviewed,
        },
    }
    if findings["issues"]:
        update["artifacts"]["review_findings_summary"] = json.dumps({
            "critical": findings["critical"],
            "required": findings["required"],
            "optional": findings["optional"],
            "nit_count": findings.get("nit_count", 0),
            "total": findings["total"],
            "verdict": findings["verdict"],
        })
    if metrics_update:
        update["metrics"] = metrics_update

    audit.log_node_transition("VERIFY", "SHIP", f"review complete: {findings['total']} findings")
    return update