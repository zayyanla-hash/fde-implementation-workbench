"""Stateless validation for the public, per-browser portfolio demo.

Each request owns its snapshot. Nothing is kept in function memory or written to
an ephemeral filesystem. Browser IndexedDB provides persistence and commits.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from .onboarding import (OnboardingError, empty_state, export_plan, import_intake,
                         parse_intake, parse_plan, task_blockers, update_task, _tasks_for)

MAX_BODY = 1024 * 1024


def validate_snapshot(state: object) -> dict:
    fields = {"schema_version", "revision", "customers", "tasks", "activity"}
    if (not isinstance(state, dict) or set(state) != fields
            or type(state["schema_version"]) is not int or state["schema_version"] != 1
            or type(state["revision"]) is not int or state["revision"] < 0
            or any(not isinstance(state[key], list) for key in ("customers", "tasks", "activity"))):
        raise OnboardingError("This browser's saved plan has an invalid state schema. It was not reset.")
    if len(state["customers"]) > 50 or len(state["tasks"]) > 250:
        raise OnboardingError("This demo supports up to 50 synthetic customers per browser.")
    if state["customers"]:
        parsed = parse_intake(json.dumps(state["customers"]), "json")
        if parsed["issues"] or len(parsed["records"]) != len(state["customers"]):
            raise OnboardingError("Saved customer records are invalid. Existing data was not reset.")
    tasks = parse_plan(json.dumps({"schema_version": 1, "tasks": state["tasks"]}), "json")
    expected = {task["id"]: task for customer in state["customers"] for task in _tasks_for(customer)}
    if set(expected) != {task["id"] for task in tasks}:
        raise OnboardingError("Saved tasks must match the five generated stages for each customer.")
    for task in tasks:
        original = expected[task["id"]]
        if any(task[key] != original[key] for key in ("customer_id", "depends_on", "acceptance_criteria")):
            raise OnboardingError("Generated dependencies and acceptance criteria cannot be changed.")
    for event in state["activity"]:
        if (not isinstance(event, dict) or set(event) != {"at", "action", "details"}
                or any(not isinstance(value, str) for value in event.values())):
            raise OnboardingError("Saved activity is invalid. Existing data was not reset.")
    return copy.deepcopy(state)


def project(state: dict) -> dict:
    return {**state, "tasks": [{**task, "blocked_reasons": task_blockers(task, state["tasks"])}
                              for task in state["tasks"]]}


def dispatch(body: dict, now: str | None = None) -> dict:
    if not isinstance(body, dict) or set(body) != {"operation", "state", "data"}:
        raise OnboardingError("Expected operation, state, and data fields.")
    operation, data = body["operation"], body["data"]
    if not isinstance(operation, str) or not isinstance(data, dict):
        raise OnboardingError("operation must be text and data must be an object.")
    state = validate_snapshot(body["state"])
    now = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    allowed = {"read": set(), "example": {"format", "invalid"},
               "preview": {"format", "text"}, "import": {"format", "text", "revision"},
               "update": {"task_id", "changes", "revision"}, "export": {"format"}}
    if operation not in allowed or set(data) != allowed[operation]:
        raise OnboardingError("Unknown operation or unexpected operation fields.")
    if "format" in data and data["format"] not in ("csv", "json"):
        raise OnboardingError("format must be csv or json.")
    if "text" in data and not isinstance(data["text"], str):
        raise OnboardingError("Intake source must be text.")
    if "revision" in data:
        if type(data["revision"]) is not int or data["revision"] != state["revision"]:
            raise OnboardingError("This plan changed. Refresh before saving.", status=409)
    if operation == "preview":
        return {"result": parse_intake(data["text"], data["format"], state["customers"])}
    if operation == "example":
        if type(data["invalid"]) is not bool:
            raise OnboardingError("invalid must be a boolean.")
        name = "incomplete" if data["invalid"] else "valid"
        path = Path(__file__).resolve().parents[2] / "fixtures" / "onboarding" / f"customer-intake-{name}.{data['format']}"
        return {"result": {"text": path.read_text(), "format": data["format"]}}
    if operation == "export":
        return {"result": {"text": export_plan(state, data["format"]), "format": data["format"]}}
    if operation == "import":
        state = import_intake(state, data["text"], data["format"], now)
        if len(state["customers"]) > 50:
            raise OnboardingError("This demo supports up to 50 synthetic customers per browser.")
    if operation == "update":
        if not isinstance(data["task_id"], str) or not isinstance(data["changes"], dict):
            raise OnboardingError("task_id must be text and changes must be an object.")
        state = update_task(state, data["task_id"], data["changes"], now)
    return {"state": state, "result": project(state)}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Repeated JSON field")
        value[key] = item
    return value


def send(request, status: int, payload: object):
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    request.send_response(status)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Cache-Control", "no-store")
    request.send_header("X-Content-Type-Options", "nosniff")
    request.send_header("Content-Length", str(len(data)))
    request.end_headers()
    request.wfile.write(data)


def handle(request):
    from urllib.parse import urlsplit
    if request.command == "GET":
        send(request, 200, {"ok": True, "mode": "per-browser-demo", "persistence": "visitor-indexeddb",
                            "validation": "python-domain-rules", "schema_version": 1})
        return
    if request.command != "POST":
        send(request, 405, {"error": "Use POST for demo operations."})
        return
    try:
        origin = request.headers.get("Origin")
        host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
        if (origin and (urlsplit(origin).netloc != host or urlsplit(origin).scheme not in ("https", "http"))) or request.headers.get("Sec-Fetch-Site") == "cross-site":
            send(request, 403, {"error": "Cross-origin changes are not allowed."})
            return
        if request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            send(request, 415, {"error": "Send application/json."})
            return
        try:
            length = int(request.headers.get("Content-Length", "0"))
        except ValueError:
            send(request, 400, {"error": "Invalid request length."})
            return
        if length <= 0 or length > MAX_BODY:
            send(request, 413 if length > MAX_BODY else 400, {"error": "Request must contain JSON and be no larger than 1 MB."})
            return
        try:
            body = json.loads(request.rfile.read(length).decode("utf-8"), object_pairs_hook=_unique_object)
        except (ValueError, UnicodeDecodeError, RecursionError):
            send(request, 400, {"error": "Malformed JSON or repeated fields."})
            return
        send(request, 200, dispatch(body))
    except OnboardingError as exc:
        send(request, exc.status, {"error": str(exc), "issues": exc.issues})
    except (ValueError, TypeError, KeyError, RecursionError):
        send(request, 422, {"error": "Invalid demo state. Existing browser data was not reset."})
