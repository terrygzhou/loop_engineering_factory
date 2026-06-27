"""
Graph compilation: wire up the LangGraph workflow with all nodes and edges.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import WorkflowState
from graph.nodes.discover import discover_node
from graph.nodes.define import define_node
from graph.nodes.plan import plan_node
from graph.nodes.build import build_node
from graph.nodes.seed_data import seed_data_node
from graph.nodes.verify import verify_node
from graph.nodes.ship import ship_node
from graph.nodes.reflect import reflect_node
from graph.nodes.arch_review import arch_review_node
from graph.edges import route_phase


def build_graph(checkpointer=None, auto_approve=False):
    """
    Build and compile the LangGraph workflow.

    Flow: DISCOVER -> DEFINE -> PLAN -> ARCH_REVIEW -> BUILD
         -> SEED_DATA -> VERIFY -> SHIP -> REFLECT -> END
    With conditional routing for quality gates.

    PLAN generates: specification, implementation plan, tasks, and architecture diagrams.
    ARCH_REVIEW pauses for user review of all Plan outputs before BUILD.
    Single HIL node (interrupt_after): ARCH_REVIEW (skipped when auto_approve=True)
    """
    workflow = StateGraph(WorkflowState)

    # Register nodes
    workflow.add_node("DISCOVER", discover_node)
    workflow.add_node("DEFINE", define_node)
    workflow.add_node("PLAN", plan_node)
    workflow.add_node("ARCH_REVIEW", arch_review_node)
    workflow.add_node("BUILD", build_node)
    workflow.add_node("SEED_DATA", seed_data_node)
    workflow.add_node("VERIFY", verify_node)
    workflow.add_node("SHIP", ship_node)
    workflow.add_node("REFLECT", reflect_node)

    # Wire edges
    workflow.add_edge(START, "DISCOVER")
    workflow.add_edge("DISCOVER", "DEFINE")
    workflow.add_edge("DEFINE", "PLAN")

    # PLAN -> ARCH_REVIEW (PLAN generates all outputs including diagrams)
    workflow.add_edge("PLAN", "ARCH_REVIEW")

    # ARCH_REVIEW -> conditional: approve → BUILD, reject → DEFINE
    workflow.add_conditional_edges("ARCH_REVIEW", route_phase)

    # Conditional routing with quality gates
    workflow.add_conditional_edges("BUILD", route_phase)
    workflow.add_conditional_edges("SEED_DATA", route_phase)
    workflow.add_conditional_edges("VERIFY", route_phase)

    # SHIP -> always reflect
    workflow.add_edge("SHIP", "REFLECT")

    # REFLECT -> END
    workflow.add_edge("REFLECT", END)

    # DISCOVER raises its own GraphInterrupt mid-node — don't list it in interrupt_after.
    # Only ARCH_REVIEW needs interrupt_after because it raises GraphInterrupt at the end.
    interrupt_nodes: list[str] = [] if auto_approve else ["ARCH_REVIEW"]
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_nodes,
    )
