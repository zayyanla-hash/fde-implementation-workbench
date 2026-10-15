"""HTTP API surface tests (stdlib server, ephemeral port)."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbench.server import ENGINES, RUNS, Handler  # noqa: E402


def _request(method: str, url: str, payload: dict | None = None):
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode())


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_health_and_run_and_approve(self):
        status, body = _request("GET", self.url("/health"))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        status, run = _request("POST", self.url("/runs"), {"scenario": "vendor_payments_v1"})
        self.assertEqual(status, 201)
        run_id = run["run_id"]
        self.assertEqual(len(run["decisions"]), 6)

        pending = [d for d in run["decisions"] if d["decision"] == "needs_approval"]
        self.assertTrue(pending, "demo must produce at least one escalation")
        target = pending[0]["invoice"]["invoice_id"]

        status, resolved = _request("POST", self.url(f"/runs/{run_id}/approve"),
                                    {"invoice_id": target, "approve": True,
                                     "approver": "maria", "reason": "api test"})
        self.assertEqual(status, 200)
        self.assertEqual(resolved["decision"]["decision"], "paid")

        status, audit = _request("GET", self.url(f"/runs/{run_id}/audit"))
        self.assertEqual(status, 200)
        self.assertTrue(len(audit["audit"]) > 10)

    def test_unknown_scenario_rejected(self):
        try:
            _request("POST", self.url("/runs"), {"scenario": "nope"})
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.read()
            exc.close()
        else:
            self.fail("expected HTTP 400")


if __name__ == "__main__":
    unittest.main()
