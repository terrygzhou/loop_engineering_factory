# Change: ArcKit ingestion reachable from the Web UI

## Why

The `arckit-artifact-list-input` change (options 1+2) wired an explicit
ArcKit artefact list and context-folder auto-population into DISCOVER, but
the deployed Web UI — the primary user-facing surface — can exercise
**neither** input path. A 2026-09-15 smoke run against the live stack
proved it: with `context_folder=/app/output/_smoke_arckit` (valid ADMP +
OAAL artefacts, verified visible in-container), DISCOVER produced zero
ArcKit artifacts and paused at the generic interview gate.

Root causes (two, both on the bridge/discover boundary):

1. `graph/nodes/discover.py` gates the ArcKit pre-scan on
   `if not auto_approve and not force_hil:` — and the Web bridge always
   sets `force_hil=True` (workflow_bridge._build_executor_state). So in
   every Web run the scan is skipped: no auto-population, and even an
   explicitly supplied `arckit_artifacts` list is ignored.
2. `frontend/backend/app.py` `StartRequest` has no `arckit_artifacts`
   field and `graph/executor.py` never seeds the key, so there is no
   API path for the explicit list at all. (The setup-interrupt form
   field added by `arckit-artifact-list-input` is unreachable in the Web
   flow because the bridge pre-seeds `discover_setup_done=True`.)

The base `human-in-the-loop` spec's "ArcKit auto-ingestion" requirement
already mandates auto-population "when valid ArcKit artefacts are
present in the context folder" with no force_hil exception — the node's
gating contradicts its own spec.

## What changes

- **DISCOVER pre-scan runs under force_hil.** The gate becomes
  `if not auto_approve:` — headless auto-approve (stub path) still skips
  the scan; forced-HIL runs (Web bridge) now scan and auto-populate when
  valid artefacts are found (skipping both interrupts per EYW-171 §4.1),
  and fall through to the existing HIL gates when none are found
  (generic interview, unchanged).
- **Web API explicit artefact list.** `StartRequest` gains an optional
  `arckit_artifacts: list[str]` field; the bridge carries it as
  `_arckit_artifacts` and seeds `state["arckit_artifacts"]` in
  `_build_executor_state` when non-empty, so the loader's explicit-list
  path (glob skip, MALFORMED_FILENAME tolerance) applies to Web runs.
- `tests/test_discover_arckit.py::test_force_hil_preserved` is
  re-pointed at the new behaviour (valid tree + force_hil →
  auto-populated, no interrupt); new tests pin force_hil + empty context
  → interview interrupt still fires (HIL preserved when no artefacts).

## Non-goals

- No change to auto-approve scan-skip behaviour (stub path unchanged).
- No change to `graph/executor.py` CLI seeding or CLI flags (CLI
  interactive HIL already works; Web is the gap).
- The setup-interrupt `arckit_artifacts` form field stays as-is (live in
  CLI interactive runs; unreachable in Web flow by design of the
  orphaned-resume fix).

## Impact

- Affected specs: `human-in-the-loop` (ArcKit auto-ingestion scope),
  `web-frontend` (start request body).
- Code: `graph/nodes/discover.py` (1-line gate + comment),
  `frontend/backend/app.py` (StartRequest + start handler),
  `frontend/backend/workflow_bridge.py` (attr + state builder + call
  site), `tests/test_discover_arckit.py`, new bridge seed test.
- `AGENTS.md`: DISCOVER phase note gains the Web-flow exception.
- Smoke re-test: Web run with ArcKit context_folder must show
  `discover_artifact_audit` + `arckit_artifacts` in DISCOVER artifacts.
