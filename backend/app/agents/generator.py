"""Generator Agent (§1)."""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, AgentResult
from app.agents.prompts import SYSTEM_BASE, get_prompt
from app.schemas.agents import GeneratedSample, GenerationBatch


class GeneratorAgent(Agent):
    name = "generator"
    prompt_key = "generator"

    async def run(
        self,
        *,
        objective: str,
        count: int,
        offset: int = 0,
        required_fields: list[str] | None = None,
        existing_inputs: list[str] | None = None,
        instructions: str = "",
    ) -> AgentResult[GenerationBatch]:
        version = self.ctx.prompt_version("generator")
        tpl = get_prompt("generator", version)
        prompt = tpl.render(
            objective=objective,
            domain=self.ctx.config.get("domain_hint", "general"),
            fields=", ".join(required_fields or ["input", "response", "category", "difficulty"]),
            instructions=instructions or self.ctx.config.get("generation_instructions", ""),
            count=str(count),
            offset=str(offset),
            existing="; ".join((existing_inputs or [])[-25:]),
        )
        return await self.call_structured(
            prompt,
            GenerationBatch,
            system=SYSTEM_BASE,
            input_summary={"objective": objective, "count": count, "offset": offset},
            prompt_version=tpl.version,
            temperature=float(self.ctx.config.get("temperature", 0.6)),
            max_tokens=4000,
        )


def attach_metadata(
    sample: GeneratedSample, *, sample_key: str, run_id: str, plan_objective: str
) -> dict[str, Any]:
    """Every generated sample carries provenance metadata (§1)."""
    payload = sample.model_dump(mode="json")
    payload["sample_id"] = sample_key
    payload["metadata"] = {
        "run_id": run_id,
        "objective": plan_objective,
        "generator_version": 1,
        "source": "generator",
    }
    return payload
