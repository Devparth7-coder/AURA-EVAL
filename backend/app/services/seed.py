"""Demo seeding (§26): the app is useful the first time it boots, with no API key."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.prompts import all_prompts
from app.models import (
    SOP,
    Project,
    PromptTemplate,
    PromptVersion,
    SOPVersion,
    User,
    Workflow,
)
from app.services.sop_engine import DEFAULT_SCORING, default_sop

DEMO_PROJECT = "Coding Assistant Evaluation"


def seed_prompts(db: Session) -> None:
    for prompt in all_prompts():
        tpl = db.execute(
            select(PromptTemplate).where(PromptTemplate.key == prompt.key)
        ).scalar_one_or_none()
        if tpl is None:
            tpl = PromptTemplate(
                key=prompt.key,
                agent=prompt.agent,
                description=f"Default {prompt.agent} prompt",
                current_version=prompt.version,
            )
            db.add(tpl)
            db.flush()
        exists = any(v.version == prompt.version for v in tpl.versions)
        if not exists:
            db.add(
                PromptVersion(
                    template_id=tpl.id, version=prompt.version, body=prompt.body, notes=prompt.notes
                )
            )
            tpl.current_version = max(tpl.current_version, prompt.version)
    db.flush()


def seed_demo(db: Session) -> dict[str, Any]:
    """Idempotent: creates the demo project, SOPs, workflows and prompt registry."""
    seed_prompts(db)
    project = db.execute(select(Project).where(Project.name == DEMO_PROJECT)).scalar_one_or_none()
    if project is None:
        user = db.execute(
            select(User).where(User.email == "demo@aura-eval.dev")
        ).scalar_one_or_none()
        if user is None:
            user = User(email="demo@aura-eval.dev", name="Demo User", role="admin")
            db.add(user)
            db.flush()
        project = Project(
            name=DEMO_PROJECT,
            description="Reference project: build and evaluate datasets for coding assistants.",
            tags=["demo", "coding", "evaluation"],
            owner_id=user.id,
        )
        db.add(project)
        db.flush()

    if not project.sops:
        base = default_sop("Technical Answer Quality SOP")
        sop = SOP(
            project_id=project.id,
            name=base["name"],
            description="Baseline correctness/safety rules for technical answers.",
            current_version=1,
        )
        db.add(sop)
        db.flush()
        db.add(
            SOPVersion(
                sop_id=sop.id,
                version=1,
                rules=base["rules"],
                scoring=base["scoring"],
                threshold=75.0,
                changelog="Initial version.",
            )
        )
        strict = SOP(
            project_id=project.id,
            name="Strict Research SOP",
            description="High bar: 85/100 threshold, zero unsupported claims.",
            current_version=1,
        )
        db.add(strict)
        db.flush()
        db.add(
            SOPVersion(
                sop_id=strict.id,
                version=1,
                rules=base["rules"]
                + [
                    {
                        "id": "R7",
                        "text": "Every factual claim must be traceable to the reference.",
                        "criterion": "correctness",
                        "weight": 2.0,
                        "severity": "critical",
                    }
                ],
                scoring=DEFAULT_SCORING,
                threshold=85.0,
                changelog="Initial strict version.",
            )
        )
        db.flush()
    else:
        sop = project.sops[0]

    if not project.workflows:
        db.add(
            Workflow(
                project_id=project.id,
                sop_id=sop.id,
                name="Python Assistant Dataset v1",
                objective="Create a dataset for evaluating Python coding assistants",
                config={
                    "sample_count": 8,
                    "batch_size": 4,
                    "max_retries": 3,
                    "provider": "mock",
                    "model": "mock-1",
                    "temperature": 0.4,
                    "use_planner": True,
                    "judges": 3,
                    "judge_models": [],
                    "approval_threshold": 75.0,
                    "borderline_low": 60.0,
                    "borderline_high": 75.0,
                    "human_review_enabled": True,
                    "dataset_style": "instruction",
                    "dataset_formats": ["jsonl", "json", "csv"],
                    "domain_hint": "python coding",
                    "mock_failure_rate": 0.06,
                },
            )
        )
        db.add(
            Workflow(
                project_id=project.id,
                sop_id=sop.id,
                name="Networking Q&A Eval Set",
                objective="Build an evaluation dataset covering computer networking fundamentals",
                config={
                    "sample_count": 6,
                    "batch_size": 6,
                    "max_retries": 2,
                    "provider": "mock",
                    "model": "mock-1",
                    "judges": 1,
                    "dataset_style": "evaluation",
                    "dataset_formats": ["jsonl"],
                    "domain_hint": "computer networks",
                    "mock_failure_rate": 0.05,
                },
            )
        )
    db.commit()
    return {"project_id": str(project.id), "seeded": True}


def is_empty(db: Session) -> bool:
    return (db.execute(select(func.count()).select_from(Project)).scalar() or 0) == 0
