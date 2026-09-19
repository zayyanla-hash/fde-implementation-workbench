"""Human approval checkpoint.

The gate never auto-pays escalated items. `pending()` lists invoices in
`needs_approval`; `resolve()` records an explicit approve/reject with an
approver identity and reason, appended to the audit trail by the caller.
"""

from __future__ import annotations

from .models import InvoiceDecision


class ApprovalGate:
    def __init__(self, decisions: list[InvoiceDecision]):
        self._decisions = {d.invoice.invoice_id: d for d in decisions}

    def pending(self) -> list[InvoiceDecision]:
        return [d for d in self._decisions.values() if d.decision == "needs_approval"]

    def resolve(self, invoice_id: str, approve: bool, approver: str, reason: str = "") -> InvoiceDecision:
        if invoice_id not in self._decisions:
            raise KeyError(f"unknown invoice {invoice_id}")
        d = self._decisions[invoice_id]
        if d.decision != "needs_approval":
            raise ValueError(f"invoice {invoice_id} is {d.decision}; only needs_approval can be resolved")
        if not approver.strip():
            raise ValueError("approver identity is required")
        d.decision = "paid" if approve else "held"
        d.approved_by = approver
        d.decision_reason = (f"{'approved' if approve else 'rejected'} by {approver}" + (f": {reason}" if reason else ""))
        return d
