"""Exercise the real public adapter, including hostile/malformed snapshots."""
import copy
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from workbench.hosted import dispatch, handle, validate_snapshot
from workbench.onboarding import OnboardingError, empty_state, parse_plan

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures/onboarding/customer-intake-valid.json"
NOW = "2026-10-15T06:30:00Z"


class PublicHandler(BaseHTTPRequestHandler):
    do_GET = handle
    do_POST = handle
    do_PATCH = handle
    def log_message(self, *args): pass


class HostedTests(unittest.TestCase):
    def call(self, operation, state=None, **data):
        return dispatch({"operation": operation, "state": state if state is not None else empty_state(), "data": data}, NOW)

    def imported(self):
        return self.call("import", text=FIXTURE.read_text(), format="json", revision=0)["state"]

    def test_read_is_empty_without_other_visitors_state(self):
        first = self.imported()
        second = self.call("read")
        self.assertEqual(len(first["tasks"]), 5)
        self.assertEqual(second["result"]["tasks"], [])
        self.assertEqual(empty_state()["revision"], 0)

    def test_invalid_import_returns_field_diagnostics(self):
        data = json.loads(FIXTURE.read_text()); data[0]["technical_owner"] = ""
        with self.assertRaises(OnboardingError) as caught:
            self.call("import", text=json.dumps(data), format="json", revision=0)
        self.assertTrue(any(x["field"] == "technical_owner" for x in caught.exception.issues))

    def test_duplicate_import_has_no_new_revision_or_events(self):
        state = self.imported()
        again = self.call("import", state, text=FIXTURE.read_text(), format="json", revision=1)
        self.assertEqual(again["state"], state)

    def test_server_enforces_dependency_without_mutating_snapshot(self):
        state = self.imported(); before = copy.deepcopy(state)
        with self.assertRaises(OnboardingError) as caught:
            self.call("update", state, task_id="harbor-demo:integration", changes={"status": "in_progress"}, revision=1)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(state, before)

    def test_saved_scope_and_projection_follow_the_same_rules(self):
        state = self.imported()
        state = self.call("update", state, task_id="harbor-demo:scope", changes={"status": "in_progress"}, revision=1)["state"]
        result = self.call("update", state, task_id="harbor-demo:scope", changes={"status": "done"}, revision=2)
        self.assertEqual(result["state"]["revision"], 3)
        self.assertEqual(result["result"]["tasks"][0]["blocked_reasons"], [])
        self.assertNotIn("blocked_reasons", result["state"]["tasks"][0])
        self.assertEqual(validate_snapshot(result["state"]), result["state"])

    def test_stale_and_boolean_revision_rejected(self):
        for revision in [0, True]:
            with self.subTest(revision=revision), self.assertRaises(OnboardingError) as caught:
                self.call("update", self.imported(), task_id="harbor-demo:scope", changes={"status": "in_progress"}, revision=revision)
            self.assertEqual(caught.exception.status, 409)

    def test_tampered_graph_and_criteria_rejected(self):
        for field, value in [("depends_on", []), ("acceptance_criteria", "bypass")]:
            state = self.imported(); state["tasks"][2][field] = value
            with self.subTest(field=field), self.assertRaises(OnboardingError): validate_snapshot(state)

    def test_incomplete_task_set_rejected(self):
        state = self.imported(); state["tasks"].pop()
        with self.assertRaises(OnboardingError): validate_snapshot(state)

    def test_malformed_history_and_state_not_reset(self):
        for state in [{}, {**empty_state(), "schema_version": True}, {**empty_state(), "activity": ["fake"]}]:
            with self.subTest(state=state), self.assertRaises(OnboardingError): validate_snapshot(state)

    def test_plan_export_roundtrips(self):
        state = self.imported()
        plans = [parse_plan(self.call("export", state, format=f)["result"]["text"], f) for f in ("json", "csv")]
        self.assertEqual(plans[0], plans[1]); self.assertEqual(plans[0], state["tasks"])

    def test_fixture_examples_cover_both_formats(self):
        for format in ("json", "csv"):
            example = self.call("example", format=format, invalid=True)["result"]
            check = self.call("preview", text=example["text"], format=format)["result"]
            self.assertTrue(any(x["field"] == "technical_owner" for x in check["issues"]))

    def test_unknown_operation_or_extra_fields_rejected(self):
        for op, data in [("delete", {}), ("read", {"extra": True}), ("import", {"revision": 0})]:
            with self.subTest(op=op), self.assertRaises(OnboardingError): self.call(op, **data)


class HostedHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PublicHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def send(self, body, headers=None, method="POST"):
        client = HTTPConnection(*self.server.server_address)
        try:
            client.request(method, "/api/onboarding", body, headers or {"Content-Type": "application/json"})
            response = client.getresponse(); result = json.loads(response.read())
            return response.status, result
        finally: client.close()

    def test_http_import_and_read(self):
        body = {"operation": "import", "state": empty_state(), "data": {"format": "json", "text": FIXTURE.read_text(), "revision": 0}}
        code, result = self.send(json.dumps(body))
        self.assertEqual(code, 200); self.assertEqual(len(result["state"]["tasks"]), 5)

    def test_malformed_and_repeated_json_are_400(self):
        for body in ['{', '{"operation":"read","operation":"import"}']:
            self.assertEqual(self.send(body)[0], 400)

    def test_wrong_content_type_and_large_body_rejected(self):
        self.assertEqual(self.send('{}', {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.send('{}', {"Content-Type": "application/json", "Content-Length": str(1024 * 1024 + 1)})[0], 413)

    def test_cross_origin_rejected(self):
        self.assertEqual(self.send('{}', {"Content-Type": "application/json", "Origin": "https://other.example"})[0], 403)

    def test_health_describes_browser_persistence(self):
        code, body = self.send(None, method="GET")
        self.assertEqual(code, 200); self.assertEqual(body["persistence"], "visitor-indexeddb")

    def test_wrong_method_rejected(self):
        self.assertEqual(self.send('{}', method="PATCH")[0], 405)
