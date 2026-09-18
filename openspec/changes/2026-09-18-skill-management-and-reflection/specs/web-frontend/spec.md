# web-frontend (delta)

## ADDED Requirements

### Requirement: Skill management API surface
`frontend/backend/app.py` SHALL expose a skill-management surface under
`/api/skills*`, backed by `tools/skill_manager.py`. Endpoints and
contracts:

- `GET /api/skills` → `200 {"skills": [...]}` where each item is the
  manager's `list_skills` entry `{name, version, path, description,
  triggers, category, active_in_graph}`.
- `POST /api/skills/register` body `{name: str, content: str,
  source?: str}` → `200` with the registry entry; `400` with
  `{"detail": <error>}` on `SkillRegistrationError`.
- `POST /api/skills/remove` body `{name: str}` → `200 {"removed":
  bool}`.
- `POST /api/skills/update` body `{name: str, source?: str, ref?:
  str}` → `200` with the updated registry entry; `400` with
  `{"detail": <error>}` on `SkillUpdateError`.
- `POST /api/skills/sync` (no body) → `200 {"results": [{name,
  source, ref, status}]}` where `status` is `updated (v<ver>)` or
  `error: <msg>`.
- `GET /api/skills/recommendations` → `200 {"recommendations":
  [...]}`; an absent or empty
  `storage/skill_recommendations.json` yields `{"recommendations":
  []}`.

Request models SHALL be Pydantic (matching the existing
`StartRequest`/`UserInput` idiom in the same file). Endpoints SHALL
import the manager lazily (inside the handler) so the app import path
stays independent of skill-filesystem state.

#### Scenario: List reflects the on-disk registry
- **WHEN** `skills/` contains 34 skill directories
- **THEN** `GET /api/skills` returns 34 items, each with `name`,
  `version`, and `active_in_graph`

#### Scenario: Update with no configured source is a 400
- **WHEN** `config/skill_sources.yaml` lists no source providing
  skill `alpha`
- **THEN** `POST /api/skills/update` with `{"name": "alpha"}` returns
  400 and `detail` names the failure (e.g. "No source provides skill
  'alpha'")
