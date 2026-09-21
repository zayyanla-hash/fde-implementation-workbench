"""Small Vercel adapter for the deterministic, offline FDE demo.

Vercel Functions are stateless.  The portfolio surface therefore recreates the
synthetic fixture pipeline for every request rather than pretending in-memory
runs are durable.  The browser owns the short-lived display session; the
pipeline and approval invariant remain the repository's real implementation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workbench.approval import ApprovalGate
from workbench.config import Settings
from workbench.scenarios import fixture_dir_for
from workbench.workflow import _summarize, run_fixture_scenario


def read_json(request) -> dict:
    length = int(request.headers.get("Content-Length", "0") or 0)
    if not length:
        return {}
    try:
        return json.loads(request.rfile.read(length).decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def send_json(request, status: int, payload: object) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    request.send_response(status)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Cache-Control", "no-store")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


def run_demo(scenario: str = "vendor_payments_v1"):
    settings = Settings.from_env()
    fixture = fixture_dir_for(scenario)
    flaky = {"V-HOOLI": settings.flaky_vendor_fails} if settings.flaky_vendor_fails else {}
    return run_fixture_scenario(
        fixture,
        rules_path=Path(settings.rules_path) if settings.rules_path else None,
        flaky_vendor_fails=flaky,
        max_tool_attempts=settings.max_tool_attempts,
    )


def resolve_demo(invoice_id: str, approve: bool, approver: str, reason: str):
    result, engine = run_demo()
    decision = ApprovalGate(result.decisions).resolve(
        invoice_id, approve=approve, approver=approver, reason=reason
    )
    engine.record_resolution(decision)
    result.audit = engine.audit.events
    result.summary = _summarize(result.decisions)
    return result
