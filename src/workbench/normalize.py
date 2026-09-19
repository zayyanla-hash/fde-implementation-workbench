"""Stage 2 — normalize: messy rows -> typed configuration.

Deterministic parsing with no ML dependency:
- trims / case-folds vendor names, resolves vendor_id via alias map
- parses amounts tolerantly ("$4,200.00" -> 4200.0), records parse notes
- normalizes currency to upper-case, empties PO to None
- flags rows that need human attention instead of raising
"""

from __future__ import annotations

import re

from .ingest import IngestedInputs
from .models import NormalizedInvoice

_AMOUNT_RE = re.compile(r"[^0-9.\-]")


def normalize(inputs: IngestedInputs) -> list[NormalizedInvoice]:
    alias_map = _build_alias_map(inputs.vendor_registry)
    out: list[NormalizedInvoice] = []
    for row in inputs.invoice_rows:
        notes: list[str] = []
        key = row.vendor_name.strip().lower()
        vendor_id = alias_map.get(key)
        if vendor_id is None and row.vendor_name:
            notes.append(f"vendor '{row.vendor_name}' not in registry; left unresolved")

        amount, amount_note = _parse_amount(row.amount)
        if amount_note:
            notes.append(amount_note)

        currency = (row.currency or "").strip().upper()
        if row.currency and row.currency.strip() != currency:
            notes.append(f"currency normalized '{row.currency}' -> '{currency}'")
        if not currency:
            notes.append("missing currency; flagged for validation")

        po = (row.po_number or "").strip() or None
        if po is None:
            notes.append("missing PO number")

        out.append(
            NormalizedInvoice(
                invoice_id=row.invoice_id or f"ROW-{row.row_no}",
                vendor_name=row.vendor_name,
                vendor_id=vendor_id,
                amount=amount,
                currency=currency,
                po_number=po,
                invoice_date=row.invoice_date.strip(),
                description=row.description.strip(),
                source_row=row.row_no,
                parse_notes=notes,
            )
        )
    return out


def _build_alias_map(vendor_registry: dict[str, dict]) -> dict[str, str]:
    alias: dict[str, str] = {}
    for vid, rec in vendor_registry.items():
        names = [rec.get("name", "")] + list(rec.get("aliases", []))
        for name in names:
            if name:
                alias[name.strip().lower()] = vid
    return alias


def _parse_amount(raw: str) -> tuple[float | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, "missing amount; flagged for validation"
    cleaned = _AMOUNT_RE.sub("", text)
    try:
        value = float(cleaned)
    except ValueError:
        return None, f"unparseable amount '{raw}'; flagged for validation"
    if text != cleaned and text != f"{value:.2f}":
        return value, f"amount normalized '{raw}' -> {value:.2f}"
    return value, None
