# Change: Skill management API + REFLECT skill-performance review

## Why

The 34 skills in `skills/` are currently managed by hand: adding a skill
means copying a directory into `skills/` (and remembering that
`build_skill_registry` picks it up by mtime), removing one means deleting
the directory and hoping nothing still references it, and "update from the
upstream agent-skills repo" has no tooling at all. Meanwhile REFLECT
reviews cycle metrics and proposes config diffs, but it never looks at the
skills themselves — the one subsystem that decides the quality of every
prompt in the loop is the only one with no performance signal and no
improvement loop of its own.

## What Changes

- **Skill lifecycle module (new):** `tools/skill_manager.py` —
  `list_skills`, `register_skill`, `remove_skill`, `update_skill`,
  `sync_from_sources`. All paths resolve through
  `config.workflow.skill_registry_path` so the module works identically
  host (`./skills`) and in-container (`/app/skills`).
- **Config-driven GitHub sources (new):** `config/skill_sources.yaml`
  declares the upstream repos/refs the manager may pull skills from
  (`{name, repo, ref, skills: [...]}`); no repo URL is hardcoded in the
  manager code. New `config.Config.Skills` (sources path + update
  timeout) in `config/loader.py`.
- **Web API (new):** six endpoints in `frontend/backend/app.py` —
  `GET /api/skills`, `POST /api/skills/register`, `POST
  /api/skills/remove`, `POST /api/skills/update`, `POST
  /api/skills/sync`, `GET /api/skills/recommendations`.
- **REFLECT skill review (new):** a step in `graph/nodes/reflect.py`
  (after config-diff generation, before the HIL approval gate) that feeds
  an LLM the cycle's per-skill usage counts, loop counters,
  `test_errors`, `acceptance_results`, and the cycle's own proposed
  config diffs; the LLM returns per-skill verdicts
  (keep/improve/retire) + 1–3 next-iteration recommendations. Result is
  stored in `artifacts.skill_review` (JSON string, matching the
  `proposed_diffs` convention) and persisted to
  `storage/skill_recommendations.json`.
- **Advisory injection into the next cycle:** DISCOVER
  (`_generate_requirement_via_fabric`) and DEFINE
  (`_arckit_advisory_context`, which already feeds both parallel
  DEFINE prompts) append the prior cycle's recommendations as an
  advisory prompt block. Byte-identical prompt when the file is absent or
  empty.
- **Docs:** `skills/PHASE_SKILL_MAP.md` gains a Skill Management
  section; AGENTS.md Skills/REFLECT lines updated (also fixes the stale
  "35 SKILL.md" count).

**Non-breaking:** no route changes, no new HIL gate, no change to the
existing REFLECT approval flow. `artifacts.skill_review` is a new
`artifacts.*` key (governance note: top-level artifacts keys read back
from a different node — this one is written by REFLECT and read by
DISCOVER/DEFINE, which is exactly the ArcKit pattern already established
for `arckit_*` keys; no new key is read by a node that did not already
read advisory context).

## Capabilities

### New Capabilities

(none — all behavior lands in existing capabilities)

### Modified Capabilities

- `skill-registry`: new requirements — skill lifecycle management
  (register/remove/update/sync via `tools/skill_manager.py`), config-driven
  GitHub sources, skill-management Web API.
- `workflow-orchestration`: new requirement — REFLECT skill-performance
  review (verdicts + recommendations, `artifacts.skill_review` +
  persistent file) and advisory injection into DISCOVER/DEFINE.
- `web-frontend`: new requirement — the six `/api/skills*` endpoints and
  their request/response contracts.

## Impact

- **New files:** `tools/skill_manager.py`, `tools/skill_recommendations.py`,
  `feedback/skill_review.py`, `config/skill_sources.yaml`,
  `tests/test_skill_manager.py`, `tests/test_skill_review.py`,
  `tests/test_skills_api.py`, `tests/test_reflect_skill_review.py`,
  `tests/test_skill_recommendation_injection.py`.
- **Modified:** `config/loader.py` (add `Config.Skills`),
  `graph/nodes/reflect.py` (new review step), `graph/nodes/discover.py`
  + `graph/nodes/define.py` (advisory block), `frontend/backend/app.py`
  (endpoints), `skills/PHASE_SKILL_MAP.md`, `AGENTS.md`.
- **Dependencies:** none new — `git` via `subprocess` (already in the
  container; the `git-workflow` skill assumes it).
- **Gate:** full suite green with the documented sandbox caveats
  (7 `to_thread`-hang files `--ignore`d, 9 `test_health` socket tests
  `--deselect`ed) + `ruff check .` clean.
