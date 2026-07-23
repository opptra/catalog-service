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

# Install Docker if missing, then pull/run compose with sudo (group membership
# often isn't active in the same SSH session after usermod).
gcloud compute ssh "${VM_NAME}" --zone="${VM_ZONE}" --command="
  set -euo pipefail

  if ! command -v docker >/dev/null 2>&1; then
    echo 'Docker not found; installing...'
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker \"\$(whoami)\" || true
  fi

  # Ensure compose plugin is available (get.docker.com usually includes it)
  if ! sudo docker compose version >/dev/null 2>&1; then
    echo 'Docker Compose plugin missing; installing...'
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-compose-plugin || sudo apt-get install -y -qq docker-compose-v2 || true
  fi

  cd ${REMOTE_DIR}
  gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

  # sudo docker uses root's config; copy credential helper config for Artifact Registry pulls
  sudo mkdir -p /root/.docker
  if [[ -f \"\${HOME}/.docker/config.json\" ]]; then
    sudo cp \"\${HOME}/.docker/config.json\" /root/.docker/config.json
  fi

  export CLIENT_IMAGE='${CLIENT_IMAGE}'
  export SERVER_IMAGE='${SERVER_IMAGE}'
  sudo -E docker compose pull
  sudo -E docker compose up -d --no-build --remove-orphans
  sudo docker image prune -f
"
