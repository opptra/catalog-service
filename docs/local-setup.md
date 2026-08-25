# Local setup

Local development talks to the same GCP resources as production: Cloud SQL (via Auth Proxy), GCS, Cloud Workflows, and Google Sign-In. You still need an [OpenRouter](https://openrouter.ai/keys) key for generation and verification.

`.env` files are not in git. Copy the examples and fill real values (Secret Manager `catalog-service` is the source of truth for shared config).

---

## What you need

- Git
- Node.js (current LTS is fine)
- Python **3.12**
- `gcloud` CLI
- [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/connect-auth-proxy)
- An [OpenRouter](https://openrouter.ai/keys) API key
- Access to the GCP project (`opptra-commerce-studio`) and the `catalog-service` secret

---

## 1. Clone the repo

```bash
git clone <repo-url>
cd catalog-service
```

---

## 2. Google Cloud credentials

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project opptra-commerce-studio
```

`google.auth.default()` uses ADC locally. Set `GOOGLE_CLOUD_PROJECT` in `server/.env` so Workflows can resolve the project (on GCE, metadata supplies it).

---

## 3. Cloud SQL Auth Proxy

Keep the proxy on **5432** while the API is running:

```bash
cloud-sql-proxy opptra-commerce-studio:asia-south1:catalog-service-pg
```

Point `DB_*` at `127.0.0.1:5432`. Do not mix this with `docker-compose.local.yml` Postgres on 5433 in the same `.env`.

---

## 4. Server env

```bash
cd server
cp .env.example .env
```

Fill `server/.env` from Secret Manager / a teammate. At least:

```
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=...
USER_SERVICE_DB_NAME=user-service

SESSION_JWT_SECRET=...
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
CORS_ORIGINS=http://localhost:5173

OPENROUTER_API_KEY=...
OPENROUTER_TEXT_MODEL=openai/gpt-5.4
OPENROUTER_IMAGE_MODEL=google/gemini-3-pro-image
OPENROUTER_VERIFY_MODEL=openai/gpt-4o

GOOGLE_CLOUD_PROJECT=opptra-commerce-studio
GCS_BUCKET=catalog-service
GCS_SIGNER_SERVICE_ACCOUNT_EMAIL=...@....iam.gserviceaccount.com
REGION=asia-south1
SERVICE_CLIENT_CATALOG_WORKFLOWS=...
```

Use the real Google Web client ID (same value as `VITE_GOOGLE_CLIENT_ID`). Local user ADC / the VM SA need `roles/iam.serviceAccountTokenCreator` on the signer SA for V4 signed URLs.

Flatfile browser PUT/DELETE to GCS needs bucket CORS allowing `http://localhost:5173` (already configured on `catalog-service`).

---

## 5. Client env

```bash
cd client
cp .env.example .env
```

`client/.env`:

```
VITE_API_BASE_URL=/api
VITE_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
```

Vite proxies `/api` to `http://127.0.0.1:8000`. Use the same Google Web client ID as the server.

---

## 6. Install and run the server

Use Python 3.12. From `server/`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Check http://localhost:8000/health

---

## 7. Install and run the client

From `client/` (second terminal):

```bash
npm install
npm run dev
```

Open **http://localhost:5173** and sign in with Google. Select a brand you have access to.

---

## What success looks like

- UI at http://localhost:5173 (Google login, then brand picker)
- API at http://localhost:8000 (`/api/health`, `/docs`)
- Creating a job starts **Cloud Workflows** (not an in-process pipeline)
- Uploads and generated images go to **GCS** (`gs://catalog-service/...`)

---

## If something is wrong

| Problem | What to check |
|---------|----------------|
| Login screen / 401 | Real `VITE_GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_ID`; authorized JS origin `http://localhost:5173` |
| Server will not boot | Python 3.12, `SESSION_JWT_SECRET`, Auth Proxy on **5432** |
| 503 Cloud Workflows | `gcloud auth application-default login`, `GOOGLE_CLOUD_PROJECT`, `REGION` |
| 503 GCS | `GCS_BUCKET`, ADC; Token Creator on `GCS_SIGNER_SERVICE_ACCOUNT_EMAIL` |
| Empty brands | Sign in as a user with grants in `user-service` |
| Generation never starts | Workflows execution in GCP; `SERVICE_CLIENT_CATALOG_WORKFLOWS` matches the cloud secret |
| Port already in use | 5173 = client, 8000 = API, 5432 = Auth Proxy |
