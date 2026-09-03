"""LangGraph state definition (§7). Fully JSON-serialisable → DB checkpoint."""

from __future__ import annotations

from typing import Any, TypedDict


class EvaluationState(TypedDict, total=False):
    # inputs
    run_id: str
    task: str
    sop: dict[str, Any]
    config: dict[str, Any]

    # planning / generation
    plan: dict[str, Any]
    generated_samples: list[dict[str, Any]]
    queue: list[str]  # sample_ids still to process

    # per-sample working set
    current_sample: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    consensus: dict[str, Any] | None
    feedback: str | None
    retry_count: int

    # buckets
    approved_samples: list[dict[str, Any]]
    rejected_samples: list[dict[str, Any]]
    failed_samples: list[dict[str, Any]]
    review_samples: list[dict[str, Any]]
    seen_hashes: list[str]

    # outputs
    dataset: dict[str, Any] | None

    # control / observability
    resume_at: str
    done: bool
    stop_requested: bool
    execution_metadata: dict[str, Any]


def new_state(
    *,
    run_id: str,
    task: str,
    sop: dict[str, Any],
    config: dict[str, Any],
) -> EvaluationState:
    return EvaluationState(
        run_id=run_id,
        task=task,
        sop=sop,
        config=config,
        plan={},
        generated_samples=[],
        queue=[],
        current_sample=None,
        evaluation=None,
        consensus=None,
        feedback=None,
        retry_count=0,
        approved_samples=[],
        rejected_samples=[],
        failed_samples=[],
        review_samples=[],
        seen_hashes=[],
        dataset=None,
        resume_at="planner",
        done=False,
        stop_requested=False,
        execution_metadata={
            "steps": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "agent_failures": {},
            "failure_chain": [],
            "latency_ms": 0,
            "node_history": [],
        },
    )


def bump(meta: dict[str, Any], telemetry: Any) -> None:
    meta["input_tokens"] = meta.get("input_tokens", 0) + getattr(telemetry, "input_tokens", 0)
    meta["output_tokens"] = meta.get("output_tokens", 0) + getattr(telemetry, "output_tokens", 0)
    meta["cost_usd"] = round(
        meta.get("cost_usd", 0.0) + float(getattr(telemetry, "cost_usd", 0.0)), 8
    )
    meta["latency_ms"] = meta.get("latency_ms", 0) + int(getattr(telemetry, "latency_ms", 0))
