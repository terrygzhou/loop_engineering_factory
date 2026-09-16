## MODIFIED Requirements

### Requirement: ArcKit auto-ingestion
When valid ArcKit artefacts are present in the context folder, DISCOVER SHALL
auto-populate setup and interview answers and skip their interrupts
(EYW-171). Ingested types: Tier-1 `ADMP`/`REQ`/`STKE`/`OAAL`/`PRIN`;
Tier-2 `OAPR`/`OASTR`/`BPCM`/`GAPA`/`TRANS`; build-context `DATA`/`TECH`/
`OASEC` (canonical `ARC-NNN-XXXX` pattern, per-type highest-version
selection) and `OAA-ADM-lite` (content-based fallback glob: a fenced
`vision.yaml` block whose `vision.scope` contains `use_cases`). Tier-2 and
build-context artefacts SHALL be discovered in the same scan; a malformed or
unparseable artefact SHALL be recorded in the `discover_artifact_audit` and
skipped without aborting the scan. Any subset of the fourteen types is a
valid context: absent types SHALL leave their derived keys unset (never
sentinel values), and a valid context requires at least one valid artefact of
any type. The pre-scan SHALL run in every interactive run (i.e. whenever
`auto_approve` is off), including forced-HIL runs driven by the Web bridge
(`force_hil=True`); headless auto-approve (`auto_approve=True`, stub path)
SHALL keep skipping the scan. When no valid artefacts are found, DISCOVER
SHALL fall through to the existing HIL gates unchanged (project setup and/or
generic interview).

#### Scenario: Valid ArcKit context
- **WHEN** DISCOVER runs with a valid ArcKit artefact set
- **THEN** the setup and interview HIL pauses are skipped and answers come
  from the artefacts

#### Scenario: Build-context types ingest as advisory content
- **WHEN** the tree contains a valid DATA, TECH, OASEC, and OAA-ADM-lite
  artefact
- **THEN** all four are parsed and their content is available to DEFINE/PLAN/
  BUILD as advisory context, without changing any HIL skip semantics

#### Scenario: OAA-ADM-lite matched by content, not filename
- **WHEN** a vision-style file named `vision.md` (non-canonical) contains a
  fenced `vision.yaml` block with `vision.scope.use_cases`
- **THEN** it is ingested as `OAA-ADM-lite` via the fallback glob

#### Scenario: Malformed build-context artefact is skipped, not fatal
- **WHEN** the tree contains one valid ADMP and one TECH that fails schema
  validation
- **THEN** the ADMP is consumed, the TECH is recorded in the audit with its
  error, and ingestion proceeds

#### Scenario: Unrecognised status is PENDING
- **WHEN** an ACHG board status is unrecognised
- **THEN** it is normalised to PENDING and the interlock applies

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

#### Scenario: Auto-approve still skips the scan
- **WHEN** an auto-approve run (auto_approve=True) starts with valid
  ArcKit context
- **THEN** the pre-scan is skipped and the stub auto-approve path runs
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
