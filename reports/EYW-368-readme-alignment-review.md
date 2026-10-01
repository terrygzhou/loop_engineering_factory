# EYW-368 — README / codebase alignment review (reviewer disposition)

- **Issue:** EYW-368 — "review the code against readme"
- **Reviewed commit:** `ff8f0db` (EYW-368: align README + edges.py comments with current code)
- **Reviewer:** CEO (agent 2e7617b4)
- **Date:** 2026-09-30 (AEST)
- **Verdict:** **APPROVED** — the executor's 7-item drift fix is correct, complete, and zero-behavior-change. Verified independently against the live tree.

## Method

Re-derived every README claim against the live code and `config/` values; did not trust the
executor's comments. Confirmed the dead-edge text is gone, re-counted the skill registry,
re-ran the stated test suite and linter.

## Verification results

| # | Fix claimed | Independent check | Result |
|---|------------|-------------------|--------|
| R1 | `BUILD --> REFLECT` dead edge → `BUILD --> ERROR` (budget exhausted) | README L36 now `BUILD --> ERROR : retry budget (BUILD_MAX_RETRIES=2) exhausted`; prose L92 matches. `openhands_merge.py:71` `BUILD_MAX_RETRIES=2`, `:135` halts on `fail_count > 2`. `grep 'consecutive build failures'` → 0 hits in README+edges.py. | ✅ aligned |
| R2 | 35 → 34 skills; tree = live | `ls -d skills/*/` = **34** dirs, each has SKILL.md; README tree regex-extract = **34** unique names; `diff` live-vs-README = **identical**. "34 skills" at README L255; `pre-commit-review` present. | ✅ aligned |
| R3 | VERIFY = conditional gate (Decision 2 + W5) | README L251 describes VERIFY as conditional gate writing `verify_status`, fail → BUILD/ERROR. No "placeholder/pass-through to SHIP" wording remains for VERIFY. | ✅ aligned |
| R4 | SEED_DATA model-driven / placeholder | README L250: "Model-driven when `arckit_data_model` is set ... otherwise a pass-through placeholder (`skipped_placeholder`)". No docker seed-script execution claim. | ✅ aligned |
| R5 | base_url → `http://pop-os:8080/v1` | README L322/L425 both `http://pop-os:8080/v1`; live `config/config.yaml:10` identical. No `host.docker.internal` remains. | ✅ aligned |
| R6 | project_name + openhands block | README L417 `test-proj-123` (matches live L2); README L446-450 `openhands:` block present, values match live `config/config.yaml:49-53`. | ✅ aligned |
| R7 | image.png screenshot-pending note | README L5 `![](image.png)` + L7 "Screenshot pending" note; `image.png` confirmed absent in repo root. | ✅ aligned |

**Live-suite confirmation:** `.venv/bin/python3 -m pytest tests/test_edges.py tests/test_workflow_lifecycle.py tests/test_w2_wayforward.py -q` → **97 passed in 3.67s** (matches executor). `ruff check .` → **All checks passed!**. `git status` clean.

## Out-of-scope items flagged by executor (accepted as-is, tracked, not blocking)

1. **Restore `image.png`** — the actual Web UI screenshot is not in the repo root; README now carries a "screenshot pending" note. Cosmetic; needs a capture before publish.
2. **AGENTS.md test-suite count drift** — AGENTS.md still cites 322/364 (and "322 tests across 17 test files") while the live suite is larger (~626 / 28 files). This doc was **not** touched by `ff8f0db` (only `README.md` + `graph/edges.py`), so it remains a separate, open drift item.

Both are minor and do not block approval of the README-alignment work.

## Reviewer notes / follow-ups

- **AGENTS.md count drift** is the one substantive residual: AGENTS.md's Testing section and
  the "322 tests across 17 test files" line are now stale. Recommend a follow-up task to
  re-count and update AGENTS.md (and any hardcoded counts in docs) so all three docs
  (README, AGENTS.md, CLAUDE.md) agree with the live suite.
- **image.png**: owner to capture a current Web UI screenshot and drop it at repo root,
  then drop the "screenshot pending" note.
- No code behavior changed; no new test added for the README fix (docs-only, correct).

## Disposition

- **Action:** `approve` → close EYW-368 as `done`.
- **Remaining (non-blocking):** create follow-up issue(s) for the two out-of-scope items above.
