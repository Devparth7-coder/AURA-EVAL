"""SQLAlchemy ORM entities (§10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, JSONType, TimestampMixin, UUIDMixin
from app.models.enums import (
    AgentStatus,
    DatasetFormat,
    DatasetStyle,
    RunStatus,
    SampleStatus,
)


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(32), default="admin")
    hashed_password: Mapped[str | None] = mapped_column(String(256), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    projects: Mapped[list[Project]] = relationship(back_populates="owner")


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    owner: Mapped[User | None] = relationship(back_populates="projects")
    workflows: Mapped[list[Workflow]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sops: Mapped[list[SOP]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SOP(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sops"
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    project: Mapped[Project | None] = relationship(back_populates="sops")
    versions: Mapped[list[SOPVersion]] = relationship(
        back_populates="sop", cascade="all, delete-orphan", order_by="SOPVersion.version"
    )


class SOPVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sop_versions"
    __table_args__ = (UniqueConstraint("sop_id", "version", name="uq_sop_version"),)
    sop_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sops.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    scoring: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    threshold: Mapped[float] = mapped_column(Float, default=70.0)
    changelog: Mapped[str] = mapped_column(Text, default="")

    sop: Mapped[SOP] = relationship(back_populates="versions")


class PromptTemplate(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    key: Mapped[str] = mapped_column(String(120), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version",
    )


class PromptVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_version"),)
    template_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    template: Mapped[PromptTemplate] = relationship(back_populates="versions")


class Workflow(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflows"
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    sop_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("sops.id", ondelete="SET NULL"), default=None
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="workflows")
    sop: Mapped[SOP | None] = relationship()
    runs: Mapped[list[WorkflowRun]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class WorkflowRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.PENDING, index=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # checkpoint
    plan: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    sop_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    steps_executed: Mapped[int] = mapped_column(Integer, default=0)
    samples_generated: Mapped[int] = mapped_column(Integer, default=0)
    samples_approved: Mapped[int] = mapped_column(Integer, default=0)
    samples_rejected: Mapped[int] = mapped_column(Integer, default=0)
    samples_failed: Mapped[int] = mapped_column(Integer, default=0)
    samples_review: Mapped[int] = mapped_column(Integer, default=0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    workflow: Mapped[Workflow] = relationship(back_populates="runs")
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list[WorkflowEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    samples: Mapped[list[Sample]] = relationship(back_populates="run", cascade="all, delete-orphan")
    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentRun(UUIDMixin, TimestampMixin, Base):
    """One agent invocation — powers the trace viewer, cost and reliability views."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_run_agent", "run_id", "agent"),)
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("samples.id", ondelete="SET NULL"), default=None
    )
    agent: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default=AgentStatus.SUCCESS)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    model: Mapped[str] = mapped_column(String(120), default="mock-1")
    prompt_key: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_type: Mapped[str | None] = mapped_column(String(60), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    run: Mapped[WorkflowRun] = relationship(back_populates="agent_runs")


class WorkflowEvent(UUIDMixin, Base):
    __tablename__ = "workflow_events"
    __table_args__ = (Index("ix_events_run_seq", "run_id", "seq"),)
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[WorkflowRun] = relationship(back_populates="events")


class Sample(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "samples"
    __table_args__ = (
        Index("ix_samples_run_status", "run_id", "status"),
        UniqueConstraint("run_id", "sample_key", name="uq_sample_key"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    sample_key: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(24), default=SampleStatus.PENDING, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    final_score: Mapped[float | None] = mapped_column(Float, default=None)
    approval_report: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)

    run: Mapped[WorkflowRun] = relationship(back_populates="samples")
    versions: Mapped[list[SampleVersion]] = relationship(
        back_populates="sample",
        cascade="all, delete-orphan",
        order_by="SampleVersion.version",
    )
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="sample",
        cascade="all, delete-orphan",
        order_by="Evaluation.created_at",
    )
    reviews: Mapped[list[HumanReview]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )


class SampleVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sample_versions"
    sample_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    source: Mapped[str] = mapped_column(String(24), default="generator")  # generator|refiner|human
    feedback_applied: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(24), default="pending")

    sample: Mapped[Sample] = relationship(back_populates="versions")


class Evaluation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evaluations"
    sample_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    judge_label: Mapped[str] = mapped_column(String(40), default="consensus")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    issues: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    hallucination_risk: Mapped[str] = mapped_column(String(16), default="low")
    is_consensus: Mapped[bool] = mapped_column(Boolean, default=False)
    variance: Mapped[float] = mapped_column(Float, default=0.0)
    agreement_rate: Mapped[float] = mapped_column(Float, default=1.0)
    sop_version: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    sample: Mapped[Sample] = relationship(back_populates="evaluations")


class HumanReview(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "human_reviews"
    sample_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("samples.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(200), default="anonymous")
    decision: Mapped[str] = mapped_column(String(20))
    feedback: Mapped[str] = mapped_column(Text, default="")
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    agreed_with_model: Mapped[bool | None] = mapped_column(Boolean, default=None)

    sample: Mapped[Sample] = relationship(back_populates="reviews")


class Dataset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("workflow_runs.id", ondelete="CASCADE"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    style: Mapped[str] = mapped_column(String(24), default=DatasetStyle.INSTRUCTION)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    run: Mapped[WorkflowRun | None] = relationship(back_populates="datasets")
    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetVersion.version",
    )


class DatasetVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    fmt: Mapped[str] = mapped_column(String(16), default=DatasetFormat.JSONL)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    storage_key: Mapped[str] = mapped_column(String(512), default="")
    rows: Mapped[list[Any]] = mapped_column(JSONType, default=list)  # inline copy (small sets)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")


class Experiment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "experiments"
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    arms: Mapped[list[ExperimentArm]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentArm(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "experiment_arms"
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    model: Mapped[str] = mapped_column(String(120), default="mock-1")
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    experiment: Mapped[Experiment] = relationship(back_populates="arms")
