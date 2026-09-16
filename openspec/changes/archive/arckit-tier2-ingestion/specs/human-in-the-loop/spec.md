# human-in-the-loop (delta)

## MODIFIED Requirements

### Requirement: ArcKit auto-ingestion
When valid ArcKit artefacts (ADMP/REQ/STKE/OAAL/PRIN, and — Tier-2 —
OAPR/OASTR/BPCM/GAPA/TRANS) are present in the context folder, DISCOVER
SHALL auto-populate setup and interview answers and skip their
interrupts (EYW-171). Tier-2 artefacts SHALL be discovered via the same
canonical filename pattern and per-type highest-version selection as the
Tier-1 types; a malformed or unparseable Tier-2 artefact SHALL be
recorded in the `discover_artifact_audit` and skipped without aborting
the scan. Any subset of the ten types is a valid context: absent types
SHALL leave their derived keys unset (never sentinel values), and a
valid context requires at least one valid artefact of any type.

#### Scenario: Valid ArcKit context
- **WHEN** DISCOVER runs with a valid ArcKit artefact set
- **THEN** the setup and interview HIL pauses are skipped and answers come
  from the artefacts

#### Scenario: Tier-2 OAPR context auto-populates
- **WHEN** DISCOVER scans a tree containing a valid OAPR artefact
- **THEN** the OAPR mission/outcome is available for project description
  (precedence after ADMP and REQ), and the D1–D10 coverage table and
  backlog are parsed and recorded in the audit

#### Scenario: Partial type coverage is accepted
- **WHEN** the supplied folder contains only three of the ten types
  (e.g. PRIN, OAPR, OAAL)
- **THEN** those three are ingested, the other seven's keys stay unset,
  and auto-population proceeds on the partial context

#### Scenario: Malformed Tier-2 artefact is skipped, not fatal
- **WHEN** the tree contains one valid ADMP and one OAPR that fails
  schema validation
- **THEN** the ADMP is consumed, the OAPR is recorded in the audit with
  its error, and ingestion proceeds

#### Scenario: Unrecognised status is PENDING
- **WHEN** an ACHG board status is unrecognised
- **THEN** it is normalised to PENDING and the interlock applies

## ADDED Requirements

### Requirement: OAPR discovery-dimension open questions
When a valid OAPR artefact's D1–D10 coverage table lists `TBD`
dimensions (Unresolved Fields), DISCOVER SHALL write
`artifacts.arckit_open_questions` (a list of `{dimension, question}`
objects, one per `TBD` row) and the synthesised interview notes
(`synthesize_interview_notes`) SHALL include an
"Open questions (OAPR D1–D10)" section listing the same questions. This
section SHALL be appended to the existing synthesised content; it SHALL
NOT introduce an additional HIL interrupt, and the EYW-171 skip
semantics for a valid artefact set SHALL be unchanged. When no `TBD`
rows exist the key SHALL be unset.

#### Scenario: OAPR with unresolved dimensions targets the interview
- **WHEN** a valid OAPR marks D2, D5, D8 as `TBD` and DISCOVER
  auto-populates
- **THEN** `artifacts.arckit_open_questions` holds those three
  dimension/question pairs and the synthesised notes contain the
  "Open questions (OAPR D1–D10)" section, with no new interrupt

#### Scenario: OAPR with full coverage adds no section
- **WHEN** every D1–D10 dimension is confirmed (no `TBD`)
- **THEN** `artifacts.arckit_open_questions` is unset and no
  "Open questions (OAPR D1–D10)" section is emitted

### Requirement: Tier-2 delivery-shape carry-forward
When valid Tier-2 artefacts are present, DISCOVER SHALL write
`artifacts.arckit_product_backlog` (OAPR §3 product-backlog rows with
architecture items) and `artifacts.arckit_strategy_waves` (OASTR
transformation-wave rows; falling back to TRANS transition-wave rows
when no OASTR exists). PLAN and BUILD SHALL consume both keys as
delivery-shape context alongside the existing `oaal_sprint_map`;
absence of a key (type not present in the tree) SHALL leave it unset,
never a sentinel value.

#### Scenario: OAPR + OASTR present
- **WHEN** the tree contains valid OAPR and OASTR artefacts
- **THEN** DISCOVER writes both `arckit_product_backlog` and
  `arckit_strategy_waves` and PLAN receives them with `oaal_sprint_map`
  semantics (advisory delivery shape, not a routing input)

#### Scenario: TRANS provides the wave fallback
- **WHEN** the tree contains a valid TRANS artefact and no OASTR
- **THEN** `arckit_strategy_waves` holds the TRANS transition-wave rows

#### Scenario: No Tier-2 artefacts leaves keys unset
- **WHEN** the tree contains only Tier-1 artefacts
- **THEN** neither key is written and PLAN/BUILD behaviour is identical
  to today

### Requirement: ARCH_REVIEW missing-build-inputs channel
Residual build-critical information missing from the ingested ArcKit
context SHALL be asked at the existing ARCH_REVIEW human gate — no new
interrupt is introduced. When `artifacts.arckit_open_questions` is
non-empty, or the `discover_artifact_audit` shows valuable-absent
artefact types (Tier-2 types absent from the tree), the ARCH_REVIEW
interrupt payload SHALL include a `missing_build_inputs` field: the
open questions plus an advisory "valuable but absent" type list. The
resume payload SHALL accept an optional `answers` mapping
(question → answer text); non-empty answers SHALL be written to
`artifacts.arch_review_answers` and handed to BUILD as advisory context
alongside the plan. Answers SHALL NOT change approval routing, and the
ACHG safety interlock and px-gate interlock SHALL apply unchanged. When
nothing is missing, the field SHALL be absent and behaviour SHALL be
identical to today.

#### Scenario: Open questions surface at the gate
- **WHEN** ARCH_REVIEW pauses with `arckit_open_questions` holding two
  OAPR D-dimension questions
- **THEN** the payload's `missing_build_inputs` lists both questions and
  the reviewer may answer either or both before approving

#### Scenario: Answers feed BUILD, not routing
- **WHEN** the reviewer resumes with `approved=true` and two `answers`
- **THEN** `artifacts.arch_review_answers` holds them, BUILD receives
  them as advisory context, and approve/reject routing is unaffected

#### Scenario: Nothing missing changes nothing
- **WHEN** no open questions exist and no valuable types are absent
- **THEN** the payload has no `missing_build_inputs` field and the gate
  behaves exactly as today
