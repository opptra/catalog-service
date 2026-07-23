# Catalog Service

React client + FastAPI server, deployed as two Docker images on one GCE VM (Mumbai / `asia-south1`).

## Local Docker

```bash
# Create server env (required by compose)
cp server/.env.example server/.env
# fill DATABASE_URL and API_KEY

docker compose up --build
```

- Client: http://localhost (port 80)
- API: http://localhost:8000
- Browser API via nginx proxy: http://localhost/api/...

## What you need to run the Cloud Build pipeline

1. **GCP project** + `gcloud` auth
2. **APIs** — Cloud Build, Artifact Registry, Compute, Secret Manager
3. **Secret Manager secrets** (JSON objects), already in your project:
   - `catalog-service-client` — e.g. `{"VITE_API_BASE_URL":"/api"}`
   - `catalog-service-server` — e.g. `{"DATABASE_URL":"...","API_KEY":"..."}`
4. **Artifact Registry** repo `catalog-service` in `asia-south1`
5. **GCE VM** in `asia-south1-c` with Docker Compose + firewall TCP `80`
6. **IAM** for Cloud Build SA (push images, read secrets, SSH to VM) and VM SA (pull images)
7. Trigger on `main`, or run `gcloud builds submit --config=cloudbuild.yaml`

Pipeline flow:

1. Fetch both secrets → write `client/.env` + `server/.env` (not committed)
2. Build/push client + server images (client bakes Vite env; server stays secret-free)
3. SCP compose + `server/.env` to the VM and `docker compose up`

## GCP setup (one-time)

### 1. Enable APIs

```bash
gcloud services enable \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  secretmanager.googleapis.com
```

### 2. Secret Manager

Secrets should look like:

```json
{
  "DATABASE_URL": "postgresql://...",
  "API_KEY": "..."
}
```

Client secret may include Vite keys (`VITE_API_BASE_URL`, etc.).

### 3. Artifact Registry (Mumbai)

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION=asia-south1
export AR_REPO=catalog-service

gcloud artifacts repositories create "${AR_REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Catalog service images"
```

### 4. GCE VM (Mumbai)

```bash
export VM_NAME=catalog-service-1
export VM_ZONE=asia-south1-c
```

Install Docker + Compose on the VM (auto-installs if missing). Deploy uses
SSH via IAP, a short-lived Cloud Build access token for `docker login` on the VM,
then pull/run — so the VM SA does not need Artifact Registry Reader for image pulls.

Firewall: allow TCP `80`. Open `8000` only if you need direct API access.

Grant the VM service account `roles/artifactregistry.reader`.

### 5. Cloud Build service account

Grant `PROJECT_NUMBER@cloudbuild.gserviceaccount.com`:

- `roles/secretmanager.secretAccessor`
- `roles/artifactregistry.writer`
- `roles/compute.instanceAdmin.v1`
- `roles/iam.serviceAccountUser`
- SSH / OS Login access for `gcloud compute ssh` / `scp`

The SSH user on the VM also needs passwordless `sudo` for `mkdir`/`chown` under `/opt` (common on GCE images).

### 6. Trigger on `main`

```bash
gcloud builds triggers create github \
  --name=catalog-service-main \
  --repo-name=catalog-service \
  --repo-owner=opptra \
  --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml \
  --substitutions=_REGION=asia-south1,_AR_REPO=catalog-service,_VM_NAME=catalog-service-1,_VM_ZONE=asia-south1-c
```

### 7. Manual build

```bash
gcloud builds submit --config=cloudbuild.yaml
```

## Images

| Image | Port on VM |
|-------|------------|
| `catalog-client` (nginx) | 80 |
| `catalog-server` (uvicorn) | 8000 |
