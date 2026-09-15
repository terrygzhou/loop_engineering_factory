# Tasks: arckit-web-ingestion

## 1. DISCOVER pre-scan under forced HIL (TDD)

- [x] 1.1 RED: re-point `tests/test_discover_arckit.py::test_force_hil_preserved`
      to the new contract — valid ArcKit tree + `force_hil=True` → node
      returns WITHOUT raising (auto-populated: project_name from ADMP,
      `discover_setup_done=True`, `discover_interview_done=True`, audit
      valid ≥ 3). Add `test_force_hil_no_artifacts_keeps_interview`:
      empty context + force_hil → interview interrupt still fires
      (patched interrupt, call_count == 1).
- [x] 1.2 Run the two tests — new expectation FAILS (node raises
      interrupt outside graph), fallback test passes.
- [x] 1.3 GREEN: `graph/nodes/discover.py` — change the scan gate from
      `if not auto_approve and not force_hil:` to `if not auto_approve:`
      and update the block comment (auto_approve skips the scan as the
      stub path; forced-HIL runs now scan and auto-populate when valid
      artefacts exist).
- [x] 1.4 Re-run `tests/test_discover_arckit.py` — all green.

## 2. Web API explicit artefact list (TDD)

- [x] 2.1 RED: new `tests/test_bridge_arckit_seed.py`:
      (a) `StartRequest` accepts and defaults `arckit_artifacts` to `[]`
      and accepts a non-empty list;
      (b) `bridge._build_executor_state(..., arckit_artifacts=[p])`
      seeds `state["arckit_artifacts"] == [p]`; empty/absent → key
      absent.
- [x] 2.2 Run — FAILS (field/param do not exist).
- [x] 2.3 GREEN: add `arckit_artifacts: list[str] = []` to
      `StartRequest`; start handler sets `bridge._arckit_artifacts`;
      bridge attr declared in `__init__`; `_build_executor_state`
      gains the parameter and seeds state when non-empty; `run_real`
      call site passes `self._arckit_artifacts`.
- [x] 2.4 Re-run the new tests — green.

## 3. Docs + full verification

- [x] 3.1 `AGENTS.md`: DISCOVER phase line — note that Web/forced-HIL
      runs now perform the ArcKit pre-scan (auto-populate when valid
      artefacts present; HIL gates otherwise) and that `POST /api/start`
      accepts `arckit_artifacts`.
- [x] 3.2 Full suite: `.venv/bin/python3 -m pytest tests/ -q` (escalated
      — sandbox thread-pool deadlock) and `ruff check .` — 0 failures.
- [x] 3.3 Smoke re-test on the deployed stack: start Web run with
      `context_folder` pointing at an ArcKit tree → DISCOVER artifacts
      include `discover_artifact_audit` (+ `arckit_artifacts` when the
      list is posted). Done 2026-09-16: run A (`_smoke_arckit` tree,
      auto-populate logged "ArcKit artefacts detected") and run B
      (empty folder + posted `arckit_artifacts` list) both fired
      auto-population; run A aborted later in DEFINE on a pre-existing
      LLM-timeout robustness gap (unrelated).
