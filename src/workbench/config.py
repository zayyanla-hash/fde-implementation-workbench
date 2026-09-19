"""Runtime configuration — env vars with sane offline defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    scenario: str = "vendor_payments_v1"
    rules_path: str | None = None
    audit_dir: str = "./var/audit"
    port: int = 8765
    flaky_vendor_fails: int = 1
    max_tool_attempts: int = 3

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            scenario=os.getenv("WORKBENCH_SCENARIO", "vendor_payments_v1"),
            rules_path=os.getenv("WORKBENCH_RULES") or None,
            audit_dir=os.getenv("WORKBENCH_AUDIT_DIR", "./var/audit"),
            port=int(os.getenv("WORKBENCH_PORT", "8765")),
            flaky_vendor_fails=int(os.getenv("WORKBENCH_FLAKY_VENDOR_FAILS", "1")),
            max_tool_attempts=int(os.getenv("WORKBENCH_MAX_ATTEMPTS", "3")),
        )

    def audit_path_for(self, run_id: str) -> Path:
        return Path(self.audit_dir) / f"{run_id}.jsonl"
