"""
Shared ArcKit advisory-block helper.

``arckit_advisory_block`` builds a consolidated advisory block from the ArcKit
artifact keys set in the state's ``artifacts`` dict. Each key present and
non-empty becomes one ``## <KEY_NAME>`` section carrying the raw JSON value.
The total output is capped at ``max_chars``. Returns ``""`` when no advisory
key is set, so callers that append the result to their prompt context
produce a byte-identical prompt for non-ArcKit runs.
"""

__all__ = ["ARCKIT_ADVISORY_KEYS", "arckit_advisory_block"]

# Fixed key order: Tier-2 planning keys first, then W3 build-context keys.
ARCKIT_ADVISORY_KEYS: tuple[str, ...] = (
    "arckit_product_backlog",
    "arckit_strategy_waves",
    "arckit_integration_standards",
    "arckit_nfr_constraints",
    "arckit_security_controls",
    "arckit_data_model",
)


def arckit_advisory_block(artifacts: dict, max_chars: int = 4000) -> str:
    """Return a consolidated advisory block for the ArcKit keys set in
    ``artifacts``.

    Checks the keys in :data:`ARCKIT_ADVISORY_KEYS` order; for each key
    present and non-empty, emits one ``## <KEY_NAME>`` section containing the
    raw (JSON string) value. The total output is truncated to ``max_chars``.
    Returns ``""`` when no advisory key is set — callers that append the
    result produce a byte-identical prompt when ArcKit context is absent.
    """
    if not artifacts:
        return ""
    sections: list[str] = []
    for key in ARCKIT_ADVISORY_KEYS:
        raw = artifacts.get(key)
        if not raw:
            continue
        sections.append(f"## {key}\n{str(raw)}")
    if not sections:
        return ""
    block = "\n\n".join(sections)
    return block[:max_chars]
