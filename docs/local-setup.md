# Local setup

This is the laptop path: Postgres on your machine, files on disk, no Cloud Workflows, no GCS, no Google login. You still need an **OpenRouter** key because image generation and the “Verified” check call that API.

Dumps and `.env` files are not in git. Someone with Cloud SQL access has to give you data (or you dump it yourself).

---

## What you need

- Git
- Docker
- Node.js (current LTS is fine)
- Python **3.12**
- `psql` / `pg_restore` (Postgres client)
- An [OpenRouter](https://openrouter.ai/keys) API key

Optional: `gcloud` + `gsutil` if you want to copy existing product photos from GCS.

---

## 1. Clone the repo

```bash
git clone <repo-url>
cd catalog-service
```

---

## 2. Get database dumps

These files are gitignored (`*.dump`). Put them in the **repo root**.
Run Cloud SQL Auth Proxy using this command after gcloud login
gcloud login 
```bash
gcloud auth application-default login
```
```bash
cloud-sql-proxy opptra-commerce-studio:asia-south1:catalog-service-pg
```
If Cloud SQL Auth Proxy is listening on `5432`:

```bash
pg_dump -h 127.0.0.1 -p 5432 -U postgres -d postgres -Fc -f catalog.dump
pg_dump -h 127.0.0.1 -p 5432 -U postgres -d user-service -Fc -f user.dump
```

You need both:

| File | Database |
|------|----------|
| `catalog.dump` | catalog (`postgres`) |
| `user.dump` | users (`user-service`) |

Stop the Auth Proxy before the next step so port 5432 is not mixed up with local Postgres.

---

## 3. Start local Postgres

This runs Postgres **16** on port **5433** (so it does not fight a proxy on 5432). User `postgres`, password `postgres`.

```bash
docker compose -f docker-compose.local.yml up -d
```

Wait until it is healthy:

```bash
docker compose -f docker-compose.local.yml ps
```

---

## 4. Restore the dumps

```bash
pg_restore -h 127.0.0.1 -p 5433 -U postgres -d postgres --no-owner --no-acl catalog.dump
pg_restore -h 127.0.0.1 -p 5433 -U postgres -d user-service --no-owner --no-acl user.dump
```

Password: `postgres`.

You may see errors about `transaction_timeout` (dump from a newer Postgres) or `cloudsqlsuperuser` GRANTs. Ignore those if the restore otherwise finishes.

If `user-service` looks empty, restore `user.dump` again.

---

## 5. Add the verification column if it is missing

Image verification stores a JSON blob on `sku_marketplace_attribute_value`. Older dumps may not have the column. Run this yourself on the **local** catalog DB (`127.0.0.1:5433`, database `postgres`):

```sql
ALTER TABLE sku_marketplace_attribute_value
  ADD COLUMN IF NOT EXISTS verification jsonb NULL;
```

---

## 6. Server env

```bash
cd server
cp .env.example .env
```

Edit `server/.env`. For this laptop path, set at least:

```
DEV_MODE=true
DB_HOST=127.0.0.1
DB_PORT=5433
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=postgres
USER_SERVICE_DB_NAME=user-service

SESSION_JWT_SECRET=replace-with-a-long-random-secret
GOOGLE_CLIENT_ID=local-dev.apps.googleusercontent.com
REGION=asia-south1
CORS_ORIGINS=http://localhost:5173

OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TEXT_MODEL=openai/gpt-5.4
OPENROUTER_IMAGE_MODEL=google/gemini-3-pro-image
OPENROUTER_VERIFY_MODEL=openai/gpt-4o
```

Generate a real JWT secret, for example:

```bash
openssl rand -hex 32
```

Optional:

- `DEV_USER_EMAIL` — auto-login as that user. If unset, the first user in `user-service` is used.
- `LOCAL_STORAGE_DIR` — defaults to `../local-data/objects`.

`GOOGLE_CLIENT_ID` is still required by config. Login is skipped in DEV_MODE, so a placeholder is fine.

**Never** put `DEV_MODE=true` in Secret Manager or the production image.

---

## 7. Client env

```bash
cd client
cp .env.example .env
```

`client/.env`:

```
VITE_API_BASE_URL=/api
VITE_DEV_MODE=true
VITE_GOOGLE_CLIENT_ID=local-dev.apps.googleusercontent.com
```

Vite proxies `/api` to `http://127.0.0.1:8000`. **Never** set `VITE_DEV_MODE` in Secret Manager or the production client image.

---

## 8. Install and run the server

Use Python 3.12. From `server/`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Check http://localhost:8000/health

---

## 9. Install and run the client

From `client/` (second terminal):

```bash
npm install
npm run dev
```

Open **http://localhost:5173**

You should not see Google login. The first brand is selected for you.

---

## 10. Optional: copy product photos from GCS

You can skip this. New batches can upload a zip in the wizard.

To copy existing photos (needs ADC / `gsutil`):

```bash
gsutil -m rsync -r gs://catalog-service/products local-data/objects/products
```

---

## What success looks like

- UI at http://localhost:5173
- API at http://localhost:8000 (`/health`, `/docs`)
- Creating a job generates in-process (watch the uvicorn log: `DEV_MODE SKU execute…`)
- Images land under `local-data/objects/jobs/.../images/` (often with a sibling `*.debug.json`)
- Passed IMAGE / A+ tiles show a **Verified** corner badge; hover shows match % and reasoning

---

## If something is wrong

| Problem | What to check |
|---------|----------------|
| Login screen still appears | `VITE_DEV_MODE=true` in `client/.env`, restart `npm run dev` |
| Server will not boot | Python 3.12, `SESSION_JWT_SECRET` set, `DEV_MODE=true`, DB on **5433** |
| Empty brands / no user | Restore `user.dump` into `user-service`; optional `DEV_USER_EMAIL` |
| Generation never starts | `OPENROUTER_API_KEY`; uvicorn logs; job row in catalog DB |
| Verification badge never shows | Run the `ALTER TABLE` in step 5; generate a **new** image |
| Restore errors about owners / ACLs | Use `--no-owner --no-acl` |
| Port already in use | 5173 = client, 8000 = API, 5433 = local Postgres |

---

## Cloud-connected local (DEV_MODE off)

This is the older path: Cloud SQL via Auth Proxy on **5432**, Google login, GCS, Cloud Workflows.

1. Copy `.env.example` → `.env` on server and client. Leave `DEV_MODE` and `VITE_DEV_MODE` unset.
2. Point `DB_*` at the proxy (`DB_PORT=5432`). Use real `GOOGLE_CLIENT_ID` on both apps.
3. `gcloud auth application-default login`, set `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET`, `GCS_SIGNER_SERVICE_ACCOUNT_EMAIL`.
4. Start uvicorn and `npm run dev` the same way.

Do not mix this with the laptop Postgres on 5433 in the same `.env`.
