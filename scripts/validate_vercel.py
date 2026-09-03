#!/usr/bin/env python3
"""Validate every vercel.json in the repo before it reaches a deploy.

Vercel rejects several configurations at build time with errors that are slow to
discover from CI. This script encodes those rules so a bad manifest fails in
seconds on a pull request instead.

Two manifest styles are supported, and the rules differ per style:

* **services style** (the repo-root manifest) — the modern way to deploy a
  polyglot monorepo as one project. Build/runtime keys (``functions``,
  ``buildCommand``, ``installCommand``, ``devCommand``, ``ignoreCommand``,
  ``outputDirectory``, ``framework``) are NOT valid at the top level; they must
  live inside a service. Legacy ``builds``/``routes`` must not appear at all.

* **single-project style** (``frontend/vercel.json``, ``backend/vercel.json``) —
  a plain project rooted at that directory.

Deprecation guard: the legacy ``builds`` key silently opts a project out of
modern framework detection, so it is rejected outright.

Usage
-----
    python scripts/validate_vercel.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFESTS = [
    Path("vercel.json"),
    Path("frontend/vercel.json"),
    Path("backend/vercel.json"),
]

# Not valid at the top level once `services` is used: their owner is ambiguous.
BUILD_KEYS_FORBIDDEN_WITH_SERVICES = {
    "functions",
    "installCommand",
    "buildCommand",
    "devCommand",
    "ignoreCommand",
    "outputDirectory",
    "framework",
}

EXCLUSIVE_WITH_ROUTES = {
    "headers",
    "redirects",
    "rewrites",
    "cleanUrls",
    "trailingSlash",
}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        print(f"  {'ok  ' if condition else 'FAIL'}  {message}")
        if not condition:
            self.failures.append(message)


def validate_services_manifest(config: dict[str, Any], base: Path, report: Report) -> None:
    services = config["services"]
    report.check(bool(services), "`services` declares at least one service")

    offenders = sorted(set(config) & BUILD_KEYS_FORBIDDEN_WITH_SERVICES)
    report.check(
        not offenders,
        "no build/runtime keys at top level with `services` "
        f"({', '.join(offenders) if offenders else 'none found'})",
    )
    report.check("routes" not in config, "no legacy `routes` alongside `services`")

    for name, svc in services.items():
        root = svc.get("root")
        report.check(bool(root), f"service '{name}' declares `root`")
        if root:
            report.check(
                (base / root).is_dir(),
                f"service '{name}' root exists: {root}",
            )

        entrypoint = svc.get("entrypoint")
        if entrypoint and ":" in entrypoint:
            module, _, _attr = entrypoint.partition(":")
            rel = Path(module.replace(".", "/") + ".py")
            report.check(
                (base / (root or "") / rel).exists(),
                f"service '{name}' entrypoint module exists: {root}{rel}",
            )

    # Every service must be reachable, or it is dead configuration.
    rewrites = config.get("rewrites", [])
    targeted = {
        r["destination"]["service"]
        for r in rewrites
        if isinstance(r.get("destination"), dict) and "service" in r["destination"]
    }
    for name in services:
        report.check(
            name in targeted,
            f"service '{name}' is exposed by a top-level rewrite",
        )
    for name in sorted(targeted - set(services)):
        report.check(False, f"rewrite targets undefined service '{name}'")

    # A catch-all should come last, otherwise it shadows later rules.
    sources = [r.get("source", "") for r in rewrites]
    catch_alls = [i for i, s in enumerate(sources) if s in {"/(.*)", "/:path*"}]
    if catch_alls:
        report.check(
            catch_alls[-1] == len(sources) - 1,
            "catch-all rewrite is the last rewrite rule",
        )


def validate_single_project_manifest(config: dict[str, Any], base: Path, report: Report) -> None:
    keys = set(config)
    report.check(
        not ("builds" in keys and "functions" in keys),
        "`builds` not combined with `functions`",
    )
    report.check(
        not ("routes" in keys and keys & EXCLUSIVE_WITH_ROUTES),
        "`routes` not combined with headers/redirects/rewrites/cleanUrls",
    )
    for build in config.get("builds", []):
        src = build.get("src", "")
        report.check((base / src).exists(), f"build src exists: {src}")


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

    base = abs_path.parent

    # Legacy `builds` disables modern framework detection — reject it outright.
    report.check(
        "builds" not in config,
        "does not use the deprecated `builds` key",
    )

    if "services" in config:
        print("  ..    style: services (multi-service project)")
        validate_services_manifest(config, base, report)
    else:
        print("  ..    style: single project")
        validate_single_project_manifest(config, base, report)

    for rule_key in ("rewrites", "redirects", "headers"):
        for rule in config.get(rule_key, []):
            source = rule.get("source")
            if source is None:
                report.check(False, f"{rule_key} entry missing `source`: {rule}")
                continue
            report.check(
                source.startswith("/"),
                f"{rule_key} source is a path: {source}",
            )

    for cron in config.get("crons", []):
        schedule = cron.get("schedule", "")
        path = cron.get("path", "")
        report.check(len(schedule.split()) == 5, f"cron schedule has 5 fields: {schedule!r}")
        report.check(path.startswith("/"), f"cron path is absolute: {path!r}")
        report.check(len(path) <= 512, "cron path within the 512 character limit")
        report.check(len(schedule) <= 256, "cron schedule within the 256 character limit")

        rewrites = config.get("rewrites", [])
        if rewrites:
            reachable = any(
                re.fullmatch(_to_regex(r.get("source", "")), path) for r in rewrites
            )
            report.check(reachable, f"cron path is routable: {path}")


def _to_regex(source: str) -> str:
    """Translate a Vercel path pattern into a Python regex (approximate)."""
    pattern = re.sub(r":\w+\*", ".*", source)
    pattern = re.sub(r":\w+", "[^/]+", pattern)
    return pattern


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
