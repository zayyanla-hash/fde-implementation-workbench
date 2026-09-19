# Demo guide — vendor_payments_v1

## Story (all data synthetic)

Acme Industrial's AP lead Maria is drowning in ~200 supplier invoices/month
with a Q3 audit in 3 weeks. Her requirement email (`fixtures/requirement.md`)
plus 3 inbox documents, a sloppy 6-row CSV extract, and flaky vendor-master/PO
APIs must become **paid / escalated / rejected** decisions with a full audit log.

The 6 invoices each exercise a different path:

| Invoice | Shape | Expected outcome |
|---|---|---|
| INV-1001 Northwind $1,200 + PO-501 | clean | **paid** (auto-approved; duplicate warning noted) |
| INV-1002 Globex $18,500 | blocked vendor, under procurement review | **rejected** |
| INV-1003 Initech $4,800 vs PO $4,100 | 17% PO drift > 2% tolerance | **escalated** (`E_PO_MISMATCH`) |
| INV-1004 Umbrella €3,200, no PO | uncertain case: wrong currency + missing PO | **escalated** (`E_CURRENCY_BLOCKED`, `E_PO_MISSING`) |
| INV-1005 northwind $1,200 | messy casing, duplicate of INV-1001 | **paid** with `W_DUPLICATE` warning |
| INV-1006 Hooli $2,300 | vendor API times out first call | **paid** after 1 bounded retry |

## Commands

```bash
PYTHONPATH=src python3 -m workbench demo            # full narrated demo
PYTHONPATH=src python3 -m workbench run --scenario vendor_payments_v1
PYTHONPATH=src python3 -m workbench run --scenario vendor_payments_v1 --json  # machine-readable
PYTHONPATH=src python3 -m workbench list-scenarios
./scripts/test.sh                                    # build + full test suite
./scripts/serve.sh                                   # local API on :8765
```

## HTTP API walkthrough

```bash
# 1. health
curl -s localhost:8765/health
# 2. run the pipeline
curl -s -X POST localhost:8765/runs -d '{"scenario":"vendor_payments_v1"}' | python3 -m json.tool | head -40
# 3. inspect audit trail
curl -s localhost:8765/runs/<run_id>/audit | python3 -m json.tool | head -30
# 4. human approves the uncertain case
curl -s -X POST localhost:8765/runs/<run_id>/approve \
  -d '{"invoice_id":"INV-1004","approve":true,"approver":"maria","reason":"one-off solvent buy"}'
```

## Try the failure knobs

```bash
WORKBENCH_FLAKY_VENDOR_FAILS=0 PYTHONPATH=src python3 -m workbench demo   # no failure injection
WORKBENCH_FLAKY_VENDOR_FAILS=99 PYTHONPATH=src python3 -m workbench demo  # retry exhaustion -> INV-1006 escalates
```

Edit `fixtures/rules.json` (e.g. raise `max_auto_approve_amount`, add a
blocklist entry) and re-run `demo` to see configurable policy change outcomes
with zero code changes.
