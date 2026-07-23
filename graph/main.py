"""
Graph compilation: wire up the LangGraph workflow with all nodes and edges.

Uses LangGraph OOTB APIs:
- interrupt() inside nodes for HIL pauses (DISCOVER, ARCH_REVIEW)
- SQLiteSaver for checkpoint persistence
"""
from langgraph.graph import StateGraph, START, END

from graph.state import WorkflowState
from graph.nodes.discover import discover_node
from graph.nodes.define import define_node
from graph.nodes.plan import plan_node
from graph.nodes.review import review_node
from graph.nodes.build_proxy import build_proxy_node
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
    workflow.add_node("DISCOVER", discover_node)
    workflow.add_node("DEFINE", define_node)
    workflow.add_node("PLAN", plan_node)
    workflow.add_node("ARCH_REVIEW", review_node)

    # BUILD: proxy to remote builder service (with local fallback)
    workflow.add_node("BUILD", build_proxy_node())

    # SEED_DATA & VERIFY: placeholders — pass-through to be implemented
    workflow.add_node("SEED_DATA", seed_data_node)
    workflow.add_node("VERIFY", verify_node)

    workflow.add_node("SHIP", ship_node)
    workflow.add_node("REFLECT", reflect_node)

    # Wire edges
    workflow.add_edge(START, "DISCOVER")
    workflow.add_edge("DISCOVER", "DEFINE")
    workflow.add_edge("DEFINE", "PLAN")
    workflow.add_edge("PLAN", "ARCH_REVIEW")
    workflow.add_conditional_edges("ARCH_REVIEW", route_phase)
    workflow.add_conditional_edges("BUILD", route_phase)
    workflow.add_edge("BUILD", "SEED_DATA")
    workflow.add_edge("SEED_DATA", "VERIFY")
    workflow.add_edge("VERIFY", "SHIP")
    workflow.add_edge("SHIP", "REFLECT")
    workflow.add_edge("REFLECT", END)

    return workflow.compile(
        checkpointer=checkpointer,
    )