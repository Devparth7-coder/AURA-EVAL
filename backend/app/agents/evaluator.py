"""Critic / Evaluator Agent + multi-judge consensus engine (§2, §20)."""

from __future__ import annotations

import asyncio
import json
import statistics
from typing import Any

from app.agents.base import Agent, AgentResult
from app.agents.prompts import SYSTEM_BASE, get_prompt
from app.core.config import settings
from app.core.errors import AgentExecutionError
from app.providers import get_provider
from app.schemas.agents import (
    ConsensusResult,
    EvaluationIssue,
    EvaluationResult,
    EvaluationScores,
    JudgeVerdict,
)
from app.services.sop_engine import normalise_sop, render_sop, weighted_overall

JUDGE_LABELS = ["A", "B", "C", "D", "E"]


class EvaluatorAgent(Agent):
    name = "evaluator"
    prompt_key = "evaluator"

    async def run_single(
        self, sample: dict[str, Any], judge: str = "A", model: str | None = None
    ) -> AgentResult[EvaluationResult]:
        sop = normalise_sop(self.ctx.sop)
        tpl = get_prompt("evaluator", self.ctx.prompt_version("evaluator"))
        prompt = tpl.render(
            judge=judge,
            sop=render_sop(sop),
            threshold=str(sop.get("threshold", 75.0)),
            sample=json.dumps(_core(sample), ensure_ascii=False),
        )
        provider = None
        if model:
            cfg = self.ctx.config
            kwargs: dict[str, Any] = {}
            if (cfg.get("provider") or "mock") == "mock":
                kwargs = {
                    "failure_rate": float(cfg.get("mock_failure_rate", 0.06)),
                    "quality_bias": float(cfg.get("quality_bias", 0.0)),
                }
            provider = get_provider(cfg.get("provider"), model, **kwargs)

        result = await self.call_structured(
            prompt,
            EvaluationResult,
            system=SYSTEM_BASE,
            input_summary={"sample_id": sample.get("sample_id"), "judge": judge},
            prompt_version=tpl.version,
            sample_key=sample.get("sample_id"),
            temperature=0.0,
            provider=provider,
            max_tokens=1800,
        )
        # Never trust the model's own arithmetic: recompute from dimensions (§34.3).
        ev = result.data
        recomputed = weighted_overall(ev.scores.as_dict(), sop)
        if abs(recomputed - ev.overall_score) > 8:
            ev.overall_score = recomputed
        ev.approved = ev.overall_score >= float(sop.get("threshold", 75.0)) and not any(
            i.severity == "critical" for i in ev.issues
        )
        return AgentResult(data=ev, telemetry=result.telemetry)

    async def run(self, sample: dict[str, Any]) -> ConsensusResult:
        """Run 1..N judges and reduce to a consensus verdict."""
        cfg = self.ctx.config
        n = max(1, min(int(cfg.get("judges", 1)), len(JUDGE_LABELS)))
        models: list[str | None] = list(cfg.get("judge_models") or [])
        while len(models) < n:
            models.append(None)

        tasks = [self.run_single(sample, judge=JUDGE_LABELS[i], model=models[i]) for i in range(n)]
        settled = await asyncio.gather(*tasks, return_exceptions=True)
        verdicts: list[JudgeVerdict] = []
        errors: list[str] = []
        for i, item in enumerate(settled):
            if isinstance(item, BaseException):
                errors.append(str(item))
                continue
            verdicts.append(
                JudgeVerdict(
                    judge=JUDGE_LABELS[i],
                    model=item.telemetry.model,
                    result=item.data,
                )
            )
        if not verdicts:
            raise AgentExecutionError(
                f"all {n} judges failed: {errors[0] if errors else 'unknown'}", agent=self.name
            )
        return build_consensus(verdicts, self.ctx.sop, cfg)


def build_consensus(
    verdicts: list[JudgeVerdict], sop: dict[str, Any] | None, config: dict[str, Any]
) -> ConsensusResult:
    scores = [v.result.overall_score for v in verdicts]
    mean = round(statistics.fmean(scores), 2)
    median = round(statistics.median(scores), 2)
    variance = round(statistics.pvariance(scores), 2) if len(scores) > 1 else 0.0
    stdev = round(variance**0.5, 2)
    approvals = [v.result.approved for v in verdicts]
    agreement = round(max(approvals.count(True), approvals.count(False)) / len(approvals), 3)
    threshold = float(normalise_sop(sop).get("threshold", 75.0))
    disagree_limit = float(
        config.get("judge_disagreement_threshold", settings.judge_disagreement_threshold)
    )
    disagreement = len(scores) > 1 and (stdev > disagree_limit or agreement < 1.0)

    dims = ["correctness", "relevance", "completeness", "instruction_following", "safety"]
    merged_scores = {
        d: int(round(statistics.fmean([getattr(v.result.scores, d) for v in verdicts])))
        for d in dims
    }
    issues: list[EvaluationIssue] = []
    seen: set[tuple[str, str]] = set()
    for v in verdicts:
        for issue in v.result.issues:
            key = (issue.criterion, issue.detail[:60])
            if key not in seen:
                seen.add(key)
                issues.append(issue)
    approved = mean >= threshold and not any(i.severity == "critical" for i in issues)
    risk_rank = {"low": 0, "medium": 1, "high": 2}
    worst_risk = max((v.result.hallucination_risk for v in verdicts), key=lambda r: risk_rank[r])

    final = EvaluationResult(
        approved=approved,
        scores=EvaluationScores(**merged_scores),
        overall_score=mean,
        issues=issues[:12],
        reasoning_summary=" | ".join(
            v.result.reasoning_summary for v in verdicts if v.result.reasoning_summary
        )[:1200],
        confidence=round(statistics.fmean([v.result.confidence for v in verdicts]), 2),
        hallucination_risk=worst_risk,
        format_valid=all(v.result.format_valid for v in verdicts),
    )
    return ConsensusResult(
        mean_score=mean,
        median_score=median,
        variance=variance,
        stdev=stdev,
        agreement_rate=agreement,
        disagreement=disagreement,
        approved=approved,
        final=final,
        verdicts=verdicts,
    )


def _core(sample: dict[str, Any]) -> dict[str, Any]:
    keys = ("sample_id", "input", "response", "category", "difficulty", "reference")
    return {k: sample.get(k) for k in keys if k in sample}
