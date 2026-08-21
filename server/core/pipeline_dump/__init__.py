"""Slot-planner input/output JSON for each image-generation execute.

Each execute gets its own file (never overwrites a prior run):

  tmp/generation-runs/{parent_job_external_id}/{stamp}__{sku_job_id}.json

``latest.json`` in that folder is rewritten to point at the current run's path.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_RUNS_ROOT = Path(__file__).resolve().parents[3] / "tmp" / "generation-runs"

_lock = threading.Lock()
_active: _RunState | None = None


@dataclass
class _RunState:
    run_key: str
    parent_job_external_id: UUID
    sku_generation_job_external_id: UUID | None
    sku: str
    started_at: datetime
    path: Path
    latest_pointer: Path
    slots: list[dict[str, Any]] = field(default_factory=list)

    def add_slot(
        self,
        *,
        attribute: str,
        slot: int,
        input: str,
        output: dict[str, Any],
    ) -> None:
        with _lock:
            self.slots.append(
                {
                    "attribute": attribute,
                    "slot": slot,
                    "input": input,
                    "output": output,
                }
            )
            self._flush_unlocked()

    def _payload(self) -> dict[str, Any]:
        return {
            "parent_job_external_id": str(self.parent_job_external_id),
            "sku_generation_job_external_id": (
                str(self.sku_generation_job_external_id)
                if self.sku_generation_job_external_id is not None
                else None
            ),
            "sku": self.sku,
            "started_at": self.started_at.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "slots": self.slots,
        }

    def _write_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _flush_unlocked(self) -> None:
        payload = self._payload()
        self._write_atomic(self.path, payload)
        self._write_atomic(
            self.latest_pointer,
            {
                "parent_job_external_id": str(self.parent_job_external_id),
                "current_run_path": str(self.path),
                "updated_at": payload["updated_at"],
                "slot_count": len(self.slots),
            },
        )


def _run_path(
    parent_job_external_id: UUID,
    *,
    sku_generation_job_external_id: UUID | None,
    started_at: datetime,
) -> tuple[str, Path, Path]:
    job_dir = _RUNS_ROOT / str(parent_job_external_id)
    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    sku_part = (
        str(sku_generation_job_external_id)
        if sku_generation_job_external_id is not None
        else "no-sku-job"
    )
    run_key = f"{stamp}__{sku_part}"
    path = job_dir / f"{run_key}.json"
    latest = job_dir / "latest.json"
    return run_key, path, latest


@contextmanager
def run_scope(
    parent_job_external_id: UUID,
    *,
    sku: str,
    sku_generation_job_external_id: UUID | None = None,
) -> Iterator[Path]:
    """Start a new dump file for this execute; never overwrites prior runs."""
    global _active
    started_at = datetime.now(UTC)
    run_key, path, latest_pointer = _run_path(
        parent_job_external_id,
        sku_generation_job_external_id=sku_generation_job_external_id,
        started_at=started_at,
    )
    state = _RunState(
        run_key=run_key,
        parent_job_external_id=parent_job_external_id,
        sku_generation_job_external_id=sku_generation_job_external_id,
        sku=sku,
        started_at=started_at,
        path=path,
        latest_pointer=latest_pointer,
    )
    with _lock:
        previous = _active
        _active = state
        try:
            state._flush_unlocked()
        except Exception:
            logger.exception("Failed to create slot planner dump for %s", run_key)
    try:
        yield path
    finally:
        with _lock:
            if _active is state:
                try:
                    state._flush_unlocked()
                    logger.info(
                        "Slot planner dump (%s slots) written to %s",
                        len(state.slots),
                        path,
                    )
                except Exception:
                    logger.exception("Failed to flush slot planner dump for %s", run_key)
                _active = previous
            else:
                _active = previous


def record_slot(
    *,
    attribute: str,
    slot: int,
    input: str,
    output: dict[str, Any],
) -> None:
    """Append one slot's planner prompt and tool JSON."""
    state = _active
    if state is None:
        return
    try:
        state.add_slot(attribute=attribute, slot=slot, input=input, output=output)
    except Exception:
        logger.exception("Failed to write slot planner dump for %s slot %s", attribute, slot)
