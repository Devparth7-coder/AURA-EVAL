"""LLM provider abstraction (§9). Agents never import a vendor SDK directly."""

from __future__ import annotations

import abc
import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.errors import (
    InvalidJSONError,
    ProviderError,
    ProviderTimeoutError,
    SchemaViolationError,
)
from app.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class LLMResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    attempts: int = 1
    degraded: bool = False


@dataclass(slots=True)
class StructuredResponse[TModel: BaseModel]:
    data: TModel
    raw: LLMResponse


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 chars/token) for providers
    that do not report usage."""
    return max(1, len(text) // 4)


def cost_for(model: str, usage: Usage) -> float:
    price = settings.price_for(model)
    return round(
        usage.input_tokens / 1_000_000 * price.get("input", 0.0)
        + usage.output_tokens / 1_000_000 * price.get("output", 0.0),
        8,
    )


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Never trust raw LLM output (§34.3): tolerate fences and prose."""
    candidate = text.strip()
    m = _JSON_BLOCK.search(candidate)
    if m:
        candidate = m.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced object/array.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise InvalidJSONError("LLM response did not contain parsable JSON")


class LLMProvider(abc.ABC):
    """Base provider. Subclasses only implement `_complete`."""

    name: str = "base"

    def __init__(self, model: str, api_key: str | None = None, **kwargs: Any) -> None:
        self.model = model
        self._api_key = api_key
        self.options = kwargs

    # -- vendor specific ------------------------------------------------
    @abc.abstractmethod
    async def _complete(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> tuple[str, Usage]: ...

    # -- public API -----------------------------------------------------
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Retries with exponential backoff + jitter and a hard timeout (§34.5/34.6)."""
        retries = settings.llm_max_retries if max_retries is None else max_retries
        timeout = timeout or settings.llm_timeout_seconds
        started = time.perf_counter()
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                text, usage = await asyncio.wait_for(
                    self._complete(prompt, system, temperature, max_tokens), timeout=timeout
                )
                return LLMResponse(
                    text=text,
                    usage=usage,
                    model=self.model,
                    provider=self.name,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempt,
                    degraded=attempt > 1,
                )
            except TimeoutError as exc:
                last = ProviderTimeoutError(
                    f"{self.name} timed out after {timeout}s", provider=self.name
                )
                log.warning("llm.timeout attempt=%s provider=%s", attempt, self.name)
                _ = exc
            except ProviderError as exc:
                last = exc
                log.warning(
                    "llm.error attempt=%s provider=%s code=%s", attempt, self.name, exc.code
                )
            except Exception as exc:  # noqa: BLE001 - normalise vendor errors
                last = ProviderError(f"{self.name} call failed: {type(exc).__name__}")
                log.warning("llm.unexpected attempt=%s provider=%s", attempt, self.name)
            if attempt < retries:
                delay = settings.llm_backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(delay + random.random() * 0.1)
        raise last or ProviderError("LLM call failed")

    async def structured_generate[TModel: BaseModel](
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        repair_attempts: int = 1,
    ) -> StructuredResponse[TModel]:
        """Validate every structured response; one self-repair pass on failure (§34.4)."""
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        full = (
            f"{prompt}\n\n"
            "Respond with a single JSON object only. No markdown, no commentary.\n"
            "Do not include chain-of-thought; give concise summaries only.\n"
            f"It must validate against this JSON Schema:\n{schema_json}"
        )
        attempt_prompt = full
        total = Usage()
        last_raw: LLMResponse | None = None
        errors: list[str] = []
        for i in range(repair_attempts + 1):
            raw = await self.generate(
                attempt_prompt, system=system, temperature=temperature, max_tokens=max_tokens
            )
            total.input_tokens += raw.usage.input_tokens
            total.output_tokens += raw.usage.output_tokens
            last_raw = raw
            try:
                payload = extract_json(raw.text)
                model_obj = schema.model_validate(payload)
                raw.usage = total
                raw.degraded = raw.degraded or i > 0
                return StructuredResponse(data=model_obj, raw=raw)
            except InvalidJSONError as exc:
                errors.append(str(exc))
                attempt_prompt = (
                    f"{full}\n\nYour previous reply was not valid JSON. Return ONLY JSON."
                )
            except ValidationError as exc:
                errors.append(exc.errors(include_url=False).__str__()[:500])
                attempt_prompt = (
                    f"{full}\n\nYour previous reply failed schema validation with:\n"
                    f"{errors[-1]}\nReturn ONLY corrected JSON."
                )
        assert last_raw is not None
        raise SchemaViolationError(
            f"Structured output invalid after {repair_attempts + 1} attempts: {errors[-1][:300]}",
            provider=self.name,
        )
