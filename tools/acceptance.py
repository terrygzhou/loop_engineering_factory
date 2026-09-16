"""W5 verify-acceptance-criteria — acceptance-test block parser.

The DEFINE spec LLM emits a fenced JSON block of the form::

    ```json
    {"acceptance_tests": [
      {"id": "AT-01", "check": "pytest -q", "expect": "all pass"}
    ]}
    ```

``parse_acceptance_block`` returns the first well-formed
``acceptance_tests`` list found in the text, or ``None`` when no valid
block is present (absent block, invalid JSON, wrong shape, or empty
list). Malformed blocks are skipped, never raised on — a bad block
followed by a good one yields the good one (Decision 3: typed errors,
no sentinel strings, no exceptions from parsing).
"""

from __future__ import annotations

import json
import re
from typing import Any

# Fenced ```json blocks, non-greedy up to the next closing fence.
_JSON_FENCE_RE = re.compile(r"```json[ \t]*\n(.*?)```", re.DOTALL)


def _well_formed_tests(data: Any) -> list[dict] | None:
    """Return ``data["acceptance_tests"]`` if well-formed, else ``None``.

    Well-formed: ``data`` is a dict whose ``acceptance_tests`` is a
    non-empty list of dicts, each carrying required ``id`` + ``check``
    keys (``expect`` optional).
    """
    if not isinstance(data, dict):
        return None
    tests = data.get("acceptance_tests")
    if not isinstance(tests, list) or not tests:
        return None
    for item in tests:
        if not isinstance(item, dict) or "id" not in item or "check" not in item:
            return None
    return tests


def parse_acceptance_block(text: str | None) -> list[dict] | None:
    """Extract the first valid acceptance-test block from *text*.

    Scans every ```json fenced block; the first one that (a) parses as
    JSON, (b) carries a non-empty ``acceptase_tests``/``acceptance_tests``
    list of ``{id, check[, expect]}`` dicts is returned. Invalid JSON,
    non-list values, empty lists, or items missing ``id``/``check``
    yield ``None`` (or, for a later block, are simply skipped).
    """
    if not text:
        return None
    for match in _JSON_FENCE_RE.finditer(str(text)):
        try:
            data = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        tests = _well_formed_tests(data)
        if tests is not None:
            return tests
    return None
