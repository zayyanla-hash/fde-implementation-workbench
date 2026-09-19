"""Append-only audit trail: in-memory + JSONL file sink."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AuditEvent


class AuditLog:
    def __init__(self, run_id: str, jsonl_path: Path | None = None):
        self.run_id = run_id
        self.events: list[AuditEvent] = []
        self.jsonl_path = jsonl_path
        if jsonl_path is not None:
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, stage: str, event: str, **detail: Any) -> AuditEvent:
        evt = AuditEvent(seq=len(self.events) + 1, run_id=self.run_id, stage=stage, event=event, detail=detail)
        self.events.append(evt)
        if self.jsonl_path is not None:
            with self.jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**evt.to_dict(), "ts": _now()}) + "\n")
        return evt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
