"""LangGraph adapter for closed router decisions."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .contracts import (
    ContinuationDirective,
    RouterDecision,
    RouterEvent,
    RouterModel,
    RouterState,
)
from .profile import ProjectWorkflowProfile
from .router import RouterEngine


class RouterGraphState(RouterModel):
    """Graph state intentionally holds descriptors and decisions, never raw Context packets."""

    router_state: RouterState
    router_event: RouterEvent
    profile: ProjectWorkflowProfile
    decision: RouterDecision | None = None
    graph_terminal: Literal["continue", "waiting", "halted"] | None = None


def build_router_graph(
    *,
    engine: RouterEngine,
) -> CompiledStateGraph[RouterGraphState, None, RouterGraphState, RouterGraphState]:
    """Compile a graph whose branch surface is fixed to complete or blocked."""

    graph: StateGraph[RouterGraphState, None, RouterGraphState, RouterGraphState] = StateGraph(
        RouterGraphState
    )

    def decide(state: RouterGraphState) -> RouterGraphState:
        """Evaluate one pure, profile-owned routing transition."""

        decision = engine.decide(
            state=state.router_state,
            event=state.router_event,
            profile=state.profile,
        )
        return state.model_copy(update={"decision": decision})

    def select_terminal(state: RouterGraphState) -> Literal["continue", "waiting", "halted"]:
        """Route only declared auto, human-wait, and halt dispositions."""

        if state.decision is None:
            return "halted"
        if state.decision.continuation is ContinuationDirective.AUTO_CONTINUE:
            return "continue"
        if state.decision.continuation is ContinuationDirective.WAIT_FOR_HUMAN:
            return "waiting"
        return "halted"

    def continue_(state: RouterGraphState) -> RouterGraphState:
        """Mark a legal automatic continuation for this graph invocation."""

        return state.model_copy(update={"graph_terminal": "continue"})

    def waiting(state: RouterGraphState) -> RouterGraphState:
        """Mark an explicit human gate without conflating it with a failure."""

        return state.model_copy(update={"graph_terminal": "waiting"})

    def halted(state: RouterGraphState) -> RouterGraphState:
        """Mark a fail-closed result as terminal for this graph invocation."""

        return state.model_copy(update={"graph_terminal": "halted"})

    graph.add_node("decide", decide)
    graph.add_node("continue", continue_)
    graph.add_node("waiting", waiting)
    graph.add_node("halted", halted)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        select_terminal,
        {"continue": "continue", "waiting": "waiting", "halted": "halted"},
    )
    graph.add_edge("continue", END)
    graph.add_edge("waiting", END)
    graph.add_edge("halted", END)
    return graph.compile()
