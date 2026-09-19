"""W5 acceptance-test execution for the VERIFY node (seam split, node-module-seams spec)."""

import subprocess
import time
from typing import Any

from config.bounds_loader import bounds


def _run_acceptance_tests(
    tests: list[dict], project_path: str, writer
) -> dict:
    """W5: execute each spec acceptance-test check locally (bounded).

    Each check runs via ``subprocess`` (shell, cwd=project_path) with
    the per-test timeout from ``config/bounds.yaml``
    (``bounds.verify.acceptance_timeout_s``). Returns a dict keyed by
    test id: ``{id, check, expect, passed, output, timed_out}`` where
    ``passed`` is ``returncode == 0`` and a timed-out check is
    ``passed=False, timed_out=True``.
    """
    timeout = bounds.verify.acceptance_timeout_s
    results: dict[str, dict] = {}
    for test in tests:
        test_id = str(test.get("id", "AT-?"))
        check = str(test.get("check", ""))
        expect = str(test.get("expect", ""))
        record: dict[str, Any] = {
            "id": test_id,
            "check": check,
            "expect": expect,
            "passed": False,
            "output": "",
            "timed_out": False,
        }
        writer(
            {
                "type": "progress",
                "phase": "VERIFY",
                "step": "progress",
                "detail": f"  → Acceptance test {test_id}: {check or '(no check command)'}",
                "ts": time.time(),
            }
        )
        if not check:
            record["output"] = "no check command - counted as failure"
        elif timeout <= 0:
            record["timed_out"] = True
            record["output"] = "timed out (0s timeout budget)"
        else:
            try:
                proc = subprocess.run(
                    check,
                    shell=True,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                record["passed"] = proc.returncode == 0
                record["output"] = ((proc.stdout or "") + (proc.stderr or ""))[-500:]
            except subprocess.TimeoutExpired:
                record["passed"] = False
                record["timed_out"] = True
                record["output"] = f"Timeout after {timeout}s"
            except Exception as e:  # noqa: BLE001 - bounded: any check error is a failure
                record["output"] = str(e)
        results[test_id] = record
    return results
