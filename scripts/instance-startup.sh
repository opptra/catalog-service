#!/usr/bin/env bash
set -euo pipefail

# GCE instance-template startup script (paste into template metadata, or
# reference this file). Flat layout under /opt/catalog-service — no client/
# or server/ source trees on the VM.
#
# VM SA needs:
#   - roles/artifactregistry.reader
#   - roles/secretmanager.secretAccessor (catalog-service)
#   - Access scopes: Allow full access to all Cloud APIs
# Optional: roles/logging.logWriter

REGION="${REGION:-asia-south1}"
AR_REPO="${AR_REPO:-catalog-service}"
SECRET_NAME="${SECRET_NAME:-catalog-service}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
APP_DIR=/opt/catalog-service

exec > >(tee -a /var/log/catalog-startup.log) 2>&1
echo "[catalog-startup] begin $(date -u +%Y-%m-%dT%H:%M:%SZ)"

PROJECT_ID="$(curl -sf -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/project/project-id)"
REGISTRY="${REGION}-docker.pkg.dev"
CLIENT_IMAGE="${REGISTRY}/${PROJECT_ID}/${AR_REPO}/catalog-client:${IMAGE_TAG}"
SERVER_IMAGE="${REGISTRY}/${PROJECT_ID}/${AR_REPO}/catalog-server:${IMAGE_TAG}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose-v2 || true
fi

TOKEN="$(curl -sf -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')"

echo "${TOKEN}" | docker login -u oauth2accesstoken --password-stdin "https://${REGISTRY}"

mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

cat > docker-compose.yml <<'EOF'
services:
  client:
    image: ${CLIENT_IMAGE}
    ports:
      - "80:80"
    depends_on:
      - server
    restart: unless-stopped
  server:
    image: ${SERVER_IMAGE}
    ports:
      - "8000:8000"
    env_file:
      - server.env
    restart: unless-stopped
EOF

# Compose auto-loads `.env` for ${VAR} interpolation in compose.yml.
# Keep secrets in server.env so characters like `$` in DB_PASSWORD are not
# treated as compose variables.
cat > .env <<EOF
CLIENT_IMAGE=${CLIENT_IMAGE}
SERVER_IMAGE=${SERVER_IMAGE}
EOF

curl -sf -H "Authorization: Bearer ${TOKEN}" \
  "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${SECRET_NAME}/versions/latest:access" \
  | python3 -c 'import sys,json,base64; from pathlib import Path
p=json.load(sys.stdin)
raw=base64.b64decode(p["payload"]["data"])
payload=json.loads(raw)
if not isinstance(payload, dict) or "server" not in payload:
  raise SystemExit("catalog-service secret must be a JSON object with a top-level \"server\" key")
data=payload["server"]
if not isinstance(data, dict):
  raise SystemExit("catalog-service secret \"server\" must be a JSON object of env key/value pairs")
lines=[]
for k,v in data.items():
  if v is None:
    t=""
  elif isinstance(v, (dict, list)):
    t=json.dumps(v, separators=(",", ":"))
  else:
    t=str(v).replace("\\", "\\\\").replace("\n", "\\n")
  # Quote values so special chars ($ # etc.) survive dotenv parsing.
  lines.append(f"{k}={json.dumps(t)}")
Path("server.env").write_text("\n".join(lines)+"\n")
print("Wrote server.env", len(lines), "keys")'

docker compose pull
docker compose up -d --no-build --remove-orphans
docker compose ps

echo "[catalog-startup] done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
