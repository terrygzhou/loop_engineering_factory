# Change: ArcKit build-context ingestion (Lane A, types DATA/TECH/OASEC/OAA-ADM-lite)

## Why

The factory splits architecture truth (Lane A: provided by a human or read from ArcKit
artefacts) from engineering output (Lane B: generated inside the factory — spec, plan,
diagrams, acceptance tests). BUILD currently sees neither Lane A context: its prompt
is spec + plan + tasks + doubt + 4 PLAN-generated diagrams + `arch_review_answers`.
Four ArcKit types carry build-critical architecture content that no other source
covers, verified against the `arckit-togaf-adm` / `arckit-oaa` templates and the
generated test trees:

| Type | Source command | Build-critical content |
|------|---------------|------------------------|
| `DATA` | togaf-adm `data-architecture` | Entity/relationship model + data classification + data flows → SEED_DATA + VERIFY; a wrong data model = broken seeding |
| `TECH` | togaf-adm `technology-architecture` | Integration-pattern table (pub/sub, gRPC, REST) + API-standards table + integration security + observability stack → stops the build agent inventing its own stack |
| `OASEC` | oaa `agile-security` | AuthN/AuthZ model + threat responses → concrete security controls instead of "add auth" |
| `OAA-ADM-lite` | oaa `oaa-adm-lite` | `vision.yaml` `use_cases` array + NFR constraints (`user_count`, `latency_requirement_ms`, `infrastructure`, `jurisdiction`, budget) → scale targets + the explicit use-case list |

`OAA-ADM-lite` (and `DISC.md`) do not match the canonical `ARC-NNN-XXXX` filename
glob — a fallback glob is required (the `DISC.md` follow-up deferred in
`arckit-tier2-ingestion` is folded into this change).

These types were explicit non-goals of `arckit-tier2-ingestion` (PLAN/ARCH_REVIEW
context, not interview seeds). This change promotes them to ingested advisory
context: read-only inputs to DEFINE/PLAN/BUILD, never routing inputs.

## What changes

- **Loader** (`tools/arckit_loader.py`): new extractors + `_TYPE_GLOBS` entries for
  `DATA`, `TECH`, `OASEC` (canonical pattern) and `OAA-ADM-lite` (fallback glob:
  file contains a fenced `vision.yaml` block whose `vision.scope` has `use_cases`;
  also covers `DISC.md`-style names). All use the header-table + fenced-YAML
  parsing shared with Tier-1/Tier-2; malformed artefacts are audit-logged and
  skipped (existing Tier-2 rule, unchanged).
- **New `artifacts.*` keys** (written by DISCOVER, read back by other nodes —
  SPEC.md §7 ask-first rule, covered by this change):
  - `arckit_data_model` — DATA entities/relationships/classification rows
  - `arckit_integration_standards` — TECH messaging-patterns + API-standards +
    integration-security tables
  - `arckit_security_controls` — OASEC authN/authZ + threat-response controls
  - `arckit_nfr_constraints` — OAA-ADM-lite `use_cases` + NFR fields
  Absent types leave keys unset (never sentinel values), consistent with all
  Tier-1/Tier-2 keys.
- **DEFINE** (`graph/nodes/define.py`): `arckit_integration_standards` +
  `arckit_nfr_constraints` fed as advisory context into the parallel
  source-driven + api-design LLM calls (prompt capping per engineering-conventions
  applies).
- **BUILD** (`graph/nodes/openhands_build.py`): `_build_prompt` gains advisory
  sections, each emitted only when the key is set: `arckit_data_model`,
  `arckit_integration_standards`, `arckit_security_controls`,
  `arckit_nfr_constraints`, `arckit_product_backlog`, `arckit_strategy_waves`
  (the last two come from `arckit-tier2-ingestion`). `arch_review_answers`
  (Tier-2 P0.5) is already specified to flow here.
- **ARCH_REVIEW** (`graph/nodes/review.py`): the `missing_build_inputs` advisory
  "valuable but absent" list (defined in `arckit-tier2-ingestion` P0.5) is
  extended to include `DATA`/`TECH`/`OASEC`/`OAA-ADM-lite` when absent from the
  tree. Payload/resume shape unchanged.
- **SEED_DATA** (`graph/nodes/seed_data.py`): when `arckit_data_model` is set,
  seed generation is driven by it instead of being a pure pass-through.

## Non-goals

- No new HIL interrupts; no routing changes; ACHG/px-gate interlocks unchanged.
- No change to VERIFY's gate semantics (that is `verify-acceptance-criteria`).
- No change to PLAN's diagram set (that is `plan-sequence-view`).
- No renderer/parsing change for the existing 5 Tier-1 + 5 Tier-2 types.
- `DISC.md` content is still deferred (fallback-glob plumbing lands here; the
  DISC extractor itself is a follow-up).
- OAA-ADM-lite is not promoted to a canonical-pattern type; its glob is
  content-based (vision.yaml signature) by design.

## Impact

- Affected specs: `human-in-the-loop` (ArcKit auto-ingestion type list + new
  carry-forward keys), `build-delegation` (BUILD prompt advisory-context
  requirement).
- Code: `tools/arckit_loader.py`, `graph/state.py`, `graph/nodes/discover.py`,
  `graph/nodes/define.py`, `graph/nodes/review.py`,
  `graph/nodes/openhands_build.py`, `graph/nodes/seed_data.py`; tests + fixtures
  under `tests/fixtures/arckit/`.
- `AGENTS.md`: DISCOVER phase note + artifacts-key inventory.
- Wave order: after `arckit-tier2-ingestion` P0+P1 (shares the loader's
  Tier-2 extractor scaffolding and the P0.5 answers channel).
