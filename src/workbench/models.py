"""Domain types for the FDE implementation workbench.

All types are stdlib dataclasses so the pipeline stays deterministic,
serializable, and easy to extend with new scenarios.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Decision = Literal["auto_approved", "needs_approval", "rejected", "paid", "held"]
Severity = Literal["error", "warning", "info"]
ToolStatus = Literal["ok", "retrying", "failed", "skipped"]
StageName = Literal[
    "ingest", "normalize", "rules", "execute", "validate", "recover", "approval", "finalize"
]


@dataclass(frozen=True)
class Document:
    doc_id: str
    kind: str  # email | contract_memo | policy_note | ...
    path: str
    text: str


@dataclass(frozen=True)
class InvoiceRow:
    row_no: int
    invoice_id: str
    vendor_name: str
    amount: str
    currency: str
    po_number: str
    invoice_date: str
    description: str


@dataclass
class NormalizedInvoice:
    invoice_id: str
    vendor_name: str
    vendor_id: str | None
    amount: float | None
    currency: str
    po_number: str | None
    invoice_date: str
    description: str
    source_row: int
    parse_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BusinessRules:
    max_auto_approve_amount: float = 5000.0
    allowed_currencies: tuple[str, ...] = ("USD",)
    require_po_match: bool = True
    blocked_vendors: tuple[str, ...] = ()
    high_risk_score_threshold: int = 70
    allow_duplicate_amounts: bool = False
    auto_approve_low_risk_only: bool = True

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BusinessRules":
        return BusinessRules(
            max_auto_approve_amount=float(d.get("max_auto_approve_amount", 5000.0)),
            allowed_currencies=tuple(d.get("allowed_currencies", ["USD"])),
            require_po_match=bool(d.get("require_po_match", True)),
            blocked_vendors=tuple(d.get("blocked_vendors", [])),
            high_risk_score_threshold=int(d.get("high_risk_score_threshold", 70)),
            allow_duplicate_amounts=bool(d.get("allow_duplicate_amounts", False)),
            auto_approve_low_risk_only=bool(d.get("auto_approve_low_risk_only", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_auto_approve_amount": self.max_auto_approve_amount,
            "allowed_currencies": list(self.allowed_currencies),
            "require_po_match": self.require_po_match,
            "blocked_vendors": list(self.blocked_vendors),
            "high_risk_score_threshold": self.high_risk_score_threshold,
            "allow_duplicate_amounts": self.allow_duplicate_amounts,
            "auto_approve_low_risk_only": self.auto_approve_low_risk_only,
        }


@dataclass
class ToolCall:
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    status: ToolStatus = "ok"
    attempts: int = 1
    latency_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    invoice_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvoiceDecision:
    invoice: NormalizedInvoice
    tool_calls: list[ToolCall] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    risk_score: int = 0
    decision: Decision = "needs_approval"
    decision_reason: str = ""
    approved_by: str | None = None

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice": self.invoice.to_dict(),
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "issues": [i.to_dict() for i in self.issues],
            "risk_score": self.risk_score,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "approved_by": self.approved_by,
        }


@dataclass
class AuditEvent:
    seq: int
    run_id: str
    stage: str
    event: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    run_id: str
    scenario: str
    decisions: list[InvoiceDecision] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "summary": self.summary,
            "decisions": [d.to_dict() for d in self.decisions],
            "audit": [a.to_dict() for a in self.audit],
        }
