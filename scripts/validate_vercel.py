#!/usr/bin/env python3
"""Validate every vercel.json in the repo before it reaches a deploy.

Vercel rejects several key combinations at build time with errors that are slow
and annoying to discover from CI. This script encodes those rules so a bad
manifest fails in seconds on a pull request instead.

Rules checked
-------------
* ``builds`` cannot be combined with ``functions``.
* ``routes`` cannot be combined with ``headers`` / ``redirects`` / ``rewrites``
  / ``cleanUrls`` / ``trailingSlash``.
* ``builds`` cannot be combined with ``framework`` / ``buildCommand`` /
  ``outputDirectory`` / ``installCommand``.
* Every ``builds[].src`` must exist on disk.
* Every route ``src`` must be a valid regular expression.
* Cron schedules must have five fields and cron paths must be absolute.
* Every cron path must be routable by the manifest that declares it.

Usage
-----
    python scripts/validate_vercel.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFESTS = [
    Path("vercel.json"),
    Path("frontend/vercel.json"),
    Path("backend/vercel.json"),
]

EXCLUSIVE_WITH_ROUTES = {
    "headers",
    "redirects",
    "rewrites",
    "cleanUrls",
    "trailingSlash",
}
EXCLUSIVE_WITH_BUILDS = {
    "framework",
    "buildCommand",
    "outputDirectory",
    "installCommand",
}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        print(f"  {'ok  ' if condition else 'FAIL'}  {message}")
        if not condition:
            self.failures.append(message)


def route_matches(routes: list[dict], path: str) -> bool:
    """True if any route's src regex matches `path` (Vercel anchors patterns)."""
    for route in routes:
        src = route.get("src")
        if not src:
            continue
        try:
            if re.fullmatch(src, path) or re.match(f"^{src}$", path):
                return True
        except re.error:
            continue
    return False


def validate(rel_path: Path, report: Report) -> None:
    abs_path = REPO_ROOT / rel_path
    print(f"\n{rel_path}")

    if not abs_path.exists():
        report.check(False, "file exists")
        return

    try:
        config = json.loads(abs_path.read_text())
    except json.JSONDecodeError as exc:
        report.check(False, f"valid JSON ({exc})")
        return
    report.check(True, "valid JSON")

    keys = set(config)
    base = abs_path.parent

    report.check(
        not ("builds" in keys and "functions" in keys),
        "`builds` not combined with `functions`",
    )
    report.check(
        not ("routes" in keys and keys & EXCLUSIVE_WITH_ROUTES),
        "`routes` not combined with headers/redirects/rewrites/cleanUrls",
    )
    report.check(
        not ("builds" in keys and keys & EXCLUSIVE_WITH_BUILDS),
        "`builds` not combined with framework/buildCommand/outputDirectory",
    )

    for build in config.get("builds", []):
        src = build.get("src", "")
        report.check(
            (base / src).exists(),
            f"build src exists: {src} -> {build.get('use')}",
        )

    routes = config.get("routes", [])
    for route in routes:
        src = route.get("src")
        if src is None:
            report.check(
                "handle" in route,
                f"route without `src` declares `handle`: {route}",
            )
            continue
        try:
            re.compile(src)
            report.check(True, f"route regex compiles: {src}")
        except re.error as exc:
            report.check(False, f"route regex compiles: {src} ({exc})")

    for cron in config.get("crons", []):
        schedule = cron.get("schedule", "")
        path = cron.get("path", "")
        report.check(
            len(schedule.split()) == 5,
            f"cron schedule has 5 fields: {schedule!r}",
        )
        report.check(path.startswith("/"), f"cron path is absolute: {path!r}")
        if routes:
            report.check(
                route_matches(routes, path),
                f"cron path is routable by this manifest: {path}",
            )


def main() -> int:
    report = Report()
    print("Validating Vercel manifests...")
    for manifest in MANIFESTS:
        validate(manifest, report)

    print()
    if report.failures:
        print(f"RESULT: {len(report.failures)} problem(s) found")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("RESULT: all Vercel manifests are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
