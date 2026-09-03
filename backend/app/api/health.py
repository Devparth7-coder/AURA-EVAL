from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.database.session import get_engine
from app.providers import available_providers, provider_is_configured

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, Any]:
    db_ok = _db_ok()[0]
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
        "llm": "available" if provider_is_configured(settings.llm_provider) else "mock-only",
        "environment": settings.environment,
        "version": "1.0.0",
    }


@router.get("/database")
def health_database() -> dict[str, Any]:
    ok, latency, err = _db_ok()
    return {
        "status": "healthy" if ok else "unhealthy",
        "database": "connected" if ok else "unavailable",
        "latency_ms": latency,
        "dialect": get_engine().dialect.name,
        "error": err,
    }


@router.get("/llm")
def health_llm() -> dict[str, Any]:
    providers = {
        name: ("configured" if provider_is_configured(name) else "no-key")
        for name in available_providers()
    }
    return {
        "status": "healthy",
        "active_provider": settings.llm_provider,
        "active_model": settings.llm_model,
        "providers": providers,
        "demo_mode": settings.llm_provider == "mock"
        or not provider_is_configured(settings.llm_provider),
    }


@router.get("/config")
def public_config() -> dict[str, Any]:
    """Non-sensitive runtime config for the frontend. Never contains secrets."""
    return settings.safe_public_dict()


def _db_ok() -> tuple[bool, int, str | None]:
    start = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, int((time.perf_counter() - start) * 1000), None
    except Exception as exc:  # noqa: BLE001
        return False, int((time.perf_counter() - start) * 1000), type(exc).__name__
