from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, Viewer
from app.services import analytics as svc

router = APIRouter(tags=["analytics"])


@router.get("/analytics")
def overview(db: DB, _: Viewer, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "summary": svc.dashboard(db, run_id),
        "charts": svc.charts(db, run_id),
    }


@router.get("/analytics/evaluation")
def evaluation(db: DB, _: Viewer, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    return svc.evaluation_analytics(db, run_id)


@router.get("/analytics/reliability")
def reliability(db: DB, _: Viewer, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    return svc.reliability(db, run_id)


@router.get("/analytics/cost")
def cost(db: DB, _: Viewer, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    return svc.cost_report(db, run_id)
