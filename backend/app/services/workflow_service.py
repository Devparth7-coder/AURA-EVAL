"""Workflow lifecycle orchestration: the only layer that joins DB + graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.database.session import session_scope
from app.models import SOP, Dataset, DatasetVersion, Workflow, WorkflowRun
from app.models.enums import EventType, RunStatus
from app.services.queue import get_queue
from app.services.sop_engine import default_sop, normalise_sop
from app.services.storage import get_storage
from app.workflows.executor import StepExecutor, initialise_state

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def sop_snapshot(db: Session, sop_id: uuid.UUID | None) -> dict[str, Any]:
    if not sop_id:
        return default_sop()
    sop = db.get(SOP, sop_id)
    if not sop or not sop.versions:
        return default_sop()
    current = next((v for v in sop.versions if v.version == sop.current_version), sop.versions[-1])
    return normalise_sop(
        {
            "name": sop.name,
            "version": current.version,
            "rules": current.rules,
            "scoring": current.scoring,
            "threshold": current.threshold,
        }
    )


def create_run(db: Session, workflow: Workflow, *, sample_count: int | None = None) -> WorkflowRun:
    active = (
        db.execute(
            select(WorkflowRun).where(
                WorkflowRun.workflow_id == workflow.id,
                WorkflowRun.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
            )
        )
        .scalars()
        .first()
    )
    if active:
        raise ConflictError("workflow already has an active run", run_id=str(active.id))

    config = dict(workflow.config or {})
    if sample_count:
        config["sample_count"] = min(int(sample_count), settings.max_samples_per_run)
    config.setdefault("max_steps", settings.max_workflow_steps)
    sop = sop_snapshot(db, workflow.sop_id)

    run = WorkflowRun(
        workflow_id=workflow.id,
        status=RunStatus.RUNNING,
        config_snapshot=config,
        sop_snapshot=sop,
        started_at=_now(),
    )
    db.add(run)
    db.flush()
    state = initialise_state(run, task=workflow.objective or workflow.name, sop=sop, config=config)
    run.state = dict(state)
    executor = StepExecutor(db, run)
    executor.emit(
        EventType.RUN_STARTED,
        f"Run started for workflow '{workflow.name}' ({config.get('sample_count')} samples)",
        {"config": {k: v for k, v in config.items() if k != "prompt_versions"}},
    )
    db.commit()
    db.refresh(run)
    return run


async def execute_run(run_id: uuid.UUID, slice_steps: int | None = None) -> None:
    """Background entry point. Opens its own session (serverless-safe)."""
    with session_scope() as db:
        run = db.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError("run not found", run_id=str(run_id))
        executor = StepExecutor(db, run)
        await executor.run_to_completion(slice_steps)
        await persist_datasets(db, run)


async def enqueue_run(run: WorkflowRun) -> str:
    q = get_queue()
    q.register("execute_run", _queue_handler)
    return await q.enqueue("execute_run", {"run_id": str(run.id)})


async def _queue_handler(payload: dict[str, Any]) -> None:
    await execute_run(uuid.UUID(payload["run_id"]))


async def advance_run(db: Session, run: WorkflowRun, max_steps: int) -> WorkflowRun:
    """One bounded slice — the endpoint a Vercel cron / worker tick calls."""
    if run.status not in (RunStatus.RUNNING, RunStatus.PENDING, RunStatus.PAUSED):
        return run
    run.status = RunStatus.RUNNING
    executor = StepExecutor(db, run)
    await executor.advance(max_steps)
    if run.status == RunStatus.COMPLETED:
        await persist_datasets(db, run)
    db.commit()
    db.refresh(run)
    return run


async def persist_datasets(db: Session, run: WorkflowRun) -> Dataset | None:
    """Materialise the built dataset into Dataset/DatasetVersion + object storage."""
    state = run.state or {}
    built = state.get("dataset")
    if not built:
        return None
    existing = db.execute(select(Dataset).where(Dataset.run_id == run.id)).scalars().first()
    if existing:
        return existing

    workflow = db.get(Workflow, run.workflow_id)
    dataset = Dataset(
        project_id=workflow.project_id if workflow else None,
        run_id=run.id,
        name=f"{workflow.name if workflow else 'dataset'} — {str(run.id)[:8]}",
        style=str(built.get("style", "instruction")),
        row_count=int(built.get("row_count", 0)),
        dataset_metadata={
            "objective": (run.plan or {}).get("objective", ""),
            "sop": (run.sop_snapshot or {}).get("name", ""),
            "approved": run.samples_approved,
            "rejected": run.samples_rejected,
            "cost_usd": run.total_cost_usd,
        },
    )
    db.add(dataset)
    db.flush()

    from app.agents.dataset_builder import checksum, serialize

    rows = built.get("rows") or []
    storage = get_storage()
    for i, fmt in enumerate(built.get("formats") or ["jsonl"], start=1):
        payload, media = serialize(rows, fmt)
        key = f"datasets/{dataset.id}/v1.{fmt}"
        try:
            await storage.upload(key, payload, media)
        except Exception as exc:
            log.warning("dataset.upload_failed fmt=%s err=%s", fmt, type(exc).__name__)
            key = ""
        db.add(
            DatasetVersion(
                dataset_id=dataset.id,
                version=i,
                fmt=fmt,
                row_count=len(rows),
                size_bytes=len(payload),
                checksum=checksum(payload),
                storage_key=key,
                rows=rows if len(rows) <= 2000 else [],
            )
        )
    dataset.current_version = 1
    db.commit()
    db.refresh(dataset)
    return dataset


def stop_run(db: Session, run: WorkflowRun) -> WorkflowRun:
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPED):
        return run
    run.stop_requested = True
    db.commit()
    db.refresh(run)
    return run
