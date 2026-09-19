# Architecture — fde-implementation-workbench

## Goal

Show, in one runnable repo, how a Forward-Deployed / implementation engineer
turns a messy customer ask into a **reliable, configurable, auditable workflow**
— without depending on live model APIs or customer credentials.

## Pipeline

```
requirement.md + documents/*.txt + invoices.csv + vendors.json + rules.json
        │ ingest            (workbench/ingest.py)
        ▼
NormalizedInvoice[]         (workbench/normalize.py, models.py)
        │ execute           (workbench/workflow.py + tools.py + retry.py)
        │   vendor_lookup (retryable) → po_match → risk_score
        ▼
ValidationIssue[] + policy  (workbench/validate.py)
        │ decide            approval policy: auto_approved / needs_approval / rejected
        ▼
ApprovalGate                (workbench/approval.py) — humans resolve escalations
        │ finalize          payment_schedule for auto-approved
        ▼
RunResult + JSONL audit     (workbench/audit.py)
```

Every stage transition emits an `AuditEvent(run_id, stage, event, detail)`,
kept in memory and appended to `var/audit/<run>.jsonl`.

## Module map

| File | Responsibility |
|---|---|
| `models.py` | Frozen/typed domain: `Document`, `InvoiceRow`, `NormalizedInvoice`, `BusinessRules`, `ToolCall`, `ValidationIssue`, `InvoiceDecision`, `RunResult`, `AuditEvent` |
| `ingest.py` | Loads fixtures; never raises on messy data — records warnings |
| `normalize.py` | Tolerant parsing (`"$4,200.00"` → `4200.0`, case-folded vendor aliases); problems become parse notes, not exceptions |
| `tools.py` | `Tool` protocol + 4 mock adapters (`vendor_lookup`, `po_match`, `risk_score`, `payment_schedule`). `ToolError` = retryable, `FatalToolError` = not |
| `retry.py` | `call_with_retry()` — bounded attempts, attempt counts on the `ToolCall`, simulated deterministic latency, no sleeping |
| `validate.py` | Schema validation → policy evaluation (`apply_policy`) → `decide()` approval policy |
| `approval.py` | `ApprovalGate`: `pending()` + explicit `resolve()` with approver identity; rejects double-resolution |
| `audit.py` | Append-only `AuditLog` (memory + JSONL) |
| `workflow.py` | `WorkflowEngine.run()` orchestrates all stages; `run_fixture_scenario()` convenience entry |
| `scenarios.py` | Registry — new scenarios = new fixture dir + one registry entry, zero engine changes |
| `config.py` | Env-var settings with offline defaults (see `.env.example`) |
| `cli.py` / `render.py` | `demo/run/approve/pending/list-scenarios/serve` commands + human-readable rendering |
| `server.py` | Stdlib `http.server` API: health, scenarios, run, approve, audit |

## Key design decisions

1. **Errors as data, not exceptions.** Messy rows produce `ValidationIssue`s and
   parse notes; the pipeline completes and escalates instead of crashing. This is
   what makes the "uncertain case" path (INV-1004: EUR, no PO) demonstrable.
2. **Two error classes for tools.** `ToolError` (transient → bounded retry) vs
   `FatalToolError` (bad request → immediate failure). The flaky vendor-master
   (`V-HOOLI` fails once) exercises the retry path deterministically via an
   explicit `fail_plan` — no randomness, no network.
3. **Warnings don't block; errors escalate; blocklist rejects.** Duplicates are
   warnings (visible, auditable) while missing POs / bad currency are errors
   (approval required). Blocked vendors are rejected outright with no approval
   option — a deliberate safety asymmetry.
4. **Approval gate is a hard checkpoint.** `auto_approved` items still go through
   `payment_schedule`; `needs_approval` items can never self-pay. Resolution
   requires an approver identity + is audit-logged.
5. **Determinism everywhere.** No clocks in decisions (ISO timestamps only in
   audit JSONL), no random IDs in fixtures, seeded UUIDs only for run IDs.
   Tests assert exact decisions, attempt counts, and risk bands.
6. **Zero runtime dependencies.** Stdlib only (`argparse`, `csv`, `json`,
   `http.server`, `dataclasses`, `unittest`). Install = `python3`, nothing to
   download — important for air-gapped customer environments.

## Failure handling matrix

| Failure | Layer | Behavior |
|---|---|---|
| Transient tool timeout | `retry.py` | Retry ≤ N attempts, then `E_VENDOR_LOOKUP` + escalate |
| Fatal tool error (bad payload, rail limit) | `tools.py` | No retry; `failed` ToolCall + escalate/hold |
| Unparseable amount / unknown vendor | `normalize` + `validate` | Parse note + `error` issue → `needs_approval` |
| PO drift > 2% / missing PO | `po_match` + policy | `E_PO_MISMATCH` / `E_PO_MISSING` → escalate |
| Blocked vendor | policy | `rejected`, no approval path |
| Over-limit / high-risk | `decide()` | `needs_approval` with reason |
| Double approval / unknown invoice | `approval.py` | `ValueError` / `KeyError`, no state change |

## Extending: add a scenario in ~15 minutes

1. Create `fixtures_<name>/` with `requirement.md`, `documents/`, `invoices.csv`
   (or any tabular input), `vendors.json`, `rules.json`.
2. If the domain differs (e.g. employee onboarding, refund triage), add a
   normalizer next to `normalize.py` and new `Tool` adapters in `tools.py`
   following the `Tool` protocol.
3. Register in `SCENARIOS` (`scenarios.py`). Engine, retry, approval, audit,
   CLI, and server work unchanged.
