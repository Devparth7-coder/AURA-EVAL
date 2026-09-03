"""Planner Agent (§8)."""

from __future__ import annotations

from app.agents.base import Agent, AgentResult
from app.agents.prompts import SYSTEM_BASE, get_prompt
from app.schemas.agents import WorkflowPlan
from app.services.sop_engine import render_sop


class PlannerAgent(Agent):
    name = "planner"
    prompt_key = "planner"

    async def run(self, objective: str, sample_count: int) -> AgentResult[WorkflowPlan]:
        version = self.ctx.prompt_version("planner")
        prompt_tpl = get_prompt("planner", version)
        prompt = prompt_tpl.render(
            objective=objective or "Create a high-quality evaluation dataset",
            domain=self.ctx.config.get("domain_hint", "general"),
            sample_count=str(sample_count),
            sop=render_sop(self.ctx.sop),
        )
        result = await self.call_structured(
            prompt,
            WorkflowPlan,
            system=SYSTEM_BASE,
            input_summary={"objective": objective, "sample_count": sample_count},
            prompt_version=prompt_tpl.version,
            temperature=0.2,
        )
        plan = result.data
        # The plan is advisory: the workflow config is authoritative for count.
        plan.sample_count = sample_count
        plan.difficulty_distribution = _rebalance(plan.difficulty_distribution, sample_count)
        return AgentResult(data=plan, telemetry=result.telemetry)

    def fallback(self, objective: str, sample_count: int, reason: str) -> WorkflowPlan:
        """Graceful degradation: a deterministic plan when the LLM is unavailable."""
        self.local_telemetry(
            status="DEGRADED",
            input_json={"objective": objective, "sample_count": sample_count},
            output_json={"fallback": True, "reason": reason},
            latency_ms=0,
            error_type="PLANNER_FALLBACK",
            error_message=reason[:500],
        )
        return WorkflowPlan(
            objective=objective or "Create a high-quality evaluation dataset",
            subtasks=["Generate samples", "Evaluate samples", "Refine rejects", "Export dataset"],
            sample_count=sample_count,
            difficulty_distribution=_rebalance({}, sample_count),
            notes=f"Deterministic fallback plan ({reason}).",
        )


def _rebalance(dist: dict[str, int], total: int) -> dict[str, int]:
    if not dist:
        easy = round(total * 0.3)
        hard = round(total * 0.2)
        return {"easy": easy, "medium": max(0, total - easy - hard), "hard": hard}
    scale = total / max(1, sum(dist.values()))
    out = {k: max(0, int(round(v * scale))) for k, v in dist.items()}
    drift = total - sum(out.values())
    if out:
        key = max(out, key=lambda k: out[k])
        out[key] = max(0, out[key] + drift)
    return out
