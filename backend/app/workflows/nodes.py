"""LangGraph node implementations (§7).

Every node is a pure `state -> partial state` async function. Nodes never touch
the database: side effects are emitted through the `AgentContext.record` sink and
the `emit` event callback supplied in `config["_runtime"]`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents import (
    AgentContext,
    ApprovalAgent,
    DatasetBuilderAgent,
    EvaluatorAgent,
    GeneratorAgent,
    PlannerAgent,
    RefinerAgent,
    attach_metadata,
    content_hash,
)
from app.core.config import settings
from app.core.errors import AuraError, BudgetExceededError
from app.core.logging import get_logger
from app.models.enums import EventType, SampleStatus
from app.workflows.state import EvaluationState, bump

log = get_logger(__name__)

Emit = Callable[[str, str, dict[str, Any]], None]


class Runtime:
    """Side-effect hooks injected by the executor (kept out of the graph state)."""

    def __init__(self, emit: Emit, record: Any, sample_sink: Any) -> None:
        self.emit = emit
        self.record = record
        self.sample_sink = sample_sink


_RUNTIMES: dict[str, Runtime] = {}


def register_runtime(run_id: str, runtime: Runtime) -> None:
    _RUNTIMES[run_id] = runtime


def unregister_runtime(run_id: str) -> None:
    _RUNTIMES.pop(run_id, None)


def _rt(state: EvaluationState) -> Runtime:
    rid = state.get("run_id", "")
    rt = _RUNTIMES.get(rid)
    if rt is None:  # tests / dry runs
        rt = Runtime(lambda *_a, **_k: None, lambda _t: None, lambda *_a, **_k: None)
    return rt


def _ctx(state: EvaluationState) -> AgentContext:
    rt = _rt(state)
    return AgentContext(
        config=dict(state.get("config") or {}),
        sop=dict(state.get("sop") or {}),
        record=rt.record,
    )


def _note_failure(meta: dict[str, Any], agent: str, error: str) -> None:
    failures = meta.setdefault("agent_failures", {})
    failures[agent] = int(failures.get(agent, 0)) + 1
    chain = meta.setdefault("failure_chain", [])
    chain.append({"agent": agent, "error": error})
    del chain[:-50]


def _budget_guard(state: EvaluationState) -> None:
    meta = state.get("execution_metadata") or {}
    cap = float((state.get("config") or {}).get("max_cost_usd", settings.max_cost_usd_per_run))
    if cap and float(meta.get("cost_usd", 0)) > cap:
        raise BudgetExceededError(
            f"run exceeded the configured cost cap of ${cap}", spent=meta.get("cost_usd")
        )


# --- nodes --------------------------------------------------------------
async def planner_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    cfg = dict(state.get("config") or {})
    count = int(cfg.get("sample_count", 6))
    agent = PlannerAgent(_ctx(state))
    rt.emit(EventType.AGENT_STARTED, "Planner started", {"agent": "planner"})
    if not cfg.get("use_planner", True):
        plan = agent.fallback(state.get("task", ""), count, "planner disabled by config")
    else:
        try:
            res = await agent.run(state.get("task", ""), count)
            bump(meta, res.telemetry)
            plan = res.data
        except AuraError as exc:
            _note_failure(meta, "planner", exc.code)
            plan = agent.fallback(state.get("task", ""), count, exc.code)
            rt.emit(
                EventType.AGENT_FAILED,
                f"Planner degraded ({exc.code}); using fallback plan",
                {"agent": "planner", "error": exc.code},
            )
    rt.emit(
        EventType.AGENT_COMPLETED,
        f"Planner produced a plan for {plan.sample_count} samples",
        {"agent": "planner", "plan": plan.model_dump(mode="json")},
    )
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("planner")
    return {
        "plan": plan.model_dump(mode="json"),
        "execution_metadata": meta,
        "resume_at": "generator",
    }


async def generator_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    cfg = dict(state.get("config") or {})
    plan = dict(state.get("plan") or {})
    target = int(plan.get("sample_count") or cfg.get("sample_count", 6))
    batch = max(1, min(int(cfg.get("batch_size", 6)), 25))
    samples: list[dict[str, Any]] = list(state.get("generated_samples") or [])
    agent = GeneratorAgent(_ctx(state))
    rt.emit(EventType.AGENT_STARTED, "Generator started", {"agent": "generator", "target": target})

    offset = len(samples)
    guard = 0
    while len(samples) < target and guard < target * 3:
        guard += 1
        want = min(batch, target - len(samples))
        try:
            res = await agent.run(
                objective=plan.get("objective") or state.get("task", ""),
                count=want,
                offset=offset,
                required_fields=plan.get("required_fields"),
                existing_inputs=[s.get("input", "") for s in samples],
            )
            bump(meta, res.telemetry)
            for s in res.data.samples:
                if len(samples) >= target:
                    break
                key = f"sample_{len(samples) + 1:03d}"
                payload = attach_metadata(
                    s,
                    sample_key=key,
                    run_id=state.get("run_id", ""),
                    plan_objective=plan.get("objective", ""),
                )
                samples.append(payload)
                rt.sample_sink(payload, SampleStatus.PENDING)
            offset += want
        except AuraError as exc:
            _note_failure(meta, "generator", exc.code)
            rt.emit(
                EventType.AGENT_FAILED,
                f"Generator batch failed ({exc.code}); retrying",
                {"agent": "generator", "error": exc.code},
            )
            offset += want
            if guard >= target * 2 and not samples:
                raise
    rt.emit(
        EventType.AGENT_COMPLETED,
        f"Generator produced {len(samples)} samples",
        {"agent": "generator", "count": len(samples)},
    )
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("generator")
    return {
        "generated_samples": samples,
        "queue": [s["sample_id"] for s in samples],
        "execution_metadata": meta,
        "resume_at": "dispatch",
    }


async def dispatch_node(state: EvaluationState) -> dict[str, Any]:
    """Single re-entry point: pops the next sample, guaranteeing termination."""
    meta = dict(state.get("execution_metadata") or {})
    queue = list(state.get("queue") or [])
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("dispatch")
    if state.get("stop_requested"):
        return {"execution_metadata": meta, "resume_at": "dataset_builder", "queue": []}
    if not queue:
        return {"execution_metadata": meta, "current_sample": None, "resume_at": "dataset_builder"}
    next_id = queue.pop(0)
    sample = next(
        (s for s in state.get("generated_samples") or [] if s.get("sample_id") == next_id), None
    )
    if sample is None:
        return {"queue": queue, "execution_metadata": meta, "resume_at": "dispatch"}
    _rt(state).emit(
        EventType.SAMPLE_EVALUATING,
        f"Evaluating {next_id} ({len(state.get('generated_samples') or []) - len(queue)}"
        f"/{len(state.get('generated_samples') or [])})",
        {"sample_id": next_id},
    )
    return {
        "queue": queue,
        "current_sample": sample,
        "evaluation": None,
        "consensus": None,
        "feedback": None,
        "retry_count": 0,
        "execution_metadata": meta,
        "resume_at": "critic",
    }


async def critic_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    sample = state.get("current_sample") or {}
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("critic")
    agent = EvaluatorAgent(_ctx(state))
    try:
        consensus = await agent.run(sample)
    except AuraError as exc:
        _note_failure(meta, "evaluator", exc.code)
        rt.emit(
            EventType.AGENT_FAILED,
            f"Evaluator failed on {sample.get('sample_id')} ({exc.code})",
            {"agent": "evaluator", "error": exc.code, "sample_id": sample.get("sample_id")},
        )
        # Evaluator unavailable → the sample cannot be judged → route to human review.
        return {
            "evaluation": None,
            "feedback": exc.code,
            "execution_metadata": meta,
            "resume_at": "human_gate",
        }
    _budget_guard({**state, "execution_metadata": meta})
    ev = consensus.final.model_dump(mode="json")
    ev["variance"] = consensus.variance
    ev["agreement_rate"] = consensus.agreement_rate
    ev["judges"] = [v.model_dump(mode="json") for v in consensus.verdicts]
    ev["sample_id"] = sample.get("sample_id")
    ev["attempt"] = int(state.get("retry_count", 0)) + 1

    cfg = dict(state.get("config") or {})
    low = float(cfg.get("borderline_low", settings.borderline_low))
    high = float(cfg.get("borderline_high", settings.borderline_high))
    score = consensus.mean_score
    borderline = low <= score < high
    human_enabled = bool(cfg.get("human_review_enabled", True))
    retries_left = int(state.get("retry_count", 0)) < int(
        cfg.get("max_retries", settings.max_retries)
    )

    # Routing priority (§4/§18/§20):
    #   1. passed          → approval
    #   2. judges disagree → human review (a refiner cannot resolve a dispute)
    #   3. retries left    → refinement, then back to the critic
    #   4. borderline      → human review rather than a hard reject
    #   5. otherwise       → terminal failure
    if consensus.approved:
        nxt = "approval"
    elif consensus.disagreement and human_enabled:
        nxt = "human_gate"
    elif retries_left:
        nxt = "refiner"
    elif borderline and human_enabled:
        nxt = "human_gate"
    else:
        nxt = "fail_sample"

    rt.emit(
        EventType.SAMPLE_APPROVED if consensus.approved else EventType.SAMPLE_REJECTED,
        f"{sample.get('sample_id')} scored {score} — "
        + ("passed critic" if consensus.approved else f"rejected → {nxt}"),
        {
            "sample_id": sample.get("sample_id"),
            "score": score,
            "approved": consensus.approved,
            "attempt": ev["attempt"],
        },
    )
    return {
        "evaluation": ev,
        "consensus": consensus.model_dump(mode="json"),
        "feedback": consensus.final.reasoning_summary,
        "execution_metadata": meta,
        "resume_at": nxt,
    }


async def refiner_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("refiner")
    sample = dict(state.get("current_sample") or {})
    attempt = int(state.get("retry_count", 0)) + 1
    rt.emit(
        EventType.REFINEMENT_STARTED,
        f"Refinement attempt {attempt} for {sample.get('sample_id')}",
        {"sample_id": sample.get("sample_id"), "attempt": attempt},
    )
    agent = RefinerAgent(_ctx(state))
    try:
        res = await agent.run(
            sample=sample, evaluation=state.get("evaluation") or {}, attempt=attempt
        )
        bump(meta, res.telemetry)
        improved = {**sample, **res.data.sample.model_dump(mode="json")}
        improved["sample_id"] = sample.get("sample_id")
        improved.setdefault("metadata", {})
        improved["metadata"] = {
            **(sample.get("metadata") or {}),
            "source": "refiner",
            "refined_attempt": attempt,
        }
        rt.sample_sink(
            improved,
            SampleStatus.IN_PROGRESS,
            version_source="refiner",
            feedback="; ".join(res.data.problems_identified)[:1000],
        )
        samples = [
            improved if s.get("sample_id") == improved.get("sample_id") else s
            for s in state.get("generated_samples") or []
        ]
        return {
            "current_sample": improved,
            "generated_samples": samples,
            "retry_count": attempt,
            "execution_metadata": meta,
            "resume_at": "critic",
        }
    except AuraError as exc:
        _note_failure(meta, "refiner", exc.code)
        rt.emit(
            EventType.AGENT_FAILED,
            f"Refiner failed ({exc.code})",
            {"agent": "refiner", "error": exc.code, "sample_id": sample.get("sample_id")},
        )
        cfg = dict(state.get("config") or {})
        exhausted = attempt >= int(cfg.get("max_retries", settings.max_retries))
        return {
            "retry_count": attempt,
            "execution_metadata": meta,
            "resume_at": "fail_sample" if exhausted else "critic",
        }


async def approval_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("approval")
    sample = dict(state.get("current_sample") or {})
    evaluation = dict(state.get("evaluation") or {})
    seen = set(state.get("seen_hashes") or [])
    plan = dict(state.get("plan") or {})
    agent = ApprovalAgent(_ctx(state))
    report = agent.run(
        sample=sample,
        evaluation=evaluation,
        seen_hashes=seen,
        required_fields=plan.get("required_fields"),
    )
    approved = list(state.get("approved_samples") or [])
    rejected = list(state.get("rejected_samples") or [])
    failed = list(state.get("failed_samples") or [])
    entry = {
        "sample": sample,
        "evaluation": evaluation,
        "approval": report.model_dump(mode="json"),
        "retry_count": int(state.get("retry_count", 0)),
    }
    if report.approved:
        approved.append(entry)
        seen.add(content_hash(sample))
        rt.sample_sink(
            sample,
            SampleStatus.AUTO_APPROVED,
            approval=entry["approval"],
            score=evaluation.get("overall_score"),
        )
        rt.emit(
            EventType.SAMPLE_APPROVED,
            f"{sample.get('sample_id')} approved",
            {"sample_id": sample.get("sample_id"), "score": evaluation.get("overall_score")},
        )
        nxt = "dispatch"
    else:
        failed.append({**entry, "reason": "; ".join(report.reasons)})
        rt.sample_sink(
            sample,
            SampleStatus.FAILED,
            approval=entry["approval"],
            reason="; ".join(report.reasons)[:500],
        )
        rt.emit(
            EventType.SAMPLE_FAILED,
            f"{sample.get('sample_id')} blocked by approval agent",
            {"sample_id": sample.get("sample_id"), "reasons": report.reasons},
        )
        nxt = "dispatch"
    return {
        "approved_samples": approved,
        "rejected_samples": rejected,
        "failed_samples": failed,
        "seen_hashes": sorted(seen),
        "execution_metadata": meta,
        "resume_at": nxt,
    }


async def human_gate_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("human_gate")
    sample = dict(state.get("current_sample") or {})
    evaluation = dict(state.get("evaluation") or {})
    review = list(state.get("review_samples") or [])
    review.append(
        {
            "sample": sample,
            "evaluation": evaluation,
            "retry_count": int(state.get("retry_count", 0)),
        }
    )
    rt.sample_sink(
        sample,
        SampleStatus.NEEDS_REVIEW,
        score=evaluation.get("overall_score"),
        reason="borderline score or judge disagreement",
    )
    rt.emit(
        EventType.SAMPLE_NEEDS_REVIEW,
        f"{sample.get('sample_id')} routed to human review",
        {"sample_id": sample.get("sample_id"), "score": evaluation.get("overall_score")},
    )
    return {"review_samples": review, "execution_metadata": meta, "resume_at": "dispatch"}


async def fail_sample_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("fail_sample")
    sample = dict(state.get("current_sample") or {})
    evaluation = dict(state.get("evaluation") or {})
    rejected = list(state.get("rejected_samples") or [])
    reason = (
        f"rejected after {state.get('retry_count', 0)} refinement attempts "
        f"(final score {evaluation.get('overall_score', 0)})"
    )
    rejected.append({"sample": sample, "evaluation": evaluation, "reason": reason})
    rt.sample_sink(
        sample, SampleStatus.AUTO_REJECTED, score=evaluation.get("overall_score"), reason=reason
    )
    rt.emit(
        EventType.SAMPLE_REJECTED,
        f"{sample.get('sample_id')} failed — {reason}",
        {"sample_id": sample.get("sample_id"), "reason": reason},
    )
    return {"rejected_samples": rejected, "execution_metadata": meta, "resume_at": "dispatch"}


async def dataset_builder_node(state: EvaluationState) -> dict[str, Any]:
    rt = _rt(state)
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("dataset_builder")
    cfg = dict(state.get("config") or {})
    approved = list(state.get("approved_samples") or [])
    items = [(e["sample"], e.get("evaluation")) for e in approved]
    agent = DatasetBuilderAgent(_ctx(state))
    rt.emit(
        EventType.AGENT_STARTED,
        "Dataset builder started",
        {"agent": "dataset_builder", "rows": len(items)},
    )
    dataset = agent.run(
        items=items,
        style=str(cfg.get("dataset_style", "instruction")),
        formats=list(cfg.get("dataset_formats") or ["jsonl"]),
    )
    rt.emit(
        EventType.DATASET_BUILT,
        f"Dataset built with {dataset['row_count']} rows",
        {
            "row_count": dataset["row_count"],
            "style": dataset["style"],
            "formats": dataset["formats"],
        },
    )
    return {"dataset": dataset, "execution_metadata": meta, "resume_at": "export"}


async def export_node(state: EvaluationState) -> dict[str, Any]:
    meta = dict(state.get("execution_metadata") or {})
    meta["steps"] = int(meta.get("steps", 0)) + 1
    meta.setdefault("node_history", []).append("export")
    return {"execution_metadata": meta, "resume_at": "done", "done": True}
