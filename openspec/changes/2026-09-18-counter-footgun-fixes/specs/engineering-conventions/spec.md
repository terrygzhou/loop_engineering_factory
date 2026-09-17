# engineering-conventions (delta)

## ADDED Requirements

### Requirement: No in-place LangGraph state mutation
Nodes and edges SHALL pass state around as returned partial-update
dicts. In-place mutation of `state["artifacts"]` (or any
`_dict_merge`-annotated channel) is forbidden: the reducer only sees
returned values, so in-place writes are silently lost — the exact
failure mode behind the E1 DEFINE livelock. A CI-friendly contract
test SHALL exist (P0's `tests/test_state_contract.py` extends this to
all keys; for now a lint-level assertion in `tests/test_edges.py`
that `route_phase` leaves `state["artifacts"]` unchanged).

### Requirement: Config is import-time resolved; document, don't fake
`config.Config` values are resolved ONCE at import time
(env > config.yaml > default). `Config.reload()` is REMOVED; the module
docstring states that picking up env/yaml changes requires a process
restart, and names `config.guardrails._get_cache()` as the one working
mtime-reload path. Any new "reload" API must actually re-resolve
values or not exist.
