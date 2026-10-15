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
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import Settings
from .scenarios import SCENARIOS, fixture_dir_for
from .workflow import run_fixture_scenario

RUNS: dict[str, object] = {}
ENGINES: dict[str, object] = {}
STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 1_048_576


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Repeated JSON key: {key}")
        result[key] = value
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkbenchHTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, indent=2).encode()
        self._bytes(status, body, "application/json; charset=utf-8")

    def _bytes(self, status: int, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise RequestError("Transfer-Encoding is unsupported; send Content-Length.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RequestError("Invalid Content-Length.")
        if not 0 < length <= MAX_BODY:
            raise RequestError("Provide a JSON body of at most 1 MiB.", 413 if length > MAX_BODY else 400)
        if self.headers.get_content_type() != "application/json":
            raise RequestError("Content-Type must be application/json.", 415)
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=_unique_keys,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite number")))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise RequestError(f"Malformed JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RequestError("Request body must be a JSON object.")
        return value

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            self._send(403, {"error": "Use this local demo through its localhost URL."})
            return False
        return True

    def _mutation_allowed(self) -> bool:
        if not self._host_allowed():
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self._send(403, {"error": "Cross-origin changes are not allowed."})
            return False
        return True

    def _store(self):
        from .onboarding_store import OnboardingStore
        return OnboardingStore(getattr(self.server, "onboarding_db", os.getenv("WORKBENCH_DB", "./var/onboarding.sqlite3")))

    @staticmethod
    def _project(state: dict) -> dict:
        from .onboarding import task_blockers
        return {**state, "tasks": [{**task, "blocked_reasons": task_blockers(task, state["tasks"])} for task in state["tasks"]]}

    def _onboarding_error(self, exc: Exception) -> None:
        from .onboarding import OnboardingError
        from .onboarding_store import RevisionConflict, StorageError
        if isinstance(exc, OnboardingError):
            self._send(exc.status, {"error": str(exc), "issues": exc.issues})
        elif isinstance(exc, RevisionConflict):
            self._send(409, {"error": str(exc), "revision": exc.revision})
        elif isinstance(exc, RequestError):
            self._send(exc.status, {"error": str(exc)})
        elif isinstance(exc, StorageError):
            self._send(500, {"error": str(exc)})
        else:
            raise exc

    @staticmethod
    def _fields(body: dict, expected: set[str]) -> None:
        if set(body) != expected:
            raise RequestError(f"Expected exactly these fields: {', '.join(sorted(expected))}.", 422)

    @staticmethod
    def _intake_fields(body: dict) -> None:
        if body.get("format") not in ("csv", "json") or not isinstance(body.get("text"), str):
            raise RequestError("format must be csv or json, and text must be a string.", 422)

    @staticmethod
    def _revision(body: dict) -> int:
        revision = body.get("revision")
        if type(revision) is not int or revision < 0:
            raise RequestError("revision must be a non-negative integer.", 422)
        return revision

    def _onboarding_get(self, path: str) -> bool:
        if not path.startswith("/api/onboarding"):
            return False
        from .onboarding import export_plan
        try:
            query = parse_qs(urlparse(self.path).query)
            if path == "/api/onboarding":
                self._send(200, self._project(self._store().read()))
            elif path == "/api/onboarding/export":
                format = query.get("format", ["json"])[0]
                if format not in ("json", "csv"):
                    raise RequestError("Export format must be json or csv.", 422)
                content = export_plan(self._store().read(), format)
                content_type = "application/json" if format == "json" else "text/csv; charset=utf-8"
                self._bytes(200, content.encode(), content_type, f"implementation-plan.{format}")
            elif path == "/api/onboarding/example":
                import csv
                import io
                record = {"customer_id": "harbor-demo", "customer_name": "Harbor Supply (synthetic)",
                          "integration": "CRM sandbox webhook for fictional Aster AI",
                          "technical_owner": "technical-owner@example.test",
                          "data_access_owner": "data-owner@example.test", "launch_owner": "launch-owner@example.test",
                          "acceptance_criteria": "10 synthetic CRM records reconcile; duplicate webhook retries create no duplicate records; launch owner signs off."}
                if query.get("invalid", ["1"])[0] != "0":
                    record["technical_owner"] = ""
                format = query.get("format", ["csv"])[0]
                if format == "json":
                    text = json.dumps([record], indent=2)
                elif format == "csv":
                    output = io.StringIO(newline="")
                    writer = csv.DictWriter(output, fieldnames=list(record))
                    writer.writeheader()
                    writer.writerow(record)
                    text = output.getvalue()
                else:
                    raise RequestError("Example format must be json or csv.", 422)
                self._send(200, {"text": text, "format": format})
            else:
                self._send(404, {"error": "Unknown onboarding endpoint."})
        except Exception as exc:
            self._onboarding_error(exc)
        return True

    def _onboarding_mutate(self, path: str) -> None:
        from .onboarding import import_intake, parse_intake, update_task
        try:
            body = self._read_json()
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if self.command == "POST" and path == "/api/onboarding/preview":
                self._fields(body, {"format", "text"})
                self._intake_fields(body)
                result = parse_intake(body["text"], body["format"], self._store().read()["customers"])
                self._send(200, result)
            elif self.command == "POST" and path == "/api/onboarding/import":
                self._fields(body, {"format", "text", "revision"})
                self._intake_fields(body)
                revision = self._revision(body)
                state = self._store().change(revision, lambda state: import_intake(state, body["text"], body["format"], now))
                self._send(201 if state["revision"] > revision else 200, self._project(state))
            elif self.command == "PATCH" and path.startswith("/api/onboarding/tasks/"):
                self._fields(body, {"changes", "revision"})
                revision = self._revision(body)
                if not isinstance(body["changes"], dict):
                    raise RequestError("changes must be an object.", 422)
                task_id = unquote(path.removeprefix("/api/onboarding/tasks/"))
                state = self._store().change(revision, lambda state: update_task(state, task_id, body["changes"], now))
                self._send(200, self._project(state))
            else:
                self._send(404, {"error": "Unknown onboarding endpoint or method."})
        except Exception as exc:
            self._onboarding_error(exc)

    def do_GET(self) -> None:
        if not self._host_allowed():
            return
        path = urlparse(self.path).path
        static_files = {"/": ("index.html", "text/html; charset=utf-8"),
                        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                        "/manrope.ttf": ("manrope.ttf", "font/ttf"),
                        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
                        "/motion-14.2.0.js": ("motion-14.2.0.js", "text/javascript; charset=utf-8")}
        if path in static_files:
            name, content_type = static_files[path]
            self._bytes(200, (STATIC_DIR / name).read_bytes(), content_type)
            return
        if self._onboarding_get(path):
            return
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
        if not self._mutation_allowed():
            return
        path = urlparse(self.path).path
        if path.startswith("/api/onboarding"):
            self._onboarding_mutate(path)
            return
        try:
            self._invoice_post()
        except RequestError as exc:
            self._send(exc.status, {"error": str(exc)})

    def do_PATCH(self) -> None:
        if self._mutation_allowed():
            self._onboarding_mutate(urlparse(self.path).path)

    def _invoice_post(self) -> None:
        path = urlparse(self.path).path
        settings = Settings.from_env()
        if path == "/runs":
            body = self._read_json()
            if set(body) - {"scenario"} or ("scenario" in body and not isinstance(body["scenario"], str)):
                raise RequestError("scenario must be a string and is the only supported field.", 422)
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
            self._fields(body, {"invoice_id", "approve", "approver", "reason"})
            if (type(body["approve"]) is not bool or
                    any(not isinstance(body[key], str) for key in ("invoice_id", "approver", "reason"))):
                raise RequestError("approve must be boolean; invoice_id, approver and reason must be strings.", 422)
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
    print(f"workbench UI + API listening on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    print("  GET  /health   GET /scenarios   POST /runs   GET /runs/{id}   POST /runs/{id}/approve")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def app_handler():  # reserved for future WSGI embedding
    return Handler
