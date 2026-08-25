# Run in local mode

Laptop-only overlay. It is gitignored and never imported by production.

| | `uvicorn main:app` | `uvicorn local.app:app` (this overlay) |
|---|---|---|
| Storage | GCS | Disk (`local-data/objects`) |
| Jobs | Cloud Workflows | In-process threads |
| Auth | Google Sign-In + session cookie | Auto-login as `LOCAL_USER_EMAIL` or the first user row |
| Dropbox | Real client if configured | Disabled |
| Client | Unchanged | Unchanged (no client flag) |

## Prerequisites

- Docker (local Postgres)
- Python 3.12+ and `server/.venv` with `requirements.txt`
- Node.js (Vite client)
- OpenRouter API key (generation still calls OpenRouter)
- At least one row in the **user** database (auto-login binds that user)
- Catalog data (brand, SKUs, attributes) if you want to run a real job

## 1. Local Postgres

From the **repo root**:

```bash
docker compose -f docker-compose.local.yml up -d
```

Postgres listens on **port 5433**. On first boot it creates database `user-service`. Create the catalog database once:

```bash
docker exec -it "$(docker compose -f docker-compose.local.yml ps -q postgres)" \
  psql -U postgres -c 'CREATE DATABASE catalog_service;'
```

Ignore the error if `catalog_service` already exists.

Stop Cloud SQL Auth Proxy if this instance should own the API connection, or leave the proxy on 5432 and use 5433 only for local mode.

## 2. Server env

```bash
cd server
cp .env.example .env   # if you do not already have one
```

Point at Docker Postgres:

```bash
DB_HOST=127.0.0.1
DB_PORT=5433
DB_NAME=catalog_service
DB_USER=postgres
DB_PASSWORD=postgres
USER_SERVICE_DB_NAME=user-service
```

Also set `SESSION_JWT_SECRET`, `GOOGLE_CLIENT_ID`, `CORS_ORIGINS=http://localhost:5173`, and `OPENROUTER_API_KEY`.

`GCS_BUCKET` may stay in `.env`. The overlay blanks it at process start so a real GCS client is not constructed.

### Overlay-only variables

Settings ignores unknown keys. Export these in the same shell as uvicorn (or `export` them from a file you `source`):

```bash
export LOCAL_STORAGE_DIR=../local-data/objects   # default if unset
export LOCAL_USER_EMAIL=you@example.com          # optional; otherwise first user row
```

| Variable | Default | Purpose |
|---|---|---|
| `LOCAL_STORAGE_DIR` | `../local-data/objects` (relative to `server/`) | Generated images and uploads |
| `LOCAL_USER_EMAIL` | first user in `user-service` | Auto-login target |

If `LOCAL_USER_EMAIL` is set and that email is missing, session auth returns 401.

## 3. Start the API

From `server/`, venv active:

```bash
cd server
source .venv/bin/activate
uvicorn local.app:app --reload --host 0.0.0.0 --port 8000
```

- Health: http://localhost:8000/api/health → `{"status":"ok"}`
- OpenAPI: http://localhost:8000/docs

Do **not** use `uvicorn main:app` for this loop. That path uses GCS and Cloud Workflows.

## 4. Start the client

```bash
cd client
cp .env.example .env   # if needed
# Keep VITE_API_BASE_URL=/api  (Vite proxies /api → http://127.0.0.1:8000)
npm install
npm run dev
```

Open http://localhost:5173. Session restore should succeed without Google Sign-In. Pick a brand and create a job as in production.

Files land under `local-data/objects/` (repo root, gitignored). Browser PUT/GET uses `/api/local-storage/...`.

## 5. What “working” looks like

1. `/api/health` is 200.
2. The UI does not require Google login (or `getCurrentUser` returns a user immediately).
3. Creating a job returns 200 without Cloud Workflows.
4. Images appear under `local-data/objects/` and the job UI polls as in production.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `No module named 'local'` | CWD is not `server/`, or `server/local/` is missing |
| `Cloud Workflows is not configured` | You started `main:app` instead of `local.app:app` |
| `Missing session cookie` / 401 | No user rows, or `LOCAL_USER_EMAIL` does not match |
| DB connection refused | Compose not up, or `DB_PORT` is still 5432 |
| Database does not exist | Create `catalog_service`; `USER_SERVICE_DB_NAME` must be `user-service` |
| Generation fails | `OPENROUTER_API_KEY` unset or invalid — local mode does not mock the LLM |
| Still hitting GCS | Overlay did not boot; uvicorn target must be `local.app:app` |

## Switch back to GCP from the laptop

```bash
cd server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Use ADC, Cloud SQL proxy on 5432, and a real `GCS_BUCKET`.
