#!/usr/bin/env bash
set -euo pipefail

# Fetch the single Catalog Service secret from Secret Manager and write dotenv files.
#
# Secret name (default): catalog-service
# Expected payload shape:
#   {
#     "client": { "VITE_API_BASE_URL": "/api", ... },
#     "server": {
#       "DB_HOST": "...",
#       "SERVICE_CLIENTS": { "catalog-workflows": "<token>", ... },
#       ...
#     }
#   }
#
# SERVICE_CLIENTS (nested map in the secret) is flattened here to
# SERVICE_CLIENT_<ID> env keys so local .env and the running process stay flat
# and easy to edit for testing. Humans edit the nested map; scripts own the
# SERVICE_CLIENT_ naming convention.
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


def flatten_service_clients(server: dict) -> dict:
    """Expand nested SERVICE_CLIENTS into SERVICE_CLIENT_<ID> env keys."""
    out = dict(server)
    clients = out.pop("SERVICE_CLIENTS", None)
    region = out.get("REGION")
    if not isinstance(region, str) or not region.strip():
        raise SystemExit("server.REGION is required in the catalog-service secret")
    out["REGION"] = region.strip()
    if clients is None:
        return out
    if not isinstance(clients, dict):
        raise SystemExit(
            'server.SERVICE_CLIENTS must be a JSON object of {"client-id": "token", ...}'
        )
    for client_id, token in clients.items():
        if not isinstance(client_id, str) or not client_id.strip():
            raise SystemExit("SERVICE_CLIENTS keys must be non-empty client-id strings")
        env_key = "SERVICE_CLIENT_" + client_id.strip().upper().replace("-", "_")
        if env_key in out:
            raise SystemExit(
                f"Conflict: both SERVICE_CLIENTS[{client_id!r}] and {env_key} are set"
            )
        out[env_key] = token
    return out


def section_to_dotenv(data: dict, dest: Path) -> None:
    if not isinstance(data, dict):
        raise SystemExit(f"{dest}: section must be a JSON object of env key/value pairs")
    lines = []
    for key, value in data.items():
        if value is None:
            text = ""
        elif isinstance(value, (dict, list)):
            raise SystemExit(
                f"{dest}: unexpected nested value for {key!r}; "
                "only SERVICE_CLIENTS may be an object (it is flattened before write)"
            )
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
section_to_dotenv(flatten_service_clients(payload["server"]), root / "server/.env")
PY

# Keep JSON out of docker build contexts
rm -f .secrets/catalog-service.json
