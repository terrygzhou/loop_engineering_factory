# Change: ArcKit Tier-2 artefact ingestion into DISCOVER

## Why

DISCOVER ingests only 5 of the 17 artefact types the ArcKit `togaf-adm` and
`oaa` plugins produce (`ADMP`, `REQ`, `STKE`, `OAAL`, `PRIN`). A 2026-09-16
evidence review of the two plugins and their generated trees
(`test-adm-australian-post`, `test-oaa-australian-post`,
`test-oaa-australian-post-product`, `test-oaa-dummy` in
`~/projects/arc-kit`) found five further types that are structurally
machine-parseable and carry content DISCOVER/PLAN currently cannot see:

| Type | Source command | DISCOVER/PLAN value |
|------|---------------|---------------------|
| `OAPR` | oaa `product-architecture` | Product mission/outcome → project description; backlog **with architecture items** → PLAN work breakdown; **D1–D10 coverage table with explicit `TBD` unresolved fields** → targeted HIL interview questions instead of the generic interview |
| `OASTR` | oaa `agile-strategy` | Strategy canvas → objectives/value props; transformation **wave sequencing** → delivery shape |
| `BPCM` | togaf-adm `business-capability-map` | Capability hierarchy L1–L3 + maturity table + value streams → capability seeds |
| `GAPA` | togaf-adm `gap-analysis` | Gaps/pain points → constraints/risks seeds |
| `TRANS` | togaf-adm `transition-architecture` | Transition waves → delivery shape where no `OAAL` exists (ADM-based projects) |

The `OAPR` D1–D10 "Unresolved Fields" list (verified in the ParcelTrack tree:
`D2/D8` capability+gap questions and `D5` current-state question, each rendered
as the exact interview question text) is the single highest-leverage input: it
turns the factory's interview from generic into targeted at near-zero parser
cost (one table + one bullet list per artefact).

## What changes

Phased TDD waves (P0 first, P1 follows in the same change):

- **P0 — `OAPR` ingestion.**
  - Loader: add `OAPR` to `DISCOVER_TYPES` + `_TYPE_GLOBS` + `_EXTRACTORS`
    (tools/arckit_loader.py). OAPR uses the OAA 2-column header-table style
    (no `## Document Control` section — parse like `OAAL` header), and its
    fenced YAML blocks (§1 mission/outcome, §3 backlog, §5 value streams) are
    extracted as content, not code.
  - Seeds: mission+outcome → `project_description` fallback with precedence
    ADMP vision → REQ business context → OAPR mission; product backlog
    (architecture items) → new DISCOVER artifact key `arckit_product_backlog`
    (carried forward for PLAN/BUILD, mirroring `oaal_sprint_map`).
  - HIL targeting: DISCOVER writes
    `artifacts.arckit_open_questions` (per `TBD` dimension: question
    text) and the synthesised interview notes gain an
    **"Open questions (OAPR D1–D10)"** section listing the same
    questions. EYW-171 skip semantics are unchanged — a valid artefact
    set still skips both interrupts; residual questions are answered at
    the existing ARCH_REVIEW gate (see P0.5 below), never a new pause.
- **P0 — ARCH_REVIEW missing-build-inputs channel** (user decision
  2026-09-16: residual build-critical information is asked at the
  existing ARCH_REVIEW HIL gate, not a new pause).
  - When `artifacts.arckit_open_questions` (OAPR `TBD` dimensions) is
    non-empty, or the discovery audit shows valuable-absent Tier-2
    types, the ARCH_REVIEW interrupt payload gains a
    `missing_build_inputs` field (open questions + advisory
    "valuable but absent" type list).
  - The resume payload accepts an optional `answers` mapping
    (question → text); non-empty answers → `artifacts.arch_review_answers`,
    handed to BUILD as advisory context. Answers never change
    approval routing; ACHG and px-gate interlocks apply unchanged.
  - `graph/nodes/review.py` payload + resume handling; no routing change.
- **P1 — `OASTR` + `BPCM` + `GAPA` + `TRANS` ingestion.**
  - `OASTR`: strategy-canvas dimensions → `objectives`/`outcomes` seeds;
    transformation waves (Defend/Attack/outcome) → new DISCOVER artifact key
    `arckit_strategy_waves`.
  - `TRANS`: transition-wave table → `arckit_strategy_waves` fallback when no
    `OASTR` waves exist (delivery shape for pure-ADM projects).
  - `BPCM`: capability hierarchy (L1–L3) + maturity rows → "Capabilities"
    section of the synthesised interview notes.
  - `GAPA`: gap/pain-point bullets → Constraints/Risks sections of the
    synthesised notes.

Test fixtures are generated artefacts copied from the ArcKit repo's
`test-oaa-dummy` and `test-oaa-australian-post-product` trees (OAPR/OASTR),
plus ADM-test `BPCM`; `GAPA`/`TRANS` fixtures are authored to their
templates' section shapes.

## Non-goals

- **`DISC.md`** (the ADM `discovery` command writes a plain `DISC.md`,
  which the canonical `ARC-NNN-XXXX` filename pattern cannot match) —
  deferred to a follow-up change that adds a fallback glob, if wanted.
- `TECH`, `DATA`, `APP`, `APPR` (PLAN/ARCH_REVIEW context, not interview
  seeds) and governance types `OAGOV`, `OASEC`, `BORD`, `ACHG`, `REPO`.
- No change to the filename canonical pattern, to the five existing
  extractors' behaviour, to the `files=` explicit-list path, or to the
  EYW-171 auto-populate skip semantics.
- No new HIL interrupt; targeted questions flow through the existing
  synthesised-interview content path and, for build-critical gaps, the
  existing ARCH_REVIEW gate.

## Impact

- Affected specs: `human-in-the-loop` (ArcKit auto-ingestion type list;
  new OAPR open-questions + delivery-shape carry-forward requirements).
- Code: `tools/arckit_loader.py` (extractors, globs, seed merge,
  `synthesize_interview_notes`), `graph/nodes/discover.py` (new artifact
  keys), `graph/nodes/review.py` (`missing_build_inputs` payload +
  `answers` resume), `graph/state.py` (new artifacts keys),
  `tests/test_arckit_loader.py` + new fixtures under
  `tests/fixtures/arckit/` + review tests.
- `AGENTS.md`: DISCOVER phase note gains the Tier-2 type list + new keys.
- `openspec/config.yaml`: the `open_questions_resolved` entry "New ArcKit
  TYPE codes in v2 — No new types planned" is superseded by this change.
- Governance: adds three top-level `artifacts.*` keys read back
  by different nodes (`arckit_product_backlog`, `arckit_strategy_waves`,
  `arch_review_answers`) — covered by this change per SPEC.md §7
  ask-first rule.
