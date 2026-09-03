"""Internal maintenance endpoints.

These are *not* part of the public product surface. They exist so a scheduler
(Vercel Cron, QStash, Kubernetes CronJob, ...) can drive resumable work without
the app needing a long-running worker process (§41 — no background daemons on
serverless).

Security: when ``CRON_SECRET`` is configured the caller must present it via the
``Authorization: Bearer <secret>`` header (the format Vercel Cron sends) or the
``x-cron-secret`` header. If it is unset the endpoint is only reachable in
non-production environments.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import DB
from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.models import WorkflowRun
from app.models.enums import RunStatus
from app.services import workflow_service

router = APIRouter(prefix="/internal", tags=["internal"])

#: Maximum runs advanced per tick, and steps per run, so one invocation always
#: finishes well inside a serverless function timeout.
MAX_RUNS_PER_TICK = 5
MAX_STEPS_PER_RUN = 40


def _authorize(request: Request, authorization: str | None, cron_secret: str | None) -> None:
    expected = settings.cron_secret
    if not expected:
        if settings.environment == "production":
            raise UnauthorizedError(
                "CRON_SECRET is not configured; internal endpoints are disabled"
            )
        return
    presented = cron_secret
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:]
    if presented != expected:
        raise UnauthorizedError("invalid cron secret")


@router.post("/tick")
async def tick(
    request: Request,
    db: DB,
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Advance every in-flight run by a bounded slice.

    Idempotent and safe to call concurrently: :func:`workflow_service.advance_run`
    re-reads persisted state and is a no-op for terminal runs.
    """
    _authorize(request, authorization, x_cron_secret)

    pending = list(
        db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
            .order_by(WorkflowRun.created_at.asc())
            .limit(MAX_RUNS_PER_TICK)
        ).scalars()
    )

    advanced: list[dict[str, Any]] = []
    for run in pending:
        run_id: uuid.UUID = run.id
        try:
            updated = await workflow_service.advance_run(db, run, MAX_STEPS_PER_RUN)
            advanced.append(
                {
                    "run_id": str(run_id),
                    "status": updated.status.value
                    if hasattr(updated.status, "value")
                    else str(updated.status),
                    "steps_executed": updated.step_count,
                }
            )
        except Exception as exc:  # never let one bad run break the whole tick
            advanced.append({"run_id": str(run_id), "error": type(exc).__name__})

    return {"ok": True, "picked_up": len(pending), "runs": advanced}


@router.get("/tick")
async def tick_get(
    request: Request,
    db: DB,
    authorization: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Vercel Cron issues GET requests; delegate to the POST implementation."""
    return await tick(request, db, authorization, x_cron_secret)
