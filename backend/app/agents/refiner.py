"""Reflection / Refinement Agent (§4)."""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import Agent, AgentResult
from app.agents.prompts import SYSTEM_BASE, get_prompt
from app.schemas.agents import RefinementResult
from app.services.sop_engine import render_sop


class RefinerAgent(Agent):
    name = "refiner"
    prompt_key = "refiner"

    async def run(
        self, *, sample: dict[str, Any], evaluation: dict[str, Any], attempt: int
    ) -> AgentResult[RefinementResult]:
        tpl = get_prompt("refiner", self.ctx.prompt_version("refiner"))
        issues = evaluation.get("issues") or []
        prompt = tpl.render(
            sample=json.dumps(_core(sample), ensure_ascii=False),
            feedback=str(evaluation.get("reasoning_summary", ""))[:1500],
            issues=json.dumps(issues, ensure_ascii=False)[:2000],
            sop=render_sop(self.ctx.sop),
            attempt=str(attempt),
        )
        return await self.call_structured(
            prompt,
            RefinementResult,
            system=SYSTEM_BASE,
            input_summary={
                "sample_id": sample.get("sample_id"),
                "attempt": attempt,
                "issue_count": len(issues),
            },
            prompt_version=tpl.version,
            sample_key=sample.get("sample_id"),
            temperature=0.3,
            max_tokens=3000,
        )


def _core(sample: dict[str, Any]) -> dict[str, Any]:
    keys = ("input", "response", "category", "difficulty", "reference", "tags")
    return {k: sample.get(k) for k in keys if k in sample}
