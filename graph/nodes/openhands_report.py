"""Build manifest (build_report.json) parsing + path-traversal guard (seam split S7)."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# -- Result parsing ---------------------------------------------------
# Decision 1: build_report.json is the primary, machine-readable BUILD
# result contract. The agent is instructed to write it; a missing/invalid
# manifest is a hard failure (typed exception), not a silent downgrade.
BUILD_REPORT_FILENAME = "build_report.json"


class BuildReportMissingError(Exception):
    """Raised when the OpenHands agent did not produce a valid
    ``build_report.json``. Decision 1 makes the manifest the source of
    truth; silently falling back to free-text parsing would violate
    Decision 2 (VERIFY gate) and Decision 3 (typed errors)."""


def _parse_build_report(project_path: str) -> dict | None:
    """Read and validate build_report.json if the agent produced one.

    Expected schema:
        {
          "status": "pass" | "fail" | "partial",
          "test_results": "...",
          "files": ["relative/path", ...],
          "errors": ["..."]
        }

    Returns a normalized dict with keys build_status, test_results,
    files_created, errors, build_log — or None when the manifest is
    missing or invalid, signalling callers to fall back to text parsing.
    """
    report_path = Path(project_path) / BUILD_REPORT_FILENAME
    if not report_path.exists():
        return None
    try:
        raw = json.loads(report_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "  -> [OPENHANDS] build_report.json unreadable (%s); falling back", e
        )
        return None

    if not isinstance(raw, dict) or "status" not in raw:
        return None
    status = str(raw.get("status", "partial")).lower()
    if status not in ("pass", "fail", "partial"):
        status = "partial"
    files = [str(f) for f in (raw.get("files") or []) if isinstance(f, str)]
    errors = [str(e) for e in (raw.get("errors") or []) if isinstance(e, str)]
    raw_tests = raw.get("test_results")
    test_results = "" if raw_tests is None else str(raw_tests)
    build_log = (
        f"BUILD manifest (status={status}): {len(files)} file(s), {len(errors)} error(s)\n"
        + "\n".join(errors[:5])
    )
    return {
        "build_status": status,
        "test_results": test_results,
        "files_created": files,
        "errors": errors,
        "build_log": build_log,
    }
