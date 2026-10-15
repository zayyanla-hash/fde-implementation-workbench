# Customer onboarding proof implementation plan

Goal: Extend the existing offline stdlib Python workbench with a complete synthetic customer-onboarding flow, keeping the existing invoice scenario intact.

Architecture: strict CSV/JSON intake -> deterministic domain functions -> SQLite state with revision checks -> existing HTTP handler -> plain HTML/JS using textContent. All storage and activity are local demo data, without authentication or secure audit guarantees.

User supplied a detailed execution specification and authorized autonomous implementation within one hour. Avoid extra approval gates; reserve the last portion for rendered and clean-environment verification.

- [x] Establish baseline in isolated branch; preserve original checkout.
- [x] Domain worker: strict intake schema, issue rows/fields, deterministic task generation, duplicate/conflict handling, task edits/dependency invariants, serialization/CSV round-trip and unit tests.
- [x] UI worker: restrained accessible intake correction, plan edits, visible blockers, history and downloads with safe text rendering; no new dependencies.
- [x] Parent: SQLite transactional state/revision API integration, strict HTTP errors and HTTP tests.
- [x] Parent: browser import -> validation -> correction -> plan -> editing/history -> reload -> JSON/CSV downloads on desktop/narrow viewport, safe-markup verification, screenshots.
- [x] Proof package: verified setup/test commands, architecture, 2-minute demo, honest resume options and grounded interview answers; clean temporary install and full tests; review and commit only task changes.

The final schema and interfaces are documented in docs/INTAKE_SCHEMA.md and docs/ONBOARDING_ARCHITECTURE.md. Verification: 50 Python tests, a 15-check initial browser flow, and final desktop/narrow visual checks after correcting CSS pseudo selectors. Alternative frontend rewrite and cloud persistence rejected: unnecessary infrastructure for this existing stack and timebox.
