"""Deterministic intake, dependency-aware onboarding plans, and portable exports.

Functions return new values and never mutate caller-owned state. The caller owns
storage, timestamps, optimistic concurrency, and transport size limits.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from collections import Counter
from typing import Any


INTAKE_FIELDS = (
    "customer_id", "customer_name", "integration", "technical_owner",
    "data_access_owner", "launch_owner", "acceptance_criteria",
)
TASK_FIELDS = (
    "id", "customer_id", "title", "owner", "status", "depends_on", "blocker",
    "acceptance_criteria",
)
STATUSES = frozenset(("todo", "in_progress", "blocked", "done"))
OWNER_FIELDS = frozenset(("technical_owner", "data_access_owner", "launch_owner"))
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+\Z")


class OnboardingError(ValueError):
    """An actionable domain error suitable for an HTTP response."""

    def __init__(self, message: str, issues: list[dict] | None = None, status: int = 422):
        super().__init__(message)
        self.message = message
        self.issues = list(issues or [])
        self.status = status


class _JSONObject(list):
    """Keep object pairs until duplicate field names have been reported."""


def _issue(row: int, field: str, code: str, message: str, severity: str = "error") -> dict:
    return {"row": row, "field": field, "code": code, "message": message, "severity": severity}


def _portable_text(value: str) -> bool:
    try:
        value.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def empty_state() -> dict:
    return {"schema_version": 1, "revision": 0, "customers": [], "tasks": [], "activity": []}


def _json_value(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_JSONObject)


def _object(pairs: Any, row: int, issues: list[dict]) -> dict | None:
    if not isinstance(pairs, _JSONObject):
        issues.append(_issue(row, "", "invalid_record", "Each record must be a JSON object."))
        return None
    result = {}
    for key, value in pairs:
        if key in result:
            issues.append(_issue(row, key, "duplicate_field", f"Field '{key}' appears more than once; remove the duplicate key."))
        result[key] = value
    return result


def _read_intake_rows(text: str, format: str, issues: list[dict]) -> list[tuple[int, dict]]:
    if not isinstance(text, str):
        issues.append(_issue(1, "", "invalid_text", "Intake source must be text."))
        return []
    if format == "json":
        try:
            source = _json_value(text)
        except (ValueError, RecursionError) as exc:
            issues.append(_issue(1, "", "malformed_json", f"Invalid JSON: {exc}"))
            return []
        if not isinstance(source, list) or isinstance(source, _JSONObject):
            issues.append(_issue(1, "", "invalid_shape", "JSON intake must be an array of customer objects."))
            return []
        rows = []
        for index, pairs in enumerate(source, 1):
            record = _object(pairs, index, issues)
            if record is not None:
                rows.append((index, record))
        if not source:
            issues.append(_issue(1, "", "empty_intake", "Add at least one customer record."))
        return rows
    if format != "csv":
        issues.append(_issue(1, "format", "unsupported_format", "Choose CSV or JSON."))
        return []
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        header = next(reader, None)
        if not header:
            issues.append(_issue(1, "", "missing_header", "CSV needs a header and at least one customer record."))
            return []
        for name, count in Counter(header).items():
            if count > 1:
                issues.append(_issue(1, name, "duplicate_field", f"Column '{name}' appears more than once."))
            if name not in INTAKE_FIELDS:
                issues.append(_issue(1, name, "unknown_field", f"Unknown column '{name}'; use the documented intake columns."))
        for name in INTAKE_FIELDS:
            if name not in header:
                issues.append(_issue(1, name, "missing_field", f"Required column '{name}' is missing."))
        if issues:
            return []
        rows = []
        for row_number, values in enumerate(reader, 2):
            if not values:
                issues.append(_issue(row_number, "", "empty_row", "Blank CSV record; remove it or provide all required fields."))
            elif len(values) != len(header):
                issues.append(_issue(row_number, "", "row_width", f"Expected {len(header)} cells but found {len(values)}; check commas and quoting."))
            else:
                rows.append((row_number, dict(zip(header, values))))
        if not rows and not issues:
            issues.append(_issue(2, "", "empty_intake", "Add at least one customer record below the header."))
        return rows
    except csv.Error as exc:
        issues.append(_issue(max(1, reader.line_num), "", "malformed_csv", f"Invalid CSV: {exc}"))
        return []


def parse_intake(text: str, format: str, existing_customers: list[dict] = ()) -> dict:
    """Validate source without mutation; diagnostics use logical record positions."""
    issues: list[dict] = []
    rows = _read_intake_rows(text, format, issues)
    records = []
    duplicates = 0
    known = {record["customer_id"]: record for record in existing_customers}
    invalid_json_rows = {issue["row"] for issue in issues if issue["severity"] == "error"}
    for row_number, record in rows:
        before = len(issues)
        for field in record:
            if field not in INTAKE_FIELDS:
                issues.append(_issue(row_number, field, "unknown_field", f"Unknown field '{field}'; remove it or use a documented intake field."))
        for field in INTAKE_FIELDS:
            if field not in record:
                issues.append(_issue(row_number, field, "missing_field", f"Required field '{field}' is missing."))
            elif not isinstance(record[field], str):
                issues.append(_issue(row_number, field, "invalid_type", f"'{field}' must be a string."))
            elif not _portable_text(record[field]):
                issues.append(_issue(row_number, field, "invalid_unicode", f"'{field}' contains an invalid Unicode surrogate; replace the invalid character before importing."))
            elif not record[field].strip():
                issues.append(_issue(row_number, field, "required", f"Provide a nonempty '{field}'."))
            elif field == "customer_id" and not ID_PATTERN.fullmatch(record[field]):
                issues.append(_issue(row_number, field, "invalid_id", "customer_id must be 1–64 lowercase letters, digits, underscores, or hyphens, starting with a letter or digit."))
            elif field in OWNER_FIELDS and not EMAIL_PATTERN.fullmatch(record[field]):
                issues.append(_issue(row_number, field, "invalid_owner", f"'{field}' must be an email-shaped owner, such as owner@example.test."))
        if len(issues) != before or row_number in invalid_json_rows:
            continue
        identifier = record["customer_id"]
        if identifier in known:
            if record == known[identifier]:
                duplicates += 1
                issues.append(_issue(row_number, "customer_id", "duplicate", f"Customer '{identifier}' already has identical intake; no customer or tasks will be created.", "warning"))
            else:
                differing = ", ".join(field for field in INTAKE_FIELDS if record.get(field) != known[identifier].get(field))
                issues.append(_issue(row_number, "customer_id", "conflict", f"customer_id '{identifier}' has conflicting values ({differing}). Use unchanged intake or a new customer_id; existing data will not be overwritten."))
            continue
        known[identifier] = record
        records.append(copy.deepcopy(record))
    return {"records": records, "issues": issues, "duplicates": duplicates}


def _tasks_for(customer: dict) -> list[dict]:
    identifier = customer["customer_id"]
    customer_name = customer["customer_name"]
    task_id = lambda suffix: f"{identifier}:{suffix}"
    specifications = (
        ("scope", f"Confirm scope — {customer_name}", "technical_owner", [], "", "Confirm the integration scope and sandbox boundaries."),
        ("data-access", f"Grant sandbox data access — {customer_name}", "data_access_owner", [], "Sandbox data access has not been confirmed; the data access owner must provision and verify access.", "Confirm access to synthetic sandbox data."),
        ("integration", f"Build {customer['integration']} integration — {customer_name}", "technical_owner", [task_id("scope"), task_id("data-access")], "", "Implement and verify the agreed sandbox integration."),
        ("acceptance", f"Verify acceptance — {customer_name}", "technical_owner", [task_id("integration")], "", customer["acceptance_criteria"]),
        ("launch", f"Launch handoff — {customer_name}", "launch_owner", [task_id("acceptance")], "", customer["acceptance_criteria"]),
    )
    return [{"id": task_id(suffix), "customer_id": identifier, "title": title,
             "owner": customer[owner], "status": "blocked" if blocker else "todo",
             "depends_on": dependencies, "blocker": blocker, "acceptance_criteria": criteria}
            for suffix, title, owner, dependencies, blocker, criteria in specifications]


def import_intake(state: dict, text: str, format: str, now: str) -> dict:
    parsed = parse_intake(text, format, state["customers"])
    if any(issue["severity"] == "error" for issue in parsed["issues"]):
        raise OnboardingError("Intake has errors. Correct the source and validate again; no customers or tasks were changed.", parsed["issues"])
    result = copy.deepcopy(state)
    if not parsed["records"]:
        return result
    for customer in parsed["records"]:
        result["customers"].append(customer)
        result["tasks"].extend(_tasks_for(customer))
        result["activity"].append({"at": now, "action": "customer_imported", "details": f"Imported {customer['customer_name']} ({customer['customer_id']}); created 5 deterministic onboarding tasks."})
    result["revision"] += 1
    return result


def task_blockers(task: dict, tasks: list[dict]) -> list[str]:
    """Explain explicit blockers and unmet immediate dependencies by name."""
    reasons = [task["blocker"]] if task.get("blocker", "").strip() else []
    by_id = {item["id"]: item for item in tasks}
    for identifier in task["depends_on"]:
        dependency = by_id.get(identifier)
        if dependency is None:
            reasons.append(f"Missing dependency: {identifier}.")
        elif dependency["status"] != "done":
            reasons.append(f"Dependency '{dependency['title']}' must be done (currently {dependency['status']}).")
    return reasons


def update_task(state: dict, task_id: str, changes: dict, now: str) -> dict:
    current = next((item for item in state["tasks"] if item["id"] == task_id), None)
    if current is None:
        raise OnboardingError(f"Task '{task_id}' was not found.", status=404)
    if not isinstance(changes, dict):
        raise OnboardingError("Task changes must be an object.")
    allowed = frozenset(("title", "owner", "status", "blocker"))
    invalid_fields = set(changes) - allowed
    if invalid_fields:
        raise OnboardingError(f"Task fields are immutable or unknown: {', '.join(sorted(invalid_fields))}.")
    for field, value in changes.items():
        if not isinstance(value, str):
            raise OnboardingError(f"'{field}' must be a string.")
        if not _portable_text(value):
            raise OnboardingError(f"'{field}' contains an invalid Unicode surrogate; replace the invalid character.")
        if field in ("title", "owner") and not value.strip():
            raise OnboardingError(f"'{field}' cannot be empty.")
        if field == "owner" and not EMAIL_PATTERN.fullmatch(value):
            raise OnboardingError("Owner must be an email-shaped value, such as owner@example.test.")
        if field == "status" and value not in STATUSES:
            raise OnboardingError("Status must be todo, in_progress, blocked, or done.")
    candidate = dict(copy.deepcopy(current), **changes)
    status = candidate["status"]
    if status == "blocked" and not candidate["blocker"].strip():
        raise OnboardingError("A blocked task needs a nonempty blocker explaining what is required.", status=409)
    if status == "done" and current["status"] not in ("in_progress", "done"):
        raise OnboardingError("Move the task to in_progress before marking it done.", status=409)
    if status in ("in_progress", "done"):
        reasons = task_blockers(candidate, state["tasks"])
        if reasons:
            raise OnboardingError("Cannot start or complete this task: " + " ".join(reasons), status=409)
    if candidate == current:
        return copy.deepcopy(state)
    result = copy.deepcopy(state)
    index = next(index for index, item in enumerate(result["tasks"]) if item["id"] == task_id)
    result["tasks"][index] = candidate
    for dependent in result["tasks"]:
        if dependent["status"] in ("in_progress", "done"):
            reasons = task_blockers(dependent, result["tasks"])
            if reasons:
                raise OnboardingError(f"This change would invalidate '{dependent['title']}'. Reopen dependent work first. " + " ".join(reasons), status=409)
    result["revision"] += 1
    description = "; ".join(f"{field}: {current[field]!r} → {candidate[field]!r}"
                            for field in ("title", "owner", "status", "blocker") if candidate[field] != current[field])
    result["activity"].append({"at": now, "action": "task_updated", "details": f"Updated {task_id}: {description}."})
    return result


def export_plan(state: dict, format: str) -> str:
    """Export tasks; CSV prefixes all data cells with one reversible apostrophe."""
    tasks = [{field: copy.deepcopy(task[field]) for field in TASK_FIELDS} for task in state["tasks"]]
    if format == "json":
        return json.dumps({"schema_version": 1, "tasks": tasks}, ensure_ascii=False, indent=2) + "\n"
    if format != "csv":
        raise OnboardingError("Choose CSV or JSON for plan export.")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=TASK_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for task in tasks:
        writer.writerow({field: "'" + (json.dumps(value, ensure_ascii=False) if field == "depends_on" else value)
                         for field, value in task.items()})
    return stream.getvalue()


def _validate_plan(tasks: Any) -> list[dict]:
    if not isinstance(tasks, list) or isinstance(tasks, _JSONObject):
        raise OnboardingError("Plan tasks must be an array.")
    result = []
    identifiers = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != set(TASK_FIELDS):
            raise OnboardingError("Each plan task must include exactly the documented task fields.")
        if any(not isinstance(task[field], str) for field in TASK_FIELDS if field != "depends_on"):
            raise OnboardingError("Plan task fields must be strings, except depends_on must be an array of strings.")
        if any(not _portable_text(task[field]) for field in TASK_FIELDS if field != "depends_on"):
            raise OnboardingError("Plan task strings contain an invalid Unicode surrogate.")
        if not isinstance(task["depends_on"], list) or isinstance(task["depends_on"], _JSONObject) or any(not isinstance(value, str) for value in task["depends_on"]):
            raise OnboardingError("depends_on must be an array of task IDs.")
        if not task["id"] or task["id"] in identifiers:
            raise OnboardingError("Plan task IDs must be nonempty and unique.")
        if not ID_PATTERN.fullmatch(task["customer_id"]) or not task["title"].strip():
            raise OnboardingError("Plan tasks need a valid customer_id and nonempty title.")
        if not EMAIL_PATTERN.fullmatch(task["owner"]) or task["status"] not in STATUSES:
            raise OnboardingError("Plan tasks need an email-shaped owner and a valid status.")
        identifiers.add(task["id"])
        result.append(copy.deepcopy(task))
    by_id = {task["id"]: task for task in result}
    for task in result:
        dependencies = task["depends_on"]
        if len(dependencies) != len(set(dependencies)) or task["id"] in dependencies or any(identifier not in by_id for identifier in dependencies):
            raise OnboardingError("Plan dependencies must be unique, exist in the exported plan, and cannot reference the task itself.")
        if task["status"] == "blocked" and not task["blocker"].strip():
            raise OnboardingError("A blocked plan task needs an explanation.")
        if task["status"] in ("in_progress", "done") and task_blockers(task, result):
            raise OnboardingError("An active or completed plan task has unresolved blockers or dependencies.")
    # Reject cycles, including cycles in work that has not started yet.
    visited = set()
    visiting = set()
    def visit(identifier):
        if identifier in visiting:
            raise OnboardingError("Plan dependencies contain a cycle.")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in by_id[identifier]["depends_on"]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)
    for identifier in by_id:
        visit(identifier)
    return result


def parse_plan(text: str, format: str) -> list[dict]:
    """Read our portable plan format. This never imports customer intake or state."""
    if not isinstance(text, str):
        raise OnboardingError("Plan source must be text.")
    if format == "json":
        try:
            source = _json_value(text)
        except (ValueError, RecursionError) as exc:
            raise OnboardingError(f"Invalid plan JSON: {exc}") from exc
        issues = []
        envelope = _object(source, 1, issues)
        if envelope is None or issues or set(envelope) != {"schema_version", "tasks"} or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1:
            raise OnboardingError("Plan JSON must contain schema_version: 1 and tasks, with no duplicate or extra fields.", issues)
        raw_tasks = envelope["tasks"]
        if not isinstance(raw_tasks, list) or isinstance(raw_tasks, _JSONObject):
            raise OnboardingError("Plan tasks must be an array.")
        tasks = [_object(raw, index, issues) for index, raw in enumerate(raw_tasks, 1)]
        if issues:
            raise OnboardingError("Plan task objects contain errors.", issues)
        return _validate_plan(tasks)
    if format != "csv":
        raise OnboardingError("Choose CSV or JSON for plan parsing.")
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        header = next(reader, None)
        if header != list(TASK_FIELDS):
            raise OnboardingError("Plan CSV header must contain the documented task fields in export order.")
        tasks = []
        for values in reader:
            if len(values) != len(TASK_FIELDS) or any(not value.startswith("'") for value in values):
                raise OnboardingError("Plan CSV requires complete rows and the apostrophe text prefix on every data cell.")
            task = dict(zip(TASK_FIELDS, (value[1:] for value in values)))
            try:
                task["depends_on"] = json.loads(task["depends_on"])
            except (ValueError, RecursionError) as exc:
                raise OnboardingError("Plan CSV depends_on must contain a JSON array of task IDs.") from exc
            tasks.append(task)
        return _validate_plan(tasks)
    except csv.Error as exc:
        raise OnboardingError(f"Invalid plan CSV: {exc}") from exc
