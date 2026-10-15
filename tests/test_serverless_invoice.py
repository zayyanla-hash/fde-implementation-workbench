"""Regression: Vercel imports handlers as modules from the repository root."""
import importlib
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer


class ServerlessInvoiceTests(unittest.TestCase):
    def test_all_handlers_import_from_repository_root(self):
        for name in ("run", "health", "approve", "onboarding"):
            self.assertTrue(hasattr(importlib.import_module("api." + name), "handler"))

    def test_invoice_function_serves_fixture_pipeline(self):
        handler = importlib.import_module("api.run").handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client = HTTPConnection(*server.server_address)
        try:
            client.request("POST", "/api/run", '{}', {"Content-Type": "application/json"})
            response = client.getresponse(); result = json.loads(response.read())
            self.assertEqual(response.status, 201)
            self.assertTrue(result["decisions"])
            self.assertIn("summary", result)
        finally:
            client.close(); server.shutdown(); server.server_close(); thread.join()
