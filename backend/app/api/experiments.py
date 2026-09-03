from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select

from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.database.session import session_scope
from app.models import Experiment, ExperimentArm
from app.schemas.api import ExperimentCreate, ExperimentOut
from app.services.experiments import run_experiment

router = APIRouter(prefix="/experiments", tags=["experiments"])


async def _execute(experiment_id: uuid.UUID) -> None:
    with session_scope() as db:
        exp = db.get(Experiment, experiment_id)
        if exp:
            await run_experiment(db, exp)


@router.post("", response_model=ExperimentOut, status_code=202)
async def create_experiment(
    body: ExperimentCreate, db: DB, _: Editor, background: BackgroundTasks
) -> Experiment:
    exp = Experiment(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        status="PENDING",
        config={
            "sample_count": body.sample_count,
            "objective": body.objective,
            "sop_id": str(body.sop_id) if body.sop_id else None,
        },
    )
    db.add(exp)
    db.flush()
    for arm in body.arms:
        db.add(
            ExperimentArm(
                experiment_id=exp.id,
                label=arm.label,
                provider=arm.provider,
                model=arm.model,
                prompt_version=arm.prompt_version,
                metrics={"quality_bias": arm.quality_bias},
            )
        )
    db.commit()
    db.refresh(exp)
    background.add_task(_execute, exp.id)
    return exp


@router.get("", response_model=list[ExperimentOut])
def list_experiments(db: DB, _: Viewer, page: Pagination) -> list[Experiment]:
    return list(
        db.execute(
            select(Experiment)
            .order_by(Experiment.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: uuid.UUID, db: DB, _: Viewer) -> Experiment:
    return fetch(db, Experiment, experiment_id, "experiment")


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: uuid.UUID, db: DB, _: Editor) -> None:
    db.delete(fetch(db, Experiment, experiment_id, "experiment"))
    db.commit()
