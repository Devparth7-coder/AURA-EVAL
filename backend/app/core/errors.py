"""Typed application errors and API error envelope (§48)."""

from __future__ import annotations

from typing import Any


class AuraError(Exception):
    """Base error. `code` is a stable machine-readable identifier."""

    code = "INTERNAL_ERROR"
    status_code = 500
    retryable = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        body.update({k: v for k, v in self.context.items() if v is not None})
        return body


class NotFoundError(AuraError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationFailedError(AuraError):
    code = "VALIDATION_FAILED"
    status_code = 422


class ConflictError(AuraError):
    code = "CONFLICT"
    status_code = 409


class RateLimitedError(AuraError):
    code = "RATE_LIMITED"
    status_code = 429
    retryable = True


class UnauthorizedError(AuraError):
    code = "UNAUTHORIZED"
    status_code = 401


class ForbiddenError(AuraError):
    code = "FORBIDDEN"
    status_code = 403


# --- LLM / agent layer ------------------------------------------------
class ProviderError(AuraError):
    code = "LLM_PROVIDER_ERROR"
    status_code = 502
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "LLM_TIMEOUT"
    retryable = True


class InvalidJSONError(ProviderError):
    code = "INVALID_JSON"
    retryable = True


class SchemaViolationError(ProviderError):
    code = "SCHEMA_VIOLATION"
    retryable = True


class AgentExecutionError(AuraError):
    code = "AGENT_EXECUTION_FAILED"
    status_code = 500
    retryable = True


class WorkflowExecutionError(AuraError):
    code = "WORKFLOW_EXECUTION_FAILED"
    status_code = 500
    retryable = True


class BudgetExceededError(AuraError):
    code = "BUDGET_EXCEEDED"
    status_code = 400
    retryable = False
