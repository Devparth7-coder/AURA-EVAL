"""Vercel serverless entrypoint (§38).

Vercel's @vercel/python runtime detects a module-level ASGI `app`. Every request
is a fresh, short-lived invocation: no in-memory workflow state is kept here —
all state lives in PostgreSQL and runs are advanced in bounded slices.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ENVIRONMENT", "production")

from app.main import app  # noqa: E402

__all__ = ["app"]
