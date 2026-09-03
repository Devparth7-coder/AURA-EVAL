# AURA-EVAL — Architecture (Phase 0 Design Document)

> Autonomous Multi-Agent Evaluation & Dataset Generation Platform

This document is written **before** the implementation (per §36) and is kept in sync as
features land.

---

## 1. Requirements analysis

The product is an *AI evaluation infrastructure* platform, not a chat demo. Three
capabilities dominate the design:

| Capability | Consequence for the design |
|---|---|
| Multi-agent pipeline (plan → generate → critique → refine → approve → build) | Explicit, inspectable state machine (LangGraph) with conditional edges and a hard retry ceiling |
| Serverless deployment (Vercel, §37–§56) | **No** in-memory state, no long-lived workers, no WebSocket servers, no local files as source of truth |
| Observability / reliability as a *feature* | Every agent step writes a durable `AgentRun` row (input, output, model, tokens, latency, cost, status, error) plus a `WorkflowEvent` for streaming |

The tension between "workflows take minutes" and "serverless functions are short" is
resolved with **resumable, step-sliced execution**: a run is advanced by repeated
bounded invocations (`/runs/{id}/advance`), each of which executes a slice of the graph
and persists a checkpoint. Locally, a background task drives the loop; on Vercel a cron
job / queue consumer or the polling frontend drives it. Agent code never knows which.

---

## 2. Complete architecture

```
┌───────────────────────── Vercel ─────────────────────────┐
│  Next.js (App Router, TS, Tailwind)                      │
│    dashboard · workflow builder · live view · inspector  │
│    analytics · reliability · SOP editor · datasets       │
│                    │ fetch (NEXT_PUBLIC_API_URL)         │
│  Python serverless function  backend/api/index.py        │
│    FastAPI ASGI app (Mangum-free, native ASGI)           │
└──────────┬───────────────────────────────────────────────┘
           │
   ┌───────┴────────┬───────────────┬───────────────┐
   ↓                ↓               ↓               ↓
Managed          Queue           Object          LLM APIs
PostgreSQL       (Mock|Redis)    Storage         OpenAI / Gemini /
(SQLAlchemy,     TaskQueue ABC   StorageProvider Anthropic / Mock
 Alembic)                        ABC
```

Layering inside the backend (strict, one-directional):

```
api/routers  →  services  →  workflows(LangGraph)  →  agents  →  providers
                    ↓                ↓                  ↓
                 models/database (SQLAlchemy)     schemas (Pydantic)
```

* `providers/` knows about HTTP + tokens + pricing, nothing about agents.
* `agents/` knows about prompts + Pydantic contracts, nothing about DB or HTTP.
* `workflows/` knows about state transitions, nothing about FastAPI.
* `services/` is the only layer that touches both the DB session and the graph.

---

## 3. Database schema

All PKs are UUIDs (`uuid4`), all tables carry `created_at`/`updated_at` (UTC).

```
User 1─* Project 1─* Workflow 1─* WorkflowRun 1─* AgentRun
                 │                      │
                 │                      ├─* WorkflowEvent   (ordered event log, seq)
                 │                      ├─* Sample 1─* Evaluation
                 │                      │        └─* SampleVersion (refinement history)
                 │                      └─* Dataset 1─* DatasetVersion
                 ├─* SOP 1─* SOPVersion
                 ├─* PromptTemplate 1─* PromptVersion
                 └─* Experiment 1─* ExperimentArm
```

Key columns:

* **Workflow** — `config JSON` (sample_count, max_retries, judges, thresholds, provider/model, dataset style/format), `sop_id`, `status`.
* **WorkflowRun** — `status(PENDING|RUNNING|PAUSED|COMPLETED|FAILED|STOPPED)`, `state JSON` (the serialized LangGraph `EvaluationState` = the checkpoint), `cursor`, `error`, `started_at`, `finished_at`, aggregate counters and `total_cost_usd`, `total_tokens`.
* **AgentRun** — `agent(planner|generator|evaluator|refiner|approval|dataset_builder)`, `status`, `model`, `provider`, `input_json`, `output_json`, `prompt_version`, `latency_ms`, `input_tokens`, `output_tokens`, `cost_usd`, `error_type`, `error_message`, `attempt`. This single table powers the trace viewer, cost tracking *and* per-agent reliability %.
* **Sample** — `sample_id` (human-readable, unique per run), `payload JSON`, `content_hash` (duplicate detection), `status` in `PENDING|AUTO_APPROVED|AUTO_REJECTED|NEEDS_REVIEW|HUMAN_APPROVED|HUMAN_REJECTED|FAILED`, `retry_count`, `final_score`.
* **Evaluation** — per judge: `judge_label`, `scores JSON`, `overall_score`, `approved`, `issues JSON`, `reasoning_summary` (concise — **never** raw chain-of-thought), `confidence`, `consensus BOOL`, `variance`, `agreement_rate`.
* **HumanReview** — `sample_id`, `decision`, `edited_payload`, `feedback`, `reviewer`.
* **Dataset/DatasetVersion** — `style(instruction|chat|evaluation)`, `format(json|jsonl|csv|parquet)`, `row_count`, `storage_key`, `size_bytes`, `checksum`.

Indexes on `(run_id, seq)` for events, `(run_id, status)` for samples, `(run_id, agent)` for agent runs, and a unique index on `(run_id, content_hash)` to enforce dedup.

---

## 4. LangGraph state machine

```python
class EvaluationState(TypedDict):
    task, sop, config
    plan
    generated_samples: list[dict]
    queue: list[str]          # sample ids still to process
    current_sample: dict | None
    evaluation: dict | None
    feedback: str | None
    retry_count: int
    approved_samples / rejected_samples / failed_samples / review_samples: list
    dataset: dict | None
    execution_metadata: dict  # tokens, cost, latency, failures, step counter
```

Nodes & edges:

```
START → planner → generator → dispatch
dispatch ──(queue empty)──→ dataset_builder → export → END
dispatch ──(next sample)──→ critic
critic  ──pass──────────────→ approval → dispatch
critic  ──borderline/disagree→ human_gate → dispatch
critic  ──fail & retries left→ refiner → critic
critic  ──fail & exhausted──→ fail_sample → dispatch
approval ──schema/dup fail──→ fail_sample
```

Loop safety: `retry_count < config.max_retries` **and** a global
`execution_metadata.steps < MAX_STEPS` guard; `dispatch` is the single re-entry point so
every cycle must pass through a decrementing queue → termination is provable.

Persistence: after each node the reducer-produced state is serialized to
`WorkflowRun.state`; execution is sliced (`advance(max_steps=N)`) so any invocation can
die and be resumed by the next one. This is what makes it serverless-safe.

---

## 5. Frontend ↔ backend communication

* REST/JSON over `NEXT_PUBLIC_API_URL` (never a hardcoded host).
* Start: `POST /api/workflows/{id}/run` → `{run_id}` immediately (never blocks).
* Live view: **SSE** `GET /api/runs/{id}/stream` when available; automatic fallback to
  polling `GET /api/runs/{id}` + `GET /api/runs/{id}/events?after_seq=N`. The event layer
  is behind an `EventBus` abstraction so Ably/Supabase Realtime can be dropped in.
* Datasets download via `GET /api/datasets/{id}/download?format=jsonl` streaming from the
  storage provider.

---

## 6. Directory structure

Monorepo per §29/§38 — `backend/api/index.py` (Vercel entry) + `backend/app/**`,
`frontend/**`, `docker/`, `docs/`, `.github/workflows/`, root `vercel.json`,
`docker-compose.yml`, `.env.example`, `README.md`.

---

## 7. Implementation risks

| Risk | Mitigation |
|---|---|
| LLM returns invalid JSON | `structured_generate` = schema-in-prompt + extraction + Pydantic validate + repair retry + exponential backoff; failure recorded as `INVALID_JSON`, never crashes the run |
| Serverless timeouts mid-workflow | sliced `advance()` + DB checkpoint after every node |
| DB connection exhaustion | `NullPool` (+ pgbouncer-friendly) when `ENVIRONMENT=production`/serverless, pooled locally |
| Infinite refinement loops | per-sample `max_retries` + global step ceiling + monotonically shrinking queue |
| Cost blowout | pricing table in config, per-run cost accumulation, `max_cost_usd` circuit breaker |
| Duplicate/low-quality data | content-hash dedup + quality threshold in the Approval agent |
| Deterministic CI | `MockLLMProvider` seeded from a hash of the prompt → identical outputs every run |

---

## 8. MVP (what ships first)

1. Config, DB models, Alembic, storage/queue/event abstractions.
2. Provider abstraction + `MockLLMProvider` + OpenAI/Gemini/Anthropic adapters.
3. Six agents with Pydantic contracts + SOP engine.
4. LangGraph graph with conditional edges, retries, checkpointing.
5. REST API (projects, SOPs, workflows, runs, samples, evaluations, datasets, analytics, reliability, health) + SSE.
6. Tests: unit, integration, failure, E2E.
7. Next.js dashboard: landing, dashboard, workflows + React-Flow builder, live run view, sample inspector, SOP editor, datasets, analytics, reliability, traces.
8. Docker Compose, Vercel config, CI, README.

## 9. Phase 2 features

Multi-judge consensus, human-in-the-loop queue, experiment comparison, prompt
versioning, failure-propagation visualization, cost dashboards, RBAC/JWT auth
enforcement, Parquet export, external queue driver.
