from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("STORAGE_PROVIDER", "memory")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings, settings
from app.database.session import get_db, get_engine, get_sessionmaker, reset_engine
from app.models import SOP, Base, Project, SOPVersion, Workflow
from app.services.sop_engine import default_sop
from app.services.storage import MemoryStorageProvider, set_storage


@pytest.fixture(scope="session", autouse=True)
def _settings() -> None:
    get_settings.cache_clear()
    settings.environment = "test"
    settings.database_url = "sqlite+pysqlite:///:memory:"
    settings.storage_provider = "memory"
    settings.auth_enabled = False
    reset_engine()


@pytest.fixture()
def db() -> Iterator[Session]:
    reset_engine()
    set_storage(MemoryStorageProvider())
    Base.metadata.create_all(get_engine())
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(get_engine())


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def project(db: Session) -> Project:
    p = Project(name=f"Test Project {uuid.uuid4().hex[:6]}", description="test")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def sop(db: Session, project: Project) -> SOP:
    base = default_sop()
    s = SOP(project_id=project.id, name=base["name"], current_version=1)
    db.add(s)
    db.flush()
    db.add(
        SOPVersion(
            sop_id=s.id, version=1, rules=base["rules"], scoring=base["scoring"], threshold=75.0
        )
    )
    db.commit()
    db.refresh(s)
    return s


def make_workflow(db: Session, project: Project, sop: SOP, **overrides) -> Workflow:
    config = {
        "sample_count": 4,
        "batch_size": 4,
        "max_retries": 2,
        "provider": "mock",
        "model": "mock-1",
        "judges": 1,
        "human_review_enabled": False,
        "dataset_style": "instruction",
        "dataset_formats": ["jsonl", "csv"],
        "mock_failure_rate": 0.0,
        "domain_hint": "python",
    }
    config.update(overrides)
    wf = Workflow(
        project_id=project.id,
        sop_id=sop.id,
        name="Test WF",
        objective="Create a dataset for evaluating Python coding assistants",
        config=config,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def workflow(db: Session, project: Project, sop: SOP) -> Workflow:
    return make_workflow(db, project, sop)


@pytest.fixture()
def sample_payload() -> dict:
    return {
        "sample_id": "sample_001",
        "input": "Explain TCP congestion control.",
        "response": "TCP congestion control adapts the sending window using AIMD. "
        "For example, on loss the window halves and then grows linearly, "
        "keeping throughput high while remaining fair to other flows.",
        "category": "Computer Networks",
        "difficulty": "medium",
        "reference": "Canonical explanation of AIMD, slow start and recovery.",
        "tags": ["networking"],
        "metadata": {"run_id": "test-run", "source": "generator"},
    }
