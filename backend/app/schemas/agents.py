"""Pydantic contracts for structured LLM output (§34.2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# --- Planner -----------------------------------------------------------
class WorkflowPlan(StrictModel):
    objective: str = Field(min_length=1, max_length=2000)
    subtasks: list[str] = Field(default_factory=list, max_length=20)
    sample_count: int = Field(default=10, ge=1, le=500)
    required_fields: list[str] = Field(default_factory=lambda: ["input", "response"])
    difficulty_distribution: dict[str, int] = Field(default_factory=dict)
    evaluation_dimensions: list[str] = Field(
        default_factory=lambda: [
            "correctness",
            "relevance",
            "completeness",
            "instruction_following",
            "safety",
        ]
    )
    selected_sop: str | None = None
    notes: str = ""


# --- Generator ---------------------------------------------------------
class GeneratedSample(StrictModel):
    input: str = Field(min_length=1)
    response: str = Field(min_length=1)
    category: str = "general"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    reference: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class GenerationBatch(StrictModel):
    samples: list[GeneratedSample] = Field(min_length=1, max_length=50)


# --- Evaluator ---------------------------------------------------------
class EvaluationScores(StrictModel):
    correctness: int = Field(ge=0, le=10)
    relevance: int = Field(ge=0, le=10)
    completeness: int = Field(ge=0, le=10)
    instruction_following: int = Field(ge=0, le=10)
    safety: int = Field(ge=0, le=10)

    def as_dict(self) -> dict[str, int]:
        return self.model_dump()


class EvaluationIssue(StrictModel):
    criterion: str
    severity: Literal["minor", "major", "critical"] = "minor"
    detail: str = ""


class EvaluationResult(StrictModel):
    """Structured verdict. Contains only concise reasons — never chain-of-thought."""

    approved: bool
    scores: EvaluationScores
    overall_score: float = Field(ge=0, le=100)
    issues: list[EvaluationIssue] = Field(default_factory=list)
    reasoning_summary: str = Field(default="", max_length=1200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    hallucination_risk: Literal["low", "medium", "high"] = "low"
    format_valid: bool = True

    @field_validator("overall_score")
    @classmethod
    def _round(cls, v: float) -> float:
        return round(float(v), 2)


class JudgeVerdict(StrictModel):
    judge: str
    model: str
    result: EvaluationResult


class ConsensusResult(StrictModel):
    mean_score: float
    median_score: float
    variance: float
    stdev: float
    agreement_rate: float
    disagreement: bool
    approved: bool
    final: EvaluationResult
    verdicts: list[JudgeVerdict] = Field(default_factory=list)


# --- Refiner -----------------------------------------------------------
class RefinementResult(StrictModel):
    problems_identified: list[str] = Field(default_factory=list, max_length=20)
    changes_made: list[str] = Field(default_factory=list, max_length=20)
    sample: GeneratedSample


# --- Approval ----------------------------------------------------------
class ApprovalReport(StrictModel):
    approved: bool
    schema_valid: bool
    required_fields_present: bool
    duplicate: bool
    quality_threshold_met: bool
    metadata_valid: bool
    sop_compliant: bool
    reasons: list[str] = Field(default_factory=list)
