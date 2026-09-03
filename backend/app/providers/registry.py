"""Provider registry / factory. Keys come only from the environment (§9, §24)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.errors import ProviderError
from app.providers.base import LLMProvider
from app.providers.mock import MockLLMProvider
from app.providers.remote import AnthropicProvider, GeminiProvider, OpenAIProvider

_DEFAULT_MODELS = {
    "mock": "mock-1",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-3-5-haiku-latest",
}

_BUILDERS: dict[str, Callable[..., LLMProvider]] = {
    "mock": MockLLMProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
}


def register_provider(name: str, builder: Callable[..., LLMProvider], default_model: str) -> None:
    """Extension point for future providers."""
    _BUILDERS[name] = builder
    _DEFAULT_MODELS[name] = default_model


def available_providers() -> list[str]:
    return sorted(_BUILDERS)


def _key_for(name: str) -> str | None:
    return {
        "openai": settings.openai_api_key,
        "gemini": settings.google_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(name)


def provider_is_configured(name: str) -> bool:
    return name == "mock" or bool(_key_for(name))


def get_provider(name: str | None = None, model: str | None = None, **kwargs: Any) -> LLMProvider:
    name = (name or settings.llm_provider).lower()
    if name not in _BUILDERS:
        raise ProviderError(f"unknown provider '{name}'")
    key = _key_for(name)
    if name != "mock" and not key:
        # Graceful degradation: never break a demo because a key is absent (§26).
        name, key = "mock", None
        model = _DEFAULT_MODELS["mock"]
    model = (
        model
        or (settings.llm_model if name == settings.llm_provider else None)
        or _DEFAULT_MODELS[name]
    )
    return _BUILDERS[name](model=model, api_key=key, **kwargs)
