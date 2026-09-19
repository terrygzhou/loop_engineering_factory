# Node-Module Split — First Slice (No.1 + No.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land OpenSpec commit (No.1) + the first executable slice of the node-module split (No.2): S0 seam conventions, S1 `review_payload.py`, S6 verify siblings, S9-scan `discover_scan.py` — all with re-export shims and a green gate.

**Architecture:** Option A thin-node siblings. Helpers move to `graph/nodes/<phase>_<concern>.py`; the node file keeps a re-export line for every moved name so all existing imports (`from graph.nodes.review import _parse_json_artifact`, `import graph.nodes.verify as verify_mod`, `patch("graph.nodes.discover._detect_project_type")`, …) keep resolving. Pure move: no behavior change; byte-identity pinned by existing tests.

**Tech Stack:** Python 3.12, LangGraph, pytest, ruff.

**Spec:** `openspec/changes/2026-09-19-node-module-split/specs/node-module-seams/spec.md`

## Global Constraints

- Seam rule: a function moves ONLY when it has no `interrupt()` / `invoke_skill*` / `httpx` / LLM-`asyncio.gather`, no owned audit/writer emission, and a stateless signature.
- Node files keep: the `*_node` entry point, HIL `interrupt()` call sites, LLM orchestration (Decision-3 None-coercion at call site), audit/writer emissions, partial-update delta construction.
- Public import surface of every node module is UNCHANGED (`graph/main.py` byte-identical).
- Sibling modules are imported ONLY by their owning node file or by tests.
- No new runtime dependencies.
- Gate: `pytest tests/ -q` with the 7 hang files `--ignore`d (`test_bridge_custom_events`, `test_checkpointer`, `test_discover_arckit`, `test_runner`, `test_runner_hil_loop`, `test_ui_bridge`, `test_w3_behavioral`) and `--deselect "tests/test_health.py"` → 0 failures; `ruff check` on changed files clean. (Sandbox caveat: 4 pre-existing failures in `test_build_subgraph_d5` ×2 + `test_skill_registry` ×2 are env issues, NOT regressions — verify against stash if in doubt.)

---

### Task 1: No.1 — commit OpenSpec artifacts

**Files:**
- Verify: `openspec/changes/2026-09-19-node-module-split/{proposal.md,tasks.md,specs/node-module-seams/spec.md,specs/repo-structure/spec.md}`

- [ ] **Step 1: Verify the 4 artifacts exist and are complete on disk.**

Run: `ls openspec/changes/2026-09-19-node-module-split/ openspec/changes/2026-09-19-node-module-split/specs/*/`
Expected: all 4 files present with content (not empty/stub).

- [ ] **Step 2: Check git state — are they committed?**

Run: `git log --oneline -3 -- openspec/changes/2026-09-19-node-module-split/`
If already committed (a turnsnap commit exists), check `git status --short openspec/` — if clean, No.1 is satisfied; record the commit hash and skip to Task 2. If there are uncommitted changes, commit with:

```bash
git add openspec/changes/2026-09-19-node-module-split/
git commit -m "docs(openspec): node-module-split change (proposal + 4 spec artifacts)

Option A thin-node sibling split for graph/nodes monoliths.
Seam rule + per-file target shape in proposal.md;
ordered tasks S0–S11 in tasks.md;
node-module-seams + repo-structure spec deltas."
```

- [ ] **Step 3: Verify commit**

Run: `git log --oneline -1 -- openspec/` — expected: descriptive commit (not `[turnsnap]`). If a turnsnap commit is the only one and the tree is clean, that is acceptable — record it.

---

### Task 2: S0 — `tests/test_node_seams.py` seam-test skeleton

**Files:**
- Create: `tests/test_node_seams.py`

**Interfaces:**
- Produces: a test file later tasks append seam tests to; module docstring documents the 4-seam convention.

- [ ] **Step 1: Write the skeleton**

Create `tests/test_node_seams.py` with a module docstring ("Seam tests for graph/nodes sibling modules: pure helpers importable without LLM/network/checkpointer monkeypatching.") and one placeholder test that passes trivially, e.g.:

```python
def test_node_seams_module_importable():
    """The seam-test module is collected."""
    assert True
```

- [ ] **Step 2: Run + commit**

Run: `.venv/bin/python3 -m pytest tests/test_node_seams.py -q` → 1 passed.
Run: `.venv/bin/ruff check tests/test_node_seams.py` → clean.
Commit: `git add tests/test_node_seams.py && git commit -m "test(seams): S0 seam-test skeleton (test_node_seams.py)"`

---

### Task 3: S1 — `review.py` → `graph/nodes/review_payload.py`

**Files:**
- Create: `graph/nodes/review_payload.py`
- Modify: `graph/nodes/review.py` (move 5 helpers; add re-export block)
- Test: append to `tests/test_node_seams.py`

**Interfaces:**
- Consumes: `_parse_json_artifact` (json.loads best-effort, None on unusable), `_missing_build_inputs(artifacts: dict) -> list[str]` (uses `_parse_json_artifact` + `VALUABLE_ARTIFACT_TYPES` from `tools.arckit_loader`), `_resolve_achg_context(state: dict) -> dict` (uses `scan_achg_context` from `graph.achg_scanner`), `_extract_task_breakdown(plan_text: str) -> list` (regex only), `_spec_summary(spec_text: str, max_chars: int = 500) -> str`.
- Produces: `graph.nodes.review_payload.{_parse_json_artifact,_missing_build_inputs,_resolve_achg_context,_extract_task_breakdown,_spec_summary}` importable directly; `review.py` re-exports all 5.

**Seam-rule notes:** `_resolve_achg_context` calls `scan_achg_context` (filesystem scan, deterministic — allowed). No LLM, no interrupt, no audit emission. All 5 qualify.

- [ ] **Step 1: Create `graph/nodes/review_payload.py`**

Move the 5 function bodies verbatim. Sibling imports (top of file):

```python
import json
import re

from graph.achg_scanner import scan_achg_context
from tools.arckit_loader import VALUABLE_ARTIFACT_TYPES
```

Module docstring: `"""Pure helpers for the ARCH_REVIEW node (seam split, node-module-seams spec)."""`

- [ ] **Step 2: Edit `graph/nodes/review.py`**

Delete the 5 function definitions; replace with:

```python
from graph.nodes.review_payload import (
    _parse_json_artifact,
    _missing_build_inputs,
    _resolve_achg_context,
    _extract_task_breakdown,
    _spec_summary,
)  # noqa: F401  — re-exported for existing test imports
```

Remove now-unused top-level `import json` / `import re` ONLY if nothing else in `review.py` uses them (`review.py` still uses `json.dumps` at L428/L470 → keep `import json`; `re` was only used by `_extract_task_breakdown` → drop it if unused; verify with ruff). Keep the `VALUABLE_ARTIFACT_TYPES` import line only if still referenced in `review.py` (it isn't after the move — remove).

- [ ] **Step 3: Append seam tests to `tests/test_node_seams.py`**

```python
def test_review_parse_json_artifact():
    from graph.nodes.review_payload import _parse_json_artifact
    assert _parse_json_artifact('{"a": 1}') == {"a": 1}
    assert _parse_json_artifact("not json") is None
    assert _parse_json_artifact("") is None
    assert _parse_json_artifact(None) is None


def test_review_spec_summary_truncation():
    from graph.nodes.review_payload import _spec_summary
    assert _spec_summary("short") == "short"
    assert _spec_summary("") == ""
    out = _spec_summary("x" * 600, 500)
    assert len(out) <= 504 and out.endswith(" ...")


def test_review_extract_task_breakdown():
    from graph.nodes.review_payload import _extract_task_breakdown
    plan = "- [ ] task one\n- [x] task two\n1. task three\nsome milestone line\n"
    tasks = _extract_task_breakdown(plan)
    assert "task one" in tasks and "task two" in tasks
    assert _extract_task_breakdown("") == []
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python3 -m pytest tests/test_node_seams.py tests/test_review_missing_inputs.py tests/test_arch_review_interlocks.py tests/test_w2_wayforward.py -q` → all pass (re-exports keep `graph.nodes.review._*` resolvable).
Run: `.venv/bin/ruff check graph/nodes/review.py graph/nodes/review_payload.py tests/test_node_seams.py` → clean.
- [ ] **Step 5: Commit** — `git commit -m "refactor(review): S1 move 5 pure helpers to review_payload.py (re-export shim)"`

---

### Task 4: S6 — `verify.py` → `verify_review.py` + `verify_tooling.py` + `verify_acceptance.py`

**Files:**
- Create: `graph/nodes/verify_review.py`, `graph/nodes/verify_tooling.py`, `graph/nodes/verify_acceptance.py`
- Modify: `graph/nodes/verify.py`
- Test: append to `tests/test_node_seams.py`

**Interfaces:**
- `verify_review.py`: `_collect_source_files(project_path, max_files=30, max_file_bytes=80_000) -> list[dict]` (stdlib only: `pathlib`); `_build_review_context(files, spec_text) -> str` (pure); `_parse_review_result(review_text) -> dict` (pure parsing); `_write_review_report(project_path, review_text, findings) -> str` (filesystem write — allowed; needs `json`, `pathlib`).
- `verify_tooling.py`: `_find_venv_python(project_path) -> str | None` (pathlib); `_run_test_infrastructure(project_path, writer, audit) -> dict` (subprocess + shutil + `writer`/`audit` are passed in, not owned → qualifies).
- `verify_acceptance.py`: `_run_acceptance_tests(tests, project_path, writer) -> dict` (subprocess + `bounds.verify.acceptance_timeout_s` read — the caller node already reads `bounds`; pass the timeout in? NO: keep reading `bounds` at module top to stay byte-identical; seam rule allows config reads the caller already performs — `verify_node` imports `bounds`).

- [ ] **Step 1: Create the 3 siblings** with the moved bodies verbatim; each with its own import header (only what it uses: `verify_review` → `json, pathlib.Path`; `verify_tooling` → `shutil, subprocess, time, pathlib.Path` + `AuditLog` NOT imported — `audit` is a passed-in param, just type-annotate loosely or omit; `verify_acceptance` → `subprocess, time, typing.Any` + `from config.bounds_loader import bounds`).

- [ ] **Step 2: Edit `graph/nodes/verify.py`** — delete moved bodies; add:

```python
from graph.nodes.verify_review import (
    _collect_source_files, _build_review_context, _parse_review_result, _write_review_report,
)  # noqa: F401
from graph.nodes.verify_tooling import _find_venv_python, _run_test_infrastructure  # noqa: F401
from graph.nodes.verify_acceptance import _run_acceptance_tests  # noqa: F401
```

Clean up now-unused imports in `verify.py` (e.g. `subprocess` may stay for nothing — verify with ruff).

- [ ] **Step 3: CRITICAL monkeypatch check** — `tests/test_verify_acceptance.py` L149/161 patches `"graph.nodes.verify._run_test_infrastructure"`. Because `verify_node` calls `_run_test_infrastructure` as a module-global name, and `verify.py` re-imports it, patching `graph.nodes.verify._run_test_infrastructure` STILL works (the call site resolves from `verify.py`'s namespace). Verify: run `tests/test_verify_acceptance.py -q` — all pass. If a patch target broke (the patched attribute is looked up in the sibling at call time — it is NOT; the call is inside `verify_node` in `verify.py`), fix by pointing the patch at the sibling (import lines only).

- [ ] **Step 4: Append seam tests**

```python
def test_verify_parse_review_result_counts():
    from graph.nodes.verify_review import _parse_review_result
    r = _parse_review_result(
        "Critical: broken import at a.py:3\nRequired: missing error handling\n"
        "- [x] item\n**Nit: style thing here**\n"
    )
    assert r["critical"] == 1 and r["verdict"] == "changes"
    r2 = _parse_review_result("All good, no issues found at all here")
    assert r2["verdict"] in ("approve", "changes")


def test_verify_find_venv_python(tmp_path):
    from graph.nodes.verify_tooling import _find_venv_python
    assert _find_venv_python(str(tmp_path)) is None
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python3").write_text("#!/usr/bin/env python3")
    assert _find_venv_python(str(tmp_path)) == str(tmp_path / ".venv" / "bin" / "python3")


def test_verify_collect_source_files(tmp_path):
    from graph.nodes.verify_review import _collect_source_files
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "b.py").write_text("y = 2\n")
    files = _collect_source_files(str(tmp_path))
    assert [f["path"] for f in files] == ["a.py"]


def test_verify_build_review_context():
    from graph.nodes.verify_review import _build_review_context
    ctx = _build_review_context([{"path": "a.py", "content": "x"}], "SPEC")
    assert "a.py" in ctx and "SPEC" in ctx
```

- [ ] **Step 5: Verify + commit**

Run: `.venv/bin/python3 -m pytest tests/test_node_seams.py tests/test_verify_acceptance.py tests/test_w2_wayforward.py -q`
Run: `.venv/bin/ruff check graph/nodes/verify.py graph/nodes/verify_review.py graph/nodes/verify_tooling.py graph/nodes/verify_acceptance.py`
Commit: `git commit -m "refactor(verify): S6 split into verify_review/verify_tooling/verify_acceptance (re-export shims)"`

---

### Task 5: S9-scan — `discover.py` → `graph/nodes/discover_scan.py`

**Files:**
- Create: `graph/nodes/discover_scan.py`
- Modify: `graph/nodes/discover.py`
- Test: append to `tests/test_node_seams.py`

**Interfaces (all pure, stdlib-only or `toml`/`json` local imports):**
`_scan_codebase`, `_detect_project_type`, `_inventory_tree`, `_detect_framework`, `_discover_routes`, `_discover_models`, `_discover_templates`, `_discover_dependencies`, `_get_git_status` (subprocess — deterministic, no LLM → allowed), `_get_docker_status`, `_discover_specs`, `_collect_plain_docs`.

Seam note: `_collect_plain_docs` and the scanners are called by `discover_node` and by `_extract_doc_prefill` (which stays in `discover.py` because it calls `invoke_skill`). The sibling needs no LLM imports. `_scan_codebase` calls the other scanners — all in the sibling → no cross-phase import.

- [ ] **Step 1: Create `graph/nodes/discover_scan.py`** — move the 12 bodies verbatim. Sibling imports: `import json, re, subprocess, from pathlib import Path`.
- [ ] **Step 2: Edit `graph/nodes/discover.py`** — delete the 12 bodies; add re-export block (12 names, `# noqa: F401`). Remove `import subprocess` from `discover.py` if now unused (check: `_get_git_status` moved — grep first).
- [ ] **Step 3: CRITICAL monkeypatch check** — `tests/test_discover.py` imports `_detect_project_type`, `_inventory_tree`, `_discover_routes`, `_discover_dependencies`, `_scan_codebase`, `_generate_requirement_template`, `_generate_requirement_via_fabric` from `graph.nodes.discover` (re-export keeps all valid). `tests/test_discover_docs_prefill.py` L209-227 imports `_collect_plain_docs` (re-export keeps valid). Verify by running both.
- [ ] **Step 4: Append seam tests**

```python
def test_discover_detect_project_type(tmp_path):
    from graph.nodes.discover_scan import _detect_project_type
    assert _detect_project_type(str(tmp_path)) == "unknown"
    (tmp_path / "pyproject.toml").write_text("[project]")
    assert _detect_project_type(str(tmp_path)) == "python"
    (tmp_path / "package.json").write_text("{}")
    # pyproject wins (checked first)
    assert _detect_project_type(str(tmp_path)) == "python"


def test_discover_inventory_tree(tmp_path):
    from graph.nodes.discover_scan import _inventory_tree
    (tmp_path / "src" / "a.py").parent.mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / ".git").mkdir()
    tree = _inventory_tree(str(tmp_path))
    assert "src" in tree and ".git" not in tree
    assert tree["src"]["type"] == "dir"


def test_discover_git_status_no_repo(tmp_path):
    from graph.nodes.discover_scan import _get_git_status
    out = _get_git_status(str(tmp_path))
    assert set(out) == {"branch", "dirty"}


def test_discover_collect_plain_docs(tmp_path):
    from graph.nodes.discover_scan import _collect_plain_docs
    (tmp_path / "notes.md").write_text("hello")
    (tmp_path / "ARC-001-REQ.md").write_text("arckit")
    out = _collect_plain_docs(str(tmp_path))
    assert [p.name for p in out] == ["notes.md"]
```

- [ ] **Step 5: Verify + commit**

Run: `.venv/bin/python3 -m pytest tests/test_node_seams.py tests/test_discover.py tests/test_discover_docs_prefill.py -q`
Run: `.venv/bin/ruff check graph/nodes/discover.py graph/nodes/discover_scan.py`
Commit: `git commit -m "refactor(discover): S9-scan move 12 scanners to discover_scan.py (re-export shims)"`

---

### Task 6: Full gate close-out

- [ ] **Step 1: Run the documented gate**

```bash
.venv/bin/python3 -m pytest tests/ -q \
  --ignore=tests/test_bridge_custom_events.py \
  --ignore=tests/test_checkpointer.py \
  --ignore=tests/test_discover_arckit.py \
  --ignore=tests/test_runner.py \
  --ignore=tests/test_runner_hil_loop.py \
  --ignore=tests/test_ui_bridge.py \
  --ignore=tests/test_w3_behavioral.py \
  --deselect "tests/test_health.py"
```

Expected: 0 failures (the 4 pre-existing env failures in `test_build_subgraph_d5` ×2 + `test_skill_registry` ×2 are documented env issues — confirm via `git stash` they pre-exist).

- [ ] **Step 2: `ruff check .`** on the whole repo → clean (or only pre-existing issues).
- [ ] **Step 3: Verify `graph/main.py` is byte-identical**: `git diff HEAD~5 -- graph/main.py` → no output (the split must not touch graph wiring).
- [ ] **Step 4: Record gate numbers** in the final report.
