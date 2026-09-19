"""Local HTTP API (stdlib http.server only — no dependencies).

Endpoints:
  GET  /health
  GET  /scenarios
  POST /runs                 {"scenario": "..."} -> runs pipeline, returns summary+decisions
  GET  /runs/{id}            full run incl. audit
  POST /runs/{id}/approve    {"invoice_id": "...", "approve": true, "approver": "maria", "reason": "..."}
  GET  /runs/{id}/audit      audit events as JSON
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .scenarios import SCENARIOS, fixture_dir_for
from .workflow import run_fixture_scenario

RUNS: dict[str, object] = {}
ENGINES: dict[str, object] = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkbenchHTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode() or "{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True, "service": "fde-implementation-workbench"})
            return
        if path == "/scenarios":
            self._send(200, {"scenarios": [
                {"key": s.key, "title": s.title, "description": s.description}
                for s in SCENARIOS.values()
            ]})
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) == 2 and parts[0] == "runs":
            run_id = parts[1]
            if run_id not in RUNS:
                self._send(404, {"error": f"unknown run {run_id}"})
                return
            from .models import RunResult as RR
            result: RR = RUNS[run_id]  # type: ignore[assignment]
            self._send(200, result.to_dict())
            return
        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "audit":
            run_id = parts[1]
            if run_id not in RUNS:
                self._send(404, {"error": f"unknown run {run_id}"})
                return
            from .models import RunResult as RR
            result = RUNS[run_id]
            assert isinstance(result, RR)
            self._send(200, {"run_id": run_id, "audit": [a.to_dict() for a in result.audit]})
            return
        self._send(404, {"error": "not found", "hint": "GET /health, /scenarios, /runs/{id}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        settings = Settings.from_env()
        if path == "/runs":
            body = self._read_json()
            scenario = str(body.get("scenario") or settings.scenario)
            try:
                fixture = fixture_dir_for(scenario)
            except KeyError as exc:
                self._send(400, {"error": str(exc)})
                return
            flaky = {"V-HOOLI": settings.flaky_vendor_fails} if settings.flaky_vendor_fails else {}
            result, engine = run_fixture_scenario(
                fixture,
                rules_path=Path(settings.rules_path) if settings.rules_path else None,
                flaky_vendor_fails=flaky,
                max_tool_attempts=settings.max_tool_attempts,
            )
            RUNS[result.run_id] = result
            ENGINES[result.run_id] = engine
            self._send(201, result.to_dict())
            return
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "approve":
            run_id = parts[1]
            if run_id not in RUNS:
                self._send(404, {"error": f"unknown run {run_id}"})
                return
            body = self._read_json()
            invoice_id = str(body.get("invoice_id", ""))
            approver = str(body.get("approver", ""))
            reason = str(body.get("reason", ""))
            approve = bool(body.get("approve", False))
            if not invoice_id or not approver:
                self._send(400, {"error": "invoice_id and approver are required"})
                return
            from .approval import ApprovalGate
            from .models import RunResult as RR
            from .workflow import WorkflowEngine as WE
            result = RUNS[run_id]
            engine = ENGINES[run_id]
            assert isinstance(result, RR) and isinstance(engine, WE)
            try:
                d = ApprovalGate(result.decisions).resolve(invoice_id, approve=approve, approver=approver, reason=reason)
            except (KeyError, ValueError) as exc:
                self._send(409, {"error": str(exc)})
                return
            engine.record_resolution(d)
            result.summary = _recount(result)
            self._send(200, {"run_id": run_id, "decision": d.to_dict(), "summary": result.summary})
            return
        self._send(404, {"error": "not found"})


def _recount(result) -> dict:
    counts: dict[str, int] = {}
    for d in result.decisions:
        counts[d.decision] = counts.get(d.decision, 0) + 1
    total = sum((d.invoice.amount or 0) for d in result.decisions if d.decision == "paid")
    return {"counts": counts, "total_invoices": len(result.decisions), "total_paid_amount": round(total, 2)}


def serve(port: int = 8765) -> None:
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    print(f"workbench API listening on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    print("  GET  /health   GET /scenarios   POST /runs   GET /runs/{id}   POST /runs/{id}/approve")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def app_handler():  # reserved for future WSGI embedding
    return Handler
