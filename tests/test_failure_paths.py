"""Failure / retry / escalation-path tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbench.models import BusinessRules, InvoiceDecision, NormalizedInvoice  # noqa: E402
from workbench.retry import call_with_retry  # noqa: E402
from workbench.scenarios import fixture_dir_for  # noqa: E402
from workbench.tools import FatalToolError, ToolError  # noqa: E402
from workbench.validate import apply_policy, decide, validate_schema  # noqa: E402
from workbench.workflow import run_fixture_scenario  # noqa: E402

FIXTURES = fixture_dir_for("vendor_payments_v1")


class RetryTest(unittest.TestCase):
    def test_recovers_after_transient_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ToolError("timeout")
            return {"ok": True}

        tc = call_with_retry("vendor_lookup", flaky, {"vendor_id": "V-X"}, max_attempts=3)
        self.assertEqual(tc.status, "retrying")
        self.assertEqual(tc.attempts, 3)

    def test_exhausts_bounded_attempts(self):
        def always_fails():
            raise ToolError("down")

        tc = call_with_retry("vendor_lookup", always_fails, {}, max_attempts=2)
        self.assertEqual(tc.status, "failed")
        self.assertEqual(tc.attempts, 2)
        self.assertIn("exhausted 2 attempts", tc.error or "")

    def test_fatal_error_does_not_retry(self):
        calls = {"n": 0}

        def fatal():
            calls["n"] += 1
            raise FatalToolError("bad request")

        tc = call_with_retry("payment_schedule", fatal, {}, max_attempts=3)
        self.assertEqual(tc.status, "failed")
        self.assertEqual(tc.attempts, 1)
        self.assertEqual(calls["n"], 1)

    def test_retry_exhaustion_surfaces_as_error_issue(self):
        # V-HOOLI fails more times than allowed -> E_VENDOR_LOOKUP + escalation
        result, _ = run_fixture_scenario(FIXTURES, flaky_vendor_fails={"V-HOOLI": 99}, max_tool_attempts=2)
        by_id = {d.invoice.invoice_id: d for d in result.decisions}
        d = by_id["INV-1006"]
        self.assertEqual(d.decision, "needs_approval")
        self.assertTrue(any(i.code == "E_VENDOR_LOOKUP" for i in d.errors))


class ValidationTest(unittest.TestCase):
    def _inv(self, **kw) -> NormalizedInvoice:
        base = dict(invoice_id="T-1", vendor_name="V", vendor_id="V-NORTHWIND",
                    amount=100.0, currency="USD", po_number="PO-501",
                    invoice_date="2026-07-01", description="t", source_row=1)
        base.update(kw)
        return NormalizedInvoice(**base)  # type: ignore[arg-type]

    def test_schema_flags_unknown_vendor_and_bad_amount(self):
        issues = validate_schema(self._inv(vendor_id=None, amount=None))
        codes = {i.code for i in issues}
        self.assertIn("E_VENDOR_UNKNOWN", codes)
        self.assertIn("E_AMOUNT_MISSING", codes)

    def test_blocked_vendor_rejected(self):
        rules = BusinessRules(blocked_vendors=("V-GLOBEX",))
        d = InvoiceDecision(invoice=self._inv(invoice_id="T-2", vendor_id="V-GLOBEX"))
        apply_policy([d], rules, po_results={"T-2": True})
        decide(d, rules)
        self.assertEqual(d.decision, "rejected")

    def test_over_limit_escalated_not_rejected(self):
        rules = BusinessRules(max_auto_approve_amount=5000.0)
        d = InvoiceDecision(invoice=self._inv(amount=18000.0))
        decide(d, rules)
        self.assertEqual(d.decision, "needs_approval")

    def test_configurable_rules_change_outcome(self):
        # Same invoice auto-approves under a raised limit
        d = InvoiceDecision(invoice=self._inv(amount=18000.0))
        decide(d, BusinessRules(max_auto_approve_amount=50000.0))
        self.assertEqual(d.decision, "auto_approved")


if __name__ == "__main__":
    unittest.main()
