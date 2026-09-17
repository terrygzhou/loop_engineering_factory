# human-in-the-loop (delta)

## MODIFIED Requirements

### Requirement: DISCOVER owns its HIL counter
`artifacts.discover_hil_count` SHALL be written exclusively by the
DISCOVER node, in its returned `artifacts` delta: incremented on every
DISCOVER HIL resume (setup AND interview), read back from
`state["artifacts"]` by the dispatching code.

- `graph/runner.py` SHALL NOT pre-seed or increment the counter via
  checkpoint `update_data`, and the "unknown DISCOVER hil_type → fall
  back on the persisted count" legacy dispatch branch SHALL be deleted
  (the active Web path always knows `hil_type` from the interrupt
  payload).
- `graph/executor.py`'s auto-approve interview path SHALL NOT write the
  counter.

#### Scenario: Two DISCOVER resumes
- **WHEN** a workflow resumes DISCOVER setup and then DISCOVER interview
- **THEN** after the second resume `state["artifacts"]["discover_hil_count"]
  == 2`, read from the node's own returned delta (no side channel)
