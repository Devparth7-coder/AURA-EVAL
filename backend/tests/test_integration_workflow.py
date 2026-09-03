"""Integration tests: full LangGraph workflow + database operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    Evaluation,
    Sample,
    SampleVersion,
    WorkflowEvent,
    WorkflowRun,
)
from app.models.enums import RunStatus, SampleStatus
from app.services import analytics
from app.services.workflow_service import create_run, persist_datasets
from app.workflows.executor import StepExecutor
from app.workflows.graph import graph_topology
from tests.conftest import make_workflow


async def _run(db: Session, workflow) -> WorkflowRun:
    run = create_run(db, workflow)
    await StepExecutor(db, run).run_to_completion()
    await persist_datasets(db, run)
    db.refresh(run)
    return run


async def test_full_workflow_completes(db: Session, workflow) -> None:
    run = await _run(db, workflow)
    assert run.status == RunStatus.COMPLETED
    assert run.samples_generated == 4
    assert (
        run.samples_approved + run.samples_rejected + run.samples_review + run.samples_failed == 4
    )
    assert run.state["dataset"]["row_count"] == run.samples_approved


async def test_workflow_persists_agent_runs_and_events(db: Session, workflow) -> None:
    run = await _run(db, workflow)
    agents = {
        a.agent for a in db.execute(select(AgentRun).where(AgentRun.run_id == run.id)).scalars()
    }
    assert {"planner", "generator", "evaluator", "dataset_builder"}.issubset(agents)
    events = list(
        db.execute(
            select(WorkflowEvent).where(WorkflowEvent.run_id == run.id).order_by(WorkflowEvent.seq)
        ).scalars()
    )
    assert events[0].type == "run.started"
    assert events[-1].type == "run.completed"
    assert [e.seq for e in events] == sorted(e.seq for e in events)


async def test_samples_and_evaluations_persisted(db: Session, workflow) -> None:
    run = await _run(db, workflow)
    samples = list(db.execute(select(Sample).where(Sample.run_id == run.id)).scalars())
    assert len(samples) == 4
    for s in samples:
        assert s.versions and s.content_hash
        assert s.status != SampleStatus.PENDING
    consensus = list(
        db.execute(
            select(Evaluation).where(Evaluation.run_id == run.id, Evaluation.is_consensus.is_(True))
        ).scalars()
    )
    assert consensus and all(0 <= e.overall_score <= 100 for e in consensus)


async def test_state_checkpoint_allows_resume(db: Session, workflow) -> None:
    """A sliced execution must reach the same terminal state as a full one."""
    run = create_run(db, workflow)
    executor = StepExecutor(db, run)
    slices = 0
    while run.status == RunStatus.RUNNING and slices < 100:
        slices += 1
        await executor.advance(max_steps=1)  # one node per invocation
        db.refresh(run)
        assert run.state.get("resume_at")  # checkpoint always present
    assert run.status == RunStatus.COMPLETED
    assert slices > 5  # genuinely resumed many times


async def test_refinement_history_recorded(db: Session, project, sop) -> None:
    wf = make_workflow(db, project, sop, sample_count=8, max_retries=2)
    run = await _run(db, wf)
    refined = [
        s
        for s in db.execute(select(Sample).where(Sample.run_id == run.id)).scalars()
        if s.retry_count > 0
    ]
    assert refined, "mock provider should force at least one refinement"
    s = refined[0]
    versions = list(
        db.execute(
            select(SampleVersion)
            .where(SampleVersion.sample_id == s.id)
            .order_by(SampleVersion.version)
        ).scalars()
    )
    assert len(versions) >= 2
    assert versions[0].source == "generator" and versions[1].source == "refiner"
    assert versions[0].outcome == "rejected"


async def test_multi_judge_workflow(db: Session, project, sop) -> None:
    wf = make_workflow(db, project, sop, judges=3, sample_count=3)
    run = await _run(db, wf)
    evals = list(db.execute(select(Evaluation).where(Evaluation.run_id == run.id)).scalars())
    judges = {e.judge_label for e in evals}
    assert {"judge_A", "judge_B", "judge_C", "consensus"}.issubset(judges)


async def test_analytics_endpoints_aggregate(db: Session, workflow) -> None:
    run = await _run(db, workflow)
    summary = analytics.dashboard(db)
    assert summary["samples_generated"] == 4
    assert summary["total_runs"] == 1
    ev = analytics.evaluation_analytics(db)
    assert 0 <= ev["pass_rate"] <= 100
    assert set(ev["criteria_pass_rates"]) == {
        "correctness",
        "relevance",
        "completeness",
        "instruction_following",
        "safety",
    }
    rel = analytics.reliability(db)
    assert rel["workflow_reliability"] == 100.0
    assert {a["agent"] for a in rel["agents"]} >= {"generator", "evaluator"}
    cost = analytics.cost_report(db)
    assert cost["total_tokens"] > 0


async def test_dataset_persisted_with_all_formats(db: Session, workflow) -> None:
    run = await _run(db, workflow)
    dataset = await persist_datasets(db, run)
    assert dataset is not None
    assert {v.fmt for v in dataset.versions} == {"jsonl", "csv"}
    assert all(v.checksum and v.size_bytes > 0 for v in dataset.versions)


def test_graph_topology_is_wellformed() -> None:
    topo = graph_topology()
    ids = {n["id"] for n in topo["nodes"]}
    assert {"planner", "generator", "critic", "refiner", "approval", "dataset_builder"} <= ids
    for edge in topo["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
