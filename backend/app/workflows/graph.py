"""LangGraph state graph with conditional PASS/FAIL routing (§7).

Termination proof:
  * `dispatch` is the only re-entry point and it *pops* from `queue`.
  * `critic → refiner → critic` is bounded by `retry_count < max_retries`.
  * a global `execution_metadata.steps < MAX_STEPS` guard trips the graph to the
    dataset builder, so an infinite agent loop is structurally impossible.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.workflows.nodes import (
    approval_node,
    critic_node,
    dataset_builder_node,
    dispatch_node,
    export_node,
    fail_sample_node,
    generator_node,
    human_gate_node,
    planner_node,
    refiner_node,
)
from app.workflows.state import EvaluationState

NODES = {
    "planner": planner_node,
    "generator": generator_node,
    "dispatch": dispatch_node,
    "critic": critic_node,
    "refiner": refiner_node,
    "approval": approval_node,
    "human_gate": human_gate_node,
    "fail_sample": fail_sample_node,
    "dataset_builder": dataset_builder_node,
    "export": export_node,
}

# Static topology used by the frontend React Flow builder.
GRAPH_EDGES: list[dict[str, str]] = [
    {"source": "planner", "target": "generator", "label": ""},
    {"source": "generator", "target": "dispatch", "label": "samples"},
    {"source": "dispatch", "target": "critic", "label": "next sample"},
    {"source": "dispatch", "target": "dataset_builder", "label": "queue empty"},
    {"source": "critic", "target": "approval", "label": "PASS"},
    {"source": "critic", "target": "refiner", "label": "FAIL / retry"},
    {"source": "critic", "target": "human_gate", "label": "borderline"},
    {"source": "critic", "target": "fail_sample", "label": "retries exhausted"},
    {"source": "refiner", "target": "critic", "label": "re-evaluate"},
    {"source": "approval", "target": "dispatch", "label": ""},
    {"source": "human_gate", "target": "dispatch", "label": ""},
    {"source": "fail_sample", "target": "dispatch", "label": ""},
    {"source": "dataset_builder", "target": "export", "label": ""},
]


def _max_steps(state: EvaluationState) -> int:
    return int((state.get("config") or {}).get("max_steps", settings.max_workflow_steps))


def _guard_tripped(state: EvaluationState) -> bool:
    meta = state.get("execution_metadata") or {}
    return int(meta.get("steps", 0)) >= _max_steps(state)


def route_dispatch(state: EvaluationState) -> Literal["critic", "dataset_builder"]:
    if _guard_tripped(state) or state.get("stop_requested"):
        return "dataset_builder"
    return "critic" if state.get("current_sample") else "dataset_builder"


def route_critic(
    state: EvaluationState,
) -> Literal["approval", "refiner", "human_gate", "fail_sample"]:
    target = str(state.get("resume_at") or "fail_sample")
    if target == "refiner" and _guard_tripped(state):
        return "fail_sample"
    if target in ("approval", "refiner", "human_gate", "fail_sample"):
        return target  # type: ignore[return-value]
    return "fail_sample"


def route_refiner(state: EvaluationState) -> Literal["critic", "fail_sample"]:
    if _guard_tripped(state):
        return "fail_sample"
    return "fail_sample" if state.get("resume_at") == "fail_sample" else "critic"


def build_graph() -> Any:
    g: StateGraph = StateGraph(EvaluationState)
    for name, fn in NODES.items():
        g.add_node(name, fn)

    g.set_entry_point("planner")
    g.add_edge("planner", "generator")
    g.add_edge("generator", "dispatch")
    g.add_conditional_edges(
        "dispatch", route_dispatch, {"critic": "critic", "dataset_builder": "dataset_builder"}
    )
    g.add_conditional_edges(
        "critic",
        route_critic,
        {
            "approval": "approval",
            "refiner": "refiner",
            "human_gate": "human_gate",
            "fail_sample": "fail_sample",
        },
    )
    g.add_conditional_edges(
        "refiner", route_refiner, {"critic": "critic", "fail_sample": "fail_sample"}
    )
    g.add_edge("approval", "dispatch")
    g.add_edge("human_gate", "dispatch")
    g.add_edge("fail_sample", "dispatch")
    g.add_edge("dataset_builder", "export")
    g.add_edge("export", END)
    return g.compile()


_compiled: Any | None = None


def get_graph() -> Any:
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def graph_topology() -> dict[str, Any]:
    """Serialisable topology for the visual workflow builder (§14)."""
    descriptions = {
        "planner": "Turns the objective into an executable dataset plan.",
        "generator": "Produces structured synthetic samples with metadata.",
        "critic": "Scores each sample against the active SOP (1..N judges).",
        "refiner": "Repairs rejected samples using evaluator feedback.",
        "approval": "Final schema, duplicate, threshold and SOP gate.",
        "human_gate": "Routes borderline / disputed samples to human review.",
        "fail_sample": "Terminal state for samples that exhausted retries.",
        "dataset_builder": "Transforms approved samples into dataset rows.",
        "export": "Serialises and persists dataset artifacts.",
        "dispatch": "Queue scheduler — the single re-entry point of the loop.",
    }
    return {
        "nodes": [
            {
                "id": name,
                "label": name.replace("_", " ").title(),
                "description": descriptions.get(name, ""),
            }
            for name in NODES
        ],
        "edges": GRAPH_EDGES,
    }
