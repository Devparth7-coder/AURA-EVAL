from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, rate_limit, require_editor
from app.database.session import get_db

DB = Annotated[Session, Depends(get_db)]
Viewer = Annotated[Principal, Depends(get_principal)]
Editor = Annotated[Principal, Depends(require_editor)]
Limited = Depends(rate_limit)


def fetch[T](db: Session, model: type[T], pk: uuid.UUID, label: str) -> T:
    obj = db.get(model, pk)
    if obj is None:
        raise NotFoundError(f"{label} not found", id=str(pk))
    return obj


class Page:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.limit = limit
        self.offset = offset


Pagination = Annotated[Page, Depends(Page)]
