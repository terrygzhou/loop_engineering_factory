"""P0-A5 — count_pytest_fail helper (gate signal parsed once).

Spec delta: state-schema-contract / workflow-orchestration,
"Gate signal parsed once" — the VERIFY branch must NOT parse
artifacts.test_results JSON inline; the parse lives in
tools.acceptance.count_pytest_fail, returning 0 on absent / invalid /
missing-field input, identical to the inline try/except it replaces.
"""

import json

import pytest

from tools.acceptance import count_pytest_fail


@pytest.mark.parametrize(
    "artifacts",
    [
        {"test_results": json.dumps({"pytest_fail": 3})},
        {"test_results": json.dumps({"pytest_pass": 5, "pytest_fail": 3})},
        {"test_results": json.dumps({"pytest_fail": 0})},
        {"test_results": json.dumps({"pytest_fail": 0, "pytest_pass": 5})},
        # 0 is falsy but must still return 0 explicitly
        {"test_results": json.dumps({"pytest_fail": None})},
        # pytest_fail absent
        {"test_results": json.dumps({"pytest_pass": 5})},
        # top-level JSON but not a dict — behaves like invalid for .get()
        {"test_results": json.dumps([1, 2, 3])},
    ],
    ids=[
        "pytest_fail=3",
        "pytest_fail=3-with-pass",
        "pytest_fail=0",
        "pytest_fail=0-with-pass",
        "pytest_fail-null",
        "pytest_fail-absent",
        "json-not-a-dict",
    ],
)
def test_valid_json_returns_pytest_fail(artifacts):
    assert count_pytest_fail(artifacts) is not None


def test_valid_json_returns_pytest_fail_value():
    assert count_pytest_fail({"test_results": json.dumps({"pytest_fail": 3})}) == 3
    assert count_pytest_fail({"test_results": json.dumps({"pytest_fail": 0})}) == 0


def test_absent_test_results_returns_0():
    assert count_pytest_fail({}) == 0


def test_empty_string_test_results_returns_0():
    assert count_pytest_fail({"test_results": ""}) == 0
    assert count_pytest_fail({"test_results": None}) == 0


def test_invalid_json_returns_0():
    assert count_pytest_fail({"test_results": "not json"}) == 0
    assert count_pytest_fail({"test_results": "12 passed"}) == 0


def test_non_string_test_results_returns_0():
    # Not a str — treated as absent/invalid, not raised
    assert count_pytest_fail({"test_results": {"pytest_fail": 3}}) == 0
