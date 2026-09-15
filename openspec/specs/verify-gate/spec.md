# verify-gate

## Purpose
A deterministic post-BUILD quality gate that prevents shipping broken code.

## Requirements

### Requirement: Deterministic verify gate
graph/nodes/verify.py SHALL write artifacts.verify_status ("pass"|"fail");
the gate decision SHALL be driven by verify_status and test_errors (pytest
failures), with LLM review text advisory only.

#### Scenario: Verification passes
- **WHEN** verify_status == "pass" and test_errors == 0
- **THEN** the workflow routes to SHIP

#### Scenario: Verification fails within budget
- **WHEN** verify_status == "fail" or test_errors > 0 and the VERIFY loop
  counter is below max_loops (2)
- **THEN** the workflow loops back to BUILD

#### Scenario: Verification fails with exhausted budget
- **WHEN** verify_status == "fail" and the VERIFY loop counter is at max_loops
- **THEN** the workflow routes to ERROR and never reaches SHIP
