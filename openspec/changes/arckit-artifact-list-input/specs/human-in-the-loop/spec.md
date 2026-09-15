# human-in-the-loop (delta)

## ADDED Requirements

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
