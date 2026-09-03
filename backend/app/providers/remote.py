"""HTTP adapters for OpenAI / Google Gemini / Anthropic (§9).

Implemented with plain `httpx` so no vendor SDK is required at import time and
the serverless bundle stays small. Adding a provider = subclass + registry entry.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ProviderError
from app.providers.base import LLMProvider, Usage, estimate_tokens


class _HTTPProvider(LLMProvider):
    base_url = ""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    def _require_key(self) -> str:
        if not self._api_key:
            raise ProviderError(f"missing API key for provider '{self.name}'")
        return self._api_key

    @staticmethod
    def _raise_for_status(resp: httpx.Response, name: str) -> None:
        if resp.status_code >= 400:
            # Never echo the response body verbatim: it can contain the key.
            raise ProviderError(f"{name} returned HTTP {resp.status_code}")


class OpenAIProvider(_HTTPProvider):
    name = "openai"
    base_url = "https://api.openai.com/v1/chat/completions"

    async def _complete(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> tuple[str, Usage]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with self._client() as client:
            resp = await client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self._require_key()}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        self._raise_for_status(resp, self.name)
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        u = data.get("usage") or {}
        return text, Usage(
            input_tokens=int(u.get("prompt_tokens", estimate_tokens(prompt))),
            output_tokens=int(u.get("completion_tokens", estimate_tokens(text))),
        )


class GeminiProvider(_HTTPProvider):
    name = "gemini"

    async def _complete(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> tuple[str, Usage]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        async with self._client() as client:
            resp = await client.post(
                url, headers={"x-goog-api-key": self._require_key()}, json=body
            )
        self._raise_for_status(resp, self.name)
        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError("gemini returned no candidate content") from exc
        u = data.get("usageMetadata") or {}
        return text, Usage(
            input_tokens=int(u.get("promptTokenCount", estimate_tokens(prompt))),
            output_tokens=int(u.get("candidatesTokenCount", estimate_tokens(text))),
        )


class AnthropicProvider(_HTTPProvider):
    name = "anthropic"
    base_url = "https://api.anthropic.com/v1/messages"

    async def _complete(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> tuple[str, Usage]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        async with self._client() as client:
            resp = await client.post(
                self.base_url,
                headers={
                    "x-api-key": self._require_key(),
                    "anthropic-version": "2023-06-01",
                },
                json=body,
            )
        self._raise_for_status(resp, self.name)
        data = resp.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts)
        u = data.get("usage") or {}
        return text, Usage(
            input_tokens=int(u.get("input_tokens", estimate_tokens(prompt))),
            output_tokens=int(u.get("output_tokens", estimate_tokens(text))),
        )
