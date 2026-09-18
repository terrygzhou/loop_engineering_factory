# Findings: LangGraph State & Skills Code Review
Project: loop_engineering_factory · Date: 2026-09-16 (D section: 2026-09-17; E section: 2026-09-18)
Baseline: `ruff check .` clean; `pytest tests/test_edges.py tests/test_workflow_lifecycle.py -q` → 55 passed.
Scope: `graph/state.py`, `graph/edges.py`, `graph/nodes/*` (active path), `tools/loader.py`, `tools/llm.py`, `tools/distiller.py`, `skills/`.
Section D: `graph/nodes/build_subgraph_legacy.py` + `graph/nodes/openhands_build.py` (BUILD fallback subgraph, 2026-09-17 follow-up).
Section E: whole-codebase pass (2026-09-18) — `graph/runner.py`, `graph/executor.py`, `graph/checkpointer.py`, `graph/achg_scanner.py`, `feedback/*`, `service/*`, `config/*`, `frontend/backend/*`, `tools/*` (remainder).

---

## A. State findings

### A1. ~Half the schema is dead
`WorkflowState` declares **41 top-level keys**, but an AST audit of every active node
(discover/define/plan/review/openhands_build/seed_data/verify/ship/reflect) + runner
shows only **15 keys are ever returned** by a node:

```
artifacts, context_folder, diagram_feedback, diagram_status, discover_setup_done,
error, feedback, metrics, next_phase, phase, project_description, project_folder,
project_name, project_path, user_review_comments
```

**Dead candidates** (never written; values actually live under `artifacts.*` or are
legacy S-001 survivors): `tasks`, `tasks_text`, `backlog`, `solution_md`, `plan`,
`status`, `retry_count`, `spec_text`, `spec_refined`, `project_context`,
`interview_notes`, `diagrams`, `diagram_pngs`, `feedback_context`,
`human_approval_required`.
Proof: `define.py:155` reads `state.get("artifacts", {}).get("project_context")` —
the top-level `project_context` key is vestigial. Same for `spec_refined`
(`define.py:329`, `build_helpers.py:1289` read `artifacts.spec_refined`).

**Input-only keys** (legit — seeded by runner/bridge, read by nodes, never returned):
`skip_discover`, `improve_mode`, `force_hil`, `auto_approve_override`,
`arckit_artifacts`, `trace_id`, `cycle_id`, `config_version`.

The S-001/S-003 comments in `state.py` show the dedup was started and abandoned.

### A2. `artifacts` is an untyped dumping ground
`artifacts: Annotated[Dict[str, Any], _dict_merge]` now carries ≥20 heterogeneous
keys with no write-time validation:

- **Counters/gates:** `loop_counts`, `verify_status`, `test_results`,
  `acceptance_results`, `review_findings_summary`, `review_approved`
- **Context blobs:** `project_context` (full codebase-scan JSON dump),
  `interview_notes`, `spec_refined`, `improve_telemetry`, `discover_hil_count`
- **Diagrams:** `diagrams` (mermaid source), `diagram_pngs`
- **HIL:** `arch_review_answers`
- **ArcKit:** 7 keys (`arckit_product_backlog`, `arckit_open_questions`,
  `arckit_strategy_waves`, `arckit_data_model`, `arckit_integration_standards`,
  `arckit_security_controls`, `arckit_nfr_constraints`) + `discover_artifact_audit`

The contract is documented only in a comment block in `state.py`. A typo in a key
name silently creates a new key.

### A3. Checkpoint bloat (AsyncSqliteSaver)
Every step re-serializes **all** channels. Heavy blobs riding along on every
checkpoint write: `project_context`, `spec_refined`, `diagrams` (mermaid text),
`interview_notes`, `acceptance_results`/`test_results` (JSON strings). The
append-only `feedback` (`Annotated[List[dict], operator.add]`) is never pruned.
With VERIFY↔BUILD retries (max 2 loops), the full snapshot is rewritten 3× per gate.
Any `metrics` write (done via whole-object `model_copy()` in `define.py:493`,
`plan.py:261`, `openhands_build.py:540,558`) forces a re-serialization of the
blobs too.

### A4. `_maybe_increment_loop` (graph/edges.py) is in-place mutation with a
contradictory docstring
```python
state.setdefault("artifacts", {})["loop_counts"] = new_counts   # in-place
```
Docstring says "MUST be called from NODES" and "MUST REPLACE state['artifacts']
with new dict" — it does neither. Counter logic sitting in the edges module is
misplaced for LangGraph reducer semantics (nodes persist, edges read).

### A5. `route_phase` re-parses `artifacts.test_results` JSON inline
The VERIFY branch in `graph/edges.py` does `json.loads(state...["test_results"])`
with try/except — the gate signal is parsed in the router; the parse belongs in one
helper (next to `tools/acceptance.py`) computed once.

---

## B. Skills findings

### B1. Registry rebuilt on every node call; not thread-safe
`build_skill_registry()` is called at ~10 call sites (every node, per
execution) and re-stats all 37 `SKILL.md` files (`rglob`+`stat`, mtime check) each
time. The module globals `_registry`/`_registry_mtime` have **no lock** — and
`invoke_skill_async` dispatches LLM calls via `asyncio.to_thread`, so concurrent
rebuilds can interleave with `_save_skills_index` writing `SKILLS_INDEX.json`.

### B2. Distillation is per-invocation and heuristic-fragile
`invoke_skill`/`invoke_skill_async` call `distill_skill(content, 2000)` on **every**
LLM call (duplicate work — it belongs at load time). The distiller regex-matches a
fixed list of `## purpose / ## process / ...` headings; skills without one fall back
to `body[:2000]` — i.e. the **first 2 KB**, which for big skills is usually the
intro, not the procedure:

| Skill | Size |
|---|---|
| `docker-compose-deployment` | 45 KB |
| `systematic-debugging` | 24 KB |
| `test-driven-development` | 22 KB |
| `code-review-and-quality` | 20 KB |

Total skill corpus: 37 dirs, 564 KB.

### B3. Duplicates / overlap
- `git-workflow` vs `git-workflow-and-versioning` (both present)
- `code-review-and-quality` vs `pre-commit-review`
- `code-simplification` vs `incremental-implementation`
AGENTS.md claims 35 skills; actual is 37 dirs.

### B4. `PHASE_SKILL_MAP.md` is stale
Hand-maintained; marks skills 📦 "ready to wire" that active nodes already use
(`idea-refine` in DISCOVER at `discover.py:1082`, `source-driven-development` in
DEFINE's parallel gather, security/debug skills in VERIFY).

### B5. No per-phase skill budgets
All invocations share the `max_prompt_chars=2000` default. BUILD carries the
heaviest prompts (ArcKit advisory sections + review supplements + failing
acceptance tests) and would benefit from a larger budget; budgets should live in
`config/bounds.yaml`, not a function default.

---

## D. BUILD subgraph findings (2026-09-17 follow-up review)

Scope: `graph/nodes/build_subgraph_legacy.py` + its OpenHands wrapper
(`openhands_build.py`). The subgraph is the fallback path when the agent
gateway is unreachable. Five findings, all missed by sections A–B.

### D1. Security/code review results are computed but never written back
`security_gate_node` runs `security_review_node` + `code_review_node`, which
write `state["security_review"]` / `state["code_review"]`. But
`build_output_mapping` (line 1321) never reads either key — it only maps
`uat_pass_rate`, `uat_result`, `build_status`, `artifacts`, `metrics`. Two
LLM calls per fallback run produce output that is discarded. Wire them into
`artifacts` (`build.security_review`, `build.code_review`) or delete the node.

### D2. UAT "skip" silently reports `uat_pass_rate = 1.0`
`deploy_gate_node` sets `uat_pass_rate = 1.0` when the container is down or
the health check fails (lines 947, 969). A "skip" (broken deployment) is
indistinguishable from a perfect pass in the metrics. `build_output_mapping`
only special-cases `uat_result == "fail"`; "skip" falls into the success
branch and writes `uat_pass_rate=1.0` into `CycleMetrics`. The VERIFY gate
catches real breakage downstream, but the BUILD subgraph's UAT signal is a
false positive. Distinguish "skip" from "pass" in `build_output_mapping`.

### D3. `retry_count` not reset on `implement_node` no-code path
`implement_node` line 299 increments `retry_count` when no code is
generated, but (unlike `unit_test_node` line 529) never resets it when
advancing `backlog_idx`. `retry_count` is shared across the subgraph
lifetime (not per-item), so a no-code failure on item N carries into item
N+1's retry budget. A flaky LLM on one item can silently exhaust the budget
for subsequent items.

### D4. `int_test_result` is a dead field
`int_test_node` sets `int_test_result = "pass" | "fail"` but neither
`route_build` nor `build_output_mapping` ever reads it. The `INT_TEST → SEED`
edge is unconditional; a failing "integration test" is recorded but ignored
by routing. Also, despite its name, the node only does
`docker compose up -d` + curl health + sleep 5 — no API calls, no
multi-service checks. Either route a failing INT_TEST to a distinct
handling (append to `errors`, set `build_status="fail"` in
`build_output_mapping`) or delete the field.

### D5. `"partial"` build status is typed but never produced
`BuildSubState.build_status` is documented as `"pass" / "fail" /
"partial"` (line 72), but `build_output_mapping` only ever writes
`"pass"` or `"fail"`. A backlog with 3/5 items completed + UAT pass is
reported as full success. Compute the partial case (some items completed,
some failed, UAT passed) and write `incomplete_items` into artifacts.

### D6 (minor, not in the top-5)
- `unit_test_node` lines 312–319: redundant `NO_MORE_ITEMS` early-return
  guard (the real check is `idx >= len(backlog)`).
- `security_gate_node` docstring says "before DEPLOY_GATE" but the graph
  wires it after UAT (`UAT → SECURITY_GATE → END`).
- `MAX_ITEM_RETRIES = None` (line 80) is a dead constant; all nodes read
  `bounds.build.max_item_retries` directly.
- `implement_node` / `unit_test_node` self-recursion to skip
  completed/failed items — latent stack risk for large backlogs.

---

## C. Optimization plan (4 independently shippable phases)

### Phase 0 — Schema audit + counter fix (low risk, ~0.5 day)
1. `tests/test_state_contract.py`: assert every `WorkflowState` key is (a) returned
   by an active node, (b) input-only (explicit `INPUT_ONLY_KEYS` allowlist), else
   fail. Kill drift structurally.
2. Delete the dead top-level keys (A1 list) from `WorkflowState` + runner/bridge
   initial-state seeding; keep the 8 input-only keys.
3. Replace `_maybe_increment_loop` with a pure helper
   `graph/loop_counters.py:increment_loop(artifacts, phase) -> (dict, bool)`
   returning a **new** artifacts dict; update node call sites; extend
   `test_w2_wayforward.py` (increment / halt-at-2 / reset).
4. Extract the `test_results` JSON parse into
   `tools/acceptance.py:count_pytest_fail(artifacts) -> int`; `route_phase` calls it.

### Phase 1 — Typed artifacts + blob offload (~1–2 days)
1. `graph/artifacts.py`: `Artifacts` pydantic model with nested sections —
   `arckit`, `build` (report + loop counters + `security_review` /
   `code_review` / `uat_result` / `uat_pass_rate` / `incomplete_items` —
   see D1/D2/D5), `verify` (verify_status,
   test_results, acceptance_results, review_findings_summary), `context`
   (project_context, interview_notes, spec_refined, review_approved,
   arch_review_answers, improve_telemetry, discover_hil_count), `diagrams`.
   Thin reducer wrapper validates returned deltas (unknown key → warning/drop).
5. Fix the BUILD-subgraph findings (D1–D5):
   - **D1**: wire `security_review` / `code_review` into `artifacts.build.*` in
     `build_output_mapping` (or delete `security_gate_node` if not wanted).
   - **D2**: in `build_output_mapping`, distinguish `uat_result in ("skip",)` from
     `"pass"`: write `artifacts.build.uat_result = "skip"` + a warning into
     `errors`; do NOT write `uat_pass_rate = 1.0` for skips.
   - **D3**: `implement_node` — reset `retry_count = 0` when advancing
     `backlog_idx` (matches `unit_test_node` line 529 behaviour).
   - **D4**: route a failing INT_TEST to a distinct handling in
     `build_output_mapping` (append to `errors`, `build_status="fail"`), or
     delete the `int_test_result` field + `int_test_node` if it stays a
     health-check-only.
   - **D5**: compute `"partial"` in `build_output_mapping` when
     `all_completed=False` AND `uat_result == "pass"`; write
     `artifacts.build.incomplete_items` (count + ids).
2. Off-load blobs to disk; state keeps **paths + sizes** only:
   - `project_context` → `project_folder/build/context_scan.json`
   - mermaid source → already on disk; drop source text from state (keep png paths)
   - `spec_refined` / `interview_notes` → already written to `specs/` by DEFINE;
     state keeps path + char count.
   Add `tests/test_checkpoint_size.py` with a byte budget on the final checkpoint.
3. Prune transient verify/build keys at SHIP→REFLECT; cap `feedback` in its reducer
   (keep N most recent).
4. Give `metrics` a merge reducer (`Annotated[CycleMetrics, _metrics_merge]`) so
   nodes return only changed fields instead of whole-object `model_copy()`.

### Phase 2 — Skills: pre-distill, budgets, dedupe, audit (~1–2 days, independent)
1. Registry stores `content` **and** `distilled` (per-phase `max_chars` from
   `config/bounds.yaml: skills.max_chars`, default 2000, BUILD 4000).
   `invoke_skill` stops re-distilling. Add a `threading.Lock` around registry
   rebuild + `SKILLS_INDEX.json` write.
2. CI lint `scripts/lint_skills.py`: every `SKILL.md` must have a distillable
   Purpose+Process section (else fail instead of silent first-2-KB fallback);
   flag duplicates; regenerate `PHASE_SKILL_MAP.md` from a static scan of
   `skills["<name>"]` usages in `graph/nodes/*`; consolidate `git-workflow*`.
3. Per-phase skill budgets in `bounds.yaml`; `invoke_skill(phase=...)` selects.

### Phase 3 — Observability of state/skill costs (~0.5 day)
- Log per-node update size + checkpoint values size
  (`log_event("state.size", node=..., bytes=...)`) into the existing W2 in-process
  metrics bootstrap; visible in Phoenix/Prometheus.
- Track distilled-skill char counts per LLM call as a per-phase metric (half-there
  in `prepare_context_for_llm` headroom logging).

### Suggested order & gates
- P0 = one PR (contract test + dead keys + counter + parse helper).
- P1 = three PRs: (a) typed `Artifacts` + reducer validation, (b) the five
  BUILD-subgraph fixes (D1–D5, see Phase 1 item 5), (c) blob offload +
  size-budget test. Gate on the AGENTS.md sandbox-caveat test command
  (7 hang files `--ignore`, 9 health socket tests `--deselect` → ~355+ passed, 0
  failures; `ruff check .` clean).
- P2 independent; P3 last.

---

## E. Whole-codebase pass findings (2026-09-18)

Scope: `graph/runner.py`, `graph/executor.py`, `graph/checkpointer.py`,
`graph/achg_scanner.py`, `graph/main.py` (re-verified), `feedback/*`, `service/*`,
`config/*`, `frontend/backend/*`, `tools/*` (remainder). Builds on A–D; new
findings only.

### E1. **Bug (livelock): DEFINE retry counter is never persisted**

`graph/nodes/define.py:452-454` calls `_maybe_increment_loop(state, "DEFINE")`,
which mutates `state["artifacts"]["loop_counts"]` **in place**
(`graph/edges.py:63-65`). But `define.py:488-489` only merges the separately
built `artifacts_delta` into the returned partial update — the in-place
mutation of the incoming state dict never reaches the return value, so
LangGraph's `_dict_merge` reducer never sees it and the checkpoint keeps
`loop_counts["DEFINE"]` at 0.

Consequences:
- `route_phase`'s guard `loop_count >= 2 → _forward_paths["DEFINE"] = "PLAN"`
  (`graph/edges.py:91-94`) never fires: a project whose spec confidence is
  chronically below the `0.9` threshold loops DEFINE→DEFINE **without bound**
  (the `spec_confidence < min_spec_conf` branch routes back to DEFINE at
  `edges.py:109-112`, and the counter it depends on stays 0 forever).
- The "loop limit reached, forcing forward to PLAN" branch at
  `define.py:454-463` can never be taken for the same reason (`_maybe_increment_loop`
  returns `new_counts[phase] >= 2` on a dict that is never persisted, so it
  can never observe ≥2).

Contrast — the pattern done right: `verify.py:449-453`, `review.py:424-425`,
and `openhands_build.py:517-521` all build a fresh `loop_counts` dict and
return it inside the node's `artifacts` update, so their counters persist.
`verify.py:428-431` even carries a comment explaining that the old
`_maybe_increment_loop` call was *removed* precisely because it mutated in
place. DEFINE is the last call site of the dead helper and is broken.

**Fix:** in `define_node`, copy the counter into the returned delta, e.g.
build `loop_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))`
on low confidence, `loop_counts["DEFINE"] = +1`, and merge into
`artifacts_delta`; then delete `_maybe_increment_loop` (or make it return a
new dict, per the Phase-0 plan) and drop the `graph.edges` import from
`define.py`. Add a regression test asserting that a low-confidence DEFINE
run persists `artifacts.loop_counts["DEFINE"]` (mirror of
`test_w2_wayforward.py`'s BUILD counter tests).

Note: `_maybe_increment_loop`'s docstring says it "MUST REPLACE
state['artifacts'] with new dict" — it does not (it reassigns the nested
`loop_counts` key on the existing dict, which *is* an in-place mutation the
reducer never observes). Delete or fix the helper rather than trusting it.

### E2. `config.Config.reload()` re-reads YAML but not env — and silently no-ops for class attributes

`config/loader.py:317-321`: `reload()` rebinds the module-global `_config`
dict, but every `Config` attribute was resolved **at import time** into
class attributes (`_resolve(...)` calls at class-body execution, lines 78-106
etc.). Nothing re-resolves them, so `config.reload()` is a no-op for every
already-resolved value. Two sub-problems:
- Any caller expecting fresh values after `reload()` gets import-time values
  (stale env var or yaml).
- `_resolve`'s env-var branch (`os.getenv`) is evaluated once at import; even
  re-reading yaml wouldn't pick up env changes.

Currently no active code path calls `config.reload()` (grep: only the
definition exists), so this is latent, not a live bug — but it is a footgun:
REFLECT's guardrail updates write `config/guardrails.yaml` (not
`config/config.yaml`) and `config.guardrails._get_cache()` *does* reload on
mtime, which is the working pattern. Either delete `reload()` or make it
re-resolve; as written it misleads readers into thinking hot-reload works.

### E3. `frontend/backend/app.py` `__main__` port (8011) vs documented 48011 — container-internal vs host-published

`app.py:281` `uvicorn.run(app, host="0.0.0.0", port=8011)` vs AGENTS.md /
SPEC.md documenting the FastAPI port as `:48011`. **Not a runtime bug**: in
Docker, `docker-compose.yml` publishes `"48011:8011"` and `entrypoint.sh`
starts uvicorn on `:8011` (container-internal); `:48011` is only the
host-published port (nginx also proxies `:4080→:8011`). The `__main__`
block is the dev-only standalone entry point; running it locally binds
`8011`, not `48011`. Doc inconsistency only — but anyone running
`python frontend/backend/app.py` locally and hitting `:48011` gets
connection-refused. Either add a `PORT`/`FASTAPI_PORT` env override to the
`__main__` block or document "run with `uvicorn frontend.backend.app:app
--port 48011` for local dev". Minor.

### E4. `AbortManager` is a module-level singleton tied to one event loop

`frontend/backend/abort_manager.py:17`: `asyncio.Event()` is created in
`__init__`, and `AbortManager.get()` caches a single instance forever.
`asyncio.Event` is bound to the event loop it first runs on (3.10+: created
lazily, but `wait_for`/`set` from a *different* loop raises / no-ops).
Consequences:
- In the Web bridge this is fine in practice (one uvicorn loop owns it).
- Any test that creates a fresh event loop, or a second workflow started on
  a different loop in the same process, inherits the stale event from the
  first loop — `is_aborted` / `wait` can silently report the wrong state.
- `clear()`/`signal()` are not loop-checked, so a `signal()` on loop A after
  the loop that created the event closed is a no-op with no error.

Fix: lazily create the `asyncio.Event` on first use in the running loop
(recreate per-loop or guard by loop id), or replace with a plain
`threading.Event` (the abort check is polled from both sync and async
paths — `executor.py` calls `abort_check()` synchronously between chunks).
The singleton also means two concurrent workflows share one abort flag;
the bridge guards this by clearing on start, but that is fragile — key the
event on the workflow/thread id instead.

### E5. `feedback/diff_engine.py` writes Python code via LLM text — prompt-injection-shaped vector

`apply_prompt_diff` (`diff_engine.py:227-270`) takes the LLM-produced
`change` description and splices it **verbatim** into
`config/prompt_templates.py` as the new template body
(`new_template = f'{template_name} = """{change_desc}"""'`), then writes
the file. The regex that *locates* the template is
`rf'({template_name}\s*=\s*"""[^\"]*""")'` — note `[^\"]*`: it cannot
match a template body containing a `"` character, so it will both (a) fail
to find most real templates and (b) if it did match, the replacement
injects whatever the LLM said, unescaped, straight into a `.py` source file.
Combined with REFLECT's "human approves changes" gate this is *mitigated*
(humans sign off), but the auto-approve path applies it without a diff
review. Recommend: require the LLM to emit a structured diff (the W3 target
shape `{section,key,op,value}` — Decision 4), or at minimum escape/validate
the replacement and keep the regex quote-aware. As written it is the
least-safe code path in the repo.

### E6. `feedback/chroma_client.py` — URL parse is order-dependent and `metadatas` can mismatch docs

`get_chroma_client` (`chroma_client.py:28-30`):
`host=url.split("//")[-1].split(":")[0], port=int(url.split(":")[-1])`.
- Fails for URLs without an explicit port (no `:port` → `int("localhost")`
  → `ValueError` → falls back to embedded client, silently losing the
  server connection).
- `url.split("//")[-1]` on `http://host:port` gives `host:port` (fine) but
  on `chroma://...` or a bare host gives wrong host. The config default is
  `http://localhost:8000`, so it works today; the parse is just brittle.

`query_patterns` (`chroma_client.py:94-101`): zips `documents[i]`,
`metadatas[i]`, `distances[i]` by index with `metas[i] if metas else {}`
— if Chroma returns fewer metadatas than documents (it can, on empty
collections the arrays are empty), `metas[i]` raises `IndexError`
*after* the `if metas` check passes for short lists. Use
`zip(docs, metas, dists)` with fillvalue.

### E7. `service/health.py` — `/ready` 503s on any Chroma blip; `_ready` shadows the name

Minor:
- `HealthHandler._ready` returns 503 whenever the ChromaDB heartbeat fails
  (even a transient network blip). For a health endpoint used by the
  Docker healthcheck, that flaps the container's "ready" state on every
  Chroma hiccup; consider 200-with-degraded or a retry before 503.
- Line 118 `_health_server: Optional["HTTPServer"] = None` is declared
  *after* `start_health_server` (line 100) references it — legal (the
  `global` resolves at call time) but the forward-reference string type +
  late declaration is confusing; declare it before the function.
- `track_workflow_error` pops the project and resets the gauge, but a
  workflow that errors *mid-phase* without a corresponding
  `track_workflow_start` entry (e.g. crashed at graph compile) leaves
  `ACTIVE_WORKFLOWS` inconsistent. Acceptable; just note the asymmetry.

### E8. `graph/achg_scanner.py` — clean; one minor note

The scanner is pure, well-structured, and matches the EYW-171 spec. Two
small notes (not bugs):
- `_candidate_files` globs three patterns and dedupes with `if p not in
  found` — O(n²) on large trees; fine at ArcKit scale, but a set-based
  dedupe is cheaper.
- `parse_achg` returns `None` on `OSError` but also when frontmatter
  `docType != "ACHG"`; the docstring says "unreadable or docType not
  ACHG" — accurate, but callers can't distinguish a corrupt file from a
  non-ACHG file. For auditing, a two-tuple `(entry|None, reason)` would be
  clearer. Optional.

### E9. `tools/context_manager.py` — `estimate_tokens` heuristic is optimistic for code

`estimate_tokens` (`context_manager.py:10-23`): counts "code" by ratio of
`[{}[\]();=<>!@#$%^&*|]` characters, then uses 3.5–4.5 chars/token. For
JSON-heavy or CJK-heavy content this badly underestimates tokens
(CJK is ~1.5–2 chars/token, not 3.5–4.5), so `check_headroom` /
`compress_context` can report "fits" when the real prompt overflows. The
BUILD prompt (ArcKit advisory sections + diagrams + acceptance tests) is
exactly the heavy case. Not a correctness bug (it's a heuristic with a
`compress_context` fallback), but the "guaranteed to fit" docstring on
`compress_context` is over-claimed given the estimator. Soften the docstring
or switch to a real tokenizer for the heavy paths.

### E10. `graph/executor.py` — CLI interview questions are hardcoded and diverge from INTERVIEW_QUESTIONS

`executor.py:622-632` `_cli_interview` hardcodes 9 interview question keys
(`core_behavior`, `data_model`, `api_surface`, `validation`, `ui_template`,
`integration`, `deployment`, `edge_cases`, `non_functional`), while
`frontend/backend/workflow_bridge.py` maintains its own `INTERVIEW_QUESTIONS`
list derived from the `interview-me` SKILL.md. The two can drift: a skill
that adds/renames a category is picked up by the Web bridge but not the
CLI. Extract the question list to a single source (the skill, or a shared
constant in `graph/`) and have both the CLI and Web bridge read it. Minor
consistency finding.

### E11. `graph/checkpointer.py` — `LazyAsyncSqliteSaver.__getattr__` can materialize from a sync context

`_materialize` requires a running event loop (it calls
`AsyncSqliteSaver(aiosqlite.connect(...))`, whose `__init__` captures the
loop). `__getattr__` (line 128-130) forwards *any* unknown attribute —
including sync ones like `get_tuple`, `list`, `copy_thread` — through
`_materialize()`. If any code path touches a sync attribute of the saver
from a thread with no running loop, `AsyncSqliteSaver.__init__` raises
`RuntimeError` ("no running event loop") with a confusing traceback
pointing at `__getattr__`. All current call sites use the async API in a
running loop, so this is latent; a guard (`if not running loop: raise
RuntimeError("...")`) with a clear message would prevent a future footgun.
Minor.

### E12. `graph/runner.py` — `discover_hil_count` is a dual-written, partially-dead counter

`runner.py:261` increments `discover_hil_count` inside
`build_resume_payload` for every DISCOVER resume (setup *and* interview),
and `executor.py:547` also writes `interview["discover_hil_count"]` on the
auto-approve path. But the *reader* that actually dispatches on it —
`executor.py:520-522` (`_hil_auto_approve`) and `:574-577`
(`_hil_cli_sync`) — reads it from `state["artifacts"]`, while
`build_resume_payload` writes it via the `update_data` checkpoint
pre-seed. The two write paths (runner's `update_data` vs executor's
auto-approve interview dict) can disagree on the value the node sees, and
the "unknown DISCOVER type → fall back on hil count" legacy branch
(`runner.py:295-309`) is the only consumer of the value *as persisted*.
In the active Web path the `hil_type` is always known (either
`project_setup` or `interview`, extracted from the interrupt payload), so
the count-based fallback is dead code in practice. Consolidate: have the
node own the counter (write `discover_hil_count` into its returned
`artifacts`), drop the runner-side pre-seed increment, and delete the
legacy count-dispatch branch. Reduces the dual-write divergence risk.

### E13. `tools/audit_logger.py` — unbounded in-memory entry list

`AuditLog._log` (line 49-68) appends every entry to `self._entries`
**and** writes to the JSONL. Over a long workflow (many LLM calls × many
phases × the 355-test suite re-running nodes), `_entries` grows without
bound for the lifetime of the `AuditLog` instance. `get_entries` copies the
whole list. Cap it (keep last N, or stream-only and drop the in-memory
list) — the JSONL is the source of truth, the in-memory copy is only for
`get_entries` convenience. Minor memory finding.

### E14. No new regressions in previously-reviewed modules

`graph/main.py`, `graph/state.py`, `graph/edges.py`, `tools/llm.py`,
`tools/acceptance.py`, `graph/nodes/openhands_build.py`,
`graph/nodes/discover.py`, `graph/nodes/verify.py`,
`graph/nodes/review.py`, `graph/nodes/ship.py`, `graph/nodes/reflect.py`
— re-verified against the Decision Log (D1–D5): all invariants hold
(interrupt_after excludes DISCOVER; `verify_status` is the gate source of
truth; `build_report.json` hard contract with `BuildReportMissingError`;
`None`-coercion on active-path nodes; `loop_counts` in `artifacts`). No
divergence found. `reflect.py`'s `interrupt` is correctly guarded (the
`try/except` at `reflect.py:289-293` auto-rejects in non-HIL mode).

### E15. Suggested new Phase (P4) — counter & footgun fixes, independent of P0–P3

1. **E1 (the one true bug):** fix DEFINE's `loop_counts` persistence;
   delete `_maybe_increment_loop`; regression test.
2. **E5:** make `apply_prompt_diff` use a structured diff + escape the
   LLM text; require human diff-review on the auto-approve path.
3. **E2:** delete or fix `config.Config.reload()` (document it as a no-op
   or make it re-resolve).
4. **E4:** make `AbortManager` per-loop / per-workflow.
5. **E12:** consolidate `discover_hil_count` ownership to the node.
Gate on the same AGENTS.md close-out command. P4 is independent and can
ship before P1's typed-artifacts work; E1 specifically is a one-line
pattern fix with a test.
