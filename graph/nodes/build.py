"""
BUILD node — DEPRECATED: now a native LangGraph subgraph.

This module is kept for backward compatibility. The graph/main.py wiring
now uses build_subgraph directly with input/output mappings, so this
file's build_node() simply re-exports the subgraph entry function.
"""
from .build_subgraph import build_input_mapping as build_node  # noqa: F401


# For callers that still import build_node as a standalone function:
def __getattr__(name):
    if name == "build_node":
        return build_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
