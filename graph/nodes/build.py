"""
BUILD node — DEPRECATED: now a native LangGraph subgraph.

This module is kept for backward compatibility. The graph/main.py wiring
now uses build_subgraph directly with input/output mappings, so this
file's build_node() simply re-exports the subgraph entry function.

DEPRECATED: No longer imported by any active code. The BUILD node is
handled via build_proxy_node() -> build_subgraph(). Kept for historical
reference — import is blocked to prevent accidental usage.
"""

# ── DISABLED: Import guard to prevent accidental usage ──────────────
raise ImportError(
    "graph.nodes.build is DEPRECATED. "
    "This module was disabled in the code cleanup audit. "
    "The BUILD phase now uses graph.nodes.build_proxy -> graph.nodes.build_subgraph directly."
)
# ── End guard — original code below (preserved for reference) ──────

from .build_subgraph import build_input_mapping as build_node  # noqa: F401


# For callers that still import build_node as a standalone function:
def __getattr__(name):
    if name == "build_node":
        return build_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")