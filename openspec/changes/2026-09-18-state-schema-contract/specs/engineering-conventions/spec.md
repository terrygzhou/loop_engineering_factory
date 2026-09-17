# engineering-conventions (delta)

## ADDED Requirements

### Requirement: State schema contract test (AST audit)
A CI-friendly contract test SHALL structurally enforce the
`WorkflowState` schema:

- `tests/test_state_contract.py` AST-walks every active node in
  `graph/nodes/*.py` + `graph/runner.py`, collecting the top-level
  keys of the partial-update dicts they return.
- It asserts every `WorkflowState` key is in
  (node-returned-keys ∪ `INPUT_ONLY_KEYS`), and every
  `INPUT_ONLY_KEYS` entry is declared in the TypedDict.
- It fails (by construction) when a new top-level key appears in the
  schema without being node-returned or input-only.

This replaces the abandoned S-001/S-003 manual dedup with a
structural guard: schema drift is now a test failure, not a comment.
