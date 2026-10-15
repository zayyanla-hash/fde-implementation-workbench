"""Behavioral checks for the deterministic customer onboarding domain."""

from __future__ import annotations

import copy
import csv
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbench.onboarding import (  # noqa: E402
    OnboardingError, empty_state, export_plan, import_intake, parse_intake,
    parse_plan, task_blockers, update_task,
)


NOW = "2026-10-15T05:30:00Z"
RECORD = {
    "customer_id": "sample-customer",
    "customer_name": "Sample Customer (synthetic)",
    "integration": "Sandbox CRM export",
    "technical_owner": "technical-owner@example.test",
    "data_access_owner": "data-owner@example.test",
    "launch_owner": "launch-owner@example.test",
    "acceptance_criteria": "Import three synthetic accounts and reconcile counts.",
}


def csv_text(records, fields=None):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields or list(RECORD))
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue()


def plan():
    return import_intake(empty_state(), json.dumps([RECORD]), "json", NOW)


def task(state, suffix):
    return next(t for t in state["tasks"] if t["id"].endswith(":" + suffix))


def finish(state, suffix):
    current = task(state, suffix)
    state = update_task(state, current["id"], {"status": "in_progress", "blocker": ""}, NOW)
    return update_task(state, current["id"], {"status": "done"}, NOW)


class IntakeTests(unittest.TestCase):
    def test_csv_and_json_make_the_same_deterministic_plan(self):
        state = empty_state()
        expected = import_intake(state, json.dumps([RECORD]), "json", NOW)
        self.assertEqual(expected, import_intake(state, csv_text([RECORD]), "csv", NOW))
        self.assertEqual(state, empty_state(), "pure import must leave input unchanged")
        self.assertEqual(len(expected["customers"]), 1)
        self.assertEqual(len(expected["tasks"]), 5)
        self.assertEqual(expected["revision"], 1)
        self.assertEqual(expected["activity"][0]["action"], "customer_imported")
        access = task(expected, "data-access")
        self.assertEqual(access["status"], "blocked")
        self.assertIn("sandbox", access["blocker"].lower())
        integration = task(expected, "integration")
        self.assertEqual(integration["depends_on"], [task(expected, "scope")["id"], access["id"]])
        self.assertEqual(task(expected, "launch")["acceptance_criteria"], RECORD["acceptance_criteria"])
        self.assertEqual(task(expected, "acceptance")["owner"], RECORD["technical_owner"])

    def test_missing_owner_is_actionable_and_import_is_atomic(self):
        invalid = dict(RECORD, customer_id="other", technical_owner="")
        source = json.dumps([RECORD, invalid])
        parsed = parse_intake(source, "json")
        self.assertTrue(any(i["row"] == 2 and i["field"] == "technical_owner"
                            and i["severity"] == "error" for i in parsed["issues"]))
        state = empty_state()
        with self.assertRaises(OnboardingError) as error:
            import_intake(state, source, "json", NOW)
        self.assertEqual(error.exception.status, 422)
        self.assertTrue(error.exception.issues)
        self.assertEqual(state, empty_state())

    def test_identical_duplicates_warn_and_create_nothing_twice(self):
        parsed = parse_intake(json.dumps([RECORD, RECORD]), "json")
        self.assertEqual(parsed["duplicates"], 1)
        self.assertEqual(len(parsed["records"]), 1)
        self.assertEqual(parsed["issues"][0]["severity"], "warning")
        state = plan()
        self.assertEqual(import_intake(state, json.dumps([RECORD]), "json", NOW), state)

    def test_conflicting_duplicates_reject_both_in_source_and_against_storage(self):
        changed = dict(RECORD, integration="Different integration")
        for records, existing in (([RECORD, changed], []), ([changed], [RECORD])):
            parsed = parse_intake(json.dumps(records), "json", existing)
            conflicts = [i for i in parsed["issues"] if i["code"] == "conflict"]
            self.assertEqual(len(conflicts), 1)
            self.assertIn("customer_id", conflicts[0]["message"])
        state = plan()
        with self.assertRaises(OnboardingError):
            import_intake(state, json.dumps([changed]), "json", NOW)
        self.assertEqual(state["customers"][0], RECORD)

    def test_json_duplicate_keys_are_explicit_errors(self):
        source = json.dumps([RECORD]).replace('"customer_id": "sample-customer"',
                                             '"customer_id": "sample-customer", "customer_id": "other"')
        result = parse_intake(source, "json")
        self.assertTrue(any(i["code"] == "duplicate_field" and i["field"] == "customer_id"
                            for i in result["issues"]))
        with self.assertRaises(OnboardingError):
            import_intake(empty_state(), source, "json", NOW)

    def test_malformed_sources_and_shapes_are_rejected(self):
        for source, format_name in (("[", "json"), ("{}", "json"), ("[null]", "json"),
                                    ("[]", "json"), ("", "csv"), ('"unclosed', "csv"),
                                    (json.dumps([RECORD]), "yaml")):
            with self.subTest(source=source, format=format_name):
                result = parse_intake(source, format_name)
                self.assertTrue(any(i["severity"] == "error" for i in result["issues"]))

    def test_required_strings_ids_emails_and_unknown_fields(self):
        for field, value in (("customer_name", None), ("integration", 42), ("acceptance_criteria", " "),
                             ("customer_id", "Invalid ID"), ("technical_owner", "some person"),
                             ("launch_owner", "x@localhost"), ("unexpected", "discard me")):
            with self.subTest(field=field, value=value):
                parsed = parse_intake(json.dumps([dict(RECORD, **{field: value})]), "json")
                self.assertTrue(any(i["field"] == field and i["severity"] == "error"
                                    for i in parsed["issues"]))

    def test_invalid_unicode_is_rejected_before_persistence_or_export(self):
        record = dict(RECORD, customer_name="Invalid surrogate \ud800")
        parsed = parse_intake(json.dumps([record]), "json")
        self.assertTrue(any(i["field"] == "customer_name" and i["code"] == "invalid_unicode"
                            for i in parsed["issues"]))
        with self.assertRaises(OnboardingError):
            import_intake(empty_state(), json.dumps([record]), "json", NOW)

    def test_fixture_formats_are_equivalent_and_incomplete_examples_fail(self):
        directory = Path(__file__).resolve().parent.parent / "fixtures" / "onboarding"
        parsed = []
        for format_name in ("csv", "json"):
            valid = (directory / f"customer-intake-valid.{format_name}").read_text()
            parsed.append(parse_intake(valid, format_name))
            invalid = (directory / f"customer-intake-incomplete.{format_name}").read_text()
            self.assertTrue(any(issue["field"] == "technical_owner" and issue["severity"] == "error"
                                for issue in parse_intake(invalid, format_name)["issues"]))
        self.assertEqual(parsed[0], parsed[1])
        self.assertEqual(len(parsed[0]["records"]), 1)

    def test_csv_missing_unknown_duplicate_columns_and_extra_cells_are_errors(self):
        sources = [",".join(k for k in RECORD if k != "technical_owner") + "\n",
                   csv_text([dict(RECORD, surprise="x")], list(RECORD) + ["surprise"]),
                   csv_text([RECORD]).replace("customer_id,", "customer_id,customer_id,", 1),
                   csv_text([RECORD]).rstrip() + ",extra\n"]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(any(i["severity"] == "error" for i in parse_intake(source, "csv")["issues"]))

    def test_blank_csv_records_are_reported_instead_of_discarded(self):
        source = csv_text([RECORD]) + "\n"
        issues = parse_intake(source, "csv")["issues"]
        self.assertTrue(any(i["code"] == "empty_row" and i["row"] == 3 for i in issues))


class TaskTests(unittest.TestCase):
    def test_unmet_dependencies_explain_titles_and_prevent_progress(self):
        state = plan()
        integration = task(state, "integration")
        reasons = task_blockers(integration, state["tasks"])
        self.assertTrue(any(task(state, "scope")["title"] in reason for reason in reasons))
        self.assertEqual(len(reasons), 2)
        with self.assertRaises(OnboardingError) as error:
            update_task(state, integration["id"], {"status": "in_progress"}, NOW)
        self.assertEqual(error.exception.status, 409)
        self.assertIn("depend", str(error.exception).lower())

    def test_done_requires_in_progress_and_a_cleared_blocker(self):
        state = plan()
        with self.assertRaises(OnboardingError):
            update_task(state, task(state, "scope")["id"], {"status": "done"}, NOW)
        with self.assertRaises(OnboardingError):
            update_task(state, task(state, "data-access")["id"], {"status": "in_progress"}, NOW)
        state = finish(state, "scope")
        state = finish(state, "data-access")
        state = finish(state, "integration")
        state = finish(state, "acceptance")
        state = finish(state, "launch")
        self.assertTrue(all(t["status"] == "done" for t in state["tasks"]))

    def test_blocked_requires_a_reason_and_done_forbids_one(self):
        state = plan()
        identifier = task(state, "scope")["id"]
        with self.assertRaises(OnboardingError):
            update_task(state, identifier, {"status": "blocked", "blocker": " "}, NOW)
        state = update_task(state, identifier, {"status": "in_progress"}, NOW)
        with self.assertRaises(OnboardingError):
            update_task(state, identifier, {"status": "done", "blocker": "waiting"}, NOW)

    def test_reopening_a_dependency_cannot_invalidate_completed_or_active_work(self):
        state = finish(finish(plan(), "scope"), "data-access")
        state = update_task(state, task(state, "integration")["id"], {"status": "in_progress"}, NOW)
        with self.assertRaises(OnboardingError) as error:
            update_task(state, task(state, "scope")["id"], {"status": "todo"}, NOW)
        self.assertEqual(error.exception.status, 409)
        state = update_task(state, task(state, "integration")["id"], {"status": "done"}, NOW)
        with self.assertRaises(OnboardingError):
            update_task(state, task(state, "scope")["id"], {"status": "todo"}, NOW)

    def test_reopening_without_active_descendants_and_noop_are_allowed(self):
        state = finish(plan(), "scope")
        identifier = task(state, "scope")["id"]
        reopened = update_task(state, identifier, {"status": "todo"}, NOW)
        self.assertEqual(task(reopened, "scope")["status"], "todo")
        self.assertEqual(reopened["revision"], state["revision"] + 1)
        self.assertEqual(update_task(reopened, identifier, {"status": "todo"}, NOW), reopened)

    def test_task_edits_are_pure_validated_and_record_readable_changes(self):
        state = plan()
        original = copy.deepcopy(state)
        identifier = task(state, "scope")["id"]
        updated = update_task(state, identifier, {"title": "Confirm sandbox scope", "owner": "new@example.test"}, NOW)
        self.assertEqual(state, original)
        self.assertIn("Confirm sandbox scope", updated["activity"][-1]["details"])
        for changes in ({"depends_on": []}, {"owner": "nobody"}, {"title": " "},
                        {"status": "shipped"}, {"blocker": None}, []):
            with self.subTest(changes=changes):
                with self.assertRaises(OnboardingError) as error:
                    update_task(state, identifier, changes, NOW)
                self.assertEqual(error.exception.status, 422)
        with self.assertRaises(OnboardingError) as error:
            update_task(state, "missing", {"title": "x"}, NOW)
        self.assertEqual(error.exception.status, 404)

    def test_updated_state_does_not_share_mutable_dependencies_with_input(self):
        state = plan()
        original = copy.deepcopy(state)
        updated = update_task(state, task(state, "scope")["id"], {"title": "Updated scope"}, NOW)
        task(updated, "scope")["depends_on"].append("unexpected")
        self.assertEqual(state, original)

    def test_task_changes_reject_invalid_unicode(self):
        state = plan()
        for field in ("title", "owner", "blocker"):
            with self.subTest(field=field):
                with self.assertRaises(OnboardingError) as error:
                    update_task(state, task(state, "scope")["id"], {field: "\ud800@example.test"}, NOW)
                self.assertEqual(error.exception.status, 422)


class ExportTests(unittest.TestCase):
    def test_json_and_csv_preserve_complete_plan_data(self):
        state = plan()
        for format_name in ("json", "csv"):
            with self.subTest(format=format_name):
                exported = export_plan(state, format_name)
                self.assertEqual(parse_plan(exported, format_name), state["tasks"])
        self.assertEqual(json.loads(export_plan(state, "json"))["schema_version"], 1)

    def test_csv_formula_strings_and_apostrophes_are_safe_and_lossless(self):
        for value in ('=HYPERLINK("https://example.test")', "+SUM(A1:A2)", "-1+2", "@SUM(A1)",
                      "\t=1+1", "\r=1+1", " '=literal", "'literal", "line\nwith,comma"):
            with self.subTest(value=value):
                state = plan()
                state["tasks"][0]["title"] = value
                exported = export_plan(state, "csv")
                rows = list(csv.DictReader(io.StringIO(exported, newline="")))
                self.assertTrue(rows[0]["title"].startswith("'"))
                self.assertEqual(parse_plan(exported, "csv"), state["tasks"])

    def test_plan_parser_rejects_malformed_shapes_and_unknown_formats(self):
        for source, format_name in (("{}", "json"), ('{"schema_version": 1, "tasks": [null]}', "json"),
                                    ("id,title\nx,y\n", "csv"), ("", "csv"), ("{}", "yaml")):
            with self.subTest(source=source, format=format_name):
                with self.assertRaises(OnboardingError):
                    parse_plan(source, format_name)

    def test_plan_dependencies_require_an_array_including_when_empty(self):
        source = json.loads(export_plan(plan(), "json"))
        source["tasks"][0]["depends_on"] = {}
        with self.assertRaises(OnboardingError):
            parse_plan(json.dumps(source), "json")

    def test_portable_plan_rejects_invalid_unicode(self):
        source = json.loads(export_plan(plan(), "json"))
        source["tasks"][0]["title"] = "\ud800"
        with self.assertRaises(OnboardingError):
            parse_plan(json.dumps(source), "json")


if __name__ == "__main__":
    unittest.main()
