"""Validation + configurable business rules.

Validation is split in two layers:
1. schema validation — is the normalized invoice well-formed?
2. policy evaluation — does it satisfy the customer's business rules?

Both produce ValidationIssue lists; errors block auto-approval,
warnings route to the human checkpoint with context.
"""

from __future__ import annotations

from collections import Counter

from .models import BusinessRules, InvoiceDecision, NormalizedInvoice, ValidationIssue


def validate_schema(inv: NormalizedInvoice) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if inv.amount is None:
        issues.append(ValidationIssue("E_AMOUNT_MISSING", "error", "amount is missing/unparseable", inv.invoice_id))
    elif inv.amount <= 0:
        issues.append(ValidationIssue("E_AMOUNT_NONPOSITIVE", "error", f"amount {inv.amount} must be > 0", inv.invoice_id))
    if not inv.currency:
        issues.append(ValidationIssue("E_CURRENCY_MISSING", "error", "currency is missing", inv.invoice_id))
    if inv.vendor_id is None:
        issues.append(ValidationIssue("E_VENDOR_UNKNOWN", "error", f"vendor '{inv.vendor_name}' not in registry", inv.invoice_id))
    if not inv.po_number:
        issues.append(ValidationIssue("E_PO_MISSING", "error", "PO number is missing", inv.invoice_id))
    if not inv.invoice_date:
        issues.append(ValidationIssue("W_DATE_MISSING", "warning", "invoice date missing; using processing date", inv.invoice_id))
    return issues


def apply_policy(
    decisions: list[InvoiceDecision],
    rules: BusinessRules,
    po_results: dict[str, bool] | None = None,
) -> None:
    """Mutates decisions in place with policy issues (duplicates, currency, blocklist)."""
    seen_amounts: Counter[tuple[str, float]] = Counter()
    for d in decisions:
        if d.invoice.vendor_id and d.invoice.amount is not None:
            seen_amounts[(d.invoice.vendor_id, d.invoice.amount)] += 1

    for d in decisions:
        inv = d.invoice
        if inv.currency and inv.currency not in rules.allowed_currencies:
            d.issues.append(
                ValidationIssue(
                    "E_CURRENCY_BLOCKED",
                    "error",
                    f"currency {inv.currency} not in {list(rules.allowed_currencies)}",
                    inv.invoice_id,
                )
            )
        if inv.vendor_id in rules.blocked_vendors:
            d.issues.append(
                ValidationIssue("E_VENDOR_BLOCKED", "error", f"vendor {inv.vendor_id} is blocklisted", inv.invoice_id)
            )
        if not rules.allow_duplicate_amounts and inv.vendor_id and inv.amount is not None:
            if seen_amounts[(inv.vendor_id, inv.amount)] > 1:
                d.issues.append(
                    ValidationIssue(
                        "W_DUPLICATE",
                        "warning",
                        f"duplicate amount {inv.amount:.2f} for vendor {inv.vendor_id}",
                        inv.invoice_id,
                    )
                )
        if rules.require_po_match and po_results is not None and inv.invoice_id in po_results:
            if not po_results[inv.invoice_id] and not any(i.code == "E_PO_MISSING" for i in d.issues):
                d.issues.append(
                    ValidationIssue("E_PO_MISMATCH", "error", "PO match failed (see po_match tool output)", inv.invoice_id)
                )


def decide(decision: InvoiceDecision, rules: BusinessRules) -> None:
    """Approval policy: errors -> reject or escalate; clean + small + low-risk -> auto-approve."""
    errors = decision.errors
    amount = decision.invoice.amount or 0.0
    if any(i.code in ("E_VENDOR_BLOCKED",) for i in errors):
        decision.decision = "rejected"
        decision.decision_reason = "blocked vendor — rejected without approval option"
        return
    if errors:
        decision.decision = "needs_approval"
        decision.decision_reason = f"{len(errors)} error(s) require human review: " + ", ".join(i.code for i in errors)
        return
    if amount > rules.max_auto_approve_amount:
        decision.decision = "needs_approval"
        decision.decision_reason = (
            f"amount {amount:.2f} exceeds auto-approve limit {rules.max_auto_approve_amount:.2f}"
        )
        return
    if rules.auto_approve_low_risk_only and decision.risk_score >= rules.high_risk_score_threshold:
        decision.decision = "needs_approval"
        decision.decision_reason = f"risk score {decision.risk_score} >= threshold {rules.high_risk_score_threshold}"
        return
    if decision.risk_score >= rules.high_risk_score_threshold:
        decision.decision = "needs_approval"
        decision.decision_reason = f"high risk score {decision.risk_score}"
        return
    decision.decision = "auto_approved"
    decision.decision_reason = "clean, within limits, low risk"
