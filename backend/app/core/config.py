"""Application configuration. All secrets come from the environment (§24, §45)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Application ---------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "AURA-EVAL"
    app_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # --- Database ------------------------------------------------------
    # Local dev falls back to SQLite so the platform boots with zero infra.
    # Production MUST supply a PostgreSQL URL (§42).
    database_url: str = "sqlite+pysqlite:///./aura_eval.db"
    db_echo: bool = False

    # --- Security ------------------------------------------------------
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    auth_enabled: bool = False  # authentication-ready, off by default in dev
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 120
    cron_secret: str | None = None  # Vercel Cron / QStash shared secret

    # --- LLM providers (never exposed to the frontend) -----------------
    llm_provider: Literal["mock", "openai", "gemini", "anthropic"] = "mock"
    llm_model: str = "mock-1"
    openai_api_key: str | None = None
    google_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 3
    llm_backoff_base: float = 0.4

    # --- Workflow limits (§7, §34) --------------------------------------
    max_retries: int = 3
    max_workflow_steps: int = 2000
    max_samples_per_run: int = 500
    max_cost_usd_per_run: float = 25.0
    default_slice_steps: int = 40
    borderline_low: float = 60.0
    borderline_high: float = 75.0
    approval_threshold: float = 70.0
    judge_disagreement_threshold: float = 12.0

    # --- Infrastructure abstractions ------------------------------------
    queue_provider: Literal["mock", "redis"] = "mock"
    redis_url: str | None = None
    storage_provider: Literal["local", "memory", "blob", "s3"] = "local"
    storage_dir: str = "./_storage"
    blob_read_write_token: str | None = None

    # --- Pricing (configurable, never hardcoded in business logic §25) ---
    pricing: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            # USD per 1M tokens
            "mock-1": {"input": 0.0, "output": 0.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
            "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
            "claude-3-5-haiku-latest": {"input": 0.80, "output": 4.00},
            "claude-3-5-sonnet-latest": {"input": 3.00, "output": 15.00},
        }
    )

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Managed providers hand out postgres:// which SQLAlchemy 2 rejects.
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_serverless(self) -> bool:
        import os

        return bool(os.getenv("VERCEL")) or self.environment == "production"

    def price_for(self, model: str) -> dict[str, float]:
        return self.pricing.get(model, {"input": 0.0, "output": 0.0})

    def safe_public_dict(self) -> dict[str, Any]:
        """Config safe to return over HTTP — contains no secrets."""
        return {
            "environment": self.environment,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "max_retries": self.max_retries,
            "approval_threshold": self.approval_threshold,
            "borderline": [self.borderline_low, self.borderline_high],
            "storage_provider": self.storage_provider,
            "queue_provider": self.queue_provider,
            "auth_enabled": self.auth_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
