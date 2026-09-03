"""Security, storage, queue and experiment tests (§24, §43, §44, §21)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.logging import redact
from app.core.security import (
    Principal,
    SlidingWindowLimiter,
    create_token,
    decode_token,
)
from app.models.enums import Role
from app.services.queue import MockTaskQueue
from app.services.storage import MemoryStorageProvider


# --- secrets never leak ---------------------------------------------------
def test_logging_redacts_secrets() -> None:
    assert "sk-abcdef1234567890" not in redact("key=sk-abcdef1234567890 leaked")
    assert "postgres" not in redact("postgresql://user:pw@host/db") or "REDACTED" in redact(
        "postgresql://user:pw@host/db"
    )
    assert "REDACTED" in redact('{"api_key": "supersecretvalue"}')


def test_public_config_contains_no_secrets() -> None:
    cfg = settings.safe_public_dict()
    blob = str(cfg).lower()
    for forbidden in ("api_key", "jwt_secret", "database_url", "token", "password"):
        assert forbidden not in blob


def test_provider_errors_never_include_the_key() -> None:
    from app.core.errors import ProviderError

    err = ProviderError("openai returned HTTP 401")
    assert "sk-" not in str(err)


# --- auth -----------------------------------------------------------------
def test_jwt_roundtrip() -> None:
    token = create_token("user@example.com", Role.EDITOR)
    body = decode_token(token)
    assert body["sub"] == "user@example.com" and body["role"] == Role.EDITOR


def test_tampered_token_rejected() -> None:
    token = create_token("user@example.com")
    with pytest.raises(UnauthorizedError):
        decode_token(token[:-4] + "aaaa")


def test_expired_token_rejected() -> None:
    with pytest.raises(UnauthorizedError):
        decode_token(create_token("u", expires_in=-10))


def test_rbac_enforced() -> None:
    Principal("u", Role.ADMIN).require(Role.EDITOR)  # ok
    with pytest.raises(ForbiddenError):
        Principal("u", Role.VIEWER).require(Role.EDITOR)


def test_rate_limiter_trips() -> None:
    limiter = SlidingWindowLimiter(limit=3, window=60)
    for _ in range(3):
        limiter.check("1.2.3.4")
    with pytest.raises(RateLimitedError):
        limiter.check("1.2.3.4")


def test_auth_required_when_enabled(client: TestClient) -> None:
    settings.auth_enabled = True
    try:
        assert client.get("/api/projects").status_code == 401
        token = create_token("admin@example.com", Role.ADMIN)
        ok = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        viewer = create_token("v@example.com", Role.VIEWER)
        denied = client.post(
            "/api/projects", json={"name": "nope"}, headers={"Authorization": f"Bearer {viewer}"}
        )
        assert denied.status_code == 403
    finally:
        settings.auth_enabled = False


# --- storage abstraction ---------------------------------------------------
async def test_storage_roundtrip() -> None:
    store = MemoryStorageProvider()
    await store.upload("a/b.jsonl", b'{"x":1}', "application/x-ndjson")
    assert await store.download("a/b.jsonl") == b'{"x":1}'
    await store.delete("a/b.jsonl")
    with pytest.raises(Exception):
        await store.download("a/b.jsonl")


# --- queue abstraction -----------------------------------------------------
async def test_mock_queue_executes_handler() -> None:
    q = MockTaskQueue()
    seen: list[str] = []

    async def handler(payload):  # type: ignore[no-untyped-def]
        seen.append(payload["v"])

    q.register("t", handler)
    task_id = await q.enqueue("t", {"v": "hello"})
    await q.drain()
    assert seen == ["hello"]
    assert (await q.get_status(task_id))["state"] == "COMPLETED"


async def test_queue_reports_failures() -> None:
    q = MockTaskQueue()

    async def bad(payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("nope")

    q.register("t", bad)
    tid = await q.enqueue("t", {})
    await q.drain()
    assert (await q.get_status(tid))["state"] == "FAILED"


# --- experiments -----------------------------------------------------------
async def test_experiment_comparison_report(db, project, sop) -> None:
    from app.models import Experiment, ExperimentArm
    from app.services.experiments import run_experiment

    exp = Experiment(
        project_id=project.id,
        name="A vs B",
        config={"sample_count": 3, "objective": "python dataset", "sop_id": str(sop.id)},
    )
    db.add(exp)
    db.flush()
    db.add(
        ExperimentArm(
            experiment_id=exp.id,
            label="Model A",
            provider="mock",
            model="mock-1",
            metrics={"quality_bias": 0.0},
        )
    )
    db.add(
        ExperimentArm(
            experiment_id=exp.id,
            label="Model B",
            provider="mock",
            model="mock-1",
            prompt_version=2,
            metrics={"quality_bias": 0.5},
        )
    )
    db.commit()
    result = await run_experiment(db, exp)
    assert result.status == "COMPLETED"
    report = result.report
    assert len(report["arms"]) == 2
    assert report["winner"] in ("Model A", "Model B")
    metrics = {row["metric"] for row in report["comparison"]}
    assert {"average_score", "correctness", "latency_s", "cost_usd"} <= metrics
    for row in report["comparison"]:
        assert set(row["values"]) == {"Model A", "Model B"}


# --- internal cron tick (§41 serverless resumability) --------------------
def test_internal_tick_open_in_non_production(client, workflow):
    """With no CRON_SECRET configured, dev/test environments may tick freely."""
    started = client.post(f"/api/workflows/{workflow.id}/run", json={"async_execution": True})
    assert started.status_code in (200, 202)

    res = client.post("/api/internal/tick")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["runs"], list)


def test_internal_tick_requires_secret_when_configured(client):
    from app.core.config import settings

    original = settings.cron_secret
    settings.cron_secret = "top-secret-tick"
    try:
        assert client.post("/api/internal/tick").status_code == 401
        assert (
            client.post("/api/internal/tick", headers={"x-cron-secret": "wrong"}).status_code == 401
        )
        assert (
            client.post(
                "/api/internal/tick", headers={"x-cron-secret": "top-secret-tick"}
            ).status_code
            == 200
        )
        # Vercel Cron sends the secret as a bearer token.
        assert (
            client.get(
                "/api/internal/tick", headers={"Authorization": "Bearer top-secret-tick"}
            ).status_code
            == 200
        )
    finally:
        settings.cron_secret = original


def test_internal_tick_drives_a_run_to_completion(client, workflow):
    """Repeated ticks must terminate — proof there is no infinite loop (§13)."""
    run_id = client.post(
        f"/api/workflows/{workflow.id}/run", json={"async_execution": True}
    ).json()["id"]

    status = "PENDING"
    for _ in range(60):
        status = client.get(f"/api/runs/{run_id}/status").json()["status"]
        if status in {"COMPLETED", "FAILED", "STOPPED"}:
            break
        client.post("/api/internal/tick")

    assert status == "COMPLETED"
