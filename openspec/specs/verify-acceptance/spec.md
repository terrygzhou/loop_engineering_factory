# verify-acceptance Specification

## Purpose
Defines how VERIFY turns the spec's acceptance-test block into a
deterministic pass/fail target.

## Requirements

### Requirement: VERIFY acceptance gate
When `artifacts.spec_refined` contains a valid acceptance-test block, VERIFY
SHALL execute each `check` locally (bounded, per-test timeout from
`config/bounds.yaml`) and write `artifacts.acceptance_results` (per-test
pass/fail with output). `artifacts.verify_status` SHALL be `fail` when
`test_errors > 0` OR any acceptance test failed, `pass` otherwise. When no
acceptance block exists, VERIFY SHALL behave exactly as today (gate on
`test_errors` only). Routing SHALL be unchanged: fail → BUILD with the
failing test ids and their `expect` text in the retry prompt; loop budget
max 2; budget exhausted → ERROR, never SHIP (Decision 2 preserved).

#### Scenario: Acceptance test fails
- **WHEN** one acceptance test fails and `test_errors` is zero
- **THEN** `verify_status` is `fail` and the workflow routes to BUILD with
  the failing test id in the retry prompt

#### Scenario: All pass
- **WHEN** `test_errors` is zero and every acceptance test passes
- **THEN** `verify_status` is `pass` and the workflow routes to SHIP

#### Scenario: No acceptance block
- **WHEN** the spec has no acceptance-test block
- **THEN** VERIFY behaviour is identical to today (test_errors only)

#### Scenario: Budget exhausted
- **WHEN** the VERIFY→BUILD loop count reaches the maximum (2)
- **THEN** the workflow routes to ERROR and never SHIPs
