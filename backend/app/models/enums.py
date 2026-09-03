from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class AgentName(StrEnum):
    PLANNER = "planner"
    GENERATOR = "generator"
    EVALUATOR = "evaluator"
    REFINER = "refiner"
    APPROVAL = "approval"
    DATASET_BUILDER = "dataset_builder"


class AgentStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"  # recovered via fallback / repair retry


class SampleStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AUTO_APPROVED = "AUTO_APPROVED"
    AUTO_REJECTED = "AUTO_REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    FAILED = "FAILED"


APPROVED_STATUSES = {SampleStatus.AUTO_APPROVED, SampleStatus.HUMAN_APPROVED}
REJECTED_STATUSES = {SampleStatus.AUTO_REJECTED, SampleStatus.HUMAN_REJECTED}


class DatasetStyle(StrEnum):
    INSTRUCTION = "instruction"
    CHAT = "chat"
    EVALUATION = "evaluation"


class DatasetFormat(StrEnum):
    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    PARQUET = "parquet"


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_STOPPED = "run.stopped"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    SAMPLE_GENERATED = "sample.generated"
    SAMPLE_EVALUATING = "sample.evaluating"
    SAMPLE_APPROVED = "sample.approved"
    SAMPLE_REJECTED = "sample.rejected"
    SAMPLE_NEEDS_REVIEW = "sample.needs_review"
    SAMPLE_FAILED = "sample.failed"
    REFINEMENT_STARTED = "refinement.started"
    DATASET_BUILT = "dataset.built"
    INFO = "info"
    WARNING = "warning"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class Role(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
