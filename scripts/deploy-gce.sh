#!/usr/bin/env bash
set -euo pipefail

# Deploy docker-compose stack to a GCE VM.
# Required env:
#   CLIENT_IMAGE, SERVER_IMAGE, VM_NAME, VM_ZONE, REGION
# Optional:
#   SERVER_ENV_FILE (default: server/.env)

: "${CLIENT_IMAGE:?CLIENT_IMAGE is required}"
: "${SERVER_IMAGE:?SERVER_IMAGE is required}"
: "${VM_NAME:?VM_NAME is required}"
: "${VM_ZONE:?VM_ZONE is required}"
: "${REGION:?REGION is required}"

SERVER_ENV_FILE="${SERVER_ENV_FILE:-server/.env}"
REMOTE_DIR=/opt/catalog-service

if [[ ! -f "${SERVER_ENV_FILE}" ]]; then
  echo "Missing ${SERVER_ENV_FILE}. Run scripts/fetch-secrets.sh first." >&2
  exit 1
fi

# /opt is root-owned; create and hand ownership to the SSH user
gcloud compute ssh "${VM_NAME}" --zone="${VM_ZONE}" --command="
  set -euo pipefail
  sudo mkdir -p ${REMOTE_DIR}/server
  sudo chown -R \$(whoami):\$(whoami) ${REMOTE_DIR}
"

gcloud compute scp docker-compose.yml "${VM_NAME}:${REMOTE_DIR}/docker-compose.yml" \
  --zone="${VM_ZONE}"

gcloud compute scp "${SERVER_ENV_FILE}" "${VM_NAME}:${REMOTE_DIR}/server/.env" \
  --zone="${VM_ZONE}"

gcloud compute ssh "${VM_NAME}" --zone="${VM_ZONE}" --command="
  set -euo pipefail
  cd ${REMOTE_DIR}
  gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
  export CLIENT_IMAGE='${CLIENT_IMAGE}'
  export SERVER_IMAGE='${SERVER_IMAGE}'
  docker compose pull
  docker compose up -d --no-build --remove-orphans
  docker image prune -f
"
