"""
Graph compilation: wire up the LangGraph workflow with all nodes and edges.

Uses LangGraph OOTB APIs:
- interrupt() inside nodes for HIL pauses (DISCOVER, ARCH_REVIEW)
- SQLiteSaver for checkpoint persistence
"""
import logging

from langgraph.graph import StateGraph, START, END

from graph.state import WorkflowState
from graph.nodes.discover import discover_node
from graph.nodes.define import define_node
from graph.nodes.plan import plan_node
from graph.nodes.review import review_node
from graph.nodes.openhands_build import openhands_build_proxy_factory
from graph.nodes.seed_data import seed_data_node
from graph.nodes.verify import verify_node
from graph.nodes.ship import ship_node
from graph.nodes.reflect import reflect_node
from graph.edges import route_phase

_logger = logging.getLogger(__name__)


def error_node(state: WorkflowState) -> WorkflowState:
    """Terminal sink for unhandled exceptions — logs error and sets phase."""
    error_msg = state.get("error", "Unknown error")
    _logger.error("ERROR terminal reached: %s", error_msg)
    state["phase"] = "ERROR"
    return state

def build_graph(checkpointer=None, auto_approve=False):
    """
    Build and compile the LangGraph workflow.

    Flow: DISCOVER -> DEFINE -> PLAN -> ARCH_REVIEW -> BUILD
         -> SEED_DATA -> VERIFY -> SHIP -> REFLECT -> END

    BUILD uses the build_proxy node that delegates to a remote builder
    service. If the builder is unreachable, it falls back to the local
    build_subgraph so the orchestrator never dead-ends.

    ARCH_REVIEW is a mandatory HIL gate: approve → BUILD, reject → back to PLAN.
    ERROR is a terminal sink for unhandled exceptions (P-09 fix).
    """
    workflow = StateGraph(WorkflowState)

    # Register nodes
    # DISCOVER single async node with TWO sequential interrupt() calls
    # (setup + interview). LangGraph 1.x: merging them into one node is
    # required because interrupt() in a downstream node after resume
    # does NOT yield __interrupt__ in stream_mode='values'.
    workflow.add_node("DISCOVER", discover_node)
    workflow.add_node("DEFINE", define_node)
    workflow.add_node("PLAN", plan_node)
    workflow.add_node("ARCH_REVIEW", review_node)

    # BUILD: OpenHands agent delegation via Gateway API (with legacy fallback)
    workflow.add_node("BUILD", openhands_build_proxy_factory())

    # SEED_DATA & VERIFY: placeholders — pass-through to be implemented
    workflow.add_node("SEED_DATA", seed_data_node)
    workflow.add_node("VERIFY", verify_node)

    workflow.add_node("SHIP", ship_node)
    workflow.add_node("REFLECT", reflect_node)

    # P-09: ERROR terminal sink — captures unhandled exceptions
    workflow.add_node("ERROR", error_node)

    # Wire edges
    workflow.add_edge(START, "DISCOVER")
    workflow.add_edge("DISCOVER", "DEFINE")
    workflow.add_edge("DEFINE", "PLAN")
    workflow.add_edge("PLAN", "ARCH_REVIEW")
    workflow.add_conditional_edges("ARCH_REVIEW", route_phase)
    workflow.add_conditional_edges("BUILD", route_phase)
    # Note: no unconditional add_edge("BUILD", ...) — route_phase handles all BUILD routing
    # including BUILD→BUILD (retry), BUILD→SEED_DATA (pass), BUILD→REFLECT (fail)
    workflow.add_edge("SEED_DATA", "VERIFY")
    workflow.add_edge("VERIFY", "SHIP")
    workflow.add_conditional_edges("SHIP", route_phase)
    workflow.add_conditional_edges("REFLECT", route_phase)

    # P-09: ERROR is an explicit end node (terminal sink)
    workflow.add_edge("ERROR", END)

    # LangGraph 1.x: interrupt() only triggers when nodes are listed in
    # interrupt_after at compile time. List all HIL gate nodes so in-node
    # interrupt() calls actually pause instead of being silently swallowed.
    # SKIP interrupt_after when auto_approve=True — the graph should run
    # end-to-end without pausing, since in-node logic already bypasses
    # interrupt() calls and the executor handles auto-approve defaults.
    hil_nodes = [
        "DISCOVER",
        "ARCH_REVIEW",
        "REFLECT",
    ]
    compile_kwargs: dict = {"checkpointer": checkpointer}
    if not auto_approve:
        compile_kwargs["interrupt_after"] = hil_nodes
    return workflow.compile(**compile_kwargs)