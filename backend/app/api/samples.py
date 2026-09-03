from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.models import Evaluation, HumanReview, Sample, SampleVersion
from app.models.enums import ReviewDecision, SampleStatus
from app.schemas.api import EvaluationOut, ReviewRequest, SampleDetailOut, SampleOut

router = APIRouter(tags=["samples"])


@router.get("/samples", response_model=list[SampleOut])
def list_samples(
    db: DB,
    _: Viewer,
    page: Pagination,
    run_id: uuid.UUID | None = None,
    status: str | None = None,
    min_score: float | None = Query(None, ge=0, le=100),
    q: str | None = None,
) -> list[Sample]:
    stmt = select(Sample).order_by(Sample.created_at.desc())
    if run_id:
        stmt = stmt.where(Sample.run_id == run_id)
    if status:
        stmt = stmt.where(Sample.status == status)
    if min_score is not None:
        stmt = stmt.where(Sample.final_score >= min_score)
    rows = list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in str(r.payload).lower()]
    return rows


@router.get("/samples/review-queue", response_model=list[SampleDetailOut])
def review_queue(
    db: DB, _: Viewer, page: Pagination, run_id: uuid.UUID | None = None
) -> list[Sample]:
    stmt = select(Sample).where(Sample.status == SampleStatus.NEEDS_REVIEW)
    if run_id:
        stmt = stmt.where(Sample.run_id == run_id)
    return list(
        db.execute(stmt.order_by(Sample.created_at).limit(page.limit).offset(page.offset)).scalars()
    )


@router.get("/samples/{sample_id}", response_model=SampleDetailOut)
def get_sample(sample_id: uuid.UUID, db: DB, _: Viewer) -> Sample:
    return fetch(db, Sample, sample_id, "sample")


@router.get("/samples/{sample_id}/history")
def sample_history(sample_id: uuid.UUID, db: DB, _: Viewer) -> dict[str, Any]:
    """Version-by-version refinement timeline for side-by-side comparison (§16)."""
    sample = fetch(db, Sample, sample_id, "sample")
    evals = {e.attempt: e for e in sample.evaluations if e.is_consensus}
    timeline = []
    for v in sample.versions:
        ev = evals.get(v.version)
        timeline.append(
            {
                "version": v.version,
                "source": v.source,
                "payload": v.payload,
                "feedback_applied": v.feedback_applied,
                "outcome": v.outcome,
                "score": ev.overall_score if ev else None,
                "approved": ev.approved if ev else None,
                "issues": ev.issues if ev else [],
                "reasoning_summary": ev.reasoning_summary if ev else "",
                "created_at": v.created_at.isoformat(),
            }
        )
    return {
        "sample_id": str(sample.id),
        "sample_key": sample.sample_key,
        "status": sample.status,
        "retry_count": sample.retry_count,
        "final_score": sample.final_score,
        "timeline": timeline,
    }


def _record_review(
    db: DB, sample: Sample, decision: str, body: ReviewRequest, new_status: str
) -> Sample:
    agreed = None
    if sample.evaluations:
        last = sample.evaluations[-1]
        agreed = last.approved == (decision == ReviewDecision.APPROVE)
    db.add(
        HumanReview(
            sample_id=sample.id,
            reviewer=body.reviewer,
            decision=decision,
            feedback=body.feedback,
            edited_payload=body.edited_payload,
            agreed_with_model=agreed,
        )
    )
    if body.edited_payload:
        merged = {**sample.payload, **body.edited_payload}
        sample.payload = merged
        db.add(
            SampleVersion(
                sample_id=sample.id,
                version=(sample.versions[-1].version + 1) if sample.versions else 2,
                payload=merged,
                source="human",
                feedback_applied=body.feedback,
                outcome=decision,
            )
        )
    sample.status = new_status
    db.commit()
    db.refresh(sample)
    return sample


@router.post("/samples/{sample_id}/approve", response_model=SampleDetailOut)
def approve_sample(
    sample_id: uuid.UUID, db: DB, _: Editor, body: ReviewRequest | None = None
) -> Sample:
    sample = fetch(db, Sample, sample_id, "sample")
    return _record_review(
        db, sample, ReviewDecision.APPROVE, body or ReviewRequest(), SampleStatus.HUMAN_APPROVED
    )


@router.post("/samples/{sample_id}/reject", response_model=SampleDetailOut)
def reject_sample(
    sample_id: uuid.UUID, db: DB, _: Editor, body: ReviewRequest | None = None
) -> Sample:
    sample = fetch(db, Sample, sample_id, "sample")
    return _record_review(
        db, sample, ReviewDecision.REJECT, body or ReviewRequest(), SampleStatus.HUMAN_REJECTED
    )


@router.post("/samples/{sample_id}/edit", response_model=SampleDetailOut)
def edit_sample(sample_id: uuid.UUID, body: ReviewRequest, db: DB, _: Editor) -> Sample:
    sample = fetch(db, Sample, sample_id, "sample")
    return _record_review(db, sample, ReviewDecision.EDIT, body, SampleStatus.HUMAN_APPROVED)


@router.get("/evaluations", response_model=list[EvaluationOut])
def list_evaluations(
    db: DB,
    _: Viewer,
    page: Pagination,
    run_id: uuid.UUID | None = None,
    sample_id: uuid.UUID | None = None,
    consensus_only: bool = True,
) -> list[Evaluation]:
    stmt = select(Evaluation).order_by(Evaluation.created_at.desc())
    if run_id:
        stmt = stmt.where(Evaluation.run_id == run_id)
    if sample_id:
        stmt = stmt.where(Evaluation.sample_id == sample_id)
    if consensus_only:
        stmt = stmt.where(Evaluation.is_consensus.is_(True))
    return list(db.execute(stmt.limit(page.limit).offset(page.offset)).scalars())
