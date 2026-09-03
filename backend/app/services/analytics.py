"""Analytics, reliability and cost aggregation (§13, §17, §19, §25)."""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentRun, Dataset, Evaluation, Sample, Workflow, WorkflowRun
from app.models.enums import AgentStatus, RunStatus, SampleStatus

DIMENSIONS = ["correctness", "relevance", "completeness", "instruction_following", "safety"]
AGENTS = ["planner", "generator", "evaluator", "refiner", "approval", "dataset_builder"]


def _scope(stmt, run_id: uuid.UUID | None, col):  # type: ignore[no-untyped-def]
    return stmt.where(col == run_id) if run_id else stmt


def dashboard(db: Session, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    runs = db.execute(_scope(select(WorkflowRun), run_id, WorkflowRun.id)).scalars().all()
    samples = db.execute(_scope(select(Sample), run_id, Sample.run_id)).scalars().all()
    consensus = (
        db.execute(
            _scope(
                select(Evaluation).where(Evaluation.is_consensus.is_(True)),
                run_id,
                Evaluation.run_id,
            )
        )
        .scalars()
        .all()
    )
    agent_runs = db.execute(_scope(select(AgentRun), run_id, AgentRun.run_id)).scalars().all()

    scores = [e.overall_score for e in consensus]
    eval_latencies = [a.latency_ms for a in agent_runs if a.agent == "evaluator"]
    approved = [
        s for s in samples if s.status in (SampleStatus.AUTO_APPROVED, SampleStatus.HUMAN_APPROVED)
    ]
    rejected = [
        s for s in samples if s.status in (SampleStatus.AUTO_REJECTED, SampleStatus.HUMAN_REJECTED)
    ]

    total_cost = sum(r.total_cost_usd for r in runs)
    return {
        "total_workflows": db.execute(select(func.count()).select_from(Workflow)).scalar() or 0,
        "total_runs": len(runs),
        "running": sum(1 for r in runs if r.status == RunStatus.RUNNING),
        "completed": sum(1 for r in runs if r.status == RunStatus.COMPLETED),
        "failed": sum(1 for r in runs if r.status == RunStatus.FAILED),
        "stopped": sum(1 for r in runs if r.status == RunStatus.STOPPED),
        "samples_generated": len(samples),
        "samples_approved": len(approved),
        "samples_rejected": len(rejected),
        "samples_needs_review": sum(1 for s in samples if s.status == SampleStatus.NEEDS_REVIEW),
        "samples_failed": sum(1 for s in samples if s.status == SampleStatus.FAILED),
        "avg_quality_score": round(statistics.fmean(scores), 2) if scores else 0.0,
        "median_quality_score": round(statistics.median(scores), 2) if scores else 0.0,
        "avg_evaluation_latency_ms": round(statistics.fmean(eval_latencies))
        if eval_latencies
        else 0,
        "avg_retry_count": round(statistics.fmean([s.retry_count for s in samples]), 2)
        if samples
        else 0.0,
        "total_tokens": sum(r.total_input_tokens + r.total_output_tokens for r in runs),
        "total_input_tokens": sum(r.total_input_tokens for r in runs),
        "total_output_tokens": sum(r.total_output_tokens for r in runs),
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_per_sample": round(total_cost / len(samples), 6) if samples else 0.0,
        "datasets": db.execute(select(func.count()).select_from(Dataset)).scalar() or 0,
    }


def charts(db: Session, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    consensus = (
        db.execute(
            _scope(
                select(Evaluation).where(Evaluation.is_consensus.is_(True)),
                run_id,
                Evaluation.run_id,
            ).order_by(Evaluation.created_at)
        )
        .scalars()
        .all()
    )
    agent_runs = db.execute(_scope(select(AgentRun), run_id, AgentRun.run_id)).scalars().all()

    buckets = [f"{i}-{i + 9}" for i in range(0, 100, 10)]
    dist = Counter()
    for e in consensus:
        idx = min(9, int(e.overall_score // 10))
        dist[buckets[idx]] += 1

    by_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for a in agent_runs:
        by_agent[a.agent].append(a)

    return {
        "score_distribution": [{"bucket": b, "count": dist.get(b, 0)} for b in buckets],
        "pass_fail": [
            {"name": "Passed", "value": sum(1 for e in consensus if e.approved)},
            {"name": "Failed", "value": sum(1 for e in consensus if not e.approved)},
        ],
        "agent_execution_time": [
            {
                "agent": agent,
                "avg_ms": round(statistics.fmean([a.latency_ms for a in items])) if items else 0,
                "p95_ms": (
                    sorted(a.latency_ms for a in items)[int(len(items) * 0.95) - 1]
                    if len(items) > 1
                    else (items[0].latency_ms if items else 0)
                ),
                "calls": len(items),
            }
            for agent, items in sorted(by_agent.items())
        ],
        "token_usage": [
            {
                "agent": agent,
                "input_tokens": sum(a.input_tokens for a in items),
                "output_tokens": sum(a.output_tokens for a in items),
            }
            for agent, items in sorted(by_agent.items())
        ],
        "cost_by_agent": [
            {"agent": agent, "cost_usd": round(sum(a.cost_usd for a in items), 6)}
            for agent, items in sorted(by_agent.items())
        ],
        "scores_over_time": [
            {
                "index": i + 1,
                "score": e.overall_score,
                "approved": e.approved,
                "attempt": e.attempt,
                "ts": e.created_at.isoformat(),
            }
            for i, e in enumerate(consensus)
        ],
    }


def evaluation_analytics(db: Session, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    consensus = (
        db.execute(
            _scope(
                select(Evaluation).where(Evaluation.is_consensus.is_(True)),
                run_id,
                Evaluation.run_id,
            )
        )
        .scalars()
        .all()
    )
    samples = db.execute(_scope(select(Sample), run_id, Sample.run_id)).scalars().all()
    agent_runs = db.execute(_scope(select(AgentRun), run_id, AgentRun.run_id)).scalars().all()

    scores = [e.overall_score for e in consensus]
    total = len(consensus) or 1
    passes = sum(1 for e in consensus if e.approved)

    # per-criterion pass rate: dimension score >= 8/10 counts as a pass
    criterion_rates = {}
    for dim in DIMENSIONS:
        vals = [float((e.scores or {}).get(dim, 0)) for e in consensus]
        criterion_rates[dim] = (
            round(100 * sum(1 for v in vals if v >= 8) / len(vals), 1) if vals else 0.0
        )

    refined = [s for s in samples if s.retry_count > 0]
    refined_ok = [
        s for s in refined if s.status in (SampleStatus.AUTO_APPROVED, SampleStatus.HUMAN_APPROVED)
    ]
    schema_failures = sum(
        1 for a in agent_runs if a.error_type in ("SCHEMA_VIOLATION", "INVALID_JSON")
    )
    disagreements = [e for e in consensus if e.agreement_rate < 1.0]

    return {
        "pass_rate": round(100 * passes / total, 2),
        "failure_rate": round(100 * (total - passes) / total, 2),
        "average_score": round(statistics.fmean(scores), 2) if scores else 0.0,
        "median_score": round(statistics.median(scores), 2) if scores else 0.0,
        "stdev_score": round(statistics.pstdev(scores), 2) if len(scores) > 1 else 0.0,
        "score_distribution": charts(db, run_id)["score_distribution"],
        "average_retry_count": round(statistics.fmean([s.retry_count for s in samples]), 2)
        if samples
        else 0.0,
        "refinement_attempts": len(refined),
        "refinement_success_rate": round(100 * len(refined_ok) / len(refined), 2)
        if refined
        else 0.0,
        "hallucination_rate": round(
            100 * sum(1 for e in consensus if e.hallucination_risk in ("medium", "high")) / total, 2
        ),
        "schema_failure_rate": round(100 * schema_failures / max(1, len(agent_runs)), 2),
        "judge_disagreement_rate": round(100 * len(disagreements) / total, 2),
        "criteria_pass_rates": criterion_rates,
        "top_failure_criteria": _top_failures(consensus),
        "human_review_pending": sum(1 for s in samples if s.status == SampleStatus.NEEDS_REVIEW),
    }


def _top_failures(consensus: list[Evaluation]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    severity: dict[str, Counter[str]] = defaultdict(Counter)
    for e in consensus:
        for issue in e.issues or []:
            crit = str(issue.get("criterion", "unknown"))
            counter[crit] += 1
            severity[crit][str(issue.get("severity", "minor"))] += 1
    return [
        {"criterion": c, "failures": n, "severity_breakdown": dict(severity[c])}
        for c, n in counter.most_common(8)
    ]


def reliability(db: Session, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    agent_runs = db.execute(_scope(select(AgentRun), run_id, AgentRun.run_id)).scalars().all()
    runs = db.execute(_scope(select(WorkflowRun), run_id, WorkflowRun.id)).scalars().all()

    per_agent = []
    by_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for a in agent_runs:
        by_agent[a.agent].append(a)
    for agent in AGENTS:
        items = by_agent.get(agent, [])
        ok = sum(1 for a in items if a.status == AgentStatus.SUCCESS)
        degraded = sum(1 for a in items if a.status == AgentStatus.DEGRADED)
        failed = sum(1 for a in items if a.status == AgentStatus.FAILED)
        total = len(items)
        per_agent.append(
            {
                "agent": agent,
                "calls": total,
                "success": ok,
                "degraded": degraded,
                "failed": failed,
                "reliability": round(100 * (ok + degraded * 0.5) / total, 2) if total else 100.0,
            }
        )

    error_counter: Counter[str] = Counter()
    for a in agent_runs:
        if a.error_type:
            error_counter[a.error_type] += 1

    finished = [
        r for r in runs if r.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPED)
    ]
    workflow_reliability = (
        round(100 * sum(1 for r in finished if r.status == RunStatus.COMPLETED) / len(finished), 2)
        if finished
        else 100.0
    )

    chains: list[dict[str, Any]] = []
    for r in runs:
        meta = (r.state or {}).get("execution_metadata") or {}
        chain = meta.get("failure_chain") or []
        if chain:
            chains.append(
                {
                    "run_id": str(r.id),
                    "status": r.status,
                    "chain": _propagation(chain, r),
                }
            )

    return {
        "workflow_reliability": workflow_reliability,
        "agents": per_agent,
        "error_breakdown": [{"error": k, "count": v} for k, v in error_counter.most_common()],
        "retry_frequency": round(statistics.fmean([a.attempt for a in agent_runs]), 2)
        if agent_runs
        else 1.0,
        "invalid_json_errors": error_counter.get("INVALID_JSON", 0),
        "schema_violations": error_counter.get("SCHEMA_VIOLATION", 0),
        "timeouts": error_counter.get("LLM_TIMEOUT", 0),
        "provider_errors": error_counter.get("LLM_PROVIDER_ERROR", 0),
        "interrupted_runs": sum(1 for r in runs if r.status == RunStatus.STOPPED),
        "loop_guard_trips": sum(
            1
            for r in runs
            if int(((r.state or {}).get("execution_metadata") or {}).get("steps", 0))
            >= int((r.config_snapshot or {}).get("max_steps", 10**9))
        ),
        "failure_propagation": chains[:20],
    }


def _propagation(chain: list[dict[str, Any]], run: WorkflowRun) -> list[str]:
    """Human-readable failure propagation path (§19)."""
    steps: list[str] = []
    for item in chain[-6:]:
        agent = item.get("agent", "?")
        err = item.get("error", "?")
        steps.append(f"{agent} failure ({err})")
    if run.status == RunStatus.FAILED:
        steps += ["workflow halted", "dataset generation blocked"]
    elif chain:
        steps += ["retry / fallback engaged", "workflow delayed", "dataset generation delayed"]
    return steps


def cost_report(db: Session, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    agent_runs = db.execute(_scope(select(AgentRun), run_id, AgentRun.run_id)).scalars().all()
    samples = db.execute(_scope(select(Sample), run_id, Sample.run_id)).scalars().all()
    total = sum(a.cost_usd for a in agent_runs)
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
    )
    for a in agent_runs:
        m = by_model[a.model]
        m["input_tokens"] += a.input_tokens
        m["output_tokens"] += a.output_tokens
        m["cost_usd"] = round(m["cost_usd"] + a.cost_usd, 8)
        m["calls"] += 1
    return {
        "total_cost_usd": round(total, 6),
        "input_tokens": sum(a.input_tokens for a in agent_runs),
        "output_tokens": sum(a.output_tokens for a in agent_runs),
        "total_tokens": sum(a.input_tokens + a.output_tokens for a in agent_runs),
        "avg_cost_per_sample": round(total / len(samples), 6) if samples else 0.0,
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
    }
