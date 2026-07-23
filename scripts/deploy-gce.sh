#!/usr/bin/env bash
set -euo pipefail

# Deploy docker-compose stack to a GCE VM.
# Flow: IAP SSH → Cloud Build access token → docker login on VM → compose pull/up.
# (Registry auth uses the Cloud Build SA token, not the VM service account.)
#
# Required env:
#   CLIENT_IMAGE, SERVER_IMAGE, VM_NAME, VM_ZONE, REGION
# Optional:
#   SERVER_ENV_FILE (default: server/.env)
#   PROJECT_ID (defaults to gcloud config)

: "${CLIENT_IMAGE:?CLIENT_IMAGE is required}"
: "${SERVER_IMAGE:?SERVER_IMAGE is required}"
: "${VM_NAME:?VM_NAME is required}"
: "${VM_ZONE:?VM_ZONE is required}"
: "${REGION:?REGION is required}"

SERVER_ENV_FILE="${SERVER_ENV_FILE:-server/.env}"
REMOTE_DIR=/opt/catalog-service
REGISTRY="${REGION}-docker.pkg.dev"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project)}"

if [[ ! -f "${SERVER_ENV_FILE}" ]]; then
  echo "Missing ${SERVER_ENV_FILE}. Run scripts/fetch-secrets.sh first." >&2
  exit 1
fi

echo "Deploying to ${VM_NAME} (${VM_ZONE})"

# Ensure remote dir exists and is writable by the SSH user
gcloud compute ssh "${VM_NAME}" \
  --project="${PROJECT_ID}" \
  --zone="${VM_ZONE}" \
  --tunnel-through-iap \
  --quiet \
  --ssh-flag=-oServerAliveInterval=30 \
  --ssh-flag=-oServerAliveCountMax=10 \
  --ssh-flag=-oLogLevel=ERROR \
  --command="sudo mkdir -p ${REMOTE_DIR}/server && sudo chown -R \$(whoami):\$(whoami) ${REMOTE_DIR}"

gcloud compute scp docker-compose.yml "${VM_NAME}:${REMOTE_DIR}/docker-compose.yml" \
  --project="${PROJECT_ID}" \
  --zone="${VM_ZONE}" \
  --tunnel-through-iap \
  --quiet

gcloud compute scp "${SERVER_ENV_FILE}" "${VM_NAME}:${REMOTE_DIR}/server/.env" \
  --project="${PROJECT_ID}" \
  --zone="${VM_ZONE}" \
  --tunnel-through-iap \
  --quiet

# Short-lived Cloud Build token for docker login on the VM
TOKEN="$(gcloud auth print-access-token)"
QTOKEN="$(printf '%q' "${TOKEN}")"
QREGISTRY="$(printf '%q' "${REGISTRY}")"
QCLIENT_IMAGE="$(printf '%q' "${CLIENT_IMAGE}")"
QSERVER_IMAGE="$(printf '%q' "${SERVER_IMAGE}")"
QREMOTE_DIR="$(printf '%q' "${REMOTE_DIR}")"

REMOTE=$(cat <<'EOS'
set -euo pipefail
cd __QREMOTE_DIR__

if ! command -v docker >/dev/null 2>&1; then
  echo "[deploy] Docker not found; installing..."
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[deploy] Docker Compose plugin missing; installing..."
  apt-get update -qq
  apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose-v2 || true
fi

echo __QTOKEN__ | docker login -u oauth2accesstoken --password-stdin https://__QREGISTRY__ 2>/dev/null
echo "[deploy] pulling images..."
export CLIENT_IMAGE=__QCLIENT_IMAGE__
export SERVER_IMAGE=__QSERVER_IMAGE__
docker compose pull
echo "[deploy] starting stack..."
docker compose up -d --no-build --remove-orphans
docker image prune -f
docker compose ps
EOS
)

REMOTE="${REMOTE//__QTOKEN__/${QTOKEN}}"
REMOTE="${REMOTE//__QREGISTRY__/${QREGISTRY}}"
REMOTE="${REMOTE//__QCLIENT_IMAGE__/${QCLIENT_IMAGE}}"
REMOTE="${REMOTE//__QSERVER_IMAGE__/${QSERVER_IMAGE}}"
REMOTE="${REMOTE//__QREMOTE_DIR__/${QREMOTE_DIR}}"

gcloud compute ssh "${VM_NAME}" \
  --project="${PROJECT_ID}" \
  --zone="${VM_ZONE}" \
  --tunnel-through-iap \
  --quiet \
  --ssh-flag=-oServerAliveInterval=30 \
  --ssh-flag=-oServerAliveCountMax=10 \
  --ssh-flag=-oLogLevel=ERROR \
  --command="sudo bash -c $(printf '%q' "${REMOTE}")"

echo "VM deploy finished"
