from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class _GraphState(TypedDict):
    actions: List[str]
    idx: int
    revision_rounds: int
    next: str


def plan_actions(inject: bool) -> List[str]:
    actions = ["ingest", "aggregate"]
    if inject:
        actions.append("inject")
    actions += ["detect", "fuse", "explain", "audit", "persist"]
    return actions


def run_with_langgraph(coordinator: Any, inject: bool = False, shape: str = "gradual", magnitude: float = 10.0) -> Dict:
    from langgraph.graph import END, StateGraph

    coordinator.inject_enabled = inject
    coordinator.inject_shape = shape
    coordinator.inject_magnitude = magnitude

    actions = plan_actions(inject)

    def supervisor_node(state: _GraphState) -> dict:
        idx = state.get("idx", 0)
        if idx >= len(state.get("actions", [])):
            return {"next": "end"}
        return {"next": state["actions"][idx]}

    def make_action_node(action: str):
        def node(state: _GraphState) -> dict:
            revision_rounds = state.get("revision_rounds", 0)
            new_revision_rounds = coordinator._supervise_action(action, revision_rounds)
            return {"idx": state.get("idx", 0) + 1, "revision_rounds": new_revision_rounds}

        return node

    def route(state: _GraphState) -> str:
        return state.get("next", "end")

    workflow = StateGraph(_GraphState)
    workflow.add_node("supervisor", supervisor_node)
    for a in actions:
        workflow.add_node(a, make_action_node(a))
    workflow.set_entry_point("supervisor")

    mapping = {a: a for a in actions}
    mapping["end"] = END
    workflow.add_conditional_edges("supervisor", route, mapping)
    for a in actions:
        workflow.add_edge(a, "supervisor")

    app = workflow.compile()
    app.invoke({"actions": actions, "idx": 0, "revision_rounds": 0, "next": ""})

    if coordinator.state.get("summary") == {}:
        coordinator._task_persist()
    return dict(coordinator.state)
