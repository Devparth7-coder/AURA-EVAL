"""Task queue abstraction (§43).

The execution layer can be swapped (in-process task, Redis worker, Vercel cron)
without touching a single line of agent code.
"""

from __future__ import annotations

import abc
import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class TaskQueue(abc.ABC):
    name = "base"

    @abc.abstractmethod
    async def enqueue(self, task: str, payload: dict[str, Any]) -> str: ...

    @abc.abstractmethod
    async def get_status(self, task_id: str) -> dict[str, Any]: ...

    def register(self, task: str, handler: Handler) -> None:
        self._handlers[task] = handler  # type: ignore[attr-defined]


class MockTaskQueue(TaskQueue):
    """In-process asyncio execution. Perfect for local dev, tests and CI."""

    name = "mock"

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    async def enqueue(self, task: str, payload: dict[str, Any]) -> str:
        task_id = str(uuid.uuid4())
        handler = self._handlers.get(task)
        if handler is None:
            self._status[task_id] = {"state": "FAILED", "error": f"no handler for '{task}'"}
            return task_id
        self._status[task_id] = {"state": "QUEUED", "task": task}

        async def _run() -> None:
            self._status[task_id]["state"] = "RUNNING"
            try:
                await handler(payload)
                self._status[task_id]["state"] = "COMPLETED"
            except Exception as exc:
                log.exception("queue.task_failed task=%s", task)
                self._status[task_id].update(state="FAILED", error=type(exc).__name__)

        t = asyncio.create_task(_run())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return task_id

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def get_status(self, task_id: str) -> dict[str, Any]:
        return self._status.get(task_id, {"state": "UNKNOWN"})


class RedisTaskQueue(TaskQueue):
    """Production queue: pushes onto a Redis list consumed by an external worker.

    Falls back to in-process execution if redis is unreachable so a deployment
    without a worker still functions (degraded, but correct).
    """

    name = "redis"

    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.redis_url
        self._handlers: dict[str, Handler] = {}
        self._fallback = MockTaskQueue()

    async def enqueue(self, task: str, payload: dict[str, Any]) -> str:
        try:
            import redis.asyncio as redis  # type: ignore
        except ModuleNotFoundError:
            return await self._fallback_enqueue(task, payload)
        if not self.url:
            return await self._fallback_enqueue(task, payload)
        import json

        task_id = str(uuid.uuid4())
        try:
            client = redis.from_url(self.url)
            await client.lpush(
                "aura:tasks", json.dumps({"id": task_id, "task": task, "payload": payload})
            )
            await client.hset(f"aura:task:{task_id}", mapping={"state": "QUEUED"})
            await client.aclose()
            return task_id
        except Exception:
            log.warning("queue.redis_unavailable falling back to in-process execution")
            return await self._fallback_enqueue(task, payload)

    async def _fallback_enqueue(self, task: str, payload: dict[str, Any]) -> str:
        self._fallback._handlers = self._handlers
        return await self._fallback.enqueue(task, payload)

    async def get_status(self, task_id: str) -> dict[str, Any]:
        try:
            import redis.asyncio as redis  # type: ignore
        except ModuleNotFoundError:
            return await self._fallback.get_status(task_id)
        if not self.url:
            return await self._fallback.get_status(task_id)
        try:
            client = redis.from_url(self.url, decode_responses=True)
            data = await client.hgetall(f"aura:task:{task_id}")
            await client.aclose()
            return data or await self._fallback.get_status(task_id)
        except Exception:
            return await self._fallback.get_status(task_id)

    def register(self, task: str, handler: Handler) -> None:
        self._handlers[task] = handler


_queue: TaskQueue | None = None


def get_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = RedisTaskQueue() if settings.queue_provider == "redis" else MockTaskQueue()
    return _queue


def set_queue(q: TaskQueue | None) -> None:
    global _queue
    _queue = q
