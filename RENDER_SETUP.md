# Render — manual setup (copy/paste)

Use this if you are creating services **by hand** in the Render dashboard.
If you use **New → Blueprint** and point it at [`render.yaml`](../render.yaml),
every value below is filled in automatically and you can skip this file.

There are **two services**. They have different settings — make sure you are
filling in the right one.

---

## Service 1 — API (FastAPI)

> New → **Web Service** → connect repo → **Language: Python 3**

| Field | Value |
|---|---|
| **Root Directory** | `backend` |
| **Build Command** | see below |
| **Start Command** | see below |
| **Health Check Path** | `/api/health` |

**Build Command**

```bash
pip install --upgrade pip && pip install -r requirements-optional.txt && alembic upgrade head
```

**Start Command**

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

### Why these exact commands

- **`requirements-optional.txt`**, not `requirements.txt` — it pulls in the core
  set *plus* `pyarrow` / `pandas` / `redis`. There is no serverless bundle-size
  limit on Render, so you get Parquet dataset export. (`requirements.txt` is the
  slim set kept lean for Vercel's 250 MB lambda cap.)
- **`alembic upgrade head` in the build**, not the start command. Render keeps
  the previous version serving until the new one passes its health check, so the
  build is the safe place for migrations. Putting it in the start command would
  re-run it on every restart and race between multiple booting instances.
- **`--host 0.0.0.0`** — binding to `127.0.0.1` makes the service unreachable
  and Render's health check will fail the deploy.
- **`$PORT`** — Render assigns the port; hardcoding `8000` fails the health check.
- **`--workers 1`** — deliberate. Workflow runs execute in a FastAPI
  `BackgroundTask` inside the worker process. A second worker would not see runs
  started by the first, so status polling would intermittently look stalled.
  Scale by adding Render **instances**, not uvicorn workers.

### Environment variables

Set these under **Environment**:

```
ENVIRONMENT=production
SERVERLESS=false
PYTHON_VERSION=3.12
DATABASE_URL=<Internal Database URL from your Render Postgres>
LLM_PROVIDER=mock
STORAGE_PROVIDER=local
STORAGE_DIR=/var/data/storage
TASK_QUEUE_PROVIDER=inline
JWT_SECRET=<generate: openssl rand -hex 32>
CORS_ORIGINS=https://<your-frontend>.onrender.com
SEED_DEMO_DATA=true
```

> **`SERVERLESS=false` is not optional.** Render is a persistent host. If this is
> true (or absent on a platform that looks serverless), SQLAlchemy switches to
> `NullPool` and `STORAGE_PROVIDER=local` is silently downgraded to in-memory —
> your dataset artifacts disappear as soon as the request ends.

> **`DATABASE_URL`**: use the **Internal** Database URL — it is faster and free
> of egress charges. The app rewrites a `postgres://` scheme to
> `postgresql+psycopg://` automatically, so paste it as Render gives it to you.

### Persistent disk (recommended)

Add a disk so generated datasets survive restarts and deploys:

| Field | Value |
|---|---|
| Name | `aura-storage` |
| Mount Path | `/var/data` |
| Size | 1 GB |

`STORAGE_DIR` must live **inside** the mount path — hence
`/var/data/storage`. Disks require a paid instance type; on the free tier, drop
the disk and set `STORAGE_PROVIDER=s3` (or `blob`) instead.

---

## Service 2 — Frontend (Next.js)

> New → **Web Service** → same repo → **Language: Node**

| Field | Value |
|---|---|
| **Root Directory** | `frontend` |
| **Build Command** | see below |
| **Start Command** | see below |

**Build Command**

```bash
npm ci && npm run build && cp -r .next/static .next/standalone/.next/static && (cp -r public .next/standalone/public 2>/dev/null || true)
```

**Start Command**

```bash
node .next/standalone/server.js
```

### Why not `npm start`

`next.config.mjs` sets `output: 'standalone'`. Running `next start` against a
standalone build prints:

```
⚠ "next start" does not work with "output: standalone" configuration.
  Use "node .next/standalone/server.js" instead.
```

The standalone bundle ships its own minimal server and a pruned `node_modules`,
but Next does **not** copy static assets into it — without the `cp` steps the
pages render unstyled (every `/_next/static/*` request 404s). The `public/`
copy is wrapped in `|| true` because this project has no `public/` directory
today; the guard keeps the command working if one is added later.

### Environment variables

```
NODE_VERSION=20
NODE_ENV=production
HOSTNAME=0.0.0.0
NEXT_PUBLIC_API_URL=https://<your-api>.onrender.com
```

> `NEXT_PUBLIC_*` values are inlined into the bundle **at build time**. After
> changing `NEXT_PUBLIC_API_URL` you must trigger a **redeploy**, not just a
> restart — and it must have no trailing slash.

---

## Order of operations

1. Create the **Postgres** instance first (Render dashboard → New → Postgres).
2. Deploy the **API**, using that database's Internal URL.
3. Deploy the **frontend**, setting `NEXT_PUBLIC_API_URL` to the API's URL.
4. Go back to the API and set `CORS_ORIGINS` to the frontend URL, then redeploy
   the API.

Step 4 is unavoidable with two services: each needs the other's URL, and neither
exists until it is deployed.

## Verify

```bash
API=https://<your-api>.onrender.com

curl $API/api/health
curl $API/api/health/database
curl $API/api/health/llm

# full end-to-end: project -> SOP -> run -> dataset -> JSONL
API=$API bash scripts/acceptance.sh
```

All three health probes must return `"status": "healthy"`.

## Free-tier caveats

- Instances **sleep after 15 minutes idle**; the next request takes ~30 s to
  wake. Upgrade to `starter` to avoid it.
- Free Postgres **expires after 90 days**. Upgrade to `basic-256mb` for anything
  you care about.
- Free instances cannot mount disks — use S3/Blob storage instead.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Deploy fails at health check | Missing `--host 0.0.0.0` or `$PORT`, or `DATABASE_URL` unreachable |
| Datasets vanish after a request | `SERVERLESS` not set to `false`, or `STORAGE_DIR` outside the disk mount |
| Frontend loads unstyled | `.next/static` not copied into the standalone bundle |
| Browser console CORS errors | `CORS_ORIGINS` missing the frontend origin (exact scheme + host, no trailing slash) |
| `too many connections` | `SERVERLESS=true` on Render disables pooling — set it to `false` |
| Frontend calls the wrong API | `NEXT_PUBLIC_API_URL` changed without a rebuild |
