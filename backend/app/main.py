"""FastAPI application factory (§11, §47, §48)."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.errors import AuraError
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.security import rate_limit
from app.database.session import get_engine, session_scope
from app.models import Base

log = get_logger(__name__)


def bootstrap_database() -> None:
    """Create tables + seed demo data when the schema is empty.

    Alembic owns migrations in production; this keeps zero-config local/demo
    startup working and is a no-op when the schema already exists.
    """
    try:
        Base.metadata.create_all(get_engine())
        with session_scope() as db:
            from app.services.seed import is_empty, seed_demo, seed_prompts

            seed_prompts(db)
            db.commit()
            if is_empty(db) and settings.environment != "test":
                seed_demo(db)
    except Exception:
        log.exception("bootstrap.failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    bootstrap_database()
    log.info("app.started environment=%s provider=%s", settings.environment, settings.llm_provider)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AURA-EVAL API",
        description="Autonomous Multi-Agent Evaluation & Dataset Generation Platform",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url="/api/redoc",
    )

    # CORS: explicit origins only — never "*" for a credentialed API (§47).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=3600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_ctx.set(rid)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = str(int((time.perf_counter() - start) * 1000))
        # Conservative hardening headers.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    # --- error handlers (§48) -----------------------------------------
    @app.exception_handler(AuraError)
    async def aura_error_handler(request: Request, exc: AuraError) -> JSONResponse:
        body = exc.to_dict()
        body["request_id"] = request_id_ctx.get()
        if exc.status_code >= 500:
            log.error("api.error code=%s path=%s", exc.code, request.url.path)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_FAILED",
                "message": "Request validation failed",
                "details": exc.errors(),
                "retryable": False,
                "request_id": request_id_ctx.get(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled path=%s", request.url.path)
        # Never leak internals/secrets to the client.
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "retryable": True,
                "request_id": request_id_ctx.get(),
            },
        )

    app.include_router(api_router, prefix=settings.api_prefix, dependencies=[Depends(rate_limit)])

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": "AURA-EVAL API",
            "version": "1.0.0",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
