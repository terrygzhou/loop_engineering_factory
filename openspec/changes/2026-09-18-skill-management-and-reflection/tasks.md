# Tasks — skill-management-and-reflection

Order: S1 (skill manager core) → S2 (GitHub sources + config) → S3
(skill review in REFLECT) → S4 (advisory injection) → S5 (Web API) → S6
(docs + AGENTS.md count fix). Each task is independently testable and
ends with a commit.

Gate for the whole change: AGENTS.md close-out command — `pytest
tests/ -q` with the 7 hang files `--ignore`d
(`test_bridge_custom_events`, `test_checkpointer`,
`test_discover_arckit`, `test_runner`, `test_runner_hil_loop`,
`test_ui_bridge`, `test_w3_behavioral`) and the 9 `test_health` socket
tests `--deselect`ed → 0 failures; `ruff check .` clean.

## 1. S1 — skill manager core (`tools/skill_manager.py`)

- [ ] 1.1 Write `tests/test_skill_manager.py` (fixture registry: a
      tmp `skills/` dir + `monkeypatch.setattr` on
      `config.Config.Workflow.skill_registry_path` per test):
      - `list_skills()` returns one entry per skill dir with
        `{name, version, path, description, active_in_graph}`; the
        `active_in_graph` set matches the 21 names in
        `graph/main.py` wiring (interview-me … git-workflow)
      - `register_skill("gamma", <valid SKILL.md text>)` creates
        `skills/gamma/SKILL.md`, and the next
        `build_skill_registry` call includes `gamma`
      - `register_skill("gamma", "# no frontmatter")` raises
        `SkillRegistrationError` and leaves no `skills/gamma/`
        directory behind
      - `register_skill("gamma", "")` raises
        `SkillRegistrationError` (missing/blank frontmatter)
      - `remove_skill("gamma") -> True` deletes the dir;
        `remove_skill("nope") -> False`, no exception
      - register/remove refresh the registry index
        (`_save_skills_index` effect: a fresh
        `build_skill_registry` call reflects the change)
- [ ] 1.2 Implement `tools/skill_manager.py`:
      - resolve every path through
        `config.workflow.skill_registry_path` (host `./skills`,
        in-container `/app/skills`)
      - `list_skills() -> list[dict]` — one entry per skill
        directory under the registry path; `active_in_graph` from a
        module-level 21-name set (kept in sync with
        `graph/main.py`)
      - `register_skill(name, content, *, source="manual")` —
        validate frontmatter has a `name` field before writing;
        on validation failure, roll back any partial write and raise
        `SkillRegistrationError`
      - `remove_skill(name) -> bool` — delete the skill dir;
        `False` when absent
      - after register/remove, refresh the mtime cache so the next
        `build_skill_registry` sees the change (bump the
        `_save_skills_index` mtime or clear the loader's mtime
        cache)
      - define `SkillRegistrationError` and `SkillUpdateError`
- [ ] 1.3 Run `pytest tests/test_skill_manager.py -q`; `ruff check
      .`; commit.

## 2. S2 — config-driven GitHub sources (`config/skill_sources.yaml`)

- [ ] 2.1 Write `tests/test_skill_sources.py`:
      - `update_skill("alpha", source="agent-skills")` pulls the
        skill into the local clone cache, overwrites
        `skills/alpha/SKILL.md` via the register path, and the
        registry entry version reflects the file's frontmatter
      - `update_skill("ghost")` raises `SkillUpdateError` naming
        the failure when no source provides the skill
      - `sync_from_sources()` returns a `[{name, source, ref,
        status}]` list; a failure on one skill does not abort the
        others (one `error:` entry, one `updated` entry)
      - `_git_clone_or_pull(repo, ref, dest)` uses
        `subprocess.run` with `timeout=config.Skills.update_timeout_s`
        (default 120); a clone failure raises `SkillUpdateError`
- [ ] 2.2 Add to `config/loader.py`:
      - `Config.Skills` block: `skill_sources_path` (env
        `SKILL_SOURCES_PATH`, default `./config/skill_sources.yaml`)
        and `update_timeout_s` (env `SKILL_UPDATE_TIMEOUT_S`,
        default 120)
      - create `config/skill_sources.yaml` with the initial
        `agent-skills` source:
        ```yaml
        sources:
          - name: agent-skills
            repo: <upstream-url>   # placeholder; fill at implementation
            ref: main
            skills: null           # null = every skill under the repo's skills/ subtree
        ```
      - In `tools/skill_manager.py`: implement
        `update_skill(name, source=None, ref=None)` and
        `sync_from_sources()` per the scenarios in 2.1; git via
        `subprocess` (no new dependency — `git` is already in the
        container); clone cache at sibling
        `.skill_cache/<source>/` (never inside `skills/`)
- [ ] 2.3 Run `pytest tests/test_skill_sources.py -q`; `ruff check
      .`; commit.

## 3. S3 — skill review in REFLECT (`feedback/skill_review.py`)

- [ ] 3.1 Write `tests/test_skill_review.py`:
      - `build_skill_review_context(state)` collects per-skill
        usage counts, loop counters, `test_errors`,
        `verify_status`, `acceptance_results`, and
        `proposed_diffs` into a dict
      - `render_skill_review_prompt(ctx)` produces the LLM prompt
      - `store_skill_review(review, storage_dir)` writes
        `storage/skill_recommendations.json` with shape
        `{cycle_id, ts, verdicts: [...], recommendations: [...]}`
      - `load_skill_recommendations(storage_dir)` returns the
        top-level dict (not just the list); absent file → `[]`
      - `run_skill_review(state, llm, storage_dir)` with
        `llm=None` returns `{"status": "unavailable",
        "reason": "llm unavailable"}` and does not raise
      - `run_skill_review(state, llm, storage_dir)` with a working
        LLM returns `{"status": "ok", "verdicts": [...],
        "recommendations": [...]}`
- [ ] 3.2 Implement `feedback/skill_review.py` (pure helpers, no
      graph dependency): the five functions above; `run_skill_review`
      calls `invoke_skill` and catches `LLMError` → returns the
      unavailable dict (Decision 3: never raises)
- [ ] 3.3 In `graph/nodes/reflect.py`: insert the skill-review step
      **after** config-diff generation and **before** the HIL
      approval gate. Call `run_skill_review`; on `status: "ok"`,
      write `artifacts.skill_review` (JSON string, matching the
      `proposed_diffs` convention) and a `feedback` entry
      `{"action": "skill_reviewed", "status": "ok",
      "verdict_count": N}`; on `unavailable`, write the unavailable
      dict and a `skill_reviewed` feedback entry with
      `status: "unavailable"`. The node SHALL NOT raise or change
      `next_phase`.
- [ ] 3.4 Update `graph/state.py` `WorkflowState` docstring to
      document the new `artifacts.skill_review` key.
- [ ] 3.5 Run `pytest tests/test_skill_review.py -q`; `ruff check
      .`; commit.

## 4. S4 — advisory recommendation injection

- [ ] 4.1 Write `tests/test_skill_recommendations.py`:
      - `skill_recommendations_block(max_chars=1500)` returns `""`
        when `storage/skill_recommendations.json` does not exist
        (byte-identity)
      - non-empty recommendations → a `SKILL RECOMMENDATIONS`
        section listing each `{skill, priority, suggestion}`,
        truncated to `max_chars`
      - the block is advisory: it does not appear in any
        `route_phase` input
- [ ] 4.2 Implement `tools/skill_recommendations.py`:
      `skill_recommendations_block(max_chars=1500)` — reads
      `storage/skill_recommendations.json`; absent file or empty
      `recommendations` → `""`; otherwise a fenced `SKILL
      RECOMMENDATIONS` section (each line:
      `- [<priority>] <skill>: <suggestion>`), truncated to
      `max_chars`
- [ ] 4.3 In `graph/nodes/discover.py`: import
      `skill_recommendations_block`; append its return to
      `fabric_prompt` inside `_generate_requirement_via_fabric`
      (after the existing `fabric_prompt` build, before
      `invoke_skill`).
- [ ] 4.4 In `graph/nodes/define.py`: modify
      `_arckit_advisory_context` to append the recommendation block
      to `blocks` before the final `return` (one edit covers both
      parallel source-driven + api-design prompts called at lines 306
      and 330).
- [ ] 4.5 Run `pytest tests/test_skill_recommendations.py -q`;
      `ruff check .`; commit.

## 5. S5 — Web API endpoints (`frontend/backend/app.py`)

- [ ] 5.1 Write `tests/test_skill_api.py` (FastAPI TestClient):
      - `GET /api/skills` → 200, `{"skills": [34 entries]}`
      - `POST /api/skills/register` `{"name": "gamma", "content":
        "<valid>"}` → 200 with the registry entry
      - `POST /api/skills/register` with malformed content → 400,
        `detail` names the failure
      - `POST /api/skills/remove` `{"name": "gamma"}` → 200
        `{"removed": true}`; missing skill → `{"removed": false}`
      - `POST /api/skills/update` `{"name": "alpha",
        "source": "agent-skills"}` → 200 with the updated entry;
        unknown skill → 400
      - `POST /api/skills/sync` → 200 `{"results": [...]}`
      - `GET /api/skills/recommendations` with absent file → 200
        `{"recommendations": []}`
- [ ] 5.2 In `frontend/backend/app.py`: add six endpoints (insert
      after `POST /api/input` ~line 258):
      - `GET /api/skills` → `{"skills": <list_skills() output>}`
      - `POST /api/skills/register` with Pydantic
        `SkillRegisterRequest{name: str, content: str,
        source: str = "manual"}` → `register_skill(...)` entry;
        `SkillRegistrationError` → 400 `{"detail": str(e)}`
      - `POST /api/skills/remove` with `SkillRemoveRequest{name:
        str}` → `{"removed": <bool>}`
      - `POST /api/skills/update` with
        `SkillUpdateRequest{name: str, source: str | None = None,
        ref: str | None = None}` → updated entry;
        `SkillUpdateError` → 400
      - `POST /api/skills/sync` → `{"results":
        <sync_from_sources()>}`
      - `GET /api/skills/recommendations` → `{"recommendations":
        <load_skill_recommendations().get("recommendations", [])>}`
      - import the manager inside each handler (lazy import so app
        startup is independent of skill-filesystem state)
- [ ] 5.3 Run `pytest tests/test_skill_api.py -q`; `ruff check
      .`; commit.

## 6. S6 — docs + AGENTS.md count fix

- [x] 6.1 Update `AGENTS.md`: change "35 SKILL.md files" to
      "34 SKILL.md files" (the actual count on disk).
- [x] 6.2 Update the `Skill Loading` section in `AGENTS.md` to
      mention `tools/skill_manager.py` and
      `config/skill_sources.yaml` (one line each).
- [ ] 6.3 Run the full close-out gate: `pytest tests/ -q` (with the
      7 `--ignore` + 9 `--deselect` from AGENTS.md) → 0 failures;
      `ruff check .` clean. Commit.
