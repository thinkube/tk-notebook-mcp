# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""Records of background executions, kept in memory and mirrored to disk.

A record survives a restart of the Jupyter server because it is written under
the notebooks folder; a caller that polls after a restart still gets the last
state written, marked as no longer running.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RECORDS_FOLDER = ".tk-notebook-mcp/executions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExecutionStore:
    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}
        self._dir: Optional[Path] = None

    def _folder(self, ctx: Any) -> Path:
        if self._dir is None:
            base = Path(ctx.root_dir)
            if ctx.preferred_dir:
                base = base / ctx.preferred_dir
            self._dir = base / RECORDS_FOLDER
        return self._dir

    def create(self, ctx: Any, kind: str, **fields: Any) -> str:
        execution_id = str(uuid.uuid4())
        self._records[execution_id] = {
            "execution_id": execution_id,
            "kind": kind,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            **fields,
        }
        self._write(ctx, execution_id)
        return execution_id

    def update(self, ctx: Any, execution_id: str, **fields: Any) -> None:
        record = self._records[execution_id]
        record.update(fields)
        if record["status"] != "running" and record.get("finished_at") is None:
            record["finished_at"] = _now()
        self._write(ctx, execution_id)

    def get(self, ctx: Any, execution_id: str) -> Optional[Dict[str, Any]]:
        record = self._records.get(execution_id)
        if record is not None:
            return record
        path = self._folder(ctx) / f"{execution_id}.json"
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text())
        except Exception as e:
            logger.error("could not read execution record %s: %s", execution_id, e)
            return None
        if record.get("status") == "running":
            # The server that ran it is gone; nothing will finish it.
            record["status"] = "lost"
            record["error"] = "the notebook server restarted while this was running"
        return record

    def _write(self, ctx: Any, execution_id: str) -> None:
        try:
            folder = self._folder(ctx)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{execution_id}.json").write_text(json.dumps(self._records[execution_id], default=str))
        except Exception as e:
            logger.error("could not write execution record %s: %s", execution_id, e)


store = ExecutionStore()
