from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.agents import AgentContext, EvaluatorAgent
from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.core.errors import ValidationFailedError
from app.models import SOP, SOPVersion
from app.schemas.api import SOPCreate, SOPOut, SOPTestRequest, SOPUpdate
from app.services.sop_engine import (
    DEFAULT_RULES,
    DEFAULT_SCORING,
    normalise_sop,
    render_sop,
)

router = APIRouter(prefix="/sops", tags=["sops"])


def _current(sop: SOP) -> SOPVersion:
    return next((v for v in sop.versions if v.version == sop.current_version), sop.versions[-1])


def _snapshot(sop: SOP, version: int | None = None) -> dict[str, Any]:
    v = next((x for x in sop.versions if x.version == version), None) if version else _current(sop)
    if v is None:
        raise ValidationFailedError(f"SOP version {version} does not exist")
    return normalise_sop(
        {
            "name": sop.name,
            "version": v.version,
            "rules": v.rules,
            "scoring": v.scoring,
            "threshold": v.threshold,
        }
    )


@router.get("/defaults")
def sop_defaults(_: Viewer) -> dict[str, Any]:
    return {"rules": DEFAULT_RULES, "scoring": DEFAULT_SCORING, "threshold": 75.0}


@router.post("", response_model=SOPOut, status_code=201)
def create_sop(body: SOPCreate, db: DB, _: Editor) -> SOP:
    sop = SOP(
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        current_version=1,
    )
    db.add(sop)
    db.flush()
    db.add(
        SOPVersion(
            sop_id=sop.id,
            version=1,
            rules=[r.model_dump() for r in body.rules] or DEFAULT_RULES,
            scoring=body.scoring or DEFAULT_SCORING,
            threshold=body.threshold,
            changelog="Initial version.",
        )
    )
    db.commit()
    db.refresh(sop)
    return sop


@router.get("", response_model=list[SOPOut])
def list_sops(
    db: DB, _: Viewer, page: Pagination, project_id: uuid.UUID | None = None
) -> list[SOP]:
    stmt = select(SOP).order_by(SOP.created_at.desc())
    if project_id:
        stmt = stmt.where(SOP.project_id == project_id)
    return list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())


@router.get("/{sop_id}", response_model=SOPOut)
def get_sop(sop_id: uuid.UUID, db: DB, _: Viewer) -> SOP:
    return fetch(db, SOP, sop_id, "sop")


@router.put("/{sop_id}", response_model=SOPOut)
def update_sop(sop_id: uuid.UUID, body: SOPUpdate, db: DB, _: Editor) -> SOP:
    """Content changes create a NEW immutable version (§3 versioning)."""
    sop = fetch(db, SOP, sop_id, "sop")
    if body.name is not None:
        sop.name = body.name
    if body.description is not None:
        sop.description = body.description
    if body.is_active is not None:
        sop.is_active = body.is_active

    content_changed = any(x is not None for x in (body.rules, body.scoring, body.threshold))
    if content_changed:
        cur = _current(sop)
        new_version = sop.current_version + 1
        db.add(
            SOPVersion(
                sop_id=sop.id,
                version=new_version,
                rules=[r.model_dump() for r in body.rules] if body.rules is not None else cur.rules,
                scoring=body.scoring if body.scoring is not None else cur.scoring,
                threshold=body.threshold if body.threshold is not None else cur.threshold,
                changelog=body.changelog or f"Updated to version {new_version}.",
            )
        )
        sop.current_version = new_version
    db.commit()
    db.refresh(sop)
    return sop


@router.post("/{sop_id}/activate", response_model=SOPOut)
def activate_sop(sop_id: uuid.UUID, db: DB, _: Editor, active: bool = True) -> SOP:
    sop = fetch(db, SOP, sop_id, "sop")
    sop.is_active = active
    db.commit()
    db.refresh(sop)
    return sop


@router.post("/{sop_id}/versions/{version}/restore", response_model=SOPOut)
def restore_version(sop_id: uuid.UUID, version: int, db: DB, _: Editor) -> SOP:
    sop = fetch(db, SOP, sop_id, "sop")
    src = next((v for v in sop.versions if v.version == version), None)
    if src is None:
        raise ValidationFailedError(f"SOP version {version} does not exist")
    new_version = sop.current_version + 1
    db.add(
        SOPVersion(
            sop_id=sop.id,
            version=new_version,
            rules=src.rules,
            scoring=src.scoring,
            threshold=src.threshold,
            changelog=f"Restored from version {version}.",
        )
    )
    sop.current_version = new_version
    db.commit()
    db.refresh(sop)
    return sop


@router.delete("/{sop_id}", status_code=204)
def delete_sop(sop_id: uuid.UUID, db: DB, _: Editor) -> None:
    db.delete(fetch(db, SOP, sop_id, "sop"))
    db.commit()


@router.get("/{sop_id}/render")
def render(sop_id: uuid.UUID, db: DB, _: Viewer, version: int | None = None) -> dict[str, str]:
    """Exactly the SOP text injected into the evaluator prompt."""
    sop = fetch(db, SOP, sop_id, "sop")
    return {"text": render_sop(_snapshot(sop, version))}


@router.post("/{sop_id}/test")
async def test_sop(sop_id: uuid.UUID, body: SOPTestRequest, db: DB, _: Editor) -> dict[str, Any]:
    """Dry-run the SOP against ad-hoc samples without creating a workflow (§3)."""
    sop = fetch(db, SOP, sop_id, "sop")
    snapshot = _snapshot(sop, body.version)
    ctx = AgentContext(
        config={"provider": "mock", "judges": 1, "mock_failure_rate": 0.0}, sop=snapshot
    )
    agent = EvaluatorAgent(ctx)
    results = []
    for i, sample in enumerate(body.samples, start=1):
        payload = {"sample_id": f"test_{i:03d}", **sample}
        consensus = await agent.run(payload)
        results.append(
            {
                "sample_id": payload["sample_id"],
                "approved": consensus.approved,
                "overall_score": consensus.mean_score,
                "evaluation": consensus.final.model_dump(mode="json"),
            }
        )
    return {"sop": snapshot["name"], "version": snapshot["version"], "results": results}
