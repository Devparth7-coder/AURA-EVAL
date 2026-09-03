"""Agent base class: telemetry, error normalisation, provider plumbing.

Agents contain prompt + contract logic only. They never touch the database or
HTTP; the orchestration layer supplies a `record` sink for telemetry (§34.9/34.10).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.core.errors import AgentExecutionError, AuraError
from app.core.logging import get_logger
from app.providers import LLMProvider, cost_for, get_provider
from app.providers.base import StructuredResponse

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class AgentTelemetry:
    """One durable record of an agent invocation."""

    id: str
    agent: str
    status: str
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
    attempt: int = 1
    sample_key: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class TelemetrySink(Protocol):
    def __call__(self, telemetry: AgentTelemetry) -> None: ...


@dataclass(slots=True)
class AgentContext:
    """Everything an agent needs, injected from the orchestration layer."""

    config: dict[str, Any] = field(default_factory=dict)
    sop: dict[str, Any] = field(default_factory=dict)
    record: TelemetrySink | None = None
    provider_override: LLMProvider | None = None

    def provider(self) -> LLMProvider:
        if self.provider_override is not None:
            return self.provider_override
        kwargs: dict[str, Any] = {}
        if (self.config.get("provider") or "mock") == "mock":
            kwargs["failure_rate"] = float(self.config.get("mock_failure_rate", 0.06))
            kwargs["quality_bias"] = float(self.config.get("quality_bias", 0.0))
        return get_provider(self.config.get("provider"), self.config.get("model"), **kwargs)

    def prompt_version(self, key: str) -> int | None:
        versions = self.config.get("prompt_versions") or {}
        v = versions.get(key)
        return int(v) if v else None


@dataclass(slots=True)
class AgentResult[TModel: BaseModel]:
    data: TModel
    telemetry: AgentTelemetry


class Agent:
    name: str = "agent"
    prompt_key: str = ""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    # -- telemetry helpers ----------------------------------------------
    def _emit(self, t: AgentTelemetry) -> None:
        if self.ctx.record:
            self.ctx.record(t)

    async def call_structured[TModel: BaseModel](
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str,
        input_summary: dict[str, Any],
        prompt_version: int,
        sample_key: str | None = None,
        temperature: float | None = None,
        provider: LLMProvider | None = None,
        max_tokens: int = 3000,
    ) -> AgentResult[TModel]:
        """Run a structured LLM call and always produce a telemetry record."""
        llm = provider or self.ctx.provider()
        temp = self.ctx.config.get("temperature", 0.3) if temperature is None else temperature
        started = time.perf_counter()
        tel_id = str(uuid.uuid4())
        try:
            res: StructuredResponse[TModel] = await llm.structured_generate(
                prompt, schema, system=system, temperature=float(temp), max_tokens=max_tokens
            )
        except AuraError as exc:
            latency = int((time.perf_counter() - started) * 1000)
            tel = AgentTelemetry(
                id=tel_id,
                agent=self.name,
                status="FAILED",
                provider=llm.name,
                model=llm.model,
                prompt_key=self.prompt_key,
                prompt_version=prompt_version,
                input_json=input_summary,
                output_json={},
                latency_ms=latency,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                sample_key=sample_key,
                error_type=exc.code,
                error_message=str(exc)[:1000],
            )
            self._emit(tel)
            raise AgentExecutionError(
                f"{self.name} failed: {exc.code}", agent=self.name, cause=exc.code
            ) from exc

        raw = res.raw
        tel = AgentTelemetry(
            id=tel_id,
            agent=self.name,
            status="DEGRADED" if raw.degraded else "SUCCESS",
            provider=raw.provider,
            model=raw.model,
            prompt_key=self.prompt_key,
            prompt_version=prompt_version,
            input_json=input_summary,
            output_json=res.data.model_dump(mode="json"),
            latency_ms=raw.latency_ms,
            input_tokens=raw.usage.input_tokens,
            output_tokens=raw.usage.output_tokens,
            cost_usd=cost_for(raw.model, raw.usage),
            attempt=raw.attempts,
            sample_key=sample_key,
        )
        self._emit(tel)
        return AgentResult(data=res.data, telemetry=tel)

    def local_telemetry(
        self,
        *,
        status: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any],
        latency_ms: int,
        sample_key: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> AgentTelemetry:
        """Telemetry for agents that do deterministic local work (no LLM)."""
        tel = AgentTelemetry(
            id=str(uuid.uuid4()),
            agent=self.name,
            status=status,
            provider="local",
            model="deterministic",
            prompt_key=self.prompt_key,
            prompt_version=0,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            sample_key=sample_key,
            error_type=error_type,
            error_message=error_message,
        )
        self._emit(tel)
        return tel


def timed[R](fn: Callable[[], R]) -> tuple[R, int]:
    start = time.perf_counter()
    out = fn()
    return out, int((time.perf_counter() - start) * 1000)
