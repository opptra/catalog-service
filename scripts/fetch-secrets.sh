#!/usr/bin/env bash
set -euo pipefail

# Fetch the single Catalog Service secret from Secret Manager and write dotenv files.
#
# Secret name (default): catalog-service
# Expected payload shape:
#   {
#     "client": { "VITE_API_BASE_URL": "/api", ... },
#     "server": { "DB_HOST": "...", "API_KEY": "...", ... }
#   }
#
# Writes:
#   client/.env  ← .client  (Vite build-time)
#   server/.env  ← .server  (local / Cloud Build only; prod VM uses instance-startup.sh)

SECRET_NAME="${SECRET_NAME:-catalog-service}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

mkdir -p .secrets

echo "Fetching secret: ${SECRET_NAME}"
gcloud secrets versions access latest --secret="${SECRET_NAME}" > .secrets/catalog-service.json

python3 - <<'PY'
import json
from pathlib import Path


def section_to_dotenv(data: dict, dest: Path) -> None:
    if not isinstance(data, dict):
        raise SystemExit(f"{dest}: section must be a JSON object of env key/value pairs")
    lines = []
    for key, value in data.items():
        if value is None:
            text = ""
        elif isinstance(value, (dict, list)):
            # Nested JSON values must stay valid JSON in dotenv (no longer used for
            # service clients, which are flat SERVICE_CLIENT_<ID> scalars, but kept
            # as a defensive fallback for any other nested config).
            text = json.dumps(value, separators=(",", ":"))
        else:
            text = str(value).replace("\n", "\\n")
        lines.append(f"{key}={text}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    print(f"Wrote {dest} ({len(lines)} keys)")


root = Path(".")
payload = json.loads((root / ".secrets/catalog-service.json").read_text())
if not isinstance(payload, dict):
    raise SystemExit("catalog-service secret must be a JSON object")

missing = [key for key in ("client", "server") if key not in payload]
if missing:
    raise SystemExit(f"catalog-service secret missing top-level key(s): {missing}")

section_to_dotenv(payload["client"], root / "client/.env")
section_to_dotenv(payload["server"], root / "server/.env")
PY

# Keep JSON out of docker build contexts
rm -f .secrets/catalog-service.json
