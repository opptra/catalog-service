#!/usr/bin/env bash
# Print one KEY from a dotenv file (supports bare and JSON-quoted values).
# Usage: read-dotenv-value.sh <file> <KEY>
set -euo pipefail

FILE="${1:?dotenv file required}"
KEY="${2:?env key required}"

python3 - "$FILE" "$KEY" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.is_file():
    raise SystemExit(f"{path}: file not found")

prefix = f"{key}="
for line in path.read_text().splitlines():
    if not line.startswith(prefix):
        continue
    raw = line[len(prefix) :]
    if raw[:1] in "\"'":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw.strip("\"'")
    else:
        value = raw
    value = str(value).strip()
    if not value:
        raise SystemExit(f"{path}: {key} is empty")
    print(value)
    break
else:
    raise SystemExit(f"{path}: {key} is required")
PY
