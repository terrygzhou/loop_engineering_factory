"""W5 acceptance-test execution for the VERIFY node (seam split, node-module-seams spec)."""

import re
import shlex
import subprocess
import time
from typing import Any

from config.bounds_loader import bounds

# ── Check-command hardening (P1 security fix) ─────────────────────
# Checks are LLM/spec-derived. Running them through shell=True is an
# RCE surface: an LLM (or a prompt-injected spec) can emit commands
# like "rm -rf / && echo ok" or "cat ~/.ssh/id_rsa". Defense:
#  1. Allowlist of trusted executable names (argv[0]). Shell
#     binaries (bash/sh/zsh) are NOT allowlisted — any shell would
#     turn a check into arbitrary command execution.
#  2. Reject any check containing shell metacharacters (| & ; $( ` < >)
#     so compound/injected commands and redirections never reach a
#     shell. Note: the allowlist alone does not prevent a spec from
#     invoking an allowlisted binary with a payload argument (e.g.
#     "curl" fetching a URL is allowed); the meta-char filter and the
#     binary allowlist together bound what reaches subprocess.
# A rejected check is recorded as a failure (passed=False) — it is
# never executed.
_ALLOWED_CHECK_BINARIES = frozenset(
    {
        # language / build tooling
        "pytest", "python", "python3", "node", "npm", "npx", "make",
        "ruby", "bundle", "rspec", "cargo", "go", "pip", "pip3",
        "yarn", "pnpm", "deno", "bun", "mvn", "gradle",
        # POSIX utilities (no shells: a shell argv would re-open the
        # arbitrary-execution surface the allowlist is meant to close)
        "true", "false", "echo", "test", "printf",
        "sleep", "which", "uname", "env",
        # inspection
        "curl", "jq", "docker", "git", "ls", "cat", "grep", "diff",
        "cmp",
    }
)

# Shell metacharacters that enable command chaining / expansion /
# substitution / redirection. None of these may appear in a check
# string.
_SHELL_META_RE = re.compile(r"[|&;`$()<>]|\n|\r")


def _validate_check_command(check: str) -> tuple[list[str] | None, str]:
    """Validate a check command against the allowlist.

    Returns (argv, "") on success, or (None, reason) when the command
    is rejected (not executed; caller records a failure).
    """
    if _SHELL_META_RE.search(check):
        return None, "rejected: shell metacharacters in check"
    try:
        argv = shlex.split(check)
    except ValueError as e:
        return None, f"rejected: unparseable check ({e})"
    if not argv:
        return None, "rejected: empty check"
    base = argv[0].rsplit("/", 1)[-1]
    if base not in _ALLOWED_CHECK_BINARIES:
        return None, f"rejected: binary '{base}' not in allowlist"
    return argv, ""


def _run_acceptance_tests(
    tests: list[dict], project_path: str, writer
) -> dict:
    """W5: execute each spec acceptance-test check locally (bounded).

    Each check runs via ``subprocess`` (argv form, no shell,
    cwd=project_path) with the per-test timeout from ``config/bounds.yaml``
    (``bounds.verify.acceptance_timeout_s``). Checks are validated
    against a binary allowlist; shell metacharacters and unknown
    binaries are rejected and recorded as failures (never executed).
    Returns a dict keyed by test id: ``{id, check, expect, passed,
    output, timed_out}`` where ``passed`` is ``returncode == 0`` and a
    timed-out check is ``passed=False, timed_out=True``.
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
            argv, reject_reason = _validate_check_command(check)
            if argv is None:
                # Rejected checks are never executed — recorded as failure.
                record["output"] = reject_reason
            else:
                try:
                    proc = subprocess.run(
                        argv,
                        shell=False,
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
