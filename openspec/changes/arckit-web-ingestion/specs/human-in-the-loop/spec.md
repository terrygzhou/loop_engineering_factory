# human-in-the-loop (delta)

## MODIFIED Requirements

### Requirement: ArcKit auto-ingestion
When valid ArcKit artefacts (ADMP/REQ/STKE/OAAL/PRIN) are present in the
context folder — or supplied as an explicit `arckit_artifacts` list —
DISCOVER SHALL auto-populate setup and interview answers and skip their
interrupts (EYW-171 §4.1). The pre-scan SHALL run in every interactive
run (i.e. whenever `auto_approve` is off), including forced-HIL runs
driven by the Web bridge (`force_hil=True`); headless auto-approve
(`auto_approve=True`, stub path) SHALL keep skipping the scan. When no
valid artefacts are found, DISCOVER SHALL fall through to the existing
HIL gates unchanged (project setup and/or generic interview).

#### Scenario: Valid ArcKit context under forced HIL
- **WHEN** a Web UI run (force_hil=True) starts with a context folder
  containing a valid ArcKit artefact set
- **THEN** DISCOVER auto-populates setup + interview from the artefacts,
  skips both interrupts, and records `discover_artifact_audit` in
  artifacts

#### Scenario: Forced HIL with no valid artefacts keeps the interview gate
- **WHEN** a Web UI run (force_hil=True) starts with an empty or
  non-ArcKit context folder and no `arckit_artifacts` list
- **THEN** DISCOVER pauses at the generic interview interrupt as before
- **WHEN** an auto-approve run starts with valid ArcKit context
- **THEN** the scan is skipped and the stub auto-approve path runs
  (existing behaviour, unchanged)

## ADDED Requirements

### Requirement: Explicit ArcKit artefact list from the Web API
The `POST /api/start` body SHALL accept an optional `arckit_artifacts`
field (array of path strings, container-visible paths). When non-empty,
the bridge SHALL seed `state["arckit_artifacts"]` so DISCOVER ingests
exactly those artefacts via the loader's explicit-list path (glob
discovery skipped, per-file MALFORMED_FILENAME tolerance) — independent
of `context_folder`. An absent or empty field SHALL leave the key unset
so glob discovery of `context_folder` remains the default.

#### Scenario: Operator posts an explicit list
- **WHEN** POST /api/start includes two valid artefact paths in
  `arckit_artifacts`
- **THEN** DISCOVER parses only those files (no glob scan),
  auto-populates from them per the ArcKit auto-ingestion requirement,
  and the `discover_artifact_audit` record reflects the explicit list

#### Scenario: Empty list preserves glob behaviour
- **WHEN** POST /api/start omits `arckit_artifacts` or sends `[]`
- **THEN** `state["arckit_artifacts"]` is unset and discovery runs via
  `context_folder` globs, exactly as before
