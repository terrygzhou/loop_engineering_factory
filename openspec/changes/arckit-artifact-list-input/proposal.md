# Change: Explicit ArcKit artefact list input for DISCOVER

## Why

DISCOVER's ArcKit ingestion (EYW-171) currently accepts only one input
channel: a single `context_folder` scan root. `tools/arckit_loader.py`
discovers artefacts by glob (`projects/*/ARC-*-{TYPE}-v*.md` or
`ARC-*-{TYPE}-v*.md` under the root). This fails when the operator has a
known *list* of `ARC-*.md` files outside that layout (e.g. files pulled
from a review, a partial ArcKit export, or files scattered across several
ArcKit project dirs such as
`/home/terry/projects/arc-kit/projects/MPC-insurance/`), and it gives no
way to constrain ingestion to an exact set of artefacts.

## What changes

- `tools/arckit_loader.py:load_arckit_artifacts(root, project_id="", files=None)`
  gains an optional `files` parameter (iterable of path strings). When
  provided, glob discovery is skipped; each file is parsed directly, with
  type/pid/version derived from its filename (`ARTIFACT_FILENAME_RE`).
  Per-type highest-version selection and conflict detection still apply.
- `graph/state.py:WorkflowState` gains an optional `arckit_artifacts:
  list[str]` key (explicit artefact paths; empty/absent = current glob
  behaviour).
- `graph/nodes/discover.py` passes `files=state.get("arckit_artifacts")`
  to the loader.
- The DISCOVER `project_setup` HIL interrupt gains an optional
  `arckit_artifacts` field (newline-separated paths); DISCOVER parses it
  into a list and writes it to `state["arckit_artifacts"]`.

## Non-goals

- No new ArcKit TYPE codes (parser already tolerates unknowns — open
  question resolved 2026-07-07).
- No manifest/index file in ArcKit project dirs (deferred; see Option 5
  from the option review).
- No change to the auto-approve scan-skip behaviour, to routing, or to
  any other phase.

## Impact

- Affected specs: `human-in-the-loop` (ArcKit auto-ingestion).
- Affected code: `tools/arckit_loader.py`, `graph/state.py`,
  `graph/nodes/discover.py`, tests (`test_arckit_loader.py`,
  `test_discover_arckit.py`).
- Backward compatible: `files=None` (absent state key) preserves today's
  glob-only behaviour exactly.
