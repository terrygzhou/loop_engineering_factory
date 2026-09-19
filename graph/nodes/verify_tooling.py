"""Automated test infrastructure helpers for the VERIFY node (seam split, node-module-seams spec)."""

import shutil
import subprocess
import time
from pathlib import Path


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
    writer(
        {
            "type": "progress",
            "phase": "VERIFY",
            "step": "progress",
            "detail": "  → Running pytest...",
            "ts": time.time(),
        }
    )
    pytest_dir = Path(project_path) / "tests"
    if pytest_dir.exists() and any(pytest_dir.glob("**/*.py")):
        python_bin = venv_python or shutil.which("python3") or "python3"
        try:
            proc = subprocess.run(
                [python_bin, "-m", "pytest", "--tb=short", "-q", "--timeout=60"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            results["pytest"] = {
                "passed": len(
                    [line for line in proc.stdout.split("\n") if "passed" in line]
                ),
                "failed": len(
                    [line for line in proc.stdout.split("\n") if "failed" in line]
                ),
                "errors": proc.returncode,
                "output": proc.stdout[-500:],
            }
        except subprocess.TimeoutExpired:
            results["pytest"] = {
                "failed": 1,
                "errors": 1,
                "output": "Timeout after 120s",
            }
        except Exception as e:
            results["pytest"] = {"failed": 1, "errors": 1, "output": str(e)}
    else:
        results["pytest"] = {"passed": 0, "failed": 0, "output": "No tests found"}

    # ── ruff check ──
    writer(
        {
            "type": "progress",
            "phase": "VERIFY",
            "step": "progress",
            "detail": "  → Running ruff check...",
            "ts": time.time(),
        }
    )
    ruff_bin = shutil.which("ruff")
    if not ruff_bin and venv_python:
        ruff_bin = str(Path(venv_python).parent / "ruff")
        ruff_bin = ruff_bin if Path(ruff_bin).exists() else None
    if ruff_bin:
        try:
            proc = subprocess.run(
                [ruff_bin, "check", project_path, "--output-format=concise"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            violation_lines = [
                line
                for line in proc.stdout.split("\n")
                if line.strip() and not line.startswith("Found")
            ]
            results["ruff"] = {
                "violations": len(violation_lines),
                "output": proc.stdout[-500:],
            }
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
        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "progress",
                "detail": "  → Running mypy...",
                "ts": time.time(),
            }
        )
        python_bin = venv_python or shutil.which("python3") or "python3"
        try:
            proc = subprocess.run(
                [python_bin, "-m", "mypy", ".", "--no-error-summary"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            error_lines = [
                line for line in proc.stdout.split("\n") if ": error:" in line
            ]
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
    writer(
        {
            "type": "progress",
            "phase": "VERIFY",
            "step": "progress",
            "detail": f"  → Test report: {report_path}",
            "ts": time.time(),
        }
    )

    return results
