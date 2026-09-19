"""Tool adapters — structured, mock-friendly external calls.

Each tool implements the same tiny interface (name + call(payload))
so new integrations slot in without touching the workflow engine.
All tools are deterministic and offline; flakiness is injected
explicitly via `fail_plan` for retry-path testing.
"""

from __future__ import annotations

from typing import Any, Protocol


class ToolError(RuntimeError):
    """Recoverable tool failure (eligible for bounded retry)."""


class FatalToolError(RuntimeError):
    """Non-recoverable tool failure (no retry)."""


class Tool(Protocol):
    name: str

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class VendorLookupTool:
    """Mock vendor-master API: resolves vendor_id -> record."""

    name = "vendor_lookup"

    def __init__(self, registry: dict[str, dict], fail_plan: dict[str, int] | None = None):
        self.registry = registry
        self.fail_plan = dict(fail_plan or {})
        self.calls: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        vendor_id = payload.get("vendor_id")
        self.calls.append(dict(payload))
        remaining = self.fail_plan.get(str(vendor_id), 0)
        if remaining > 0:
            self.fail_plan[str(vendor_id)] = remaining - 1
            raise ToolError(f"transient vendor-master timeout for {vendor_id}")
        rec = self.registry.get(str(vendor_id))
        if rec is None:
            raise FatalToolError(f"unknown vendor_id {vendor_id}")
        return {"vendor_id": vendor_id, "status": rec.get("status", "active"), "record": rec}


class POMatchTool:
    """Mock PO-matching service: checks PO exists, is open, amount within tolerance."""

    name = "po_match"
    TOLERANCE = 0.02  # 2%

    def __init__(self, po_registry: dict[str, dict]):
        self.po_registry = po_registry

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        po = self.po_registry.get(str(payload.get("po_number") or ""))
        if po is None:
            return {"matched": False, "reason": "PO not found"}
        if po.get("status") != "open":
            return {"matched": False, "reason": f"PO status is {po.get('status')}"}
        try:
            po_total = float(po.get("total", 0))
            inv_amount = float(payload.get("amount") or 0)
        except (TypeError, ValueError):
            return {"matched": False, "reason": "uncomparable amounts"}
        if po_total <= 0:
            return {"matched": False, "reason": "PO has no funds"}
        drift = abs(inv_amount - po_total) / po_total
        if drift <= self.TOLERANCE:
            return {"matched": True, "po_total": po_total, "drift": round(drift, 4)}
        return {
            "matched": False,
            "reason": f"amount drift {drift:.1%} exceeds 2% tolerance",
            "po_total": po_total,
            "drift": round(drift, 4),
        }


class RiskScoreTool:
    """Deterministic rules-based risk scorer (stands in for an ML/fraud model)."""

    name = "risk_score"

    def __init__(self, blocked_vendors: tuple[str, ...] = (), high_risk_countries: tuple[str, ...] = ()):
        self.blocked = set(blocked_vendors)
        self.high_risk_countries = set(high_risk_countries)

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        score = 5  # base
        reasons: list[str] = []
        amount = float(payload.get("amount") or 0)
        if amount >= 20000:
            score += 45
            reasons.append("amount >= 20k")
        elif amount >= 8000:
            score += 25
            reasons.append("amount >= 8k")
        if payload.get("vendor_status") != "active":
            score += 30
            reasons.append("vendor not active")
        if payload.get("vendor_id") in self.blocked:
            score += 40
            reasons.append("vendor on blocklist")
        if not payload.get("po_matched"):
            score += 20
            reasons.append("no PO match")
        if payload.get("duplicate"):
            score += 25
            reasons.append("possible duplicate")
        if payload.get("currency") not in ("USD",):
            score += 10
            reasons.append("non-standard currency")
        score = min(100, score)
        band = "low" if score < 40 else ("medium" if score < 70 else "high")
        return {"score": score, "band": band, "reasons": reasons}


class PaymentScheduleTool:
    """Mock payment rail: schedules payment unless amount exceeds rail limit."""

    name = "payment_schedule"
    RAIL_LIMIT = 50_000.0

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        amount = float(payload.get("amount") or 0)
        if amount <= 0:
            raise FatalToolError("cannot schedule non-positive payment")
        if amount > self.RAIL_LIMIT:
            raise FatalToolError(f"amount {amount} exceeds rail limit {self.RAIL_LIMIT}")
        inv = payload.get("invoice_id", "UNKNOWN")
        return {"scheduled": True, "payment_ref": f"PAY-{inv}", "rail": "ach_mock"}
