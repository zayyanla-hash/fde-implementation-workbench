"""Stage 1 — ingest: load messy customer inputs from fixtures.

Reads:
  fixtures/requirement.md          messy synthetic customer requirement
  fixtures/documents/*.txt         unstructured emails / memos / policy notes
  fixtures/invoices.csv            semi-structured invoice extract
  fixtures/vendors.json            mock vendor-master API backing store
  fixtures/rules.json              configurable business rules
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import BusinessRules, Document, InvoiceRow


@dataclass
class IngestedInputs:
    requirement_text: str
    documents: list[Document] = field(default_factory=list)
    invoice_rows: list[InvoiceRow] = field(default_factory=list)
    vendor_registry: dict[str, dict] = field(default_factory=dict)
    po_registry: dict[str, dict] = field(default_factory=dict)
    rules: BusinessRules = field(default_factory=BusinessRules)
    warnings: list[str] = field(default_factory=list)


def load_inputs(fixture_dir: Path, rules_path: Path | None = None) -> IngestedInputs:
    fixture_dir = Path(fixture_dir)
    req_path = fixture_dir / "requirement.md"
    requirement_text = req_path.read_text(encoding="utf-8") if req_path.exists() else ""

    documents: list[Document] = []
    docs_dir = fixture_dir / "documents"
    if docs_dir.exists():
        for path in sorted(docs_dir.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            kind = _classify_doc(path.stem, text)
            documents.append(Document(doc_id=path.stem, kind=kind, path=str(path), text=text))

    invoice_rows: list[InvoiceRow] = []
    csv_path = fixture_dir / "invoices.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as fh:
            for n, row in enumerate(csv.DictReader(fh), start=1):
                invoice_rows.append(
                    InvoiceRow(
                        row_no=n,
                        invoice_id=(row.get("invoice_id") or "").strip(),
                        vendor_name=(row.get("vendor_name") or "").strip(),
                        amount=(row.get("amount") or "").strip(),
                        currency=(row.get("currency") or "").strip(),
                        po_number=(row.get("po_number") or "").strip(),
                        invoice_date=(row.get("invoice_date") or "").strip(),
                        description=(row.get("description") or "").strip(),
                    )
                )

    vendor_registry: dict[str, dict] = {}
    po_registry: dict[str, dict] = {}
    vendors_path = fixture_dir / "vendors.json"
    if vendors_path.exists():
        payload = json.loads(vendors_path.read_text(encoding="utf-8"))
        vendor_registry = payload.get("vendors", {})
        po_registry = payload.get("purchase_orders", {})

    rules_file = Path(rules_path) if rules_path else fixture_dir / "rules.json"
    rules = BusinessRules()
    warnings: list[str] = []
    if rules_file.exists():
        try:
            rules = BusinessRules.from_dict(json.loads(rules_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            warnings.append(f"rules file {rules_file} invalid ({exc}); using defaults")

    if not invoice_rows:
        warnings.append("no invoice rows ingested — check fixtures/invoices.csv")
    if not documents:
        warnings.append("no unstructured documents found — check fixtures/documents/")

    return IngestedInputs(
        requirement_text=requirement_text,
        documents=documents,
        invoice_rows=invoice_rows,
        vendor_registry=vendor_registry,
        po_registry=po_registry,
        rules=rules,
        warnings=warnings,
    )


def _classify_doc(stem: str, text: str) -> str:
    s = (stem + " " + text[:400]).lower()
    if "policy" in s or "finance policy" in s:
        return "policy_note"
    if "contract" in s or "master service" in s:
        return "contract_memo"
    return "email"
