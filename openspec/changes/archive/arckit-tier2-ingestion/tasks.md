# Tasks: arckit-tier2-ingestion

## P0 — OAPR ingestion (highest leverage: D1–D10 targeted HIL)

### 1. Fixtures

- [x] 1.1 Add test fixtures under `tests/fixtures/arckit/`:
      (a) OAPR from `~/projects/arc-kit/test-oaa-dummy/projects/001-test-oaa-dummy/`
      (with Document-Control-style header + fenced YAML blocks),
      (b) OAPR from
      `~/projects/arc-kit/test-oaa-australian-post-product/projects/001-parceltrack/`
      (with D2/D5/D8 `TBD` Unresolved Fields),
      (c) OASTR from the dummy tree,
      (d) BPCM from `~/projects/arc-kit/test-adm-australian-post/`
      (`ARC-001-BPCM-v1.0.md`),
      (e) minimal template-conformant `GAPA` + `TRANS` fixtures authored
      to their template section shapes.

### 2. OAPR extractor + DISCOVER plumbing (TDD)

- [x] 2.1 Add failing tests in `tests/test_arckit_loader.py`:
      (a) OAPR in `_TYPE_GLOBS` discovers via both primary and fallback
      globs; highest-version + conflict rules unchanged;
      (b) extractor parses the 2-column header table (Document ID /
      Status / Project), fenced-YAML mission + outcome blocks,
      §3 backlog rows, and the D1–D10 coverage table; `TBD` entries
      yield `(dimension, question_text)` pairs;
      (c) `project_description` precedence: ADMP vision → REQ business
      context → OAPR mission (each present-alone and combined);
      (d) `synthesize_interview_notes` emits "Open questions
      (OAPR D1–D10)" only when `TBD` rows exist, with exact question
      texts; full-coverage OAPR emits no section;
      (e) DISCOVER (graph/nodes/discover.py) writes
      `artifacts.arckit_product_backlog` when a valid OAPR is present
      and leaves the key unset otherwise;
      (f) `artifacts.arckit_open_questions` (list of
      `{dimension, question}`) is written when `TBD` rows exist and
      unset otherwise.
- [x] 2.2 Run `.venv/bin/python3 -m pytest tests/test_arckit_loader.py
      tests/test_discover_arckit.py -q` — confirm the new tests FAIL.
- [x] 2.3 Implement: OAPR entries in `DISCOVER_TYPES` / `_TYPE_GLOBS` /
      `_EXTRACTORS` (tools/arckit_loader.py); OAA header-table parse
      (shared with OAAL path); fenced-YAML extraction helper; seed merge
      in `load_arckit_artifacts`; description precedence;
      `synthesize_interview_notes` open-questions section; DISCOVER
      artifact keys (`arckit_product_backlog`, `arckit_open_questions`)
      + `graph/state.py` artifacts keys.
- [x] 2.4 Re-run the tests — all green.

### 3. P0 verify

- [x] 3.1 Full suite: `.venv/bin/python3 -m pytest tests/ -q`
      (existing 334 + new tests, 0 failures).
- [x] 3.2 Lint: `.venv/bin/python3 -m ruff check .`
- [ ] 3.3 Smoke (optional, live tree): run DISCOVER against
      `test-oaa-australian-post-product` as `context_folder` and
      confirm `discover_artifact_audit` shows OAPR valid and
      `arckit_product_backlog` + `arckit_open_questions` present in
      DISCOVER artifacts.

## P0.5 — ARCH_REVIEW missing-build-inputs channel (TDD)

User decision 2026-09-16: build-critical information still missing after
ingestion is asked at the existing ARCH_REVIEW HIL gate — no new pause.

### 4. ARCH_REVIEW payload + resume (TDD)

- [x] 4.1 Add failing tests (tests/test_review*.py or
      tests/test_discover_arckit.py):
      (a) `arckit_open_questions` non-empty → interrupt payload has
      `missing_build_inputs` listing the questions;
      (b) audit shows valuable-absent Tier-2 types → advisory
      "valuable but absent" list in the same field;
      (c) resume with `approved=true` + two `answers` →
      `artifacts.arch_review_answers` written; approval routing and
      px-gate/ACHG interlock behaviour unchanged;
      (d) nothing missing → payload has no `missing_build_inputs` field
      (byte-identical payload to today for a non-ArcKit run).
- [x] 4.2 Confirm tests FAIL; implement in `graph/nodes/review.py`:
      derive `missing_build_inputs` from
      `artifacts.arckit_open_questions` + `discover_artifact_audit`;
      accept optional `answers` mapping in the resume payload; write
      `artifacts.arch_review_answers` when non-empty.
- [x] 4.3 `_build_prompt` (graph/nodes/openhands_build.py): when
      `artifacts.arch_review_answers` is non-empty, append a
      "Review supplements" section (truncated per `PROMPT_CHAR_LIMIT`
      policy); empty/absent → prompt unchanged.
- [x] 4.4 Re-run tests — green; full suite + ruff.

## P1 — OASTR / BPCM / GAPA / TRANS ingestion

### 5. OASTR + strategy waves (TDD)

- [x] 5.1 Add failing tests: OASTR extractor (strategy-canvas dimension
      rows → `objectives`/`outcomes` seeds; wave table
      (Defend/Attack/Outcome per wave) → structured rows);
      DISCOVER writes `artifacts.arckit_strategy_waves` from OASTR.
- [x] 5.2 Confirm tests FAIL; implement OASTR extractor +
      `arckit_strategy_waves` key (state + discover + PLAN/BUILD
      context read, mirroring `oaal_sprint_map` consumption).
- [x] 5.3 Re-run — green.

### 6. TRANS wave fallback (TDD)

- [x] 6.1 Add failing tests: valid TRANS + no OASTR →
      `arckit_strategy_waves` holds TRANS transition-wave rows;
      OASTR present → OASTR wins; neither → key unset.
- [x] 6.2 Confirm FAIL; implement TRANS extractor + fallback merge
      (OASTR takes precedence; same-version conflicts already handled
      per type).
- [x] 6.3 Re-run — green.

### 7. BPCM + GAPA seeds (TDD)

- [x] 7.1 Add failing tests: BPCM extractor (L1–L3 hierarchy, maturity
      rows, value-stream rows → "Capabilities" section of the
      synthesised notes); GAPA extractor (gap/pain-point bullets →
      Constraints/Risks sections of the notes); both types discovered
      via globs and audited.
- [x] 7.2 Confirm FAIL; implement both extractors + seed/notes merge.
- [x] 7.3 Re-run — green.

## 8. Docs + close-out

- [x] 8.1 `AGENTS.md`: DISCOVER phase note — Tier-2 type list
      (OAPR/OASTR/BPCM/GAPA/TRANS) + new artifact keys
      (`arckit_product_backlog`, `arckit_open_questions`,
      `arckit_strategy_waves`, `arch_review_answers`); ARCH_REVIEW
      note gains the missing-build-inputs channel.
- [x] 8.2 `openspec/config.yaml`: supersede the
      `open_questions_resolved` entry "New ArcKit TYPE codes in v2 —
      No new types planned" with the Tier-2 outcome.
- [x] 8.3 Full suite + lint: `.venv/bin/python3 -m pytest tests/ -q`
      and `.venv/bin/python3 -m ruff check .` — 0 failures
      (mypy not run this session; suite green **except** the documented
      environmental caveats — see AGENTS.md → "Environment-Flake &
      Sandbox Caveats". Gate run: 355 passed, 9 deselected, 0 failures;
      `ruff check .` clean.)
- [x] 8.4 Archive: `openspec archive arckit-tier2-ingestion`
      (after P0+P0.5+P1 all green). Archived to `openspec/changes/archive/` on 2026-09-16.

## Execution notes (2026-09-16)
- 3.3 skipped (optional live smoke; no live ArcKit tree in CI).
- 5.2/6.2/7.2 PLAN/BUILD *consumption* of `arckit_strategy_waves` is deferred to
  `arckit-build-context` (W3); P1 scope here = ingestion + DISCOVER key + audit.
