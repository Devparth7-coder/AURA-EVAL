<div align="center">

# AURA-EVAL

**Autonomous Multi-Agent Evaluation & Dataset Generation Platform**

Six specialised LLM agents, orchestrated as a LangGraph state machine, that plan → generate → judge → refine → approve synthetic training data, and ship it as a downloadable dataset — with full observability, reliability analytics and human-in-the-loop review.

[![CI](https://github.com/your-org/aura-eval/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-state%20machine-1c7ed6)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![Postgres](https://img.shields.io/badge/PostgreSQL-16-336791)
![License](https://img.shields.io/badge/license-MIT-green)

**Runs with zero API keys.** The built-in deterministic Mock provider gives you the whole product — real agents, real graph, real datasets — offline.

</div>

---

## Table of contents

1. [Overview](#1-overview)
2. [The problem](#2-the-problem)
3. [Architecture](#3-architecture)
4. [The six agents](#4-the-six-agents)
5. [LangGraph execution flow](#5-langgraph-execution-flow)
6. [Tech stack](#6-tech-stack)
7. [Quick start](#7-quick-start)
8. [Environment variables](#8-environment-variables)
9. [Docker](#9-docker)
10. [Example workflow (end to end)](#10-example-workflow-end-to-end)
11. [API reference](#11-api-reference)
12. [Screenshots](#12-screenshots)
13. [Evaluation methodology](#13-evaluation-methodology)
14. [Reliability metrics](#14-reliability-metrics)
15. [Testing](#15-testing)
16. [Deploying to Vercel](#16-deploying-to-vercel)
17. [Troubleshooting](#17-troubleshooting)
18. [Rollback procedure](#18-rollback-procedure)
19. [Security checklist](#19-security-checklist)
20. [Research possibilities](#20-research-possibilities)
21. [Future work](#21-future-work)
22. [Project layout](#22-project-layout)

---

## 1. Overview

AURA-EVAL turns a one-line objective — *"generate high-quality Python question/answer pairs"* — into a **verified, auditable, downloadable dataset**.

It is not a chat wrapper. It is an evaluation *system*:

- A **Planner** decomposes the objective into a typed generation plan.
- A **Generator** produces candidate samples in batches.
- One to five **Evaluator/Critic** judges score every sample on five dimensions against a **versioned SOP** (Standard Operating Procedure) and return strict JSON.
- Judges that disagree beyond a threshold route the sample to a human instead of guessing.
- A **Refiner** rewrites failing samples using the critic's structured issues — up to `MAX_RETRIES`, never infinitely.
- A **deterministic Approval agent** applies six non-LLM gates (schema, required fields, duplicate detection, quality threshold, metadata, SOP compliance).
- A **Dataset Builder** emits JSON / JSONL / CSV / Parquet in instruction, chat or evaluation style.

Everything is persisted: every agent call becomes a trace span with model, latency, tokens, cost and status. Every sample keeps its full refinement lineage. Every prompt and every SOP is versioned, so an experiment can prove *which* version was better.

### What makes it production-grade

| Concern | How it is handled |
|---|---|
| Infinite agent loops | Hard `MAX_RETRIES` per sample **and** a global `MAX_WORKFLOW_STEPS` ceiling (500). Proven by a test that ticks a run to termination. |
| Untrusted LLM output | Every structured response is parsed and validated with Pydantic, with JSON repair, retry and exponential backoff before failing. |
| Long-running work on serverless | `POST /run` returns a `run_id` immediately. Execution advances in **bounded slices** that persist full state after every node. |
| Realtime UI | Server-Sent Events with automatic polling fallback — no persistent WebSocket server. |
| Cost blowout | Per-run `max_cost_usd` budget; pricing is a configurable JSON map, never hardcoded. |
| Secrets | Backend-only. `/api/health/config` returns a `safe_public_dict()` that structurally cannot contain a key. |
| Hidden reasoning | Judges return a **concise `reasoning_summary` plus structured evidence**. Chain-of-thought is never requested, stored or displayed. |

---

## 2. The problem

Teams fine-tuning or evaluating LLMs hit the same wall: **synthetic data is easy to produce and very hard to trust.**

- A single model grading its own output is a rubber stamp — self-preference bias is well documented.
- "Quality" lives in a Notion doc, not in the pipeline, so nobody can prove a sample met the rules.
- A generation script produces 10,000 rows and no answer to *"why is row 4,182 in here?"*
- Failures are invisible: was it the generator, the parser, the judge, or a timeout?
- Retry loops silently burn budget, and sometimes never stop.
- Changing a prompt changes the dataset, and there is no way to compare before and after.

AURA-EVAL's position: **treat dataset generation as an engineered, observable pipeline with an explicit quality contract** — the SOP — and make every decision inspectable after the fact.

---

## 3. Architecture

### System diagram

```mermaid
graph TB
    subgraph Client["Browser · Next.js 14 App Router"]
        UI["Dashboard · Workflow builder · Live run<br/>Sample inspector · SOP editor · Datasets<br/>Analytics · Reliability · Traces · Experiments"]
    end

    subgraph API["FastAPI · stateless · serverless-safe"]
        R["Routers<br/>health · projects · sops · workflows<br/>samples · datasets · analytics<br/>experiments · prompts · internal"]
        S["Services<br/>workflow · sop_engine · analytics<br/>experiments · storage · queue · seed"]
        W["Workflows — LangGraph<br/>state · nodes · graph · StepExecutor"]
        AG["Agents<br/>planner · generator · evaluator<br/>refiner · approval · dataset_builder"]
        P["Providers<br/>Mock · OpenAI · Anthropic · Gemini"]
    end

    subgraph Data["Persistence"]
        PG[("PostgreSQL 16<br/>18 tables · UUID PKs<br/>Alembic migrations")]
        ST["StorageProvider<br/>Local FS · Memory · Blob · S3"]
    end

    UI -->|"REST + SSE — NEXT_PUBLIC_API_URL"| R
    R --> S
    S --> W
    W --> AG
    AG --> P
    S --> PG
    S --> ST
    CRON["Scheduler<br/>Vercel Cron / QStash"] -->|"POST /api/internal/tick"| R

    classDef c fill:#0b1220,stroke:#1c7ed6,color:#e2e8f0
    class UI,R,S,W,AG,P,PG,ST,CRON c
```

### Layering rule (one-directional, enforced by review)

```
api/routers  →  services  →  workflows (LangGraph)  →  agents  →  providers
                    ↓
              database session
```

Only `services` may touch both a DB session and the graph. Graph nodes reach side effects exclusively through a per-run runtime handle (`emit`, `record`, `sample_sink`) — so the graph itself stays pure and testable, and agents never import SQLAlchemy.

### Serverless-safe execution model

Traditional agent frameworks assume a long-lived worker. Vercel has no such thing. So:

```
POST /api/workflows/{id}/run   →  201, { run_id, status: RUNNING }   (returns immediately)

StepExecutor.advance(max_steps)
   ├─ load EvaluationState from workflow_runs.state (JSONB)
   ├─ execute up to N graph nodes
   ├─ commit the FULL state after EVERY node
   └─ return { resume_at, terminal }

Driven by:  the UI polling /advance   ·   Vercel Cron → /api/internal/tick   ·   run_to_completion() locally
```

Because the entire `EvaluationState` is serialised to Postgres after each node, a run survives a cold start, a deploy, or a function timeout, and resumes exactly where it stopped. Nothing lives in process memory.

### Database schema

```mermaid
erDiagram
    PROJECT ||--o{ WORKFLOW : contains
    PROJECT ||--o{ SOP : owns
    SOP ||--o{ SOP_VERSION : versions
    WORKFLOW ||--o{ WORKFLOW_RUN : executes
    WORKFLOW }o--|| SOP : governed_by
    WORKFLOW_RUN ||--o{ AGENT_RUN : traces
    WORKFLOW_RUN ||--o{ WORKFLOW_EVENT : emits
    WORKFLOW_RUN ||--o{ SAMPLE : produces
    WORKFLOW_RUN ||--o{ DATASET : builds
    SAMPLE ||--o{ SAMPLE_VERSION : refines
    SAMPLE ||--o{ EVALUATION : judged_by
    SAMPLE ||--o| APPROVAL : gated_by
    SAMPLE ||--o{ HUMAN_REVIEW : reviewed_by
    EVALUATION ||--o{ EVALUATION_ISSUE : reports
    DATASET ||--o{ DATASET_VERSION : formats
    PROMPT ||--o{ PROMPT_VERSION : versions
    EXPERIMENT ||--o{ EXPERIMENT_ARM : compares
    AGENT_RUN ||--o{ LLM_CALL : records
```

18 tables, UUID primary keys everywhere, `created_at`/`updated_at` mixins, JSONB for flexible payloads, and a `UniqueConstraint(run_id, sample_key)` plus a `content_hash` index for duplicate detection. Full column-level detail lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Frontend ↔ backend communication

| Need | Mechanism | Why |
|---|---|---|
| CRUD | REST over `NEXT_PUBLIC_API_URL` | Cacheable, trivially debuggable |
| Live run updates | `GET /api/runs/{id}/stream` (SSE) | One-way push, no socket server needed |
| SSE unavailable (some proxies) | Automatic fallback to `GET /events?after_seq=` polling | `useRunStream` reports which transport is active |
| Long execution | Client calls `POST /advance` while a run is non-terminal | Keeps each request short |

No hardcoded hosts anywhere. In local dev, `next.config.mjs` proxies `/api/*` to the backend, so browser code can always use relative URLs.

---

## 4. The six agents

| # | Agent | Input | Output (Pydantic-validated) | LLM? |
|---|---|---|---|---|
| 1 | **Planner** | Objective, SOP, sample count, domain hint | `GenerationPlan` — topics, difficulty mix, style guidance, batch strategy | ✅ |
| 2 | **Generator** | Plan slice (`COUNT`, `OFFSET`) | `GeneratedBatch` — samples with instruction/input/output/category/difficulty | ✅ |
| 3 | **Evaluator / Critic** | Sample + rendered SOP fragment | `EvaluationResult` — 5 dimension scores (0–10), `overall_score` (0–100), typed `issues[]`, `reasoning_summary` | ✅ ×N judges |
| 4 | **Refiner** | Sample + the critic's structured issues | `RefinedSample` — rewritten sample + `changes_made[]` | ✅ |
| 5 | **Approval** | Sample, consensus evaluation, SOP, run context | `ApprovalReport` — per-gate pass/fail + final status | ❌ **Deterministic** |
| 6 | **Dataset Builder** | All approved samples | Rows in instruction / chat / evaluation style, serialised to 4 formats | ❌ Deterministic |

### The Approval agent's six gates

Approval is deliberately **not** an LLM. A non-deterministic gatekeeper is not a gatekeeper.

1. **Schema validity** — the sample parses into the expected model.
2. **Required fields** — instruction, output and any SOP-mandated fields are present and non-trivial.
3. **Duplicate detection** — normalised `content_hash` (case- and whitespace-insensitive) against every sample in the run.
4. **Quality threshold** — consensus `overall_score ≥ approval_threshold`.
5. **Metadata completeness** — category, difficulty, provenance, prompt version, SOP version.
6. **SOP compliance** — no unresolved `critical` issue against any active SOP rule.

Result → `AUTO_APPROVED`, `AUTO_REJECTED`, or `NEEDS_REVIEW`. Humans then produce `HUMAN_APPROVED` or `HUMAN_REJECTED`.

---

## 5. LangGraph execution flow

```mermaid
stateDiagram-v2
    [*] --> planner
    planner --> generator
    generator --> dispatch

    dispatch --> critic: queue non-empty
    dispatch --> dataset_builder: queue empty / stop requested

    critic --> approval: consensus PASS
    critic --> human_gate: judges disagree > threshold
    critic --> refiner: FAIL and retries remaining
    critic --> human_gate: borderline score band
    critic --> fail_sample: FAIL and retries exhausted

    refiner --> critic: attempt + 1
    approval --> dispatch
    human_gate --> dispatch
    fail_sample --> dispatch

    dataset_builder --> export
    export --> [*]
```

**Routing priority inside the critic edge is exact and order-sensitive:**

```
1. approved                      → approval
2. judge disagreement > threshold→ human_gate
3. failed AND attempts < MAX     → refiner
4. borderline_low ≤ score < high → human_gate
5. otherwise                     → fail_sample
```

> This ordering was a real bug during development. With `retries` checked before `approved`, passing samples were re-refined and the refiner recorded 0 calls while `refinement_attempts` stayed at 0 — reliability analytics showed the evaluator at 83.33% for the wrong reason. Getting the priority right is what makes retry accounting truthful.

### Loop-safety proof

Three independent bounds, any one of which terminates the run:

1. Each sample carries `attempt`, incremented only by the refiner, and `attempt ≤ max_retries` is checked on the routing edge.
2. `dispatch` pops from a finite queue that only `generator` ever fills, exactly once.
3. `StepExecutor` refuses to exceed `MAX_WORKFLOW_STEPS` (500) and marks the run `FAILED` with a clear error if it would.

An evaluator *hard failure* (provider down, unparseable after repair) routes to `human_gate`, **not** to auto-reject — an infrastructure problem must never silently become a quality verdict.

### Multi-judge consensus

With `judges: N`, the same sample is scored by N independent evaluator calls (optionally different models via `judge_models`).

- **Consensus score** = mean of per-judge `overall_score`.
- **Disagreement** = `max − min`. Above `JUDGE_DISAGREEMENT_THRESHOLD` (default 15 points) the sample is routed to `human_gate` regardless of the mean — a confidently-averaged disagreement is the most dangerous kind of false confidence.
- Per-dimension scores are averaged independently, so the UI can show *where* judges diverged.

---

## 6. Tech stack

**Backend** — Python 3.12 · FastAPI · Pydantic v2 · pydantic-settings · LangGraph · SQLAlchemy 2.0 (typed ORM) · Alembic · PostgreSQL 16 · `psycopg` 3 · pytest + pytest-asyncio · ruff · mypy

**Frontend** — Next.js 14 (App Router) · TypeScript (strict) · Tailwind CSS · shadcn/ui-style primitives · Recharts · React Flow · lucide-react

**Infrastructure** — Docker + docker-compose · GitHub Actions · Vercel (two projects) · pluggable `StorageProvider` (Local / Memory / Vercel Blob / S3) and `TaskQueue` (inline / QStash)

---

## 7. Quick start

### Prerequisites

Python 3.12+, Node 20+, and *optionally* Docker. **No LLM API key is required.**

### Backend

```bash
git clone https://github.com/your-org/aura-eval.git
cd aura-eval/backend

python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env          # defaults already work: mock provider + SQLite
alembic upgrade head          # only needed for Postgres; SQLite auto-bootstraps

uvicorn app.main:app --reload --port 8000
```

- API → <http://localhost:8000/api/health>
- Interactive docs → <http://localhost:8000/docs>

### Frontend

```bash
cd aura-eval/frontend
npm install
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local
npm run dev
```

App → <http://localhost:3000>. Demo data is seeded on first boot (`SEED_DEMO_DATA=true`), so the dashboard is populated immediately.

### Prove it works

```bash
cd aura-eval
API=http://localhost:8000 bash scripts/acceptance.sh
```

This is the full acceptance path — project → SOP → workflow → run → plan/generate/evaluate/refine/approve → dataset → **downloaded JSONL** — and it asserts every stage. Expected tail:

```
▶ 8/8 Download JSONL
    6 valid JSON lines; keys = ['category', 'difficulty', 'input', 'instruction', 'output']
✓ ACCEPTANCE TEST PASSED — artifacts in ./.acceptance
```

---

## 8. Environment variables

Backend-only unless marked public. Full annotated template: [`.env.example`](.env.example).

### Core

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production` |
| `LOG_LEVEL` | `INFO` | Structured JSON logs with automatic secret redaction |
| `SERVERLESS` | `false` | `true` on Vercel → SQLAlchemy `NullPool` |
| `DATABASE_URL` | SQLite file | **Production must be PostgreSQL.** `postgresql+psycopg://…` |
| `API_PREFIX` | `/api` | |

### LLM

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` \| `openai` \| `anthropic` \| `gemini` |
| `DEFAULT_MODEL` | `mock-1` | |
| `LLM_TIMEOUT_SECONDS` | `60` | Hard timeout on every external call |
| `LLM_MAX_RETRIES` | `3` | Exponential backoff with jitter |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | – | Never sent to the browser |
| `PRICING_JSON` | see `.env.example` | USD per 1M tokens, per model. Configurable, never hardcoded |

### Workflow safety

| Variable | Default | Notes |
|---|---|---|
| `MAX_RETRIES` | `2` | Refinement attempts per sample |
| `MAX_WORKFLOW_STEPS` | `500` | Global loop ceiling |
| `QUALITY_THRESHOLD` | `75` | Auto-approve cutoff (0–100) |
| `JUDGE_DISAGREEMENT_THRESHOLD` | `15` | Above this → human review |
| `MAX_COST_USD_PER_RUN` | `5.0` | Budget guard |

### Storage, queue, security

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_PROVIDER` | `local` | `local` \| `memory` \| `blob` \| `s3`. **Use `blob`/`s3` on Vercel** |
| `TASK_QUEUE_PROVIDER` | `inline` | `inline` \| `qstash` |
| `AUTH_ENABLED` | `false` | JWT HS256; mutating routes always depend on `require_editor` |
| `JWT_SECRET` | dev value | **Must be rotated in production** |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated. **Never `*`** |
| `RATE_LIMIT_PER_MINUTE` | `120` | Sliding window |
| `CRON_SECRET` | – | Required in production to call `/api/internal/tick` |

### Frontend (public — must never hold a secret)

| Variable | Default |
|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` |

---

## 9. Docker

The compose stack is the fastest way to see the whole product:

```bash
cd aura-eval
cp .env.example .env
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| `frontend` | <http://localhost:3000> | Next.js standalone build |
| `backend` | <http://localhost:8000/docs> | FastAPI, healthchecked |
| `postgres` | `localhost:5432` | Persisted in the `aura-pgdata` volume |

```bash
docker compose logs -f backend        # follow API logs
docker compose exec backend alembic upgrade head
docker compose down                   # stop
docker compose down -v                # stop and wipe the database
```

Both images run as a non-root UID 10001. The backend image declares a `HEALTHCHECK` against `/api/health`; the frontend uses a three-stage build so the runtime image ships only `.next/standalone`.

---

## 10. Example workflow (end to end)

```bash
API=http://localhost:8000

# 1 · Project
PROJECT=$(curl -s -X POST $API/api/projects -H 'content-type: application/json' \
  -d '{"name":"Python Tutor Dataset","description":"SFT data for a coding assistant"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 2 · SOP — the machine-readable quality contract
SOP=$(curl -s -X POST $API/api/sops -H 'content-type: application/json' -d "{
  \"name\":\"Python Q&A Standard\",
  \"project_id\":\"$PROJECT\",
  \"threshold\":75,
  \"rules\":[
    {\"id\":\"r1\",\"text\":\"Answer must be factually correct and runnable.\",
     \"criterion\":\"correctness\",\"severity\":\"critical\",\"weight\":2.0},
    {\"id\":\"r2\",\"text\":\"Answer must directly address the question.\",
     \"criterion\":\"relevance\",\"severity\":\"major\",\"weight\":1.5},
    {\"id\":\"r3\",\"text\":\"Include a short worked example.\",
     \"criterion\":\"completeness\",\"severity\":\"major\",\"weight\":1.0},
    {\"id\":\"r4\",\"text\":\"No unsafe or destructive code.\",
     \"criterion\":\"safety\",\"severity\":\"critical\",\"weight\":2.0}
  ]}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 3 · Workflow — 3 judges, up to 2 refinements per sample
WF=$(curl -s -X POST $API/api/workflows -H 'content-type: application/json' -d "{
  \"project_id\":\"$PROJECT\", \"sop_id\":\"$SOP\",
  \"name\":\"Python Q&A v1\",
  \"objective\":\"Generate high-quality Python question/answer training samples\",
  \"config\":{\"sample_count\":12,\"judges\":3,\"max_retries\":2,
              \"dataset_style\":\"instruction\",
              \"dataset_formats\":[\"jsonl\",\"json\",\"csv\"]}}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 4 · Run — returns immediately with a run_id
RUN=$(curl -s -X POST $API/api/workflows/$WF/run -H 'content-type: application/json' -d '{}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 5 · Watch it live (Ctrl-C to stop)
curl -N $API/api/runs/$RUN/stream

# 6 · Or drive it in slices (serverless-safe)
until curl -s $API/api/runs/$RUN/status | grep -q '"terminal":true'; do
  curl -s -X POST $API/api/runs/$RUN/advance -d '{"max_steps":25}' -H 'content-type: application/json' >/dev/null
done

# 7 · Inspect the trace: agent, model, latency, tokens, cost, status
curl -s $API/api/runs/$RUN/trace | head -c 800

# 8 · Build the dataset and download JSONL
DS=$(curl -s -X POST $API/api/datasets -H 'content-type: application/json' \
  -d "{\"run_id\":\"$RUN\",\"style\":\"instruction\",\"formats\":[\"jsonl\",\"csv\"]}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -sL "$API/api/datasets/$DS/download?format=jsonl" -o python_qa.jsonl
head -1 python_qa.jsonl
```

```json
{"instruction":"Explain how Python's list comprehension works.","input":"","output":"A list comprehension builds a list in a single expression …","category":"language-basics","difficulty":"beginner"}
```

### Dataset styles

| Style | Shape | Use for |
|---|---|---|
| `instruction` | `{instruction, input, output, category, difficulty}` | Alpaca-style SFT |
| `chat` | `{messages: [{role, content}, …]}` | Chat fine-tuning |
| `evaluation` | `{prompt, reference, scores{}, issues[], sop_version}` | Building an eval/benchmark set |

---

## 11. API reference

Everything is under `/api`. Live OpenAPI docs at `/docs`, schema at `/openapi.json`.

<details open>
<summary><b>Health</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness — always cheap |
| `GET` | `/api/health/database` | Executes `SELECT 1`, reports dialect + latency |
| `GET` | `/api/health/llm` | Provider reachability and configured model |
| `GET` | `/api/health/config` | Non-secret effective configuration |
</details>

<details>
<summary><b>Projects</b></summary>

`POST /api/projects` · `GET /api/projects` · `GET|PUT|DELETE /api/projects/{id}`
</details>

<details>
<summary><b>SOPs — versioned quality contracts</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sops` | Create (version 1) |
| `GET` | `/api/sops` | List |
| `GET` | `/api/sops/defaults` | Starter rule templates |
| `GET` | `/api/sops/{id}` | Fetch with version history |
| `PUT` | `/api/sops/{id}` | **Creates version N+1** — content is immutable |
| `POST` | `/api/sops/{id}/activate` | Make active for its project |
| `POST` | `/api/sops/{id}/versions/{v}/restore` | Restore an old version as a new one |
| `GET` | `/api/sops/{id}/render` | The exact prompt fragment judges receive |
| `POST` | `/api/sops/{id}/test` | Dry-run the SOP against a pasted sample |
| `DELETE` | `/api/sops/{id}` | Delete |
</details>

<details>
<summary><b>Workflows & runs</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/workflows` | Create |
| `GET` | `/api/workflows` | List |
| `GET|PUT|DELETE` | `/api/workflows/{id}` | Manage |
| `GET` | `/api/workflows/topology` | Graph nodes/edges for React Flow |
| `POST` | `/api/workflows/{id}/run` | **Start — returns `run_id` immediately** |
| `POST` | `/api/workflows/{id}/stop` | Cooperative stop of the active run |
| `GET` | `/api/workflows/{id}/runs` | Run history |
| `GET` | `/api/runs` · `/api/runs/{id}` | List / detail |
| `GET` | `/api/runs/{id}/status` | Compact progress poll |
| `GET` | `/api/runs/{id}/events?after_seq=` | Incremental event log |
| `GET` | `/api/runs/{id}/stream` | **SSE** live feed |
| `GET` | `/api/runs/{id}/trace` | Full span list: agent, model, latency, tokens, cost, status |
| `GET` | `/api/runs/{id}/graph` | Live per-node execution state |
| `POST` | `/api/runs/{id}/advance` | Execute one bounded slice |
| `POST` | `/api/runs/{id}/stop` | Request stop |
</details>

<details>
<summary><b>Samples & human review</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/samples?status=&run_id=` | Filtered list |
| `GET` | `/api/samples/review-queue` | Everything in `NEEDS_REVIEW` |
| `GET` | `/api/samples/{id}` | Full detail: judges, consensus, approval report, lineage |
| `GET` | `/api/samples/{id}/history` | Every version with the diff between attempts |
| `GET` | `/api/samples/{id}/evaluations` | Per-judge scores and issues |
| `POST` | `/api/samples/{id}/approve` | → `HUMAN_APPROVED` |
| `POST` | `/api/samples/{id}/reject` | → `HUMAN_REJECTED` (reason required) |
| `POST` | `/api/samples/{id}/edit` | Edit and approve in one action |
</details>

<details>
<summary><b>Datasets</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/datasets` | Build from a run's approved samples |
| `GET` | `/api/datasets` · `/api/datasets/{id}` | List / detail with artifacts |
| `GET` | `/api/datasets/{id}/preview?limit=` | First N rows for the UI |
| `GET` | `/api/datasets/{id}/download?format=jsonl` | `json` \| `jsonl` \| `csv` \| `parquet` |
| `DELETE` | `/api/datasets/{id}` | Delete dataset and artifacts |
</details>

<details>
<summary><b>Analytics, experiments, prompts, internal</b></summary>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/analytics` | Dashboard rollup |
| `GET` | `/api/analytics/evaluation` | Criteria pass rates, score distribution, top failures |
| `GET` | `/api/analytics/reliability` | Per-agent reliability %, error breakdown, failure chains |
| `GET` | `/api/analytics/cost` | Cost and token attribution by agent and model |
| `POST|GET` | `/api/experiments` | Create / list A-vs-B experiments |
| `GET` | `/api/experiments/{id}` | Comparison report with per-metric winner |
| `GET` | `/api/prompts` · `/api/prompts/{id}` | Prompt registry |
| `GET|POST` | `/api/prompts/{id}/versions` | History / create a version |
| `GET` | `/api/prompts/{id}/diff?a=1&b=2` | Unified diff between versions |
| `POST|GET` | `/api/internal/tick` | Cron-driven slice advance (secret-protected) |
</details>

### Error format

Every failure returns the same envelope, so the frontend has exactly one error path:

```json
{
  "error": {
    "type": "validation_failed",
    "message": "sample_count must be between 1 and 50",
    "details": { "field": "config.sample_count" },
    "request_id": "0f2a1c94-4a1e-4b7f-9d55-8b0f6a1c2d3e"
  }
}
```

`request_id` is echoed in the `X-Request-ID` response header and appears in the structured logs.

---

## 12. Screenshots

Place images in `docs/screenshots/` using these names (see that folder's README for the capture list).

| | |
|---|---|
| ![Landing](docs/screenshots/01-landing.png)<br/>**Landing** — animated agent pipeline | ![Dashboard](docs/screenshots/02-dashboard.png)<br/>**Dashboard** — throughput & quality |
| ![Workflow graph](docs/screenshots/03-workflow-graph.png)<br/>**Workflow** — LangGraph topology | ![Live run](docs/screenshots/04-live-run.png)<br/>**Live run** — SSE event feed |
| ![Sample inspector](docs/screenshots/05-sample-inspector.png)<br/>**Sample inspector** — judge consensus | ![SOP editor](docs/screenshots/06-sop-editor.png)<br/>**SOP editor** — versioned rules |
| ![Review queue](docs/screenshots/07-review-queue.png)<br/>**Review** — human in the loop | ![Analytics](docs/screenshots/08-analytics.png)<br/>**Analytics** — criteria radar |
| ![Reliability](docs/screenshots/09-reliability.png)<br/>**Reliability** — failure propagation | ![Datasets](docs/screenshots/10-datasets.png)<br/>**Datasets** — multi-format export |
| ![Traces](docs/screenshots/11-traces.png)<br/>**Traces** — latency/token waterfall | ![Experiments](docs/screenshots/12-experiments.png)<br/>**Experiments** — A vs B report |

---

## 13. Evaluation methodology

### The five dimensions

Every judge returns integer scores 0–10 on each:

| Dimension | Question it answers |
|---|---|
| **Correctness** | Is the content factually and technically right? |
| **Relevance** | Does it actually address the instruction? |
| **Completeness** | Is anything materially missing? |
| **Instruction-following** | Does it obey the requested format, length and constraints? |
| **Safety** | Is it free of harmful, unsafe or policy-violating content? |

### From dimensions to a verdict

```
overall_score (0–100) = 100 × Σ(dimension_score × sop_weight) / Σ(10 × sop_weight)
```

SOP rules carry a `weight` and a `criterion`, so the SOP directly controls what the aggregate means. A dataset that values safety over completeness simply weights those rules differently — no code change.

```
consensus       = mean(overall_score across judges)
disagreement    = max(overall_score) − min(overall_score)

consensus ≥ approval_threshold              → PASS   → Approval agent
disagreement > 15                           → NEEDS_REVIEW  (regardless of mean)
borderline_low ≤ consensus < borderline_high→ NEEDS_REVIEW
otherwise                                   → FAIL   → Refiner (if retries remain)
```

### Issues, not essays

A failing judgement must be *actionable*, so each issue is structured:

```json
{
  "criterion": "completeness",
  "severity": "major",
  "rule_id": "r3",
  "description": "No worked example is provided.",
  "suggestion": "Add a 3–5 line runnable snippet demonstrating the concept."
}
```

The Refiner consumes exactly these fields. That is why refinement converges instead of drifting.

### No chain-of-thought — deliberately

Judges are asked for a **`reasoning_summary` of at most two sentences** plus structured evidence. Hidden reasoning is never requested, never persisted and never rendered. Rationale: CoT text is unverifiable, inflates storage and token cost, frequently rationalises rather than explains, and creates a leak surface. Structured issues tied to SOP rule IDs are strictly more useful and fully auditable.

### Bias mitigations

- **Multi-judge** scoring with explicit disagreement routing rather than silent averaging.
- **Heterogeneous judges** — set `judge_models` to grade with different models/providers.
- **Deterministic final gate** — the Approval agent is code, so an eloquent-but-wrong sample cannot talk its way through.
- **SOP anchoring** — judges score against explicit written rules, not vibes.

### Determinism in mock mode

The Mock provider is prompt-routed and seeded: identical inputs produce byte-identical outputs. This is what makes CI meaningful and lets `mock_failure_rate` deterministically exercise error paths. Prompts must carry an `AURA-TASK: <agent>` header plus the relevant `<OBJECTIVE>` / `<SAMPLE>` / `<JUDGE>` tags and `COUNT:` / `OFFSET:` markers.

---

## 14. Reliability metrics

Every agent invocation is recorded as an `AgentRun` with one of three outcomes:

| Status | Meaning |
|---|---|
| `SUCCESS` | Valid, schema-conformant output on the first attempt |
| `DEGRADED` | Succeeded, but only after a retry, a JSON repair or a fallback |
| `FAILED` | Could not produce valid output within the retry budget |

```
reliability % = (success + 0.5 × degraded) / total_calls
```

Degraded calls count half: the pipeline survived, but it cost extra latency and tokens and it is a leading indicator of an unstable prompt or a flaky provider.

The `/reliability` page surfaces:

- **Per-agent reliability bars** — instantly shows whether the generator or the judges are the weak link.
- **Error taxonomy** — timeout · invalid JSON · schema violation · provider error · budget exceeded.
- **Failure propagation chains** — e.g. `generator DEGRADED → evaluator FAILED → sample NEEDS_REVIEW`, so you can see how one flaky node contaminates downstream verdicts.
- **Retry effectiveness** — what fraction of refinements actually converted a FAIL into a PASS.
- **Cost of failure** — tokens and USD burned on calls that produced nothing usable.

Additional health signals: samples per run, approval rate, average refinement attempts, human intervention rate, judge disagreement rate, p50/p95 agent latency.

---

## 15. Testing

```bash
cd backend
pytest tests -q                       # 74 tests
pytest tests --cov=app --cov-report=term-missing
```

| Suite | Count | Covers |
|---|---|---|
| `test_unit_agents.py` | 24 | Each agent in isolation, prompt rendering, SOP scoring, dataset row builders |
| `test_integration_workflow.py` | 9 | Full graph traversal, refinement loops, consensus, dataset creation |
| `test_failures.py` | 16 | Timeouts, malformed JSON, schema violations, budget exhaustion, retry exhaustion, stop requests |
| `test_api_e2e.py` | 9 | HTTP surface: run → advance → samples → dataset → download, SSE, topology, prompt versioning |
| `test_security_and_infra.py` | 16 | Auth gating, CORS, rate limiting, secret redaction, storage providers, cron tick auth and termination |

Plus [`scripts/acceptance.sh`](scripts/acceptance.sh) — the black-box acceptance path against a live server.

```bash
cd frontend
npm run typecheck     # tsc --noEmit, strict
npm run lint          # next lint — zero warnings
npm run build         # 18 routes
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs ruff, ruff-format, mypy, pytest, an Alembic up/down cycle, frontend typecheck/lint/build, and both Docker image builds on every push and PR. A weekly [`e2e.yml`](.github/workflows/e2e.yml) job runs the acceptance script against real PostgreSQL.

---

## 16. Deploying to Vercel

AURA-EVAL was architected for Vercel from day one: no in-memory state, no background workers, no WebSocket server, no local-filesystem persistence, no SQLite in production.

Deploy as **two Vercel projects** from the same repository — independent scaling and independent rollback.

### Step 1 — Provision managed Postgres

Use Neon, Supabase, or Vercel Postgres. **Do not run a database inside Vercel.** Copy the pooled connection string and convert the scheme:

```
postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require
```

### Step 2 — Deploy the backend project

| Setting | Value |
|---|---|
| Root directory | `backend` |
| Framework preset | Other |
| Build command | *(leave empty — `@vercel/python` handles it)* |

`backend/vercel.json` routes all traffic to `api/index.py`, which re-exports the FastAPI `app` as the ASGI handler, with 1024 MB memory and a 60 s max duration.

Environment variables (Production scope):

```
ENVIRONMENT=production
SERVERLESS=true
DATABASE_URL=postgresql+psycopg://…?sslmode=require
LLM_PROVIDER=openai              # or keep mock for a free public demo
OPENAI_API_KEY=sk-…
STORAGE_PROVIDER=blob            # NOT local — the FS is ephemeral and read-only
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_…
CORS_ORIGINS=https://your-frontend.vercel.app
JWT_SECRET=<openssl rand -hex 32>
CRON_SECRET=<openssl rand -hex 32>
SEED_DEMO_DATA=false
```

> `SERVERLESS=true` switches SQLAlchemy to `NullPool`. Without it, every cold start leaks connections and you will exhaust the Postgres pool.

### Step 3 — Run migrations

Vercel does not run migrations for you. From your machine, pointed at production:

```bash
cd backend
DATABASE_URL='postgresql+psycopg://…?sslmode=require' alembic upgrade head
```

### Step 4 — Deploy the frontend project

| Setting | Value |
|---|---|
| Root directory | `frontend` |
| Framework preset | Next.js |

```
NEXT_PUBLIC_API_URL=https://your-backend.vercel.app
```

Then redeploy the backend with `CORS_ORIGINS` set to the real frontend URL (chicken-and-egg: you need each URL for the other).

### Step 5 — Enable the cron tick

`backend/vercel.json` already declares:

```json
"crons": [{ "path": "/api/internal/tick", "schedule": "*/1 * * * *" }]
```

Vercel Cron sends `Authorization: Bearer $CRON_SECRET`. Each tick advances up to 5 in-flight runs by up to 40 steps each — comfortably inside the function timeout — so runs progress even when no browser is open.

### Step 6 — Verify

```bash
curl https://your-backend.vercel.app/api/health
curl https://your-backend.vercel.app/api/health/database
curl https://your-backend.vercel.app/api/health/llm
```

All three must return `{"status":"ok", …}`. Then open the frontend; the sidebar footer shows a live API health indicator.

### Vercel limits to respect

| Limit | Consequence | Mitigation |
|---|---|---|
| 60 s function duration (Pro) | A long run cannot finish in one request | Bounded `/advance` slices + cron tick |
| Ephemeral, read-only FS | `STORAGE_PROVIDER=local` loses artifacts | Use `blob` or `s3` |
| No persistent connections | SSE ends when the function does | `useRunStream` auto-falls back to polling |
| Cold starts | First request is slow | Keep the lambda lean; the tick keeps it warm |

---

## 17. Troubleshooting

<details>
<summary><b>Frontend shows "API unreachable"</b></summary>

1. `curl $NEXT_PUBLIC_API_URL/api/health` — is the backend actually up?
2. Check the browser console for a CORS error. `CORS_ORIGINS` must contain the frontend origin **exactly** (scheme + host + port, no trailing slash).
3. `NEXT_PUBLIC_*` variables are inlined **at build time** — after changing one you must rebuild/redeploy, not just restart.
</details>

<details>
<summary><b>A run is stuck in RUNNING</b></summary>

```bash
curl $API/api/runs/$RUN/status      # look at resume_at, steps_executed, error
curl -X POST $API/api/runs/$RUN/advance -d '{"max_steps":25}' -H 'content-type: application/json'
```
Nothing advances it automatically unless the UI is open or the cron tick is configured. On Vercel, verify the cron job exists and that `CRON_SECRET` matches. If `steps_executed` is near 500 the loop ceiling tripped — check the run's error field.
</details>

<details>
<summary><b>`sqlalchemy.exc.OperationalError: too many connections`</b></summary>

`SERVERLESS=true` is missing in production, so pooling is on inside lambdas. Set it and redeploy. Also prefer your provider's *pooled* connection string.
</details>

<details>
<summary><b>`ModuleNotFoundError: psycopg`</b></summary>

`pip install "psycopg[binary]"`. Ensure the URL scheme is `postgresql+psycopg://` (psycopg 3), not `postgresql+psycopg2://`.
</details>

<details>
<summary><b>Parquet download returns an error</b></summary>

Parquet needs `pandas` and `pyarrow`, which are optional to keep the serverless bundle under the size limit. Install them, or export JSONL/CSV instead.
</details>

<details>
<summary><b>Alembic: "Target database is not up to date"</b></summary>

```bash
alembic current      # where you are
alembic history      # what exists
alembic upgrade head
```
Never hand-edit a migration that has already been applied to a shared database — add a new one.
</details>

<details>
<summary><b>Everything scores identically / results feel fake</b></summary>

You are on `LLM_PROVIDER=mock`, which is deterministic by design. Set a real provider and API key for genuine variance.
</details>

<details>
<summary><b>All samples land in NEEDS_REVIEW</b></summary>

Either `QUALITY_THRESHOLD` is too high for your SOP's weighting, or judges are disagreeing. Open `/analytics` → criteria pass rates to see which dimension is dragging, and `/samples/{id}` to see the per-judge spread.
</details>

<details>
<summary><b>Datasets are empty after a run</b></summary>

Only `AUTO_APPROVED` and `HUMAN_APPROVED` samples are exported. Clear the review queue at `/review`, then rebuild the dataset.
</details>

<details>
<summary><b>429 Too Many Requests in development</b></summary>

Raise `RATE_LIMIT_PER_MINUTE`. The limiter is a per-instance sliding window; for multi-instance production use an edge/CDN rate limiter as well.
</details>

---

## 18. Rollback procedure

**1 · Application code** — instant, zero-downtime:

```bash
vercel rollback https://aura-eval-backend-<previous-deployment>.vercel.app
# or: Vercel dashboard → Deployments → previous → "Promote to Production"
```

Roll the **backend back first**, then the frontend, so the UI is never newer than the API it calls.

**2 · Database** — code rollback is only safe if the schema is compatible. If the bad release included a migration:

```bash
cd backend
alembic current
DATABASE_URL='…' alembic downgrade -1     # one step back
```

Every migration in this project implements `downgrade()`, and CI verifies `upgrade head` followed by `downgrade base` on every push.

**3 · Prefer expand/contract over downgrade.** For a destructive change, ship it in two releases — add the new column (expand), migrate reads/writes, then drop the old one (contract) in a *later* release. That way a rollback never needs a destructive downgrade.

**4 · In-flight runs.** A rollback does not corrupt runs: state is persisted per node. Any run mid-flight resumes under the old code on the next `/advance` or cron tick. If a run is wedged on removed logic, stop it:

```bash
curl -X POST $API/api/runs/$RUN/stop
```

A stopped run still builds a dataset from whatever was already approved.

**5 · Post-rollback verification.**

```bash
curl https://your-backend.vercel.app/api/health/database
curl https://your-backend.vercel.app/api/health/llm
API=https://your-backend.vercel.app bash scripts/acceptance.sh
```

---

## 19. Security checklist

**Secrets**

- [x] All API keys read from environment via `pydantic-settings`; none in source or client bundles
- [x] `.env` git-ignored; `.env.example` contains placeholders only
- [x] `/api/health/config` returns `safe_public_dict()` — secret fields are structurally excluded
- [x] Structured logger applies `redact()` to keys, tokens and connection strings
- [x] Only `NEXT_PUBLIC_API_URL` is exposed to the browser
- [ ] Rotate `JWT_SECRET` and `CRON_SECRET` (`openssl rand -hex 32`) before going live

**Transport & CORS**

- [x] `CORS_ORIGINS` is an explicit allow-list; `*` is never used for authenticated APIs
- [x] Security headers set on the frontend (`nosniff`, `SAMEORIGIN`, referrer policy, permissions policy)
- [ ] Enforce HTTPS everywhere and require `sslmode=require` on the database URL

**Authentication & authorisation**

- [x] JWT HS256 with expiry; `Principal` roles viewer / editor / admin
- [x] Every mutating endpoint depends on `require_editor`; destructive ones on `require_admin`
- [x] `/api/internal/tick` requires `CRON_SECRET` and is hard-disabled in production without it
- [ ] Set `AUTH_ENABLED=true` for any non-public deployment

**Input & output safety**

- [x] Every request body validated by a Pydantic schema with bounded lengths and ranges
- [x] Every LLM response validated before use — raw output is never trusted
- [x] SQLAlchemy parameterised queries only; no string-built SQL
- [x] `Content-Disposition` filenames sanitised to latin-1 (a raw name crashes Starlette)
- [x] Uniform error envelope — no stack traces or internals leak to clients

**Availability & cost**

- [x] Sliding-window rate limiting on all routes
- [x] Timeouts on every external call; retries with exponential backoff and jitter
- [x] `MAX_WORKFLOW_STEPS` and per-sample `MAX_RETRIES` make infinite loops impossible
- [x] Per-run USD budget cap
- [x] Pagination with hard `limit` ceilings on every list endpoint

**Data handling**

- [x] No chain-of-thought stored — concise summaries and structured evidence only
- [x] Human review actions are attributed and timestamped
- [x] Cascade deletes keep orphaned samples/artifacts from accumulating
- [ ] Define a retention policy for generated datasets containing customer-derived content

**Supply chain**

- [x] Pinned dependency versions in `requirements*.txt` and `package-lock.json`
- [x] Containers run as non-root UID 10001
- [ ] Enable Dependabot and secret scanning on the repository

---

## 20. Research possibilities

AURA-EVAL is deliberately instrumented to be a research substrate, not just a tool.

- **LLM-as-judge reliability.** Every judgement is stored with model, prompt version, SOP version and per-dimension scores — enough to compute inter-judge agreement (Krippendorff's α), test self-preference bias by grading a model's output with itself vs. others, and measure position/verbosity bias.
- **Optimal judge ensembles.** Is 3 cheap judges better than 1 expensive one at equal cost? The experiment system and cost tracking answer this empirically.
- **Refinement convergence.** With full sample lineage, you can measure the marginal score gain per refinement attempt and find where `MAX_RETRIES` stops paying for itself.
- **SOP formalisation.** How much does an explicit weighted rubric improve judge consistency over an open-ended "rate this"? Both are one SOP version apart.
- **Failure propagation modelling.** The reliability graph is real data on how degradation cascades through a multi-agent system — useful for building predictive reliability models.
- **Synthetic data quality → downstream performance.** Export at several approval thresholds, fine-tune, and correlate gate strictness with eval performance. Is stricter always better, or does it collapse diversity?
- **Human–AI agreement.** Every human review is a labelled disagreement with the machine verdict — a ready-made calibration dataset for judge prompts.
- **Cost-quality Pareto frontiers.** Token and USD attribution per agent per model makes the frontier directly plottable.

---

## 21. Future work

**Near term**

- Vector-similarity duplicate detection (embeddings) alongside the exact `content_hash`
- Diversity metrics — topic entropy, embedding-space coverage — surfaced on the analytics page
- Dataset diffing between runs, and append/merge into an existing dataset
- Bulk review actions and keyboard-driven triage in the review queue
- Direct export to Hugging Face Hub and S3

**Medium term**

- Visual drag-and-drop workflow editor that writes real graph topology
- Custom agent nodes (translation, PII redaction, style transfer) as plugins
- Scheduled recurring runs with drift alerts when quality regresses
- Per-project RBAC, teams and an audit log
- Prompt A/B testing with automatic statistical significance
- Streaming token-level output in the live run view

**Long term**

- Self-improving SOPs — mine human overrides to propose new rules automatically
- Active learning: route only maximally-informative samples to humans
- Judge calibration against a golden human-labelled set, with automatic prompt tuning
- Distributed execution across a real queue for 100k+ sample runs
- Multi-modal evaluation (images, audio, tool-use traces)
- A public benchmark leaderboard built from community SOPs

---

## 22. Project layout

```
aura-eval/
├── backend/
│   ├── app/
│   │   ├── api/              # 10 routers + shared deps (thin HTTP layer)
│   │   ├── agents/           # planner, generator, evaluator, refiner, approval, dataset_builder
│   │   ├── workflows/        # LangGraph: state, nodes, graph, StepExecutor
│   │   ├── services/         # workflow, sop_engine, analytics, experiments, storage, queue, seed
│   │   ├── providers/        # Mock, OpenAI, Anthropic, Gemini behind one interface
│   │   ├── models/           # SQLAlchemy entities, enums, GUID/JSONType, mixins
│   │   ├── schemas/          # Pydantic request/response + agent I/O contracts
│   │   ├── database/         # lazy engine, sessionmaker, session_scope
│   │   ├── core/             # config, structured logging, errors, security
│   │   └── main.py           # app factory, middleware, bootstrap
│   ├── alembic/              # migrations (up + down verified in CI)
│   ├── tests/                # 74 tests across 5 suites
│   ├── api/index.py          # Vercel ASGI entrypoint
│   ├── pyproject.toml        # ruff + mypy configuration
│   └── vercel.json           # python runtime, cron tick
├── frontend/
│   ├── app/
│   │   ├── page.tsx          # landing — animated agent pipeline
│   │   └── (app)/            # dashboard, workflows, runs, samples, review,
│   │                         # datasets, sops, prompts, experiments,
│   │                         # analytics, reliability, traces
│   ├── components/           # Shell, WorkflowGraph (React Flow), ui primitives
│   ├── hooks/                # useAsync (polling), useRunStream (SSE + fallback)
│   ├── lib/                  # typed API client, shared types, formatters
│   └── vercel.json           # security headers
├── docker/                   # Dockerfile.backend, Dockerfile.frontend
├── docs/
│   ├── ARCHITECTURE.md       # full design document
│   └── screenshots/
├── scripts/acceptance.sh     # end-to-end acceptance test
├── .github/workflows/        # ci.yml, e2e.yml
├── docker-compose.yml
├── .env.example
└── README.md
```

---

<div align="center">

**Built as a demonstration that multi-agent systems can be engineered, not just prompted.**

MIT Licensed · [Architecture deep-dive](docs/ARCHITECTURE.md) · [Report an issue](../../issues)

</div>
