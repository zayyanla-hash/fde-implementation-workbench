"""Human-readable rendering of run results for CLI / demo output."""

from __future__ import annotations

from .models import RunResult

_CHECK = {"paid": "PAID", "auto_approved": "APPROVED", "needs_approval": "ESCALATED", "rejected": "REJECTED", "held": "HELD"}


def render_run(result: RunResult) -> str:
    lines: list[str] = []
    lines.append(f"run {result.run_id}  scenario={result.scenario}")
    lines.append(f"invoices={result.summary.get('total_invoices')}  paid_total=${result.summary.get('total_paid_amount', 0):,.2f}")
    counts = result.summary.get("counts", {})
    lines.append("decisions: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    lines.append("-" * 72)
    for d in result.decisions:
        inv = d.invoice
        amt = f"${inv.amount:,.2f}" if inv.amount is not None else "?"
        tag = _CHECK.get(d.decision, d.decision)
        lines.append(f"[{tag:9}] {inv.invoice_id}  {inv.vendor_name}  {amt} {inv.currency}  PO={inv.po_number or '-'}  risk={d.risk_score}")
        lines.append(f"           -> {d.decision_reason}")
        for tc in d.tool_calls:
            state = f"{tc.tool} x{tc.attempts} [{tc.status}]"
            if tc.error and tc.status != "ok":
                state += f" :: {tc.error}"
            lines.append(f"           tool: {state}")
        for issue in d.issues:
            lines.append(f"           {issue.severity.upper()}: {issue.code} — {issue.message}")
    lines.append("-" * 72)
    pending = [d.invoice.invoice_id for d in result.decisions if d.decision == "needs_approval"]
    rejected = [d.invoice.invoice_id for d in result.decisions if d.decision == "rejected"]
    lines.append(f"approval queue: {', '.join(pending) if pending else '(empty)'}")
    lines.append(f"rejected: {', '.join(rejected) if rejected else '(none)'}")
    lines.append(f"audit events: {len(result.audit)}")
    return "\n".join(lines)


def render_pending(result: RunResult) -> str:
    pending = [d for d in result.decisions if d.decision == "needs_approval"]
    if not pending:
        return "approval queue is empty — nothing to review."
    lines = ["Pending approvals:"]
    for d in pending:
        lines.append(f"  {d.invoice.invoice_id}  {d.invoice.vendor_name}  risk={d.risk_score}  :: {d.decision_reason}")
    return "\n".join(lines)
