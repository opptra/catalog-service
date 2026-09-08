"""Put ``ops/`` and ``server/`` on ``sys.path`` for this offline utility.

Keeps marketplace listing tooling outside ``server/`` while still reusing
runtime parsers/DTOs under ``server/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPS = _REPO_ROOT / "ops"
_SERVER = _REPO_ROOT / "server"

for _path in (_OPS, _SERVER):
    _as_str = str(_path)
    if _as_str not in sys.path:
        sys.path.insert(0, _as_str)
