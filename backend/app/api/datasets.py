from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.agents.dataset_builder import build_rows, checksum, serialize
from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.core.errors import NotFoundError, ValidationFailedError
from app.models import Dataset, DatasetVersion, Sample, WorkflowRun
from app.models.enums import APPROVED_STATUSES
from app.schemas.api import DatasetCreate, DatasetOut
from app.services.storage import get_storage

router = APIRouter(prefix="/datasets", tags=["datasets"])

MEDIA = {
    "json": "application/json",
    "jsonl": "application/x-ndjson",
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
}


def _approved_items(db: DB, run_id: uuid.UUID) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    samples = list(
        db.execute(
            select(Sample)
            .where(Sample.run_id == run_id, Sample.status.in_(list(APPROVED_STATUSES)))
            .order_by(Sample.sample_key)
        ).scalars()
    )
    items = []
    for s in samples:
        ev = next((e for e in reversed(s.evaluations) if e.is_consensus), None)
        items.append((s.payload, {"overall_score": ev.overall_score if ev else 0}))
    return items


@router.post("", response_model=DatasetOut, status_code=201)
async def create_dataset(body: DatasetCreate, db: DB, _: Editor) -> Dataset:
    """Build a dataset on demand from the approved samples of a run (§6)."""
    run = fetch(db, WorkflowRun, body.run_id, "run")
    items = _approved_items(db, run.id)
    if not items:
        raise ValidationFailedError("run has no approved samples to export")
    rows = build_rows(items, body.style)
    dataset = Dataset(
        project_id=run.workflow.project_id if run.workflow else None,
        run_id=run.id,
        name=body.name or f"{run.workflow.name if run.workflow else 'dataset'} ({body.style})",
        style=body.style,
        row_count=len(rows),
        dataset_metadata={"built_from": "api", "formats": body.formats},
    )
    db.add(dataset)
    db.flush()
    storage = get_storage()
    for i, fmt in enumerate(body.formats, start=1):
        payload, media = serialize(rows, fmt)
        key = f"datasets/{dataset.id}/v{i}.{fmt}"
        try:
            await storage.upload(key, payload, media)
        except Exception:  # noqa: BLE001
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
    db.commit()
    db.refresh(dataset)
    return dataset


@router.get("", response_model=list[DatasetOut])
def list_datasets(
    db: DB,
    _: Viewer,
    page: Pagination,
    project_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
) -> list[Dataset]:
    stmt = select(Dataset).order_by(Dataset.created_at.desc())
    if project_id:
        stmt = stmt.where(Dataset.project_id == project_id)
    if run_id:
        stmt = stmt.where(Dataset.run_id == run_id)
    return list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: uuid.UUID, db: DB, _: Viewer) -> Dataset:
    return fetch(db, Dataset, dataset_id, "dataset")


@router.get("/{dataset_id}/preview")
def preview_dataset(
    dataset_id: uuid.UUID, db: DB, _: Viewer, limit: int = Query(20, ge=1, le=200)
) -> dict[str, Any]:
    dataset = fetch(db, Dataset, dataset_id, "dataset")
    version = dataset.versions[0] if dataset.versions else None
    rows = (version.rows if version else []) or []
    if not rows and dataset.run_id:
        rows = build_rows(_approved_items(db, dataset.run_id), dataset.style)
    return {
        "name": dataset.name,
        "style": dataset.style,
        "row_count": dataset.row_count,
        "rows": rows[:limit],
    }


@router.get("/{dataset_id}/download")
async def download_dataset(
    dataset_id: uuid.UUID, db: DB, _: Viewer, format: str = Query("jsonl")
) -> Response:
    """Streams the artifact from object storage; rebuilds if the object is gone."""
    if format not in MEDIA:
        raise ValidationFailedError(f"unsupported format '{format}'")
    dataset = fetch(db, Dataset, dataset_id, "dataset")
    version = next((v for v in dataset.versions if v.fmt == format), None)

    payload: bytes | None = None
    if version and version.storage_key:
        try:
            payload = await get_storage().download(version.storage_key)
        except Exception:  # noqa: BLE001 — fall through to a rebuild
            payload = None
    if payload is None:
        rows = (version.rows if version else []) or []
        if not rows and dataset.run_id:
            rows = build_rows(_approved_items(db, dataset.run_id), dataset.style)
        if not rows:
            raise NotFoundError("dataset artifact unavailable and cannot be rebuilt")
        payload, _ = serialize(rows, format)

    return Response(
        content=payload,
        media_type=MEDIA[format],
        headers={"Content-Disposition": _disposition(dataset.name, format)},
    )


def _disposition(name: str, fmt: str) -> str:
    """RFC 6266 header: ASCII fallback + UTF-8 form (headers must be latin-1 safe)."""
    from urllib.parse import quote

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "dataset"
    return (
        f"attachment; filename=\"{stem}.{fmt}\"; filename*=UTF-8''{quote(f'{name}.{fmt}', safe='')}"
    )


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: uuid.UUID, db: DB, _: Editor) -> None:
    db.delete(fetch(db, Dataset, dataset_id, "dataset"))
    db.commit()
