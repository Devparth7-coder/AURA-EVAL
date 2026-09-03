"""Request/response models for the REST API (§27)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Projects ----------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tags: list[str] | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    tags: list[Any]
    created_at: datetime
    updated_at: datetime


# --- SOPs --------------------------------------------------------------
class SOPRule(BaseModel):
    id: str = ""
    text: str = Field(min_length=1, max_length=1000)
    criterion: str = "correctness"
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    severity: Literal["minor", "major", "critical"] = "major"


class SOPCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    project_id: uuid.UUID | None = None
    rules: list[SOPRule] = Field(default_factory=list)
    scoring: dict[str, Any] = Field(default_factory=dict)
    threshold: float = Field(default=70.0, ge=0, le=100)
    is_active: bool = True


class SOPUpdate(BaseModel):
    """Any change to rules/scoring/threshold creates a NEW version (§3)."""

    name: str | None = None
    description: str | None = None
    rules: list[SOPRule] | None = None
    scoring: dict[str, Any] | None = None
    threshold: float | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    changelog: str = ""


class SOPVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    rules: list[Any]
    scoring: dict[str, Any]
    threshold: float
    changelog: str
    created_at: datetime


class SOPOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    description: str
    is_active: bool
    current_version: int
    created_at: datetime
    updated_at: datetime
    versions: list[SOPVersionOut] = Field(default_factory=list)


class SOPTestRequest(BaseModel):
    samples: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    version: int | None = None


# --- Workflows ---------------------------------------------------------
class WorkflowConfig(BaseModel):
    sample_count: int = Field(default=6, ge=1, le=settings.max_samples_per_run)
    batch_size: int = Field(default=6, ge=1, le=25)
    max_retries: int = Field(default=settings.max_retries, ge=0, le=6)
    provider: str = Field(default_factory=lambda: settings.llm_provider)
    model: str = Field(default_factory=lambda: settings.llm_model)
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    use_planner: bool = True
    judges: int = Field(default=1, ge=1, le=5)
    judge_models: list[str] = Field(default_factory=list)
    approval_threshold: float = Field(default=settings.approval_threshold, ge=0, le=100)
    borderline_low: float = Field(default=settings.borderline_low, ge=0, le=100)
    borderline_high: float = Field(default=settings.borderline_high, ge=0, le=100)
    human_review_enabled: bool = True
    dataset_style: Literal["instruction", "chat", "evaluation"] = "instruction"
    dataset_formats: list[Literal["json", "jsonl", "csv", "parquet"]] = Field(
        default_factory=lambda: ["jsonl", "json", "csv"]
    )
    domain_hint: str = ""
    max_cost_usd: float = Field(default=settings.max_cost_usd_per_run, ge=0)
    prompt_versions: dict[str, int] = Field(default_factory=dict)
    mock_failure_rate: float = Field(default=0.06, ge=0.0, le=1.0)


class WorkflowCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    objective: str = ""
    sop_id: uuid.UUID | None = None
    config: WorkflowConfig = Field(default_factory=WorkflowConfig)


class WorkflowUpdate(BaseModel):
    name: str | None = None
    objective: str | None = None
    sop_id: uuid.UUID | None = None
    config: WorkflowConfig | None = None
    is_archived: bool | None = None


class WorkflowOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    sop_id: uuid.UUID | None
    name: str
    objective: str
    config: dict[str, Any]
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class RunOut(ORMModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    steps_executed: int
    samples_generated: int
    samples_approved: int
    samples_rejected: int
    samples_failed: int
    samples_review: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    plan: dict[str, Any]
    error: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunStartRequest(BaseModel):
    async_execution: bool = True
    sample_count: int | None = Field(default=None, ge=1, le=settings.max_samples_per_run)


class AdvanceRequest(BaseModel):
    max_steps: int = Field(default=settings.default_slice_steps, ge=1, le=500)


class EventOut(ORMModel):
    id: uuid.UUID
    seq: int
    type: str
    level: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class AgentRunOut(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    sample_id: uuid.UUID | None
    agent: str
    status: str
    attempt: int
    provider: str
    model: str
    prompt_key: str
    prompt_version: int
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    error_type: str | None
    error_message: str | None
    created_at: datetime


# --- Samples -----------------------------------------------------------
class SampleVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    payload: dict[str, Any]
    source: str
    feedback_applied: str
    outcome: str
    created_at: datetime


class EvaluationOut(ORMModel):
    id: uuid.UUID
    sample_id: uuid.UUID
    attempt: int
    judge_label: str
    approved: bool
    scores: dict[str, Any]
    overall_score: float
    issues: list[Any]
    reasoning_summary: str
    confidence: float
    hallucination_risk: str
    is_consensus: bool
    variance: float
    agreement_rate: float
    latency_ms: int
    created_at: datetime


class HumanReviewOut(ORMModel):
    id: uuid.UUID
    reviewer: str
    decision: str
    feedback: str
    created_at: datetime


class SampleOut(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    sample_key: str
    payload: dict[str, Any]
    status: str
    retry_count: int
    final_score: float | None
    approval_report: dict[str, Any]
    failure_reason: str | None
    created_at: datetime


class SampleDetailOut(SampleOut):
    versions: list[SampleVersionOut] = Field(default_factory=list)
    evaluations: list[EvaluationOut] = Field(default_factory=list)
    reviews: list[HumanReviewOut] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    reviewer: str = "anonymous"
    feedback: str = ""
    edited_payload: dict[str, Any] | None = None


# --- Datasets ----------------------------------------------------------
class DatasetCreate(BaseModel):
    run_id: uuid.UUID
    name: str | None = None
    style: Literal["instruction", "chat", "evaluation"] = "instruction"
    formats: list[Literal["json", "jsonl", "csv", "parquet"]] = Field(
        default_factory=lambda: ["jsonl"]
    )


class DatasetVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    fmt: str
    row_count: int
    size_bytes: int
    checksum: str
    storage_key: str
    created_at: datetime


class DatasetOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    run_id: uuid.UUID | None
    name: str
    style: str
    row_count: int
    current_version: int
    dataset_metadata: dict[str, Any]
    created_at: datetime
    versions: list[DatasetVersionOut] = Field(default_factory=list)


# --- Experiments -------------------------------------------------------
class ExperimentArmIn(BaseModel):
    label: str
    provider: str = "mock"
    model: str = "mock-1"
    prompt_version: int = 1
    quality_bias: float = 0.0


class ExperimentCreate(BaseModel):
    name: str
    description: str = ""
    project_id: uuid.UUID | None = None
    sample_count: int = Field(default=6, ge=1, le=100)
    objective: str = "Compare model quality on an evaluation dataset"
    sop_id: uuid.UUID | None = None
    arms: list[ExperimentArmIn] = Field(min_length=2, max_length=4)


class ExperimentOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    config: dict[str, Any]
    report: dict[str, Any]
    created_at: datetime


# --- Prompts -----------------------------------------------------------
class PromptVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    body: str
    notes: str
    is_active: bool
    created_at: datetime


class PromptOut(ORMModel):
    id: uuid.UUID
    key: str
    agent: str
    description: str
    current_version: int
    versions: list[PromptVersionOut] = Field(default_factory=list)


class PromptVersionCreate(BaseModel):
    body: str = Field(min_length=10)
    notes: str = ""
