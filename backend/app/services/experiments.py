"""Experiment system (§21): run the same objective across arms and compare (§22)."""

from __future__ import annotations

import statistics
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentRun, Evaluation, Experiment, Sample, Workflow
from app.models.enums import APPROVED_STATUSES
from app.services import workflow_service
from app.services.workflow_service import execute_run

METRIC_LABELS = {
    "correctness": "Correctness",
    "relevance": "Relevance",
    "completeness": "Completeness",
    "instruction_following": "Instruction Following",
    "safety": "Safety",
}


async def run_experiment(db: Session, experiment: Experiment) -> Experiment:
    cfg = experiment.config or {}
    experiment.status = "RUNNING"
    db.commit()

    for arm in experiment.arms:
        workflow = Workflow(
            project_id=experiment.project_id,
            sop_id=uuid.UUID(cfg["sop_id"]) if cfg.get("sop_id") else None,
            name=f"[exp] {experiment.name} · {arm.label}",
            objective=cfg.get("objective", ""),
            is_archived=True,  # experiment scaffolding, hidden from the workflow list
            config={
                "sample_count": int(cfg.get("sample_count", 6)),
                "batch_size": min(6, int(cfg.get("sample_count", 6))),
                "provider": arm.provider,
                "model": arm.model,
                "judges": 1,
                "max_retries": 2,
                "human_review_enabled": False,
                "dataset_style": "evaluation",
                "dataset_formats": ["jsonl"],
                "prompt_versions": {"evaluator": arm.prompt_version},
                "mock_failure_rate": 0.0,
                "quality_bias": float((arm.metrics or {}).get("quality_bias", 0.0)),
                "domain_hint": cfg.get("domain_hint", ""),
            },
        )
        db.add(workflow)
        db.flush()
        run = workflow_service.create_run(db, workflow)
        arm.run_id = run.id
        db.commit()
        await execute_run(run.id)
        db.expire_all()
        arm.metrics = arm_metrics(db, run.id)
        db.commit()

    experiment.report = build_report(experiment)
    experiment.status = "COMPLETED"
    db.commit()
    db.refresh(experiment)
    return experiment


def arm_metrics(db: Session, run_id: uuid.UUID) -> dict[str, Any]:
    evals = list(
        db.execute(
            select(Evaluation).where(Evaluation.run_id == run_id, Evaluation.is_consensus.is_(True))
        ).scalars()
    )
    samples = list(db.execute(select(Sample).where(Sample.run_id == run_id)).scalars())
    agent_runs = list(db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalars())
    approved = [s for s in samples if s.status in APPROVED_STATUSES]

    def dim_pct(dim: str) -> float:
        vals = [float((e.scores or {}).get(dim, 0)) for e in evals]
        return round(100 * statistics.fmean(vals) / 10, 2) if vals else 0.0

    latencies = [a.latency_ms for a in agent_runs if a.agent in ("generator", "evaluator")]
    return {
        "samples": len(samples),
        "approved": len(approved),
        "pass_rate": round(100 * len(approved) / len(samples), 2) if samples else 0.0,
        "average_score": round(statistics.fmean([e.overall_score for e in evals]), 2)
        if evals
        else 0.0,
        **{k: dim_pct(k) for k in METRIC_LABELS},
        "hallucination_rate": round(
            100 * sum(1 for e in evals if e.hallucination_risk in ("medium", "high")) / len(evals),
            2,
        )
        if evals
        else 0.0,
        "latency_s": round(statistics.fmean(latencies) / 1000, 3) if latencies else 0.0,
        "cost_usd": round(sum(a.cost_usd for a in agent_runs), 6),
        "tokens": sum(a.input_tokens + a.output_tokens for a in agent_runs),
        "avg_retry_count": round(statistics.fmean([s.retry_count for s in samples]), 2)
        if samples
        else 0.0,
    }


def build_report(experiment: Experiment) -> dict[str, Any]:
    arms = [
        {
            "label": a.label,
            "provider": a.provider,
            "model": a.model,
            "prompt_version": a.prompt_version,
            "run_id": str(a.run_id) if a.run_id else None,
            "metrics": a.metrics or {},
        }
        for a in experiment.arms
    ]
    metric_keys = [
        ("average_score", "Average Score", "score"),
        ("pass_rate", "Pass Rate", "pct"),
        *[(k, v, "pct") for k, v in METRIC_LABELS.items()],
        ("hallucination_rate", "Hallucination Rate", "pct"),
        ("latency_s", "Latency", "s"),
        ("cost_usd", "Estimated Cost", "usd"),
        ("avg_retry_count", "Avg Retries", "num"),
    ]
    lower_is_better = {"hallucination_rate", "latency_s", "cost_usd", "avg_retry_count"}
    comparison = []
    for key, label, unit in metric_keys:
        values = {a["label"]: float((a["metrics"] or {}).get(key, 0)) for a in arms}
        if not values:
            continue
        winner = (min if key in lower_is_better else max)(values, key=lambda k: values[k])
        comparison.append(
            {"metric": key, "label": label, "unit": unit, "values": values, "winner": winner}
        )
    overall = {}
    for a in arms:
        wins = sum(1 for row in comparison if row["winner"] == a["label"])
        overall[a["label"]] = wins
    return {
        "arms": arms,
        "comparison": comparison,
        "wins": overall,
        "winner": max(overall, key=lambda k: overall[k]) if overall else None,
    }
