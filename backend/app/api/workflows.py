from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.core.config import settings
from app.database.session import session_scope
from app.models import AgentRun, Workflow, WorkflowEvent, WorkflowRun
from app.models.enums import RunStatus
from app.schemas.api import (
    AdvanceRequest,
    AgentRunOut,
    EventOut,
    RunOut,
    RunStartRequest,
    WorkflowCreate,
    WorkflowOut,
    WorkflowUpdate,
)
from app.services import workflow_service
from app.workflows.graph import graph_topology

router = APIRouter(tags=["workflows"])


# --- workflows ----------------------------------------------------------
@router.get("/workflows/topology")
def topology(_: Viewer) -> dict[str, Any]:
    return graph_topology()


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def create_workflow(body: WorkflowCreate, db: DB, _: Editor) -> Workflow:
    wf = Workflow(
        project_id=body.project_id,
        name=body.name,
        objective=body.objective,
        sop_id=body.sop_id,
        config=body.config.model_dump(mode="json"),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(
    db: DB, _: Viewer, page: Pagination, project_id: uuid.UUID | None = None
) -> list[Workflow]:
    stmt = (
        select(Workflow).where(Workflow.is_archived.is_(False)).order_by(Workflow.created_at.desc())
    )
    if project_id:
        stmt = stmt.where(Workflow.project_id == project_id)
    return list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: uuid.UUID, db: DB, _: Viewer) -> Workflow:
    return fetch(db, Workflow, workflow_id, "workflow")


@router.put("/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(workflow_id: uuid.UUID, body: WorkflowUpdate, db: DB, _: Editor) -> Workflow:
    wf = fetch(db, Workflow, workflow_id, "workflow")
    data = body.model_dump(exclude_none=True)
    if "config" in data:
        wf.config = body.config.model_dump(mode="json")  # type: ignore[union-attr]
        data.pop("config")
    for k, v in data.items():
        setattr(wf, k, v)
    db.commit()
    db.refresh(wf)
    return wf


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: uuid.UUID, db: DB, _: Editor) -> None:
    db.delete(fetch(db, Workflow, workflow_id, "workflow"))
    db.commit()


@router.get("/workflows/{workflow_id}/runs", response_model=list[RunOut])
def workflow_runs(workflow_id: uuid.UUID, db: DB, _: Viewer, page: Pagination) -> list[WorkflowRun]:
    return list(
        db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )


# --- execution ----------------------------------------------------------
@router.post("/workflows/{workflow_id}/run", response_model=RunOut, status_code=202)
async def run_workflow(
    workflow_id: uuid.UUID,
    db: DB,
    _: Editor,
    background: BackgroundTasks,
    body: RunStartRequest | None = None,
) -> WorkflowRun:
    """Returns the run id immediately; execution happens off the request (§40)."""
    body = body or RunStartRequest()
    wf = fetch(db, Workflow, workflow_id, "workflow")
    run = workflow_service.create_run(db, wf, sample_count=body.sample_count)
    if body.async_execution:
        if settings.queue_provider == "redis":
            await workflow_service.enqueue_run(run)
        else:
            background.add_task(workflow_service.execute_run, run.id)
    return run


@router.post("/runs/{run_id}/advance", response_model=RunOut)
async def advance_run(
    run_id: uuid.UUID, db: DB, _: Editor, body: AdvanceRequest | None = None
) -> WorkflowRun:
    """Execute one bounded slice. Safe to call from a cron tick or the UI."""
    body = body or AdvanceRequest()
    run = fetch(db, WorkflowRun, run_id, "run")
    return await workflow_service.advance_run(db, run, body.max_steps)


@router.post("/workflows/{workflow_id}/stop", response_model=RunOut)
def stop_workflow(workflow_id: uuid.UUID, db: DB, _: Editor) -> WorkflowRun:
    run = (
        db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status.in_([RunStatus.RUNNING, RunStatus.PENDING]),
            )
            .order_by(WorkflowRun.created_at.desc())
        )
        .scalars()
        .first()
    )
    if run is None:
        raise_not_found()
    return workflow_service.stop_run(db, run)


def raise_not_found() -> None:
    from app.core.errors import NotFoundError

    raise NotFoundError("no active run for this workflow")


@router.post("/runs/{run_id}/stop", response_model=RunOut)
def stop_run(run_id: uuid.UUID, db: DB, _: Editor) -> WorkflowRun:
    return workflow_service.stop_run(db, fetch(db, WorkflowRun, run_id, "run"))


# --- runs / observability ------------------------------------------------
@router.get("/runs", response_model=list[RunOut])
def list_runs(db: DB, _: Viewer, page: Pagination, status: str | None = None) -> list[WorkflowRun]:
    stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    return list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, db: DB, _: Viewer) -> WorkflowRun:
    return fetch(db, WorkflowRun, run_id, "run")


@router.get("/runs/{run_id}/status")
def run_status(run_id: uuid.UUID, db: DB, _: Viewer) -> dict[str, Any]:
    """Lightweight polling endpoint (§41 option B)."""
    run = fetch(db, WorkflowRun, run_id, "run")
    last_seq = (
        db.execute(
            select(WorkflowEvent.seq)
            .where(WorkflowEvent.run_id == run.id)
            .order_by(WorkflowEvent.seq.desc())
            .limit(1)
        ).scalar()
        or 0
    )
    state = run.state or {}
    return {
        "run_id": str(run.id),
        "status": run.status,
        "resume_at": state.get("resume_at"),
        "steps_executed": run.steps_executed,
        "queue_remaining": len(state.get("queue") or []),
        "samples_generated": run.samples_generated,
        "samples_approved": run.samples_approved,
        "samples_rejected": run.samples_rejected,
        "samples_review": run.samples_review,
        "samples_failed": run.samples_failed,
        "cost_usd": run.total_cost_usd,
        "tokens": run.total_input_tokens + run.total_output_tokens,
        "last_event_seq": last_seq,
        "error": run.error,
        "terminal": run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPED),
    }


@router.get("/runs/{run_id}/events", response_model=list[EventOut])
def run_events(
    run_id: uuid.UUID,
    db: DB,
    _: Viewer,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[WorkflowEvent]:
    return list(
        db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.run_id == run_id, WorkflowEvent.seq > after_seq)
            .order_by(WorkflowEvent.seq)
            .limit(limit)
        ).scalars()
    )


@router.get("/workflows/{workflow_id}/events", response_model=list[EventOut])
def workflow_events(
    workflow_id: uuid.UUID, db: DB, _: Viewer, after_seq: int = Query(0, ge=0)
) -> list[WorkflowEvent]:
    run = (
        db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if run is None:
        return []
    return run_events(run.id, db, _, after_seq)  # type: ignore[arg-type]


@router.get("/runs/{run_id}/stream")
async def stream_events(run_id: uuid.UUID, after_seq: int = Query(0, ge=0)) -> StreamingResponse:
    """SSE live feed (§41 option A). Bounded duration so it is serverless-safe."""

    async def gen() -> AsyncIterator[str]:
        seq = after_seq
        ticks = 0
        yield ": connected\n\n"
        while ticks < 240:  # ~2 minutes max per connection; the client reconnects
            ticks += 1
            terminal = False
            with session_scope() as db:
                rows = list(
                    db.execute(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.run_id == run_id, WorkflowEvent.seq > seq)
                        .order_by(WorkflowEvent.seq)
                        .limit(200)
                    ).scalars()
                )
                run = db.get(WorkflowRun, run_id)
                terminal = bool(run) and run.status in (
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.STOPPED,
                )
                payloads = [
                    {
                        "seq": e.seq,
                        "type": e.type,
                        "level": e.level,
                        "message": e.message,
                        "data": e.data,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in rows
                ]
            for p in payloads:
                seq = max(seq, p["seq"])
                yield f"event: workflow\ndata: {json.dumps(p)}\n\n"
            if terminal:
                yield f"event: end\ndata: {json.dumps({'status': 'terminal', 'seq': seq})}\n\n"
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/runs/{run_id}/trace", response_model=list[AgentRunOut])
def run_trace(run_id: uuid.UUID, db: DB, _: Viewer, agent: str | None = None) -> list[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.run_id == run_id).order_by(AgentRun.created_at)
    if agent:
        stmt = stmt.where(AgentRun.agent == agent)
    return list(db.execute(stmt).scalars())


@router.get("/workflows/{workflow_id}/trace", response_model=list[AgentRunOut])
def workflow_trace(workflow_id: uuid.UUID, db: DB, _: Viewer) -> list[AgentRun]:
    run = (
        db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return [] if run is None else run_trace(run.id, db, _)  # type: ignore[arg-type]


@router.get("/runs/{run_id}/graph")
def run_graph(run_id: uuid.UUID, db: DB, _: Viewer) -> dict[str, Any]:
    """Topology annotated with live per-node execution stats for React Flow (§14)."""
    run = fetch(db, WorkflowRun, run_id, "run")
    topo = graph_topology()
    rows = list(db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalars())
    stats: dict[str, dict[str, Any]] = {}
    alias = {
        "critic": "evaluator",
        "human_gate": "approval",
        "fail_sample": "approval",
        "export": "dataset_builder",
    }
    for node in topo["nodes"]:
        key = alias.get(node["id"], node["id"])
        items = [r for r in rows if r.agent == key]
        stats[node["id"]] = {
            "calls": len(items),
            "latency_ms": sum(r.latency_ms for r in items),
            "avg_latency_ms": round(sum(r.latency_ms for r in items) / len(items)) if items else 0,
            "tokens": sum(r.input_tokens + r.output_tokens for r in items),
            "cost_usd": round(sum(r.cost_usd for r in items), 6),
            "errors": sum(1 for r in items if r.status == "FAILED"),
            "model": items[-1].model if items else (run.config_snapshot or {}).get("model", ""),
            "provider": items[-1].provider
            if items
            else (run.config_snapshot or {}).get("provider", ""),
            "prompt_key": items[-1].prompt_key if items else "",
            "prompt_version": items[-1].prompt_version if items else 0,
            "last_output": items[-1].output_json if items else {},
            "last_input": items[-1].input_json if items else {},
            "status": (
                "FAILED"
                if any(r.status == "FAILED" for r in items)
                else ("SUCCESS" if items else "IDLE")
            ),
        }
    active = (run.state or {}).get("resume_at")
    return {**topo, "stats": stats, "active_node": active, "run_status": run.status}
