# Reproducible onboarding demo

All companies, people, email addresses, and integration requirements in this walkthrough are synthetic. The story is an AI software company onboarding a business customer; it is not an account of a real customer deployment.

## Start from a separate database

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
WORKBENCH_DB="$PWD/var/recruiter-demo.sqlite3" PYTHONPATH=src python -m workbench serve --port 8765
```

Open **http://127.0.0.1:8765/**. Use a different database filename if this one already contains an earlier run. No reset or deletion is required to inspect saved work.

## Walkthrough and expected evidence

Use **Load example**, **Validate intake**, and **Create plan** in the intake panel. To change a task, expand **Edit task**, choose its **Status**, then press **Save changes**. The UI labels **In progress** and **Done** correspond to `in_progress` and `done` below. Clear an explicit blocker in **Blocker / reason for waiting**; unsaved drafts do not persist across a page reload.

| Step | Action | Expected result |
|---|---|---|
| 1. Load incomplete intake | Load the example in CSV format. | An invented customer has an integration request, data-access owner, launch owner, and acceptance criteria, with the technical owner missing. |
| 2. Validate | Validate the intake. | A row/field error identifies `technical_owner`. No tasks are saved and the original source remains editable. |
| 3. Correct | Fill the missing value with `technical-owner@example.test` and validate again. | The error clears. The same workflow also accepts the equivalent JSON input. |
| 4. Create | Create the plan. | One customer produces five tasks. Data access starts blocked by missing sandbox access. Integration displays unmet scope/data-access dependencies. |
| 5. Exercise rejected changes | Try setting integration to `in_progress` and save; then try setting it directly to `done`. | Starting fails with named unmet prerequisites. Direct completion also fails because the task must start first. The task stays incomplete and the dependency reasons remain visible. |
| 6. Resolve scope | Set scope to `in_progress`, save, then `done`, and save. | Both changes appear in timestamped activity. |
| 7. Resolve access | Clear the data-access task's explicit blocker, set it to `in_progress`, and save; then mark it `done`. | The sandbox blocker clears only through an explicit edit. Integration's prerequisites are now satisfied. |
| 8. Progress the implementation | Start and complete integration, then acceptance, then launch, saving each transition. | The workflow accepts each task only after its dependencies are complete. Acceptance criteria remain visible. |
| 9. Test duplicate handling | Submit the corrected intake again. | No duplicate customer or tasks are created. |
| 10. Test a conflict | Change `customer_name` while keeping the same customer ID, then try importing. | The conflict is explained and existing data is preserved. Restore the original source afterward. |
| 11. Reload | Reload the page. | Saved task changes and activity remain. Stopping and restarting the server with the same database path also retains them. |
| 12. Export | Download JSON and CSV. | Both contain the task plan, owners, statuses, blockers, acceptance criteria, and dependency IDs. CSV adds a leading apostrophe to each data cell for spreadsheet-safe text; automated `parse_plan` round-trip tests remove that encoding and compare the original tasks. |

For JSON, quote all keys and string values, keep all seven documented fields, and submit an array of customer objects. Duplicate JSON keys and unknown fields are reported rather than accepted silently. See [INTAKE_SCHEMA.md](INTAKE_SCHEMA.md) for the complete input contract.

Plan exports are not customer intake. `parse_plan` is a Python reader used to verify exported plan data; the browser does not reimport task plans. A generic CSV reader will retain the apostrophe transport prefix. Use JSON when a downstream consumer needs the original task strings directly.

For a safe-rendering check, put `<img src=x onerror=alert(1)>` in a free-text field such as customer name on a new synthetic customer, then import it. It should appear literally as text and must not create an image element or run code. The automated/browser verification covers this rendering boundary; it is not a claim that every security property has been tested.

## Optional browser regression

The Python runtime and tests need no third-party packages to install. The frontend includes the locally vendored Motion library and Manrope font. If the **Ego Browser CLI is already installed**, the checked-in `scripts/browser_smoke.js` can replay the browser checks. It is an optional verification tool, not an application runtime dependency.

Stop the earlier demo server with Ctrl-C first. From the repository root, start a fresh database on the script's default port:

```bash
source .venv/bin/activate
BROWSER_DEMO_DIR="$(mktemp -d)"
WORKBENCH_DB="$BROWSER_DEMO_DIR/onboarding.sqlite3" PYTHONPATH=src python -m workbench serve --port 8765
```

From a second terminal at the repository root:

```bash
ego-browser nodejs < scripts/browser_smoke.js
```

The script requires an empty plan and writes its JSON results, downloaded plans, and captured screenshots to `/tmp/workbench-browser-proof` by default. Ego's embedded runtime does not inherit the launching shell's working directory or environment variables; setting an output environment variable in the shell does not change that default.

Observed local results on October 14, 2026: **50 Python tests passed** in a clean Python **3.14.7** temporary virtual environment without third-party packages or warnings, and **15 separate browser smoke checks passed**. The browser flow retained five completed tasks and 11 activity entries after reload, saved both actual downloads, showed no horizontal overflow at 390 px, kept Refresh visible at tablet width, and rendered the imported HTML/script probe literally. These are bounded functional checks, not production or comprehensive accessibility/security qualification. Screenshot capture alone is not visual verification.

## Two-minute presentation script

**0:00–0:20 — Problem.** “An implementation specialist receives an incomplete customer handoff and needs an owned launch plan. This local portfolio demo uses an invented AI software company and customer. It doesn't call a real integration.”

**0:20–0:40 — Input and failure.** Load the example and validate. “The technical owner is missing. The error points to the row and field, and the source stays available to correct. The invalid batch creates nothing.”

**0:40–1:00 — Fix and plan.** Add `technical-owner@example.test`, validate, and create. “The corrected record generates five deterministic tasks with owners and acceptance criteria. Data access is explicitly blocked until sandbox access is granted.”

**1:00–1:20 — Dependency protection.** Try starting integration early. “The backend rejects this, even if the client asks for it. The explanation names the prerequisites. Directly marking an unstarted task done is also rejected.”

**1:20–1:40 — Saved output.** Complete the scope task through `in_progress` and `done`, then reload. “The saved status and timestamped changes remain in SQLite. I can download the task plan as CSV or JSON, with dependencies preserved.”

**1:40–2:00 — Tradeoff.** “I reused the Python standard-library server and added a plain browser UI. Whole-state SQLite storage keeps this slice small and testable. It has no login or secure audit trail, and it would need a different data/access design for a shared production product. AI assisted implementation; the rules, tests, and reproducible demo are what I can inspect and explain.”

## What to show a recruiter

Open the README, run this walkthrough, and inspect `onboarding.py` beside the domain tests. The useful evidence is the correction path, server-enforced dependencies, failed-change preservation, reload, and portable export. Avoid implying that passing tests measures customer outcomes or proves production readiness.

The onboarding workflow is now published in the public repository and hosted demo. Local persistence uses SQLite; the hosted demo uses per-browser IndexedDB. See DEPLOYMENT.md for that boundary.
