"""Unit tests: agent functions, scoring logic, SOP validation, transformation."""

from __future__ import annotations

import pytest

from app.agents import (
    AgentContext,
    ApprovalAgent,
    DatasetBuilderAgent,
    EvaluatorAgent,
    GeneratorAgent,
    PlannerAgent,
    RefinerAgent,
    attach_metadata,
    build_rows,
    content_hash,
    serialize,
)
from app.agents.evaluator import build_consensus
from app.providers.base import extract_json
from app.schemas.agents import (
    EvaluationResult,
    EvaluationScores,
    GeneratedSample,
    JudgeVerdict,
)
from app.services.sop_engine import (
    check_compliance,
    default_sop,
    normalise_sop,
    render_sop,
    weighted_overall,
)


@pytest.fixture()
def ctx() -> AgentContext:
    return AgentContext(
        config={"provider": "mock", "model": "mock-1", "mock_failure_rate": 0.0, "judges": 1},
        sop=default_sop(),
    )


# --- planner ------------------------------------------------------------
async def test_planner_returns_valid_plan(ctx: AgentContext) -> None:
    res = await PlannerAgent(ctx).run("Build a Python coding dataset", 10)
    assert res.data.sample_count == 10
    assert sum(res.data.difficulty_distribution.values()) == 10
    assert res.data.subtasks
    assert res.telemetry.agent == "planner"


def test_planner_fallback_is_deterministic(ctx: AgentContext) -> None:
    plan = PlannerAgent(ctx).fallback("objective", 5, "LLM_TIMEOUT")
    assert plan.sample_count == 5
    assert sum(plan.difficulty_distribution.values()) == 5


# --- generator ----------------------------------------------------------
async def test_generator_produces_requested_count(ctx: AgentContext) -> None:
    res = await GeneratorAgent(ctx).run(objective="python", count=3)
    assert len(res.data.samples) == 3
    assert all(s.input and s.response for s in res.data.samples)


async def test_generator_is_deterministic_in_mock_mode(ctx: AgentContext) -> None:
    a = await GeneratorAgent(ctx).run(objective="python", count=3)
    b = await GeneratorAgent(ctx).run(objective="python", count=3)
    assert [s.input for s in a.data.samples] == [s.input for s in b.data.samples]


def test_attach_metadata_adds_provenance() -> None:
    s = GeneratedSample(input="q", response="a")
    payload = attach_metadata(s, sample_key="sample_007", run_id="run-1", plan_objective="obj")
    assert payload["sample_id"] == "sample_007"
    assert payload["metadata"]["run_id"] == "run-1"


# --- evaluator / scoring ------------------------------------------------
async def test_evaluator_returns_structured_scores(ctx: AgentContext, sample_payload) -> None:
    consensus = await EvaluatorAgent(ctx).run(sample_payload)
    assert 0 <= consensus.mean_score <= 100
    assert set(consensus.final.scores.as_dict()) == {
        "correctness",
        "relevance",
        "completeness",
        "instruction_following",
        "safety",
    }
    assert consensus.final.reasoning_summary


async def test_multi_judge_consensus(ctx: AgentContext, sample_payload) -> None:
    ctx.config["judges"] = 3
    consensus = await EvaluatorAgent(ctx).run(sample_payload)
    assert len(consensus.verdicts) == 3
    assert consensus.variance >= 0
    assert 0 <= consensus.agreement_rate <= 1


def test_weighted_overall_scoring() -> None:
    perfect = dict.fromkeys(
        ["correctness", "relevance", "completeness", "instruction_following", "safety"], 10
    )
    assert weighted_overall(perfect) == 100.0
    zero = dict.fromkeys(perfect, 0)
    assert weighted_overall(zero) == 0.0
    assert 45 <= weighted_overall(dict.fromkeys(perfect, 5)) <= 55


def test_consensus_flags_disagreement() -> None:
    def verdict(judge: str, score: float) -> JudgeVerdict:
        return JudgeVerdict(
            judge=judge,
            model="mock-1",
            result=EvaluationResult(
                approved=score >= 75,
                scores=EvaluationScores(
                    correctness=int(score // 10),
                    relevance=8,
                    completeness=7,
                    instruction_following=8,
                    safety=10,
                ),
                overall_score=score,
                confidence=0.8,
            ),
        )

    result = build_consensus([verdict("A", 95), verdict("B", 40)], default_sop(), {})
    assert result.disagreement is True
    assert result.variance > 0


# --- SOP engine ---------------------------------------------------------
def test_sop_rendering_includes_every_rule() -> None:
    text = render_sop(default_sop())
    for rule in default_sop()["rules"]:
        assert rule["text"] in text


def test_sop_compliance_blocks_critical_issues() -> None:
    ok, reasons = check_compliance(
        {
            "overall_score": 95,
            "issues": [{"criterion": "safety", "severity": "critical", "detail": "unsafe"}],
            "scores": {"safety": 10},
        },
        default_sop(),
    )
    assert ok is False and reasons


def test_sop_compliance_below_threshold() -> None:
    ok, reasons = check_compliance(
        {"overall_score": 10, "issues": [], "scores": {"safety": 10}}, default_sop()
    )
    assert ok is False
    assert "threshold" in reasons[0]


def test_normalise_sop_fills_defaults() -> None:
    s = normalise_sop({"name": "custom"})
    assert s["rules"] and s["scoring"] and s["threshold"]


# --- approval -----------------------------------------------------------
def test_approval_accepts_good_sample(ctx: AgentContext, sample_payload) -> None:
    report = ApprovalAgent(ctx).run(
        sample=sample_payload,
        evaluation={"overall_score": 90, "issues": [], "scores": {"safety": 10}},
        seen_hashes=set(),
    )
    assert report.approved is True


def test_approval_detects_duplicates(ctx: AgentContext, sample_payload) -> None:
    report = ApprovalAgent(ctx).run(
        sample=sample_payload,
        evaluation={"overall_score": 90, "issues": [], "scores": {"safety": 10}},
        seen_hashes={content_hash(sample_payload)},
    )
    assert report.duplicate is True and report.approved is False


def test_approval_rejects_missing_fields(ctx: AgentContext, sample_payload) -> None:
    broken = {**sample_payload, "response": ""}
    report = ApprovalAgent(ctx).run(
        sample=broken,
        evaluation={"overall_score": 90, "issues": [], "scores": {"safety": 10}},
        seen_hashes=set(),
    )
    assert report.required_fields_present is False and report.approved is False


def test_approval_rejects_low_quality(ctx: AgentContext, sample_payload) -> None:
    report = ApprovalAgent(ctx).run(
        sample=sample_payload,
        evaluation={"overall_score": 20, "issues": [], "scores": {"safety": 10}},
        seen_hashes=set(),
    )
    assert report.quality_threshold_met is False


# --- dataset builder ----------------------------------------------------
def test_dataset_styles(sample_payload) -> None:
    items = [(sample_payload, {"overall_score": 91})]
    inst = build_rows(items, "instruction")[0]
    assert set(["instruction", "input", "output"]).issubset(inst)
    chat = build_rows(items, "chat")[0]
    assert chat["messages"][0]["role"] == "user"
    assert chat["messages"][1]["role"] == "assistant"
    ev = build_rows(items, "evaluation")[0]
    assert ev["score"] == 91 and ev["prompt"] and ev["reference"]


def test_serialisation_formats(sample_payload) -> None:
    rows = build_rows([(sample_payload, {"overall_score": 91})], "instruction")
    jsonl, media = serialize(rows, "jsonl")
    assert media == "application/x-ndjson" and jsonl.decode().count("\n") == 0
    csv_bytes, media = serialize(rows, "csv")
    assert media == "text/csv" and b"instruction" in csv_bytes
    js, media = serialize(rows, "json")
    assert media == "application/json" and js.strip().startswith(b"[")


def test_dataset_builder_agent(ctx: AgentContext, sample_payload) -> None:
    out = DatasetBuilderAgent(ctx).run(
        items=[(sample_payload, {"overall_score": 90})],
        style="chat",
        formats=["jsonl", "json"],
    )
    assert out["row_count"] == 1
    assert {a["format"] for a in out["artifacts"]} == {"jsonl", "json"}


# --- refiner ------------------------------------------------------------
async def test_refiner_improves_score(ctx: AgentContext, sample_payload) -> None:
    evaluator = EvaluatorAgent(ctx)
    weak = {**sample_payload, "response": "It is incomplete."}
    before = await evaluator.run(weak)
    refined = await RefinerAgent(ctx).run(
        sample=weak, evaluation=before.final.model_dump(), attempt=1
    )
    after = await evaluator.run({**weak, **refined.data.sample.model_dump()})
    assert after.mean_score > before.mean_score
    assert refined.data.problems_identified


# --- json extraction ----------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here is the result:\n{"a": 1}\nHope that helps.',
    ],
)
def test_extract_json_tolerates_wrappers(raw: str) -> None:
    assert extract_json(raw) == {"a": 1}
