"""Authentication-ready layer + RBAC + rate limiting (§24).

Auth is *pluggable and off by default* in development so the demo works with no
setup, but every mutating endpoint already resolves a principal and checks a role.
Turn it on with AUTH_ENABLED=true.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.models.enums import Role

bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {Role.VIEWER: 0, Role.EDITOR: 1, Role.ADMIN: 2}


@dataclass(slots=True)
class Principal:
    subject: str
    role: str = Role.ADMIN
    authenticated: bool = False

    def require(self, minimum: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK.get(minimum, 99):  # type: ignore[arg-type]
            raise ForbiddenError(f"role '{self.role}' cannot perform this action")


# --- minimal dependency-free JWT (HS256) --------------------------------
def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(subject: str, role: str = Role.ADMIN, expires_in: int | None = None) -> str:
    exp = int(time.time()) + (expires_in or settings.jwt_expire_minutes * 60)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"sub": subject, "role": role, "exp": exp}).encode())
    sig = hmac.new(
        settings.jwt_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_b64(sig)}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        header, payload, sig = token.split(".")
    except ValueError as exc:
        raise UnauthorizedError("malformed token") from exc
    expected = _b64(
        hmac.new(
            settings.jwt_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
    )
    if not hmac.compare_digest(expected, sig):
        raise UnauthorizedError("invalid token signature")
    body = json.loads(_unb64(payload))
    if int(body.get("exp", 0)) < time.time():
        raise UnauthorizedError("token expired")
    return body


async def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if not settings.auth_enabled:
        return Principal(subject="local-dev", role=Role.ADMIN, authenticated=False)
    if creds is None:
        raise UnauthorizedError("missing bearer token")
    body = decode_token(creds.credentials)
    return Principal(
        subject=str(body.get("sub")), role=str(body.get("role", Role.VIEWER)), authenticated=True
    )


async def require_editor(p: Principal = Depends(get_principal)) -> Principal:
    p.require(Role.EDITOR)
    return p


async def require_admin(p: Principal = Depends(get_principal)) -> Principal:
    p.require(Role.ADMIN)
    return p


# --- rate limiting -------------------------------------------------------
class SlidingWindowLimiter:
    """In-memory limiter. Serverless instances each hold their own window;
    swap for Redis via REDIS_URL when strict global limits are required."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(hits) >= self.limit:
            raise RateLimitedError("rate limit exceeded; slow down", retry_after=int(self.window))
        hits.append(now)
        self._hits[key] = hits


limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)


async def rate_limit(request: Request) -> None:
    client = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "anonymous"
    )
    limiter.check(client.split(",")[0].strip())
