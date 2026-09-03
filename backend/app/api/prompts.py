from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, Editor, Viewer, fetch
from app.models import PromptTemplate, PromptVersion
from app.schemas.api import PromptOut, PromptVersionCreate

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("", response_model=list[PromptOut])
def list_prompts(db: DB, _: Viewer) -> list[PromptTemplate]:
    return list(db.execute(select(PromptTemplate).order_by(PromptTemplate.key)).scalars())


@router.get("/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: uuid.UUID, db: DB, _: Viewer) -> PromptTemplate:
    return fetch(db, PromptTemplate, prompt_id, "prompt")


@router.post("/{prompt_id}/versions", response_model=PromptOut, status_code=201)
def add_version(
    prompt_id: uuid.UUID, body: PromptVersionCreate, db: DB, _: Editor
) -> PromptTemplate:
    tpl = fetch(db, PromptTemplate, prompt_id, "prompt")
    version = tpl.current_version + 1
    db.add(PromptVersion(template_id=tpl.id, version=version, body=body.body, notes=body.notes))
    tpl.current_version = version
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/{prompt_id}/diff")
def diff_versions(
    prompt_id: uuid.UUID, db: DB, _: Viewer, a: int = 1, b: int = 2
) -> dict[str, Any]:
    import difflib

    tpl = fetch(db, PromptTemplate, prompt_id, "prompt")
    va = next((v for v in tpl.versions if v.version == a), None)
    vb = next((v for v in tpl.versions if v.version == b), None)
    if va is None or vb is None:
        return {"diff": [], "error": "version not found"}
    return {
        "a": a,
        "b": b,
        "diff": list(
            difflib.unified_diff(
                va.body.splitlines(),
                vb.body.splitlines(),
                fromfile=f"v{a}",
                tofile=f"v{b}",
                lineterm="",
            )
        ),
    }
