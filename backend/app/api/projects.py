from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, Editor, Pagination, Viewer, fetch
from app.models import Project
from app.schemas.api import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: DB, _: Editor) -> Project:
    project = Project(**body.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: DB, _: Viewer, page: Pagination) -> list[Project]:
    return list(
        db.execute(
            select(Project)
            .order_by(Project.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        ).scalars()
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: DB, _: Viewer) -> Project:
    return fetch(db, Project, project_id, "project")


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: uuid.UUID, body: ProjectUpdate, db: DB, _: Editor) -> Project:
    project = fetch(db, Project, project_id, "project")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(project, k, v)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: DB, _: Editor) -> None:
    db.delete(fetch(db, Project, project_id, "project"))
    db.commit()
