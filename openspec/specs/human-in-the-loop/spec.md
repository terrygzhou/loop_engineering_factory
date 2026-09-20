# human-in-the-loop

## Purpose
Human approval gates that pause the pipeline for operator decisions, a
headless auto-approve mode, and the ACHG safety interlock.

## Guidelines

### Guideline: Visibility and control over standalone agents
LEF's differentiation from standalone coding agents (Codex, OpenHands,
Claude) is the visibility and controllability provided by the LangGraph
state machine, not the build capability itself (BUILD is delegated to
OpenHands). Design SHALL therefore favour making the process inspectable
and pausable: structured phase state with typed artifacts, a live event
stream to the Web UI, and `interrupt()` gates at which a human can
review, comment (reject-with-feedback), pause, or skip/abort. New
features SHALL NOT trade a visibility or control surface for
autonomy (e.g. removing a HIL pause or suppressing an event stream)
without an explicit decision recorded in this spec.

## Requirements

### Requirement: HIL gates
The system SHALL pause at DISCOVER (project setup + interview, merged into one
node) and at ARCH_REVIEW using langgraph interrupt(); the compile-time
interrupt_after list SHALL apply only when auto_approve is off.

#### Scenario: Auto-approve bypass
- **WHEN** auto_approve=true in config or --auto-approve on the CLI
- **THEN** the graph compiles without interrupt_after and no HIL pauses fire

#### Scenario: Architectural reject
- **WHEN** a reviewer rejects at ARCH_REVIEW with feedback
- **THEN** the flow returns to PLAN with user_review_comments set

### Requirement: Interactive HIL cycle
The interactive CLI SHALL prompt at DISCOVER (project_setup + interview) and
at ARCH_REVIEW (approve/reject); approval SHALL advance to BUILD and rejection
SHALL loop back to PLAN carrying the reviewer's feedback.

#### Scenario: Approve at ARCH_REVIEW
- **WHEN** the reviewer approves the architecture at ARCH_REVIEW
- **THEN** the workflow advances to BUILD

### Requirement: ACHG safety interlock
When any ACHG board decision in the scanned ArcKit context is PENDING
(graph/achg_scanner.py has_pending_achg / pending_achg_ids), ARCH_REVIEW
auto-approval SHALL be blocked and an explicit human approve or reject SHALL be
required.

#### Scenario: PENDING ACHG blocks auto-approve
- **WHEN** auto-approve reaches ARCH_REVIEW and scan_achg_context reports a
  PENDING ACHG board decision
- **THEN** the gate pauses for an explicit human decision instead of
  auto-advancing

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

### Requirement: Explicit ArcKit artefact list input

`load_arckit_artifacts` (tools/arckit_loader.py) SHALL accept an optional
`files` parameter (iterable of path strings). When non-empty, glob
discovery SHALL be skipped and each file SHALL be parsed directly, with
type, project id and version derived from its filename via the existing
canonical filename pattern. Highest-version selection and same-version
conflict detection SHALL still apply per type. A non-conforming filename
SHALL be recorded as `MALFORMED_FILENAME` and skipped without aborting
the remaining files. When `files` is absent or empty, behaviour SHALL be
identical to today (root glob discovery).

DISCOVER (graph/nodes/discover.py) SHALL read `state["arckit_artifacts"]`
(a list of paths, optional) and pass it as `files` to the loader, so an
explicit list constrains ingestion to exactly those artefacts regardless
of the `context_folder` layout.

#### Scenario: Explicit list is ingested

- **WHEN** DISCOVER runs with `arckit_artifacts` listing an ADMP and an
  OAAL artefact from any directory layout
- **THEN** only those files are parsed (no glob scan), `has_valid_artifacts`
  reflects them, and setup + interview are auto-populated per EYW-171 §4

#### Scenario: Malformed filename is skipped, not fatal

- **WHEN** the list contains one file matching the canonical pattern and
  one that does not
- **THEN** the conforming file is parsed, the other is recorded as
  `MALFORMED_FILENAME` in the audit, and ingestion proceeds

#### Scenario: Empty list preserves legacy behaviour

- **WHEN** `arckit_artifacts` is absent or empty
- **THEN** discovery runs exactly as before via root globs

### Requirement: HIL field for ArcKit artefact paths

The DISCOVER `project_setup` interrupt payload SHALL include an optional
`arckit_artifacts` field (newline-separated artefact paths). DISCOVER
SHALL parse non-empty lines of the resumed value into a list and write it
to `state["arckit_artifacts"]`; an empty value SHALL leave the key unset
so glob discovery remains the default.

#### Scenario: Operator supplies paths at setup

- **WHEN** the operator answers the setup interrupt with two artefact
  paths, one per line
- **THEN** `state["arckit_artifacts"]` holds that list and the same
  ingestion path as the explicit-list scenario above applies on the next
  scan

#### Scenario: Operator leaves field empty

- **WHEN** the `arckit_artifacts` field is left empty
- **THEN** `state["arckit_artifacts"]` is not set and ingestion falls back
  to `context_folder` globs

### Requirement: Build-context carry-forward
DISCOVER SHALL write, when the corresponding valid artefact is present:
`artifacts.arckit_data_model` (DATA entities/relationships/classification),
`artifacts.arckit_integration_standards` (TECH messaging-patterns,
API-standards, and integration-security tables), `artifacts.arckit_security_controls` (OASEC authN/authZ and threat-response controls), and
`artifacts.arckit_nfr_constraints` (OAA-ADM-lite `use_cases` plus NFR fields).
DEFINE, PLAN, and BUILD SHALL consume these keys as read-only advisory context
and SHALL NOT use them as routing inputs; PLAN's consumption is defined by the
`plan-sequence-view` change. Absence of an artefact SHALL leave its key unset
(never a sentinel value). `artifacts.arckit_data_model`, when set, SHALL be
the driving input for SEED_DATA; when absent SEED_DATA SHALL retain its
existing pass-through behaviour.

#### Scenario: All four build-context artefacts present
- **WHEN** DISCOVER ingests valid DATA, TECH, OASEC, and OAA-ADM-lite
  artefacts
- **THEN** all four keys are written and each downstream node receives the
  corresponding advisory section

#### Scenario: No build-context artefacts changes nothing
- **WHEN** the tree contains only Tier-1 artefacts
- **THEN** no build-context key is written and DEFINE/PLAN/BUILD/SEED_DATA
  behaviour is identical to today

#### Scenario: Data model drives seeding
- **WHEN** SEED_DATA runs with `arckit_data_model` set
- **THEN** seed data is generated from the data model's entities and
  classification

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
