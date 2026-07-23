#!/usr/bin/env bash
set -euo pipefail

# Fetch JSON secrets from Secret Manager and write dotenv files.
# Secrets:
#   catalog-service-client → client/.env.production  (Vite build-time)
#   catalog-service-server → server/.env.production  (runtime on VM)
#
# Expected secret payload shape:
#   {"DATABASE_URL":"...","API_KEY":"...","VITE_API_BASE_URL":"/api"}

CLIENT_SECRET_NAME="${CLIENT_SECRET_NAME:-catalog-service-client}"
SERVER_SECRET_NAME="${SERVER_SECRET_NAME:-catalog-service-server}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

mkdir -p .secrets

echo "Fetching secret: ${CLIENT_SECRET_NAME}"
gcloud secrets versions access latest --secret="${CLIENT_SECRET_NAME}" > .secrets/client.json

echo "Fetching secret: ${SERVER_SECRET_NAME}"
gcloud secrets versions access latest --secret="${SERVER_SECRET_NAME}" > .secrets/server.json

python3 - <<'PY'
import json
from pathlib import Path

def json_to_dotenv(src: Path, dest: Path) -> None:
    data = json.loads(src.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"{src} must be a JSON object of env key/value pairs")
    lines = []
    for key, value in data.items():
        if value is None:
            value = ""
        # Escape newlines; keep values on one line for dotenv
        text = str(value).replace("\n", "\\n")
        lines.append(f"{key}={text}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    print(f"Wrote {dest} ({len(lines)} keys)")

root = Path(".")
json_to_dotenv(root / ".secrets/client.json", root / "client/.env.production")
json_to_dotenv(root / ".secrets/server.json", root / "server/.env.production")
PY

# Keep JSON out of docker build contexts
rm -f .secrets/client.json .secrets/server.json
