# skill-registry (delta)

## ADDED Requirements

### Requirement: Skill lifecycle management
The system SHALL provide `tools/skill_manager.py` as the single module
for skill lifecycle operations: `list_skills`, `register_skill`,
`remove_skill`, `update_skill`, `sync_from_sources`. All filesystem
paths SHALL resolve through `config.workflow.skill_registry_path` so
the module behaves identically on host (`./skills`) and in-container
(`/app/skills`).

- `list_skills() -> list[dict]` returns one entry per skill directory
  with at least `name`, `version`, `path`, `description`, and an
  `active_in_graph` flag.
- `register_skill(name, content, source="manual")` writes
  `skills/<name>/SKILL.md` from raw SKILL.md text (frontmatter + body)
  and raises `SkillRegistrationError` when the frontmatter lacks a
  `name` field (the partial write is rolled back).
- `remove_skill(name) -> bool` deletes `skills/<name>/`; returns
  `False` when the directory does not exist.
- After register or remove, the registry index
  (`build_skill_registry` / `_save_skills_index`) SHALL be refreshed so
  the next lookup reflects the change.

#### Scenario: Register then list
- **WHEN** `register_skill("gamma", "<valid SKILL.md>")` succeeds
- **THEN** `skills/gamma/SKILL.md` exists and the next
  `build_skill_registry` call includes `gamma`

#### Scenario: Malformed skill is rolled back
- **WHEN** `register_skill("gamma", "# no frontmatter")` is called
- **THEN** `SkillRegistrationError` is raised and no `skills/gamma/`
  directory remains on disk

#### Scenario: Remove a missing skill is a no-op
- **WHEN** `remove_skill("nope")` is called
- **THEN** it returns `False` and raises nothing

### Requirement: Config-driven GitHub skill sources
Skill updates from upstream repos SHALL be driven by
`config/skill_sources.yaml` (a `sources:` list of `{name, repo, ref,
skills}`; `skills: null` means "every skill under the repo's
`skills/` subtree"). No repository URL SHALL be hardcoded in
`tools/skill_manager.py`; new sources are added by editing the YAML only.

- `update_skill(name, source=None, ref=None)` pulls the named skill
  from the matching configured source (first source listing `name`, or
  the named source) into a local clone cache, then overwrites
  `skills/<name>/SKILL.md` via the register path. It raises
  `SkillUpdateError` when no source provides the skill, the clone/pull
  fails, or the skill directory is absent in the repo.
- `sync_from_sources()` iterates every source and every listed skill,
  returning `[{name, source, ref, status}]` where `status` is
  `updated (v<ver>)` or `error: <msg>`; a failure on one skill SHALL
  NOT abort the remaining skills.
- Git is invoked via `subprocess` with a bounded timeout
  (`config.Skills.update_timeout_s`, default 120).

#### Scenario: Update pulls the newest upstream skill
- **WHEN** `update_skill("alpha", source="agent-skills")` succeeds
- **THEN** `skills/alpha/SKILL.md` content equals the file at
  `<cache>/skills/alpha/SKILL.md` in the configured repo at the
  configured ref, and the registry entry's version reflects the file's
  frontmatter

#### Scenario: Sync failure is isolated per skill
- **WHEN** source `agent-skills` lists skills `alpha` and `beta`, and
  only `beta` fails to clone
- **THEN** `sync_from_sources()` returns one `error:` entry for `beta`
  and one `updated` entry for `alpha`

### Requirement: Skill-management Web API
The Web backend SHALL expose the skill lifecycle through six endpoints
in `frontend/backend/app.py`:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/skills` | GET | list every skill (manager `list_skills` output) |
| `/api/skills/register` | POST | register from raw SKILL.md text |
| `/api/skills/remove` | POST | remove by name |
| `/api/skills/update` | POST | update one skill from a configured source |
| `/api/skills/sync` | POST | sync every skill from every source |
| `/api/skills/recommendations` | GET | read the persistent skill-review output |

Manager errors (`SkillRegistrationError`, `SkillUpdateError`) SHALL map
to HTTP 400 with the exception message in `detail`; success responses
return the manager's dict verbatim.

#### Scenario: Register via the API
- **WHEN** `POST /api/skills/register` with `{"name": "gamma", "content": "<valid>"}`
- **THEN** the response is 200 with the registry entry, and `skills/gamma/SKILL.md` exists

#### Scenario: Malformed registration is a 400
- **WHEN** `POST /api/skills/register` with content lacking frontmatter
- **THEN** the response is 400 and `detail` names the validation failure

#### Scenario: Recommendations endpoint is safe when the file is absent
- **WHEN** `GET /api/skills/recommendations` and
  `storage/skill_recommendations.json` does not exist
- **THEN** the response is `{"recommendations": []}` (not 404/500)
