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


# --- Vercel deployment entrypoints (§38) ---------------------------------
def test_vercel_fastapi_entrypoint_resolves():
    """Vercel's FastAPI preset loads the ASGI app from tool.vercel.entrypoint.

    There is no hand-written shim any more: the modern Python runtime resolves
    `app.main:app` directly. If that module path ever moves, the deploy 500s at
    cold start, so assert it here.
    """
    import tomllib
    from importlib import import_module
    from pathlib import Path

    from fastapi import FastAPI

    backend = Path(__file__).resolve().parent.parent
    with (backend / "pyproject.toml").open("rb") as fh:
        entrypoint = tomllib.load(fh)["tool"]["vercel"]["entrypoint"]

    module_path, _, attr = entrypoint.partition(":")
    module = import_module(module_path)
    assert isinstance(getattr(module, attr), FastAPI), (
        f"pyproject tool.vercel.entrypoint '{entrypoint}' is not a FastAPI app"
    )


def test_vercel_manifests_are_valid():
    """Run the manifest linter that CI runs — catches Vercel's key conflicts."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "scripts" / "validate_vercel.py"
    assert script.exists(), "scripts/validate_vercel.py is missing"

    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=repo_root
    )
    assert result.returncode == 0, f"invalid Vercel manifest:\n{result.stdout}\n{result.stderr}"


def test_backend_requirements_stay_serverless_lean():
    """The serverless bundle must not pull in pyarrow/pandas/redis (size limit)."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    raw = (repo_root / "backend" / "requirements.txt").read_text().lower()

    # Ignore comments — the file *documents* these exclusions by name.
    core = " ".join(
        line.split("#", 1)[0].strip() for line in raw.splitlines() if not line.startswith("#")
    )

    for heavy in ("pyarrow", "pandas", "redis"):
        assert heavy not in core, (
            f"{heavy} must live in requirements-optional.txt, not requirements.txt — "
            "it would push the Vercel lambda past the 250 MB limit"
        )
    assert "fastapi" in core and "langgraph" in core and "psycopg" in core


# --- pinned-dependency compatibility -------------------------------------
def test_no_204_route_declares_a_response_body():
    """204 No Content routes must not carry a response model.

    Every api module uses `from __future__ import annotations`, so a `-> None`
    return annotation arrives at FastAPI as the *string* "None". FastAPI 0.115.x
    (our pinned version) cannot resolve that to NoneType, infers a response
    model, and then asserts at import time:

        AssertionError: Status code 204 must not have a response body

    Newer FastAPI resolves the string and does not raise, so a developer with a
    newer version installed locally will not see the breakage — only CI will.
    Passing `response_model=None` explicitly is correct on every version.
    """
    from fastapi.routing import APIRoute

    from app.main import app

    offenders = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.status_code == 204
        and route.response_model is not None
    ]
    assert not offenders, "204 routes must be declared with response_model=None: " + ", ".join(
        offenders
    )


def test_installed_versions_match_pinned_requirements():
    """Guard against a local environment masking a pinned-version failure.

    This is a warning-style check: it only asserts for the packages whose exact
    version changes API-surface behaviour we depend on.
    """
    import re
    from importlib.metadata import version
    from pathlib import Path

    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    pins = dict(re.findall(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([0-9][^\s#]*)", req, re.M))

    critical = {"fastapi", "pydantic", "SQLAlchemy"}
    mismatched = {}
    for name in critical:
        pinned = pins.get(name)
        if not pinned:
            continue
        try:
            installed = version(name)
        except Exception:
            continue
        if installed != pinned:
            mismatched[name] = (pinned, installed)

    assert not mismatched, (
        "Installed versions differ from requirements.txt pins, so local results "
        f"may not match CI: {mismatched}. Reinstall with "
        "`pip install -r requirements-dev.txt`."
    )


def test_pyproject_dependencies_match_requirements():
    """pyproject.toml mirrors requirements.txt — they must not drift apart.

    Vercel's Python runtime may read either file, so a version that appears in
    one but not the other is a deploy-time surprise.
    """
    import re
    import tomllib
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent

    with (backend / "pyproject.toml").open("rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]

    req_text = (backend / "requirements.txt").read_text()
    req = dict(re.findall(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([0-9][^\s#]*)", req_text, re.M))
    pyproj = dict(
        re.findall(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([0-9][^\s#]*)", "\n".join(declared), re.M)
    )

    assert pyproj == req, (
        "pyproject.toml [project.dependencies] and requirements.txt disagree.\n"
        f"  only in requirements.txt: {set(req) - set(pyproj)}\n"
        f"  only in pyproject.toml:   {set(pyproj) - set(req)}\n"
        f"  version mismatches:       "
        f"{ {k: (req[k], pyproj[k]) for k in set(req) & set(pyproj) if req[k] != pyproj[k]} }"
    )


def test_vercel_service_entrypoint_is_importable():
    """The `entrypoint` in vercel.json must resolve to a real ASGI app."""
    import json
    from importlib import import_module
    from pathlib import Path

    from fastapi import FastAPI

    repo_root = Path(__file__).resolve().parent.parent.parent
    config = json.loads((repo_root / "vercel.json").read_text())

    api_service = config["services"]["api"]
    module_path, _, attr = api_service["entrypoint"].partition(":")

    module = import_module(module_path)
    assert isinstance(getattr(module, attr), FastAPI), (
        f"{api_service['entrypoint']} does not resolve to a FastAPI app"
    )


# --- platform detection (persistent hosts vs serverless) ------------------
def test_is_serverless_false_on_persistent_production_host(monkeypatch):
    """Render/Fly/Docker production must NOT be treated as serverless.

    Regression guard: `is_serverless` used to return True whenever
    environment == "production", which on a persistent host disabled the
    SQLAlchemy pool and silently downgraded STORAGE_PROVIDER=local to
    in-memory, discarding dataset artifacts on every request.
    """
    from app.core.config import settings

    for var in ("SERVERLESS", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "environment", "production")

    assert settings.is_serverless is False


def test_is_serverless_true_on_vercel(monkeypatch):
    from app.core.config import settings

    monkeypatch.delenv("SERVERLESS", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert settings.is_serverless is True


def test_serverless_env_var_overrides_detection(monkeypatch):
    """The explicit SERVERLESS flag wins over platform sniffing, both ways."""
    from app.core.config import settings

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SERVERLESS", "false")
    assert settings.is_serverless is False

    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("SERVERLESS", "true")
    assert settings.is_serverless is True


def test_local_storage_survives_on_persistent_production(monkeypatch):
    """STORAGE_PROVIDER=local must stay local off-serverless (disk-backed)."""
    from app.core.config import settings
    from app.services import storage as storage_mod

    for var in ("SERVERLESS", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(storage_mod, "_instance", None)

    assert isinstance(storage_mod.get_storage(), storage_mod.LocalStorageProvider)
    storage_mod.set_storage(None)


def test_render_blueprint_is_consistent_with_the_app():
    """render.yaml must stay in sync with how the backend actually works."""
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parent.parent.parent
    blueprint = yaml.safe_load((repo_root / "render.yaml").read_text())

    services = {s["name"]: s for s in blueprint["services"]}
    api = services["aura-eval-api"]
    env = {e["key"]: e for e in api["envVars"]}

    # A persistent host must not masquerade as serverless.
    assert env["SERVERLESS"]["value"] == "false"

    # Health check must point at a route that exists and needs no auth.
    assert api["healthCheckPath"] == "/api/health"

    # BackgroundTasks live in the worker process: a second worker would not
    # see runs started by the first.
    assert "--workers 1" in api["startCommand"]

    # Artifacts must be written to the mounted persistent disk.
    assert env["STORAGE_DIR"]["value"].startswith(api["disk"]["mountPath"])

    # The DB URL must come from the managed Postgres instance.
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == blueprint["databases"][0]["name"]


def test_render_setup_doc_matches_blueprint():
    """docs/RENDER_SETUP.md must quote the same commands as render.yaml.

    The doc is what someone copy/pastes into the Render dashboard when setting
    services up by hand. If it drifts from the blueprint, manual deploys break
    in ways the blueprint users never see.
    """
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parent.parent.parent
    blueprint = yaml.safe_load((repo_root / "render.yaml").read_text())
    doc = (repo_root / "docs" / "RENDER_SETUP.md").read_text()

    for service in blueprint["services"]:
        for key in ("buildCommand", "startCommand"):
            command = service[key]
            assert command in doc, (
                f"docs/RENDER_SETUP.md is missing the {service['name']} {key}:\n  {command}"
            )


def test_python_version_is_pinned_for_deploy_platforms():
    """Every host must get an interpreter that has prebuilt wheels.

    Render (and Heroku-style buildpacks) read `.python-version` from the
    REPOSITORY ROOT, not from the service's Root Directory. When the pin is
    missing or too loose the platform picks its newest Python — 3.14 at time of
    writing — and `pydantic-core==2.27.2` publishes no cp314 wheel. pip then
    falls back to compiling Rust and the build dies on a read-only cargo cache:

        error: failed to create directory `/usr/local/cargo/registry/cache/...`
        Read-only file system (os error 30)  ->  maturin failed

    A patch-level version is required; bare "3.12" is not always honoured.
    """
    import re
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parent.parent.parent
    semver = re.compile(r"^3\.12\.\d+$")

    root_pin = repo_root / ".python-version"
    assert root_pin.exists(), (
        ".python-version is missing from the REPOSITORY ROOT — Render reads it "
        "from there, not from rootDir, and will otherwise default to Python 3.14"
    )
    assert semver.match(root_pin.read_text().strip()), (
        f"root .python-version must be an exact 3.12.x version, got "
        f"{root_pin.read_text().strip()!r}"
    )

    backend_pin = repo_root / "backend" / ".python-version"
    assert backend_pin.exists()
    assert backend_pin.read_text().strip() == root_pin.read_text().strip(), (
        "backend/.python-version and the root .python-version disagree"
    )

    blueprint = yaml.safe_load((repo_root / "render.yaml").read_text())
    api = next(s for s in blueprint["services"] if s["name"] == "aura-eval-api")
    env = {e["key"]: e.get("value") for e in api["envVars"]}
    assert semver.match(str(env["PYTHON_VERSION"])), (
        f"render.yaml PYTHON_VERSION must be an exact 3.12.x version, got {env['PYTHON_VERSION']!r}"
    )
    assert env["PYTHON_VERSION"] == root_pin.read_text().strip(), (
        "render.yaml PYTHON_VERSION disagrees with .python-version"
    )
