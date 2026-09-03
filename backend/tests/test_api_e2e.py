"""End-to-end API test (§28, §57): project → SOP → workflow → run → dataset download."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient


def _wait(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/runs/{run_id}/status").json()
        if status["terminal"]:
            return status
        time.sleep(0.2)
    raise AssertionError("run did not terminate in time")


def test_health_endpoints(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] in ("healthy", "degraded")
    assert body["database"] == "connected"
    assert client.get("/api/health/database").json()["status"] == "healthy"
    llm = client.get("/api/health/llm").json()
    assert llm["demo_mode"] is True
    cfg = client.get("/api/health/config").json()
    # no secret may ever be exposed
    assert not any("key" in k or "secret" in k or "url" in k.lower() for k in cfg)


def test_error_envelope_is_structured(client: TestClient) -> None:
    r = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "NOT_FOUND" and "request_id" in body
    assert "X-Request-ID" in r.headers


def test_request_validation_rejects_bad_payload(client: TestClient) -> None:
    r = client.post("/api/projects", json={"description": "no name"})
    assert r.status_code == 422
    assert r.json()["error"] == "VALIDATION_FAILED"


def test_full_acceptance_flow(client: TestClient) -> None:
    # 1. user creates a project
    project = client.post(
        "/api/projects",
        json={"name": "E2E Project", "description": "acceptance test", "tags": ["e2e"]},
    ).json()

    # 2. user creates an SOP
    sop = client.post(
        "/api/sops",
        json={
            "project_id": project["id"],
            "name": "E2E SOP",
            "rules": [
                {
                    "id": "R1",
                    "text": "The answer must be technically correct.",
                    "criterion": "correctness",
                    "weight": 1.5,
                    "severity": "critical",
                },
                {
                    "id": "R2",
                    "text": "The answer must address the question.",
                    "criterion": "relevance",
                    "weight": 1.0,
                    "severity": "major",
                },
            ],
            "threshold": 70.0,
        },
    ).json()
    assert sop["current_version"] == 1
    assert "technically correct" in client.get(f"/api/sops/{sop['id']}/render").json()["text"]

    # SOP versioning
    updated = client.put(
        f"/api/sops/{sop['id']}", json={"threshold": 72.0, "changelog": "raise the bar"}
    ).json()
    assert updated["current_version"] == 2
    assert len(updated["versions"]) == 2

    # 3. user creates a workflow
    workflow = client.post(
        "/api/workflows",
        json={
            "project_id": project["id"],
            "sop_id": sop["id"],
            "name": "E2E Workflow",
            "objective": "Create a dataset for evaluating Python coding assistants",
            "config": {
                "sample_count": 5,
                "batch_size": 5,
                "max_retries": 2,
                "judges": 2,
                "provider": "mock",
                "model": "mock-1",
                "human_review_enabled": True,
                "dataset_style": "instruction",
                "dataset_formats": ["jsonl", "json", "csv"],
                "domain_hint": "python",
                "mock_failure_rate": 0.0,
            },
        },
    ).json()

    # 4. user starts the evaluation — must return immediately with a run id
    start = client.post(f"/api/workflows/{workflow['id']}/run", json={"async_execution": True})
    assert start.status_code == 202
    run_id = start.json()["id"]

    # 5. planner → generator → critic → refiner → approval → dataset builder
    status = _wait(client, run_id)
    assert status["status"] == "COMPLETED"
    assert status["samples_generated"] == 5

    events = client.get(f"/api/runs/{run_id}/events").json()
    types = [e["type"] for e in events]
    assert types[0] == "run.started" and types[-1] == "run.completed"
    assert "sample.evaluating" in types

    # observability: full execution trace
    trace = client.get(f"/api/runs/{run_id}/trace").json()
    agents = {t["agent"] for t in trace}
    assert {"planner", "generator", "evaluator", "approval", "dataset_builder"} <= agents
    for step in trace:
        assert step["model"] and step["latency_ms"] >= 0 and step["cost_usd"] >= 0

    # workflow builder graph annotated with live stats
    graph = client.get(f"/api/runs/{run_id}/graph").json()
    assert graph["stats"]["generator"]["calls"] >= 1
    assert graph["run_status"] == "COMPLETED"

    # 6. sample inspector with refinement history
    samples = client.get("/api/samples", params={"run_id": run_id}).json()
    assert len(samples) == 5
    history = client.get(f"/api/samples/{samples[0]['id']}/history").json()
    assert history["timeline"] and history["timeline"][0]["source"] == "generator"

    # 7. human-in-the-loop
    review_queue = client.get("/api/samples/review-queue", params={"run_id": run_id}).json()
    for s in review_queue:
        out = client.post(
            f"/api/samples/{s['id']}/approve",
            json={"reviewer": "qa@example.com", "feedback": "acceptable"},
        ).json()
        assert out["status"] == "HUMAN_APPROVED"

    # 8. analytics
    analytics = client.get("/api/analytics").json()
    assert analytics["summary"]["samples_generated"] == 5
    assert analytics["charts"]["score_distribution"]
    ev = client.get("/api/analytics/evaluation").json()
    assert 0 <= ev["pass_rate"] <= 100
    rel = client.get("/api/analytics/reliability").json()
    assert rel["workflow_reliability"] > 0
    cost = client.get("/api/analytics/cost").json()
    assert cost["total_tokens"] > 0

    # 9. dataset produced automatically, then downloaded as JSONL
    datasets = client.get("/api/datasets", params={"run_id": run_id}).json()
    assert datasets, "the workflow must materialise a dataset"
    ds = datasets[0]
    preview = client.get(f"/api/datasets/{ds['id']}/preview").json()
    assert preview["rows"] and set(preview["rows"][0]) >= {"instruction", "output"}

    dl = client.get(f"/api/datasets/{ds['id']}/download", params={"format": "jsonl"})
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in dl.headers["content-disposition"]
    rows = [json.loads(line) for line in dl.text.splitlines() if line.strip()]
    assert rows and all("instruction" in r and "output" in r for r in rows)

    csv_dl = client.get(f"/api/datasets/{ds['id']}/download", params={"format": "csv"})
    assert csv_dl.status_code == 200 and "instruction" in csv_dl.text

    # 10. a chat-style dataset can be built on demand from the same run
    chat = client.post(
        "/api/datasets", json={"run_id": run_id, "style": "chat", "formats": ["jsonl"]}
    ).json()
    chat_rows = client.get(f"/api/datasets/{chat['id']}/preview").json()["rows"]
    assert chat_rows[0]["messages"][0]["role"] == "user"


def test_sop_test_endpoint(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "SOP Test"}).json()
    sop = client.post("/api/sops", json={"project_id": project["id"], "name": "S"}).json()
    r = client.post(
        f"/api/sops/{sop['id']}/test",
        json={
            "samples": [
                {
                    "input": "Explain TCP congestion control.",
                    "response": "AIMD adapts the window; on loss it halves and then grows linearly.",
                }
            ]
        },
    ).json()
    assert r["results"][0]["overall_score"] >= 0
    assert "approved" in r["results"][0]


def test_stop_endpoint_marks_run(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "Stop Test"}).json()
    wf = client.post(
        "/api/workflows",
        json={
            "project_id": project["id"],
            "name": "Stoppable",
            "objective": "x",
            "config": {"sample_count": 3, "provider": "mock", "mock_failure_rate": 0.0},
        },
    ).json()
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"async_execution": False}).json()
    stopped = client.post(f"/api/runs/{run['id']}/stop").json()
    assert stopped["status"] in ("PENDING", "RUNNING", "STOPPED", "COMPLETED")


def test_manual_advance_slices(client: TestClient) -> None:
    """Serverless mode: the run is driven by repeated bounded advance calls."""
    project = client.post("/api/projects", json={"name": "Slice Test"}).json()
    wf = client.post(
        "/api/workflows",
        json={
            "project_id": project["id"],
            "name": "Sliced",
            "objective": "python",
            "config": {
                "sample_count": 3,
                "batch_size": 3,
                "provider": "mock",
                "judges": 1,
                "mock_failure_rate": 0.0,
                "human_review_enabled": False,
            },
        },
    ).json()
    run = client.post(f"/api/workflows/{wf['id']}/run", json={"async_execution": False}).json()
    for _ in range(60):
        state = client.post(f"/api/runs/{run['id']}/advance", json={"max_steps": 2}).json()
        if state["status"] in ("COMPLETED", "FAILED", "STOPPED"):
            break
    assert state["status"] == "COMPLETED"
    assert state["samples_generated"] == 3


def test_topology_endpoint(client: TestClient) -> None:
    topo = client.get("/api/workflows/topology").json()
    assert {n["id"] for n in topo["nodes"]} >= {"planner", "generator", "critic", "refiner"}
    assert all(n["description"] for n in topo["nodes"])


def test_prompt_versioning_api(client: TestClient) -> None:
    prompts = client.get("/api/prompts").json()
    assert prompts, "default prompts must be registered"
    evaluator = next(p for p in prompts if p["key"] == "evaluator")
    assert evaluator["current_version"] >= 2
    diff = client.get(f"/api/prompts/{evaluator['id']}/diff", params={"a": 1, "b": 2}).json()
    assert diff["diff"]
    updated = client.post(
        f"/api/prompts/{evaluator['id']}/versions",
        json={
            "body": "AURA-TASK: evaluator v3 body with more explicit calibration guidance.",
            "notes": "v3",
        },
    ).json()
    assert updated["current_version"] == evaluator["current_version"] + 1
