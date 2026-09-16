# Tasks: arckit-artifact-list-input

## 1. Loader `files=` parameter (TDD)

- [x] 1.1 Add failing tests in `tests/test_arckit_loader.py`:
      (a) `files=[admp, oaal]` from a temp dir parses both, skips glob
      (put a decoy ADMP v9.9 in the root that must NOT be picked);
      (b) a non-conforming filename in `files` → `MALFORMED_FILENAME` in
      `ctx.errors`, other files still parsed;
      (c) `files=[]` or `files=None` → identical to legacy glob behaviour.
- [x] 1.2 Run `.venv/bin/python3 -m pytest tests/test_arckit_loader.py -q`
      — confirm the new tests FAIL.
- [x] 1.3 Implement `files` parameter in `load_arckit_artifacts`
      (tools/arckit_loader.py): when non-empty, build `chosen` directly
      from the given paths (type/pid/version from filename, per-type
      `_pick_highest`, same-version conflict detection, existing §5
      validation + §6.4 audit); skip the root-existence check when
      `files` is supplied; `files` of non-`DISCOVER_TYPES` types are
      recorded as skipped in the audit.
- [x] 1.4 Re-run the loader tests — all green.

## 2. DISCOVER plumbing (TDD)

- [x] 2.1 Add failing tests in `tests/test_discover_arckit.py`:
      (a) DISCOVER with `state["arckit_artifacts"]` calls
      `load_arckit_artifacts` with `files=` equal to that list
      (monkeypatch the lazy import);
      (b) setup-interrupt resume payload with newline-separated
      `arckit_artifacts` → returned state `arckit_artifacts` is a list
      (and empty value → key absent).
- [x] 2.2 Run the DISCOVER tests — confirm they FAIL.
- [x] 2.3 Add optional `arckit_artifacts` to `WorkflowState`
      (graph/state.py, BUILD-handoff/ArcKit section) and wire
      `graph/nodes/discover.py`: parse the resumed HIL field
      (splitlines, strip, drop empty) into the returned state, and pass
      `files=state.get("arckit_artifacts")` at the loader call site.
- [x] 2.4 Add the optional `arckit_artifacts` field to the
      `project_setup` interrupt payload (non-required,
      "ArcKit artefact paths (one per line, optional)").
- [x] 2.5 Re-run the DISCOVER tests — all green.

## 3. Verify

- [x] 3.1 Full suite: `.venv/bin/python3 -m pytest tests/ -q`
      (312 existing + new tests, 0 failures).
- [x] 3.2 Lint: `.venv/bin/python3 -m ruff check .`
