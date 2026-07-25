"""
Graph compilation: wire up the LangGraph workflow with all nodes and edges.

Uses LangGraph OOTB APIs:
- interrupt() inside nodes for HIL pauses (DISCOVER, ARCH_REVIEW)
- SQLiteSaver for checkpoint persistence
"""
from langgraph.graph import StateGraph, START, END

from graph.state import WorkflowState
from graph.nodes.discover import discover_setup_node, discover_interview_node
from graph.nodes.define import define_node
from graph.nodes.plan import plan_node
from graph.nodes.review import review_node
from graph.nodes.openhands_build import openhands_build_proxy_factory
from graph.nodes.seed_data import seed_data_node
from graph.nodes.verify import verify_node
from graph.nodes.ship import ship_node
from graph.nodes.reflect import reflect_node
from graph.edges import route_phase


def build_graph(checkpointer=None, auto_approve=False):
    """
    Build and compile the LangGraph workflow.

    Flow: DISCOVER -> DEFINE -> PLAN -> ARCH_REVIEW -> BUILD
         -> SHIP -> REFLECT -> END

    BUILD uses the build_proxy node that delegates to a remote builder
    service. If the builder is unreachable, it falls back to the local
    build_subgraph so the orchestrator never dead-ends.

    ARCH_REVIEW is a mandatory HIL gate: approve → BUILD, reject → back to PLAN.
    """
    workflow = StateGraph(WorkflowState)

    # Register nodes
    # DISCOVER split into two nodes (setup + interview) — each has ONE interrupt
    workflow.add_node("DISCOVER_SETUP", discover_setup_node)
    workflow.add_node("DISCOVER_INTERVIEW", discover_interview_node)
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

    # Wire edges
    workflow.add_edge(START, "DISCOVER_SETUP")
    workflow.add_edge("DISCOVER_SETUP", "DISCOVER_INTERVIEW")
    workflow.add_edge("DISCOVER_INTERVIEW", "DEFINE")
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

    return workflow.compile(
        checkpointer=checkpointer,
    )