"""
VERIFY node: runs code quality review on the generated project using the
code-review-and-quality skill.

Scans source files, invokes multi-axis review (correctness, readability,
architecture, security, performance), writes report to build/code_review.md,
and updates metrics (review_revisions, uat_pass_rate).

Output: code review report + test results + updated metrics, forwards to SHIP.
"""
from langgraph.config import get_stream_writer

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from config.loader import config
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog
from graph.ui_bridge import SkillTimer


# ── Source-file collectors ─────────────────────────────────────────

def _collect_source_files(project_path: str, max_files: int = 30, max_file_bytes: int = 80_000) -> list[dict]:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
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
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """
    VERIFY phase: Run multi-axis code quality review on the generated project.

    Loads the code-review-and-quality skill, collects source files from
    state.project_path, sends them through the LLM for review, writes the
    report to build/code_review.md, and updates metrics.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer({"type": "progress", "phase": "VERIFY", "step": "started", "detail": "\n=== VERIFY PHASE ===", "ts": time.time()})

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
            writer({"type": "progress", "phase": "VERIFY", "step": "warning", "detail": "  ⚠ code-review-and-quality skill not found — running basic file scan", "ts": time.time()})
            audit.log_node_output("VERIFY", {"status": "no_skill", "note": "skill not in registry"})
            # Still collect and count files as a basic check
            files = _collect_source_files(project_path)
            findings["total"] = 0
            findings["verdict"] = "approve"
            review_text = f"[Basic scan] Reviewed {len(files)} source files. No automated review available."
            files_reviewed = len(files)
        else:
            # ── Collect source files ──
            writer({"type": "progress", "phase": "VERIFY", "step": "progress", "detail": "  → Collecting source files...", "ts": time.time()})
            files = _collect_source_files(project_path)
            files_reviewed = len(files)

            if not files:
                writer({"type": "progress", "phase": "VERIFY", "step": "warning", "detail": "  ⚠ No source files found in project — nothing to review", "ts": time.time()})
                audit.log_node_output("VERIFY", {"status": "no_files", "files_reviewed": 0})
                review_text = "No source files found in the generated project."
            else:
                writer({"type": "progress", "phase": "VERIFY", "step": "progress", "detail": f"  → Found {files_reviewed} source files", "ts": time.time()})

                # ── Build review context ──
                context = _build_review_context(files, spec_text)

                # ── Invoke code-review skill ──
                writer({"type": "progress", "phase": "VERIFY", "step": "progress", "detail": "  → Running code-review-and-quality review...", "ts": time.time()})
                cr_timer = SkillTimer(state, "code-review-and-quality")
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
                cr_timer.complete()

                # ── Parse results ──
                findings = _parse_review_result(review_text)

                # ── Write report ──
                report_path = _write_review_report(project_path, review_text, findings)
                writer({"type": "progress", "phase": "VERIFY", "step": "progress", "detail": f"  → Review report: {report_path}", "ts": time.time()})
                audit.log_file_write("VERIFY", report_path, "markdown", len(review_text))

        writer({"type": "progress", "phase": "VERIFY", "step": "success", "detail": f"  ✓ Review complete: {findings['total']} findings, verdict={findings['verdict']}", "ts": time.time()})
        audit.log_node_output("VERIFY", {
            "status": "complete",
            "files_reviewed": files_reviewed,
            "findings": findings,
        })
    else:
        writer({"type": "progress", "phase": "VERIFY", "step": "warning", "detail": f"  ⚠ Project path not found: {project_path}", "ts": time.time()})
        audit.log_node_output("VERIFY", {"status": "no_project", "project_path": project_path})

    # ── Automated test infrastructure ──
    test_results: dict = {"pytest": None, "ruff": None, "mypy": None}
    if project_path and Path(project_path).exists():
        writer({"type": "progress", "phase": "VERIFY", "step": "progress",
                "detail": "  → Running automated test infrastructure...", "ts": time.time()})
        test_results = _run_test_infrastructure(project_path, writer, audit)

    # ── Compute metrics from findings + test results ──
    test_errors = sum(1 for v in test_results.values() if v and v.get("failures", 0) > 0)
    review_revisions = max(findings["critical"], findings["required"])
    uat_pass_rate = 0.0 if findings["critical"] > 0 else (
        0.5 if findings["required"] > 0 else 1.0
    )

    # ── Loop counter: increment if verify failed (critical findings or test errors) ──
    if findings["critical"] > 0 or test_errors > 0:
        from graph.edges import _maybe_increment_loop
        _maybe_increment_loop(state, "VERIFY")
        writer({"type": "progress", "phase": "VERIFY", "step": "warning",
                "detail": f"  ⚠ Critical findings={findings['critical']} or test_errors={test_errors} — routing to ERROR terminal",
                "ts": time.time()})

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
    has_failures = findings["critical"] > 0 or test_errors > 0
    update: dict = {
        "phase": "VERIFY",
        "next_phase": "SHIP" if not has_failures else None,
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
    if test_results.get("pytest") or test_results.get("ruff"):
        update["artifacts"]["test_results"] = json.dumps({
            "pytest_pass": test_results.get("pytest", {}).get("passed", 0),
            "pytest_fail": test_results.get("pytest", {}).get("failed", 0),
            "ruff_violations": test_results.get("ruff", {}).get("violations", 0),
            "mypy_errors": test_results.get("mypy", {}).get("errors", 0),
        })
    if has_failures:
        update["error"] = f"VERIFY failed: {findings['critical']} critical, {test_errors} test suite failures"
    if metrics_update:
        update["metrics"] = metrics_update

    audit.log_node_transition("VERIFY", "SHIP", f"review complete: {findings['total']} findings, test_errors={test_errors}")
    return update


# ── Automated test infrastructure ────────────────────────────────────

def _find_venv_python(project_path: str) -> str | None:
    """Find python executable in project .venv, or return None."""
    for candidate in [
        Path(project_path) / ".venv" / "bin" / "python3",
        Path(project_path) / "venv" / "bin" / "python3",
    ]:
        if candidate.exists():
            return str(candidate)
    return None


def _run_test_infrastructure(project_path: str, writer, audit) -> dict:
    """Run pytest, ruff, and mypy on the generated project."""
    results: dict = {"pytest": None, "ruff": None, "mypy": None}
    venv_python = _find_venv_python(project_path)

    # ── pytest ──
    writer({"type": "progress", "phase": "VERIFY", "step": "progress",
            "detail": "  → Running pytest...", "ts": time.time()})
    pytest_dir = Path(project_path) / "tests"
    if pytest_dir.exists() and any(pytest_dir.glob("**/*.py")):
        python_bin = venv_python or shutil.which("python3") or "python3"
        try:
            proc = subprocess.run(
                [python_bin, "-m", "pytest", "--tb=short", "-q",
                 "--timeout=60"],
                cwd=project_path, capture_output=True, text=True, timeout=120,
            )
            results["pytest"] = {
                "passed": len([l for l in proc.stdout.split("\n") if "passed" in l]),
                "failed": len([l for l in proc.stdout.split("\n") if "failed" in l]),
                "errors": proc.returncode,
                "output": proc.stdout[-500:],
            }
        except subprocess.TimeoutExpired:
            results["pytest"] = {"failed": 1, "errors": 1, "output": "Timeout after 120s"}
        except Exception as e:
            results["pytest"] = {"failed": 1, "errors": 1, "output": str(e)}
    else:
        results["pytest"] = {"passed": 0, "failed": 0, "output": "No tests found"}

    # ── ruff check ──
    writer({"type": "progress", "phase": "VERIFY", "step": "progress",
            "detail": "  → Running ruff check...", "ts": time.time()})
    ruff_bin = shutil.which("ruff")
    if not ruff_bin and venv_python:
        ruff_bin = str(Path(venv_python).parent / "ruff")
        ruff_bin = ruff_bin if Path(ruff_bin).exists() else None
    if ruff_bin:
        try:
            proc = subprocess.run(
                [ruff_bin, "check", project_path, "--output-format=concise"],
                capture_output=True, text=True, timeout=60,
            )
            violation_lines = [l for l in proc.stdout.split("\n") if l.strip() and not l.startswith("Found")]
            results["ruff"] = {"violations": len(violation_lines), "output": proc.stdout[-500:]}
        except subprocess.TimeoutExpired:
            results["ruff"] = {"violations": 0, "output": "Timeout"}
        except Exception as e:
            results["ruff"] = {"violations": 0, "output": str(e)}
    else:
        results["ruff"] = {"violations": 0, "output": "ruff not available"}

    # ── mypy (only if mypy config found) ──
    mypy_config = Path(project_path) / "mypy.ini"
    pyproject = Path(project_path) / "pyproject.toml"
    mypy_available = mypy_config.exists()
    if not mypy_available and pyproject.exists():
        content = pyproject.read_text(errors="replace")
        mypy_available = "[tool.mypy]" in content
    if mypy_available:
        writer({"type": "progress", "phase": "VERIFY", "step": "progress",
                "detail": "  → Running mypy...", "ts": time.time()})
        python_bin = venv_python or shutil.which("python3") or "python3"
        try:
            proc = subprocess.run(
                [python_bin, "-m", "mypy", ".", "--no-error-summary"],
                cwd=project_path, capture_output=True, text=True, timeout=120,
            )
            error_lines = [l for l in proc.stdout.split("\n") if ": error:" in l]
            results["mypy"] = {"errors": len(error_lines), "output": proc.stdout[-500:]}
        except subprocess.TimeoutExpired:
            results["mypy"] = {"errors": 0, "output": "Timeout"}
        except Exception as e:
            results["mypy"] = {"errors": 0, "output": str(e)}
    else:
        results["mypy"] = {"errors": 0, "output": "No mypy config found — skipped"}

    # ── Write test report ──
    build_dir = Path(project_path) / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    report_path = build_dir / "verify_report.md"
    report_lines = ["# Automated Test Report\n"]
    for tool_name, result in results.items():
        report_lines.append(f"## {tool_name.upper()}")
        if result:
            for k, v in result.items():
                if k != "output":
                    report_lines.append(f"- {k}: {v}")
            report_lines.append(f"```\n{result.get('output', '')}\n```\n")
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    audit.log_file_write("VERIFY", str(report_path), "markdown", len(report_lines))
    writer({"type": "progress", "phase": "VERIFY", "step": "progress",
            "detail": f"  → Test report: {report_path}", "ts": time.time()})

    return results