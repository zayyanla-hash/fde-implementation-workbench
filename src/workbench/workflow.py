"""Workflow engine — orchestrates the full pipeline.

ingest -> normalize -> execute (tool calls w/ bounded retry)
       -> validate+policy -> risk -> decide -> approval queue -> finalize

Every transition emits an audit event. The engine is scenario-agnostic:
scenario modules supply fixture dirs and tweak knobs; stages stay shared.
"""

from __future__ import annotations

import itertools
import uuid
from pathlib import Path
from typing import Any

from .approval import ApprovalGate
from .audit import AuditLog
from .ingest import IngestedInputs, load_inputs
from .models import InvoiceDecision, RunResult, ValidationIssue
from .normalize import normalize
from .retry import call_with_retry
from .tools import PaymentScheduleTool, POMatchTool, RiskScoreTool, VendorLookupTool
from .validate import apply_policy, decide, validate_schema


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class WorkflowEngine:
    def __init__(
        self,
        inputs: IngestedInputs,
        run_id: str | None = None,
        audit_path: Path | None = None,
        max_tool_attempts: int = 3,
        flaky_vendor_fails: dict[str, int] | None = None,
    ):
        self.inputs = inputs
        self.run_id = run_id or new_run_id()
        self.audit = AuditLog(self.run_id, audit_path)
        self.max_tool_attempts = max_tool_attempts
        self.vendor_tool = VendorLookupTool(inputs.vendor_registry, fail_plan=flaky_vendor_fails)
        self.po_tool = POMatchTool(inputs.po_registry)
        self.risk_tool = RiskScoreTool(blocked_vendors=inputs.rules.blocked_vendors)
        self.pay_tool = PaymentScheduleTool()

    def run(self, auto_pay_approved: bool = True) -> RunResult:
        rules = self.inputs.rules
        self.audit.record("ingest", "inputs_loaded", docs=len(self.inputs.documents),
                          invoices=len(self.inputs.invoice_rows), warnings=self.inputs.warnings)

        invoices = normalize(self.inputs)
        self.audit.record("normalize", "invoices_normalized", count=len(invoices))

        decisions = [InvoiceDecision(invoice=inv) for inv in invoices]

        # --- execute: structured tool calls with bounded retry ---
        po_results: dict[str, bool] = {}
        for d in decisions:
            inv = d.invoice
            d.issues.extend(validate_schema(inv))

            # vendor_lookup (retryable)
            if inv.vendor_id:
                payload = {"vendor_id": inv.vendor_id, "vendor_name": inv.vendor_name}
                tc = call_with_retry("vendor_lookup", lambda p=payload: self.vendor_tool.call(p),
                                     payload, self.max_tool_attempts)
                d.tool_calls.append(tc)
                vendor_status = tc.output.get("status", "unknown") if tc.status != "failed" else "lookup_failed"
                if tc.status == "failed":
                    d.issues.append(ValidationIssue("E_VENDOR_LOOKUP", "error",
                                                   f"vendor lookup failed: {tc.error}", inv.invoice_id))
            else:
                vendor_status = "unknown"
                d.tool_calls.append(_skipped("vendor_lookup", {"reason": "no vendor_id"}))

            # po_match (deterministic, no retry needed)
            if inv.po_number and inv.amount is not None:
                payload = {"po_number": inv.po_number, "amount": inv.amount}
                try:
                    out = self.po_tool.call(payload)
                    d.tool_calls.append(_ok("po_match", payload, out))
                    po_results[inv.invoice_id] = bool(out.get("matched"))
                except Exception as exc:  # defensive; tool is total but keep pipeline alive
                    d.tool_calls.append(_failed("po_match", payload, str(exc)))
                    po_results[inv.invoice_id] = False
            else:
                d.tool_calls.append(_skipped("po_match", {"reason": "missing po/amount"}))
                po_results[inv.invoice_id] = False

            self.audit.record("execute", "tools_called", invoice_id=inv.invoice_id,
                              tools=[t.tool for t in d.tool_calls])

        # --- validate + policy ---
        apply_policy(decisions, rules, po_results)
        dup_flags = {d.invoice.invoice_id: any(i.code == "W_DUPLICATE" for i in d.issues) for d in decisions}
        for d in decisions:
            for note in d.invoice.parse_notes:
                d.issues.append(ValidationIssue("W_PARSE_NOTE", "warning", note, d.invoice.invoice_id))
            # risk score
            vendor_status = _vendor_status_of(d)
            risk_out = self.risk_tool.call({
                "amount": d.invoice.amount or 0,
                "vendor_id": d.invoice.vendor_id,
                "vendor_status": vendor_status,
                "po_matched": po_results.get(d.invoice.invoice_id, False),
                "duplicate": dup_flags.get(d.invoice.invoice_id, False),
                "currency": d.invoice.currency,
            })
            d.risk_score = int(risk_out["score"])
            d.tool_calls.append(_ok("risk_score", {"invoice_id": d.invoice.invoice_id}, risk_out))
            decide(d, rules)
            self.audit.record("validate", "invoice_decided", invoice_id=d.invoice.invoice_id,
                              decision=d.decision, risk=d.risk_score,
                              errors=[i.code for i in d.errors])

        gate = ApprovalGate(decisions)
        pending = gate.pending()
        self.audit.record("approval", "checkpoint_opened", pending=[d.invoice.invoice_id for d in pending])

        # finalize: schedule payments for auto-approved
        paid, held = [], []
        for d in decisions:
            if d.decision == "auto_approved" and auto_pay_approved:
                payload = {"invoice_id": d.invoice.invoice_id, "amount": d.invoice.amount or 0}
                tc = call_with_retry("payment_schedule",
                                     lambda p=payload: self.pay_tool.call(p), payload, self.max_tool_attempts)
                d.tool_calls.append(tc)
                if tc.status == "failed":
                    d.decision = "held"
                    d.decision_reason += f" | payment failed: {tc.error}"
                    held.append(d.invoice.invoice_id)
                else:
                    d.decision = "paid"
                    d.decision_reason += f" | {tc.output.get('payment_ref')}"
                    paid.append(d.invoice.invoice_id)
        self.audit.record("finalize", "payments_scheduled", paid=paid, held=held)

        summary = _summarize(decisions)
        self.audit.record("finalize", "run_completed", **summary)
        return RunResult(run_id=self.run_id, scenario="vendor_payments_v1",
                         decisions=decisions, audit=self.audit.events, summary=summary)

    # Exposed for the HTTP/CLI approval path: re-emit audit after manual resolution.
    def record_resolution(self, decision: InvoiceDecision) -> None:
        self.audit.record("approval", "human_resolved", invoice_id=decision.invoice.invoice_id,
                          decision=decision.decision, by=decision.approved_by,
                          reason=decision.decision_reason)


def run_fixture_scenario(
    fixture_dir: Path,
    rules_path: Path | None = None,
    run_id: str | None = None,
    audit_path: Path | None = None,
    flaky_vendor_fails: dict[str, int] | None = None,
    max_tool_attempts: int = 3,
) -> tuple[RunResult, WorkflowEngine]:
    inputs = load_inputs(fixture_dir, rules_path)
    engine = WorkflowEngine(inputs, run_id=run_id, audit_path=audit_path,
                            max_tool_attempts=max_tool_attempts,
                            flaky_vendor_fails=flaky_vendor_fails)
    return engine.run(), engine


def _vendor_status_of(d) -> str:
    for tc in d.tool_calls:
        if tc.tool == "vendor_lookup" and tc.status != "failed" and tc.output.get("status"):
            return str(tc.output["status"])
    if d.invoice.vendor_id is None:
        return "unknown"
    return "unknown"


def _summarize(decisions: list[InvoiceDecision]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.decision] = counts.get(d.decision, 0) + 1
    total = sum((d.invoice.amount or 0) for d in decisions if d.decision == "paid")
    return {"counts": counts, "total_invoices": len(decisions), "total_paid_amount": round(total, 2)}


def _ok(tool: str, payload: dict[str, Any], output: dict[str, Any]):
    from .models import ToolCall as TC
    return TC(tool=tool, input=payload, output=output, status="ok", attempts=1, latency_ms=7)


def _skipped(tool: str, output: dict[str, Any]):
    from .models import ToolCall as TC
    return TC(tool=tool, input={}, output=output, status="skipped", attempts=0, latency_ms=0)


def _failed(tool: str, payload: dict[str, Any], error: str):
    from .models import ToolCall as TC
    return TC(tool=tool, input=payload, output={}, status="failed", attempts=1, latency_ms=7, error=error)


# Keep itertools import purposeful for future fan-out parallelism.
_ = itertools.chain
