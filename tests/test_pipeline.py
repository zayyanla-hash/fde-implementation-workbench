"""Happy-path + integration tests for the vendor_payments_v1 scenario."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbench.approval import ApprovalGate  # noqa: E402
from workbench.ingest import load_inputs  # noqa: E402
from workbench.normalize import normalize  # noqa: E402
from workbench.scenarios import fixture_dir_for  # noqa: E402
from workbench.workflow import run_fixture_scenario  # noqa: E402

FIXTURES = fixture_dir_for("vendor_payments_v1")


class IngestNormalizeTest(unittest.TestCase):
    def test_ingest_loads_all_inputs(self):
        inputs = load_inputs(FIXTURES)
        self.assertEqual(len(inputs.invoice_rows), 6)
        self.assertEqual(len(inputs.documents), 3)
        self.assertIn("V-NORTHWIND", inputs.vendor_registry)
        self.assertEqual(inputs.rules.max_auto_approve_amount, 5000.0)

    def test_normalize_tolerates_messy_amounts(self):
        inputs = load_inputs(FIXTURES)
        invoices = {i.invoice_id: i for i in normalize(inputs)}
        self.assertEqual(invoices["INV-1001"].amount, 1200.0)
        self.assertEqual(invoices["INV-1001"].vendor_id, "V-NORTHWIND")
        # lowercase vendor + lowercase currency resolve cleanly
        self.assertEqual(invoices["INV-1005"].vendor_id, "V-NORTHWIND")
        self.assertEqual(invoices["INV-1005"].currency, "USD")
        # missing PO becomes None with a parse note
        self.assertIsNone(invoices["INV-1004"].po_number)
        self.assertTrue(invoices["INV-1004"].parse_notes)


class EndToEndTest(unittest.TestCase):
    def test_demo_run_decisions(self):
        result, _ = run_fixture_scenario(FIXTURES, flaky_vendor_fails={"V-HOOLI": 1})
        by_id = {d.invoice.invoice_id: d for d in result.decisions}
        # INV-1006 must recover via retry then get paid (auto-approved path)
        self.assertEqual(by_id["INV-1006"].decision, "paid")
        vendor_calls = [t for t in by_id["INV-1006"].tool_calls if t.tool == "vendor_lookup"]
        self.assertTrue(vendor_calls and vendor_calls[0].attempts == 2)
        # Blocked vendor rejected outright
        self.assertEqual(by_id["INV-1002"].decision, "rejected")
        # PO mismatch escalated
        self.assertEqual(by_id["INV-1003"].decision, "needs_approval")
        # EUR + missing PO escalated (uncertain case)
        self.assertEqual(by_id["INV-1004"].decision, "needs_approval")
        # audit trail covers every stage
        stages = {a.stage for a in result.audit}
        for expected in ("ingest", "normalize", "execute", "validate", "approval", "finalize"):
            self.assertIn(expected, stages)

    def test_approval_gate_resolves_escalation(self):
        result, engine = run_fixture_scenario(FIXTURES, flaky_vendor_fails={})
        gate = ApprovalGate(result.decisions)
        pending_ids = {d.invoice.invoice_id for d in gate.pending()}
        self.assertIn("INV-1004", pending_ids)
        d = gate.resolve("INV-1004", approve=True, approver="maria", reason="one-off solvent buy")
        engine.record_resolution(d)
        self.assertEqual(d.decision, "paid")
        self.assertEqual(d.approved_by, "maria")

    def test_approval_gate_rejects_double_resolution(self):
        result, _ = run_fixture_scenario(FIXTURES, flaky_vendor_fails={})
        gate = ApprovalGate(result.decisions)
        with self.assertRaises(ValueError):
            gate.resolve("INV-1001", approve=True, approver="maria")  # already paid, not pending


if __name__ == "__main__":
    unittest.main()
