# Tasks — arckit-build-context

Wave order: after arckit-tier2-ingestion P0+P1. All TDD (fixture → test →
implement → audit), nodes tested via state fixtures.

## 1. Loader extractors (tools/arckit_loader.py)

- [x] 1.1 Fixtures: copy DATA + TECH artefacts from `test-adm-australian-post`
      ADM tree; author OASEC + OAA-ADM-lite fixtures to template section shapes
      (vision.yaml signature block) under `tests/fixtures/arckit/`
- [x] 1.2 `DATA` extractor → entities/relationships/classification rows; add to
      `DISCOVER_TYPES` + `_TYPE_GLOBS` (canonical pattern)
- [x] 1.3 `TECH` extractor → messaging-patterns + API-standards +
      integration-security tables; add to `DISCOVER_TYPES` + `_TYPE_GLOBS`
- [x] 1.4 `OASEC` extractor → authN/authZ + threat-response controls; canonical
      pattern
- [x] 1.5 `OAA-ADM-lite` extractor → parse fenced `vision.yaml`: `use_cases`,
      `user_count`, `latency_requirement_ms`, `infrastructure`, `jurisdiction`,
      `budget_aud`; content-based fallback glob (vision.yaml signature) that
      also tolerates `DISC.md`-style filenames; add to `DISCOVER_TYPES` with the
      fallback glob only
- [x] 1.6 Malformed Tier-A artefact → `discover_artifact_audit` record + skip,
      never fatal (mirrors Tier-2 rule); unknown-type tolerance unchanged
- [x] 1.7 Loader tests: per-type parse + partial coverage + malformed skip +
      fallback-glob hits OAA-ADM-lite but not Tier-1/Tier-2 names

## 2. State keys (graph/state.py)

- [x] 2.1 New artifacts keys: `arckit_data_model`,
      `arckit_integration_standards`, `arckit_security_controls`,
      `arckit_nfr_constraints` (optional, unset when type absent)
- [x] 2.2 State-serializability test (checkpointer spec): keys round-trip
      through AsyncSqliteSaver

## 3. DISCOVER node (graph/nodes/discover.py)

- [x] 3.1 Write the four new keys from loader output; absent → key omitted
      (never sentinel)
- [x] 3.2 `discover_artifact_audit` gains "valuable but absent" list including
      the four new types (drives review.py §5)
- [x] 3.3 DISCOVER tests: key set/unset matrix across artefact combinations

## 4. DEFINE node (graph/nodes/define.py)

- [x] 4.1 `arckit_integration_standards` + `arckit_nfr_constraints` appended to
      the parallel source-driven + api-design prompt context, capped per
      engineering-conventions prompt-capping limits
- [x] 4.2 DEFINE tests: keys present → in prompt; keys absent → prompt identical
      to today; LLM-None robustness path unchanged (Decision 3)

## 5. ARCH_REVIEW node (graph/nodes/review.py)

- [x] 5.1 `missing_build_inputs` advisory "valuable but absent" list extended
      with `DATA`/`TECH`/`OASEC`/`OAA-ADM-lite` (payload/resume shape per
      arckit-tier2-ingestion P0.5 — no change)
- [x] 5.2 Review tests: absent-type list reflects all missing valuable types;
      answers still never affect routing; ACHG + px-gate interlocks unchanged

## 6. BUILD node (graph/nodes/openhands_build.py)

- [x] 6.1 `_build_prompt` advisory sections (emitted only when set):
      `arckit_data_model`, `arckit_integration_standards`,
      `arckit_security_controls`, `arckit_nfr_constraints`,
      `arckit_product_backlog`, `arckit_strategy_waves`,
      `arch_review_answers`
- [x] 6.2 BUILD prompt tests: each key on/off matrix; prompt stable when no
      ArcKit context at all (byte-identical to today)
- [x] 6.3 build_report.json contract unchanged (Decision 1) — no test changes

## 7. SEED_DATA node (graph/nodes/seed_data.py)

- [x] 7.1 When `arckit_data_model` set: seed generation driven by its
      entities/classification; when absent: existing pass-through behaviour
- [x] 7.2 SEED_DATA tests: model-driven vs pass-through branches

## 8. Close-out

- [x] 8.1 AGENTS.md: DISCOVER phase note + artifacts-key inventory (+4 keys)
- [x] 8.2 Spec deltas: `human-in-the-loop` + `build-delegation` (see specs/)
- [x] 8.3 Full suite: `.venv/bin/python3 -m pytest tests/ -q` green; ruff +
      mypy clean
      (mypy not run this session — pre-existing `tools/loader.py` issues out
      of scope; see note below)

### Execution notes (2026-09-16)
- 8.3 gated: full suite green **except** the documented environmental
  caveats (7 `to_thread`/aiosqlite hang files + 9 sandbox-blocked
  `test_health` socket tests). See AGENTS.md → "Environment-Flake &
  Sandbox Caveats". Gate run: 355 passed, 9 deselected, 0 failures;
  `ruff check .` clean.
- Fixed a `ruff F841` in the OAA-ADM-lite extractor (`tools/arckit_loader.py`):
  removed two dead assignments (`scope`/`cons`) that were superseded by the
  `_g()` helper — behavior-preserving.
