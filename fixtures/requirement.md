# Acme Industrial — messy AP requirement (synthetic)

From: Maria Santos <maria.santos@acme-industrial.example>
To: Forward-Deployed Engineering <fde@workbench.example>
Subject: PLEASE HELP — invoices piling up, audit in 3 weeks!!!

Hi team,

Sorry for the messy thread — pulling together what I could find before our
Q3 audit. We get ~200 supplier invoices a month and right now it's all me
and a spreadsheet. I need something that:

1. Reads whatever lands in ap-inbox@ (PDFs, forwarded emails, scans — I saved
   a few as .txt for this pilot), plus our invoice export CSV.
2. Figures out the vendor, amount, currency, PO number even when the CSV is
   sloppy (accounting sometimes types "$4,200.00" or leaves cells blank!).
3. Checks our rules: we only auto-pay under $5,000, USD only, must match an
   OPEN purchase order within 2%, never pay BLOCKED vendors, no duplicates.
4. Calls our vendor master + PO system (APIs are flaky on Mondays — retry!).
5. Flags anything weird for me to approve — DO NOT auto-pay big/risky stuff.
   Especially anything from "Globex" — procurement flagged them last month.
6. Keeps a full audit log because the auditors WILL ask.

Examples of the ugly reality (all synthetic pilot data):

- INV-1001 from "Northwind Traders" for $1,200 against PO-501 — should be boring/approved.
- INV-1002 from "Globex Corp" for $18,500 — procurement says do NOT pay them right now.
- INV-1003 from "Initech LLC" for $4,800 but the PO doesn't match (wrong amount?).
- INV-1004 from "Umbrella Supply" with NO PO and EUR currency — unclear, escalate!
- INV-1005 is a duplicate-looking $1,200 from "northwind traders" (lowercase!) — same amount, same vendor.
- INV-1006 from "Hooli Industrial" for $2,300 — vendor-master API times out the first time (flaky!), must retry then approve.

If INV-1006 fails outright that's a bug — your pipeline must retry and recover.

— Maria
