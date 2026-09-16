# human-in-the-loop (delta)

## MODIFIED Requirements

### Requirement: ArcKit auto-ingestion
When valid ArcKit artefacts are present in the context folder, DISCOVER SHALL
auto-populate setup and interview answers and skip their interrupts (EYW-171).
Ingested types: Tier-1 `ADMP`/`REQ`/`STKE`/`OAAL`/`PRIN`; Tier-2
`OAPR`/`OASTR`/`BPCM`/`GAPA`/`TRANS`; build-context `DATA`/`TECH`/`OASEC`
(canonical `ARC-NNN-XXXX` pattern, per-type highest-version selection) and
`OAA-ADM-lite` (content-based fallback glob: a fenced `vision.yaml` block whose
`vision.scope` contains `use_cases`). Tier-2 and build-context artefacts SHALL
be discovered in the same scan; a malformed or unparseable artefact SHALL be
recorded in the `discover_artifact_audit` and skipped without aborting the
scan. Any subset of the fourteen types is a valid context: absent types SHALL
leave their derived keys unset (never sentinel values), and a valid context
requires at least one valid artefact of any type.

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

## ADDED Requirements

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
