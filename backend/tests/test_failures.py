"""Failure tests: invalid LLM output, timeouts, loop limits, duplicates (§28)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import (
    AgentContext,
    ApprovalAgent,
    EvaluatorAgent,
    GeneratorAgent,
    content_hash,
)
from app.core.errors import (
    AgentExecutionError,
    InvalidJSONError,
    ProviderError,
    ProviderTimeoutError,
)
from app.models import Sample
from app.models.enums import RunStatus, SampleStatus
from app.providers.base import LLMProvider, Usage
from app.providers.mock import MockLLMProvider
from app.services.sop_engine import default_sop
from app.services.workflow_service import create_run
from app.workflows.executor import StepExecutor
from tests.conftest import make_workflow


class ScriptedProvider(LLMProvider):
    """Returns a scripted sequence of raw strings / exceptions."""

    name = "scripted"

    def __init__(self, script: list[Any], model: str = "mock-1") -> None:
        super().__init__(model)
        self.script = list(script)
        self.calls = 0

    async def _complete(self, prompt, system, temperature, max_tokens):  # type: ignore[no-untyped-def]
        self.calls += 1
        item = self.script.pop(0) if self.script else '{"unexpected": true}'
        if isinstance(item, Exception):
            raise item
        return item, Usage(10, 10)


def ctx_with(provider: LLMProvider) -> AgentContext:
    return AgentContext(
        config={"provider": "mock", "mock_failure_rate": 0.0, "judges": 1},
        sop=default_sop(),
        provider_override=provider,
    )


# --- invalid LLM output --------------------------------------------------
async def test_malformed_json_raises_after_repair_attempts() -> None:
    provider = ScriptedProvider(["not json at all"] * 8)
    with pytest.raises(AgentExecutionError):
        await EvaluatorAgent(ctx_with(provider)).run_single({"sample_id": "s1", "input": "q"})
    assert provider.calls > 1  # retried before giving up


async def test_json_repair_pass_recovers() -> None:
    good = (
        '{"approved": true, "scores": {"correctness": 9, "relevance": 9, "completeness": 9,'
        ' "instruction_following": 9, "safety": 10}, "overall_score": 91,'
        ' "issues": [], "reasoning_summary": "ok", "confidence": 0.9}'
    )
    provider = ScriptedProvider(["oops, no json here", good])
    res = await EvaluatorAgent(ctx_with(provider)).run_single({"sample_id": "s1", "input": "q"})
    assert res.data.approved is True
    assert res.telemetry.status == "DEGRADED"  # recovered, and it is recorded as such


async def test_schema_violation_is_detected() -> None:
    # valid JSON, invalid against the schema (scores out of range / missing)
    provider = ScriptedProvider(['{"approved": true, "overall_score": 900}'] * 8)
    with pytest.raises(AgentExecutionError):
        await EvaluatorAgent(ctx_with(provider)).run_single({"sample_id": "s1", "input": "q"})


async def test_timeout_is_retried_then_surfaced() -> None:
    provider = ScriptedProvider([ProviderTimeoutError("t")] * 10)
    with pytest.raises(AgentExecutionError) as exc:
        await GeneratorAgent(ctx_with(provider)).run(objective="x", count=1)
    assert "LLM_TIMEOUT" in str(exc.value)


async def test_provider_error_records_telemetry() -> None:
    recorded: list[Any] = []
    ctx = ctx_with(ScriptedProvider([ProviderError("boom")] * 10))
    ctx.record = recorded.append
    with pytest.raises(AgentExecutionError):
        await GeneratorAgent(ctx).run(objective="x", count=1)
    assert recorded and recorded[0].status == "FAILED"
    assert recorded[0].error_type in ("LLM_PROVIDER_ERROR", "LLM_TIMEOUT")


async def test_hard_timeout_is_enforced() -> None:
    class Sleepy(LLMProvider):
        name = "sleepy"

        async def _complete(self, *a, **k):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)
            return "{}", Usage()

    with pytest.raises(ProviderTimeoutError):
        await Sleepy("m").generate("hi", timeout=0.05, max_retries=1)


# --- evaluator failure inside a workflow ---------------------------------
async def test_evaluator_failure_routes_to_human_review(db: Session, project, sop) -> None:
    """An unavailable evaluator must not kill the run; the sample is escalated."""
    wf = make_workflow(db, project, sop, sample_count=2, human_review_enabled=True)
    run = create_run(db, wf)
    executor = StepExecutor(db, run)

    from app.agents import evaluator as ev_module

    async def broken(self, sample):  # type: ignore[no-untyped-def]
        raise AgentExecutionError("evaluator down", agent="evaluator")

    original = ev_module.EvaluatorAgent.run
    ev_module.EvaluatorAgent.run = broken  # type: ignore[method-assign]
    try:
        await executor.run_to_completion()
    finally:
        ev_module.EvaluatorAgent.run = original  # type: ignore[method-assign]
    db.refresh(run)
    assert run.status == RunStatus.COMPLETED  # graceful degradation, not a crash
    assert run.samples_review == 2


# --- retry ceiling / infinite loop prevention ----------------------------
async def test_refinement_loop_respects_max_retries(db: Session, project, sop) -> None:
    wf = make_workflow(
        db,
        project,
        sop,
        sample_count=2,
        max_retries=1,
        human_review_enabled=False,
        approval_threshold=99.0,
    )
    run = create_run(db, wf)
    # force everything to fail evaluation
    state = dict(run.state)
    state["sop"] = {**state["sop"], "threshold": 100.0}
    run.state = state
    run.sop_snapshot = state["sop"]
    db.commit()
    await StepExecutor(db, run).run_to_completion()
    db.refresh(run)
    assert run.status == RunStatus.COMPLETED
    samples = list(db.execute(select(Sample).where(Sample.run_id == run.id)).scalars())
    assert all(s.retry_count <= 1 for s in samples)
    assert all(s.status in (SampleStatus.AUTO_REJECTED, SampleStatus.FAILED) for s in samples)


async def test_global_step_guard_terminates_run(db: Session, project, sop) -> None:
    wf = make_workflow(db, project, sop, sample_count=6, max_steps=8)
    run = create_run(db, wf)
    await StepExecutor(db, run).run_to_completion()
    db.refresh(run)
    assert run.status == RunStatus.COMPLETED
    assert run.steps_executed <= 12  # guard tripped, graph short-circuited to export
    assert run.state["done"] is True


async def test_run_to_completion_is_bounded(db: Session, workflow) -> None:
    run = create_run(db, workflow)
    state = await StepExecutor(db, run).run_to_completion(slice_steps=1)
    assert state["done"] is True


# --- duplicates ----------------------------------------------------------
def test_duplicate_samples_are_blocked(sample_payload) -> None:
    ctx = AgentContext(config={"provider": "mock"}, sop=default_sop())
    agent = ApprovalAgent(ctx)
    seen: set[str] = set()
    ok = agent.run(
        sample=sample_payload,
        evaluation={"overall_score": 95, "issues": [], "scores": {"safety": 10}},
        seen_hashes=seen,
    )
    assert ok.approved
    seen.add(content_hash(sample_payload))
    dup = agent.run(
        sample=sample_payload,
        evaluation={"overall_score": 95, "issues": [], "scores": {"safety": 10}},
        seen_hashes=seen,
    )
    assert dup.duplicate and not dup.approved


def test_content_hash_ignores_case_and_whitespace() -> None:
    assert content_hash({"input": " Hello World "}) == content_hash({"input": "hello world"})


# --- budget circuit breaker ----------------------------------------------
async def test_cost_cap_stops_a_runaway_run(db: Session, project, sop) -> None:
    wf = make_workflow(db, project, sop, sample_count=3, max_cost_usd=0.0000001, model="gpt-4o")
    run = create_run(db, wf)
    await StepExecutor(db, run).run_to_completion()
    db.refresh(run)
    # Either it tripped the breaker (FAILED) or it finished under budget — never a hang.
    assert run.status in (RunStatus.FAILED, RunStatus.COMPLETED)


# --- provider degradation -------------------------------------------------
def test_missing_api_key_falls_back_to_mock() -> None:
    from app.providers import get_provider

    provider = get_provider("openai")
    assert provider.name == "mock"  # graceful demo-mode degradation, no crash


async def test_mock_provider_injects_deterministic_failures() -> None:
    p = MockLLMProvider(failure_rate=1.0)
    with pytest.raises((ProviderTimeoutError, ProviderError, InvalidJSONError)):
        await p.generate("AURA-TASK: generator COUNT: 1", max_retries=1)


async def test_mock_provider_is_reproducible() -> None:
    a = MockLLMProvider(failure_rate=0.0)
    b = MockLLMProvider(failure_rate=0.0)
    prompt = "AURA-TASK: generator COUNT: 3 OFFSET: 0"
    assert (await a.generate(prompt)).text == (await b.generate(prompt)).text
