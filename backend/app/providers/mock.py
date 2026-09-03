"""Deterministic mock provider (§26).

The platform must be fully usable with no API key: this provider produces
realistic, *seeded* agent outputs so the UI, the workflow engine and CI all
behave identically on every run. It also injects deterministic failures so the
reliability/failure-analysis features have real data to show.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from app.core.errors import InvalidJSONError, ProviderError, ProviderTimeoutError
from app.providers.base import LLMProvider, Usage, estimate_tokens

TOPICS: dict[str, list[tuple[str, str]]] = {
    "default": [
        ("Explain TCP congestion control.", "Computer Networks"),
        ("What is the CAP theorem and why does it matter?", "Distributed Systems"),
        ("Describe how a B-tree index speeds up lookups.", "Databases"),
        ("Explain the difference between processes and threads.", "Operating Systems"),
        ("What is gradient descent and why does the learning rate matter?", "Machine Learning"),
        ("How does HTTPS establish a secure channel?", "Security"),
        ("Explain eventual consistency with an example.", "Distributed Systems"),
        ("What causes a deadlock and how can it be prevented?", "Operating Systems"),
        ("Describe the purpose of a write-ahead log.", "Databases"),
        ("Explain why floating point comparison can be unsafe.", "Programming"),
        ("What is the difference between L1 and L2 regularization?", "Machine Learning"),
        ("How does a bloom filter trade accuracy for space?", "Algorithms"),
    ],
    "python": [
        ("Write a function that reverses a linked list.", "Data Structures"),
        ("Explain Python's GIL and its impact on threading.", "Python Runtime"),
        ("Implement an LRU cache with O(1) operations.", "Algorithms"),
        ("How do you safely parse untrusted JSON in Python?", "Security"),
        ("Explain list comprehension vs generator expression.", "Python Basics"),
        ("Write a decorator that retries with exponential backoff.", "Patterns"),
        ("What does asyncio.gather do and when does it fail?", "Concurrency"),
        ("Explain dataclasses vs NamedTuple vs Pydantic models.", "Modelling"),
    ],
}

DIFFICULTIES = ["easy", "medium", "hard"]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


class MockLLMProvider(LLMProvider):
    """Seeded, offline provider. Same prompt → same output, always."""

    name = "mock"

    def __init__(
        self,
        model: str = "mock-1",
        api_key: str | None = None,
        *,
        failure_rate: float = 0.06,
        quality_bias: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, api_key, **kwargs)
        self.failure_rate = failure_rate
        self.quality_bias = quality_bias

    # -- helpers --------------------------------------------------------
    def _rng(self, prompt: str) -> random.Random:
        return random.Random(_seed(prompt + self.model))

    def _maybe_fail(self, rng: random.Random, prompt: str) -> None:
        if self.failure_rate <= 0:
            return
        roll = rng.random()
        if roll < self.failure_rate * 0.4:
            raise ProviderTimeoutError("mock provider simulated timeout")
        if roll < self.failure_rate * 0.7:
            raise ProviderError("mock provider simulated 503 upstream error")
        if roll < self.failure_rate:
            raise InvalidJSONError("mock provider returned malformed JSON")

    # -- vendor hook ----------------------------------------------------
    async def _complete(
        self, prompt: str, system: str | None, temperature: float, max_tokens: int
    ) -> tuple[str, Usage]:
        rng = self._rng(prompt)
        self._maybe_fail(rng, prompt)
        body = self._route(prompt, rng)
        text = json.dumps(body)
        usage = Usage(
            input_tokens=estimate_tokens(prompt + (system or "")),
            output_tokens=estimate_tokens(text),
        )
        return text, usage

    # -- deterministic content ------------------------------------------
    def _route(self, prompt: str, rng: random.Random) -> Any:
        p = prompt.lower()
        if "aura-task: planner" in p:
            return self._plan(prompt, rng)
        if "aura-task: generator" in p:
            return self._generate(prompt, rng)
        if "aura-task: evaluator" in p:
            return self._evaluate(prompt, rng)
        if "aura-task: refiner" in p:
            return self._refine(prompt, rng)
        return {"text": "mock response", "ok": True}

    def _domain(self, prompt: str) -> str:
        return "python" if "python" in prompt.lower() or "coding" in prompt.lower() else "default"

    def _plan(self, prompt: str, rng: random.Random) -> dict[str, Any]:
        count = 6
        for token in prompt.split():
            if token.isdigit():
                count = max(1, min(int(token), 500))
                break
        easy = round(count * 0.3)
        hard = round(count * 0.2)
        return {
            "objective": _extract_field(prompt, "OBJECTIVE") or "Build an evaluation dataset",
            "subtasks": [
                "Clarify the target capability and dataset schema",
                "Generate diverse candidate samples across difficulty bands",
                "Evaluate every sample against the active SOP",
                "Refine rejected samples and re-evaluate",
                "Validate, deduplicate and export the approved dataset",
            ],
            "sample_count": count,
            "required_fields": ["input", "response", "category", "difficulty"],
            "difficulty_distribution": {
                "easy": easy,
                "medium": max(0, count - easy - hard),
                "hard": hard,
            },
            "evaluation_dimensions": [
                "correctness",
                "relevance",
                "completeness",
                "instruction_following",
                "safety",
            ],
            "notes": "Deterministic plan produced by the mock provider (demo mode).",
        }

    def _generate(self, prompt: str, rng: random.Random) -> dict[str, Any]:
        n = 1
        marker = "COUNT:"
        if marker in prompt:
            try:
                n = int(prompt.split(marker, 1)[1].split()[0])
            except (ValueError, IndexError):
                n = 1
        offset = 0
        if "OFFSET:" in prompt:
            try:
                offset = int(prompt.split("OFFSET:", 1)[1].split()[0])
            except (ValueError, IndexError):
                offset = 0
        pool = TOPICS[self._domain(prompt)]
        samples = []
        for i in range(n):
            idx = (offset + i) % len(pool)
            question, category = pool[idx]
            quality = rng.random() + self.quality_bias
            samples.append(
                {
                    "input": question,
                    "response": _mock_answer(question, category, quality),
                    "category": category,
                    "difficulty": DIFFICULTIES[(offset + i) % 3],
                    "reference": _mock_reference(question, category),
                    "tags": [category.lower().replace(" ", "-")],
                }
            )
        return {"samples": samples}

    def _evaluate(self, prompt: str, rng: random.Random) -> dict[str, Any]:
        # Quality is derived deterministically from the sample text so that a
        # refined sample scores strictly better than the version it replaced.
        body = _extract_field(prompt, "SAMPLE") or prompt
        base = (_seed(body) % 40) + 55  # 55..94
        if "[refined" in body.lower():
            base = min(98, base + 18)
        if "incomplete" in body.lower() or len(body) < 220:
            base -= 12
        base = max(5, min(99, int(base + self.quality_bias * 10)))
        judge = _extract_field(prompt, "JUDGE") or "A"
        jitter = {"A": 0, "B": 3, "C": -3}.get(judge.strip()[:1].upper(), 0)
        overall = max(1, min(100, base + jitter))

        def dim(shift: int) -> int:
            return max(0, min(10, round((overall + shift) / 10)))

        issues: list[dict[str, str]] = []
        if overall < 75:
            issues.append(
                {
                    "criterion": "completeness",
                    "severity": "major" if overall < 60 else "minor",
                    "detail": "The answer omits the mechanism and a concrete example.",
                }
            )
        if overall < 62:
            issues.append(
                {
                    "criterion": "correctness",
                    "severity": "major",
                    "detail": "One claim is not supported by the reference material.",
                }
            )
        return {
            "approved": overall >= 75,
            "scores": {
                "correctness": dim(0),
                "relevance": dim(6),
                "completeness": dim(-6),
                "instruction_following": dim(4),
                "safety": 10,
            },
            "overall_score": overall,
            "issues": issues,
            "reasoning_summary": (
                "Answer addresses the question and is technically sound."
                if overall >= 75
                else "Answer is on-topic but shallow; key mechanisms and examples are missing."
            ),
            "confidence": round(0.72 + (overall % 20) / 100, 2),
            "hallucination_risk": "low" if overall >= 70 else "medium",
            "format_valid": True,
        }

    def _refine(self, prompt: str, rng: random.Random) -> dict[str, Any]:
        original = _extract_field(prompt, "SAMPLE") or "{}"
        try:
            payload = json.loads(original)
        except json.JSONDecodeError:
            payload = {"input": "unknown", "response": original}
        response = str(payload.get("response", ""))
        payload["response"] = (
            f"[refined] {response} It additionally explains the underlying mechanism "
            "step by step, states the assumptions explicitly, and gives a worked example "
            "so the reader can verify the claim independently."
        )
        return {
            "problems_identified": [
                "Missing mechanism-level explanation",
                "No concrete example supporting the claim",
            ],
            "changes_made": [
                "Added a step-by-step mechanism walkthrough",
                "Added a worked example and explicit assumptions",
            ],
            "sample": payload,
        }


def _extract_field(prompt: str, field: str) -> str | None:
    tag = f"<{field}>"
    end = f"</{field}>"
    if tag in prompt and end in prompt:
        return prompt.split(tag, 1)[1].split(end, 1)[0].strip()
    return None


def _mock_answer(question: str, category: str, quality: float) -> str:
    core = (
        f"{question.rstrip('?.')} is a core {category.lower()} concept. "
        "At a high level the system observes signals, adapts its behaviour to the "
        "observed conditions, and converges to a stable operating point."
    )
    if quality > 0.45:
        core += (
            " Concretely, the mechanism proceeds in phases: an initial exploratory phase, "
            "a steady-state phase governed by feedback, and a recovery phase triggered by "
            "loss or error signals. For example, a client that detects congestion halves "
            "its window and then grows it linearly, which keeps throughput high while "
            "remaining fair to competing flows."
        )
    else:
        core += " It is widely used in practice."
    return core


def _mock_reference(question: str, category: str) -> str:
    return (
        f"Reference answer for '{question}' ({category}): the canonical explanation covers "
        "the mechanism, the trade-offs involved, and at least one concrete example."
    )
