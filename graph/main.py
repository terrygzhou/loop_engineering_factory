"""
Graph compilation: wire up the LangGraph workflow with all nodes and edges.

Uses LangGraph OOTB APIs:
- interrupt_after=[] (HIL removed — fully automatic)
- SQLiteSaver for checkpoint persistence
"""
from langgraph.graph import StateGraph, START, END

from graph.state import WorkflowState
from graph.nodes.discover import discover_node
from graph.nodes.define import define_node
from graph.nodes.plan import plan_node
from graph.nodes.review import review_node
from graph.nodes.build_proxy import build_proxy_node
from graph.nodes.ship import ship_node
from graph.nodes.reflect import reflect_node
from graph.edges import route_phase


def build_graph(checkpointer=None, auto_approve=False):
    """
    Build and compile the LangGraph workflow.

    Flow: DISCOVER -> DEFINE -> PLAN -> REVIEW -> BUILD
         -> SHIP -> REFLECT -> END

    BUILD uses the build_proxy node that delegates to a remote builder
    service. If the builder is unreachable, it falls back to the local
    build_subgraph so the orchestrator never dead-ends.

    REVIEW is a HIL gate: approve → BUILD, reject → back to PLAN.
    """
    workflow = StateGraph(WorkflowState)

    # Register nodes
    workflow.add_node("DISCOVER", discover_node)
    workflow.add_node("DEFINE", define_node)
    workflow.add_node("PLAN", plan_node)
    workflow.add_node("REVIEW", review_node)

    # BUILD: proxy to remote builder service (with local fallback)
    workflow.add_node("BUILD", build_proxy_node())

    workflow.add_node("SHIP", ship_node)
    workflow.add_node("REFLECT", reflect_node)

    # Wire edges
    workflow.add_edge(START, "DISCOVER")
    workflow.add_edge("DISCOVER", "DEFINE")
    workflow.add_edge("DEFINE", "PLAN")
    workflow.add_edge("PLAN", "REVIEW")
    workflow.add_conditional_edges("REVIEW", route_phase)
    workflow.add_conditional_edges("BUILD", route_phase)
    workflow.add_edge("SHIP", "REFLECT")
    workflow.add_edge("REFLECT", END)

    return workflow.compile(
        checkpointer=checkpointer,
    )
