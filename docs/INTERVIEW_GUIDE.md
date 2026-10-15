# Interview guide and defensible résumé language

This is an AI-assisted portfolio project. AI helped with implementation, tests, and documentation. Do not describe generated code as unaided work or claim customer adoption, production deployment, money moved, or time saved. Present the code paths and verification you can reproduce, then explain what you personally understand and changed.

## Two résumé-bullet options

- Built a local customer-onboarding workflow in Python, SQLite, and vanilla JavaScript that validates CSV/JSON intake, generates an owned dependency checklist, rejects invalid transitions, and exports portable plans; verified the flow with automated tests and a browser walkthrough.
- Extended an implementation workbench with deterministic onboarding rules, atomic SQLite saves, and stale-edit protection; added 35 Python tests (50 passing total) and verified 15 separate browser smoke checks covering correction, dependencies, persistence, export downloads, and safe text rendering.

Use either option after reproducing the documented demo yourself. These are implementation claims, not claims of commercial impact. The [README verification record](../README.md#verified-results) supplies observed counts and the [demo guide](ONBOARDING_DEMO.md) supplies exact commands. Python tests and browser smoke checks are different kinds of evidence; do not combine their counts into one suite or attach an unmeasured performance/business metric.

## Five likely interview questions

### 1. Why did you choose this scope and stack?

**Grounded answer:** “The existing repository already had a Python standard-library CLI and HTTP API for a synthetic invoice pipeline. I added one complete onboarding flow on that stack, with SQLite and plain browser JavaScript. That let me spend the time on input correction, workflow rules, persistence, and verification rather than a frontend rewrite. No model API is required.”

**Know the code:** `cli.py` starts `server.py`; `static/` is the browser; `onboarding.py` contains the new domain rules. The invoice engine remains separate.

**Learn before presenting:** Explain an HTTP request/response, how the browser's `fetch` reaches a handler, and why a local backend is different from a deployed service. Be able to launch the app without copying commands blindly.

### 2. How do you handle messy or duplicate customer intake?

**Grounded answer:** “CSV and JSON use the same seven-field schema. Validation reports row and field issues. An invalid batch makes no state change, so the user can correct the retained source. Reimporting identical customer data does not create duplicate tasks. A changed record with the same customer ID is a conflict rather than a silent update. Unknown columns and duplicate JSON keys are not discarded.”

**Know the code:** Follow `parse_intake` into `import_intake` in `onboarding.py`, then inspect the duplicate/conflict tests. A preview is read-only; import validates again before saving.

**Learn before presenting:** Understand an idempotent import, the difference between a duplicate and a conflict, and the user cost of all-or-nothing batches. Be ready to explain why this version requires correcting the ID/data instead of merging changed customer records.

### 3. Why can't someone complete a task with a blocked dependency?

**Grounded answer:** “The rule is enforced by the domain function on the server. Integration depends on completed scope and access tasks; acceptance depends on integration; launch depends on acceptance. A task must enter `in_progress` before `done`, and it cannot finish with an explicit blocker. The response includes named unmet prerequisites, so the UI can explain the rejected edit. Reopening a prerequisite cannot invalidate a completed descendant.”

**Know the code:** Read `update_task` and `task_blockers`, then trace a PATCH request through `server.py`. The dependency IDs are generated, not user-editable graph edges.

**Learn before presenting:** Draw this directed dependency graph, explain why client-only validation is insufficient, and distinguish stored status from computed blocker explanations. Find a test showing a rejected change leaves state unchanged.

### 4. What happens if two tabs edit the same plan, or the app restarts?

**Grounded answer:** “Onboarding state is stored in a SQLite file. Every mutation submits the revision that the client loaded, and the store checks that revision inside the write transaction. A stale edit receives a conflict rather than overwriting newer work. Invalid mutations don't commit. Reloading or restarting with the same database path reads the saved state. The existing invoice run objects still live in memory; they were not migrated into onboarding storage.”

**Know the code:** Read `OnboardingStore` and the save/reload, failed-mutation, and two-writer tests in `test_onboarding_store.py`.

**Learn before presenting:** Understand a transaction, rollback, optimistic concurrency, and why a whole-state document has scaling limits. Know that persistence alone does not provide backups, encryption, authentication, or a secure audit history.

### 5. What did you verify, and what remains unproven?

**Grounded answer:** “The Python suite grew from 15 to 50 passing tests, including intake and plan generation, malformed input, duplicates/conflicts, dependency rules, persistence, and export round-trips. A separate real-browser script passed 15 smoke checks covering the actual correction-to-download flow, reload, narrow-screen overflow, and a markup probe. The clean source run used Python 3.14.7 without third-party packages. The activity history is explicitly an editable local demo log. I haven't demonstrated real customer use, an external integration, production load, or comprehensive security.”

**Know the code:** Run the documented suite, inspect a failing-path test, compare CSV/JSON exports, and find where imported strings are assigned with `textContent`. Explain why a plain-text rendering check is narrower than a security review.

**Learn before presenting:** Separate unit tests, HTTP integration tests, browser checks, and business evidence. Reproduce one failure yourself, explain the assertion, and identify what a production version would need: user identity and authorization, a data migration plan, operational monitoring, backups, and trusted acceptance checks.

## Preparation checklist

- Run the full suite and the [two-minute demo](ONBOARDING_DEMO.md) from a fresh database.
- Trace one invalid import from browser text through parsing to the field-level response.
- Trace one valid edit through revision checking, domain validation, transaction, and UI refresh.
- Explain one tradeoff you would revisit for a shared product, without implying that you already implemented it.
- Say where AI helped and what you personally reviewed, tested, and can defend. If you cannot explain a claim yet, leave it off your résumé until you can.
