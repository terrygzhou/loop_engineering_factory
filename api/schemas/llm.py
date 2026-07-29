# ── DISABLED: Import guard to prevent accidental usage ──────────────
raise ImportError(
    "api.schemas.llm is DEPRECATED. "
    "This module was disabled in the code cleanup audit. "
    "Reason: LlmRequest/LlmResponse schemas are not consumed by any active API endpoint or service."
)
# ── End guard — original code below (preserved for reference) ──────
