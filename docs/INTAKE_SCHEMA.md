# Customer intake and portable plan format

The local onboarding demo accepts CSV and JSON. Both formats use the same seven
required fields. The examples under `fixtures/onboarding/` are synthetic; owner
addresses use the reserved `example.test` domain.

| Field | Accepted value | Used for |
| --- | --- | --- |
| `customer_id` | A string matching `[a-z0-9][a-z0-9_-]{0,63}` | Stable customer identity and task ID prefix |
| `customer_name` | Nonempty string | Human-readable task titles |
| `integration` | Nonempty string | Named integration work |
| `technical_owner` | Email-shaped string such as `technical-owner@example.test` | Scope, integration, and acceptance owner |
| `data_access_owner` | Email-shaped string such as `data-owner@example.test` | Sandbox access owner |
| `launch_owner` | Email-shaped string such as `launch-owner@example.test` | Launch handoff owner |
| `acceptance_criteria` | Nonempty string | Acceptance and launch completion criteria |

Values are preserved as supplied. Whitespace-only strings are empty; IDs and owner
addresses must not have surrounding whitespace. Email shape checks do not verify
that a mailbox exists, that its owner accepted an assignment, or that access works.
Unpaired Unicode surrogates are rejected before saving because they cannot be
represented in UTF-8 exports. Ordinary non-ASCII text and emoji are preserved.

## Source formats

CSV must have exactly the seven field names above, each once. Columns may be
reordered. Use ordinary CSV quoting for commas, quotes, and multiline values. An
optional UTF-8 byte-order mark before the header is accepted. Each data record
must have the same number of cells as the header. Blank records, missing columns,
unknown columns, duplicate columns, and malformed quotes produce explicit errors.
CSV diagnostics number logical records starting at row 2 after the header;
malformed quoting additionally uses the parser's physical line position.

JSON must be an array of objects. Every object must have exactly those seven
fields, each once, and all values must be strings. Unknown fields, duplicate keys,
non-object records, nulls, numbers, and malformed JSON produce explicit errors.
JSON diagnostics number records starting at row 1. Empty intake is rejected.

`customer-intake-incomplete.csv` and `customer-intake-incomplete.json` deliberately
leave `technical_owner` empty. Replace it with `technical-owner@example.test`,
validate again, then create the plan. The corresponding `customer-intake-valid`
fixtures show the repaired input.

## Duplicate and conflict handling

Validation compares IDs across the entire intake and against stored customers.
An identical record with an existing ID produces a warning and creates no new
customer, tasks, revision, or activity. A record with the same ID and any changed
value produces a conflict error naming the differing fields. Use unchanged intake
or a new `customer_id`; imports never overwrite existing customer data.

An import containing **any error is rejected as a whole**. Correct records in the
same source are not partially saved. The browser keeps the original source for
repair. Warnings alone permit importing the distinct new customers. One successful
import increments the state revision once, irrespective of the number of new
customers, and records one `customer_imported` activity per new customer.

## Generated plan and task edits

Each customer deterministically produces these five tasks:

| ID suffix | Owner | Initial status | Dependencies |
| --- | --- | --- | --- |
| `scope` | Technical owner | `todo` | None |
| `data-access` | Data access owner | `blocked`, with a sandbox access explanation | None |
| `integration` | Technical owner | `todo` | Scope and data access |
| `acceptance` | Technical owner | `todo` | Integration |
| `launch` | Launch owner | `todo` | Acceptance |

Full IDs have the form `harbor-demo:scope`. Tasks contain `id`, `customer_id`,
`title`, `owner`, `status`, `depends_on`, `blocker`, and `acceptance_criteria`.
Acceptance and launch copy the customer's exact acceptance criteria. No external
service, model call, access grant, integration run, or deployment is performed.

The browser may edit `title`, `owner`, `status`, and `blocker`. IDs, customer IDs,
dependencies, and acceptance criteria remain generated plan data. Owners must
remain email-shaped; titles must remain nonempty. Allowed statuses are `todo`,
`in_progress`, `blocked`, and `done`.

- `in_progress` requires completed dependencies and a cleared explicit blocker.
- `done` requires the previous status `in_progress`, completed dependencies, and a
  cleared blocker. Editing an already completed task does not require reopening it.
- `blocked` requires a nonempty explanation. Save the explanation alongside the
  status when blocking work, and clear it alongside the status when resuming.
- Reopening `done` work is allowed only if every active or completed dependent
  task would remain valid. Reopen dependent tasks first, working backward from
  launch, before reopening their prerequisites.
- A change to `todo` is allowed even when dependencies are incomplete. Dependencies
  and explicit blockers remain visible until resolved.

Edits validate the complete candidate plan before saving and record readable
before/after activity. Unchanged edits are no-ops. Activity is ordinary editable
local demo data, not a secure or tamper-evident audit trail.

## Export and verified round trips

Plan exports contain **tasks**, including owners, statuses, blockers, acceptance
criteria, and dependency IDs. They do not include customer intake, state revision,
or activity, and are not a full database backup. Customer intake import and plan
export are deliberately different schemas. `parse_plan` validates portable task
data for round-trip checks; the UI does not import exported plans into storage.

JSON exports use this envelope:

```json
{"schema_version": 1, "tasks": []}
```

CSV exports use these columns in this order:

```text
id,customer_id,title,owner,status,depends_on,blocker,acceptance_criteria
```

The `depends_on` cell contains a JSON array of task IDs. To keep exported
user-supplied strings from being interpreted as spreadsheet formulas, **every CSV
data cell begins with one additional apostrophe**. This includes ordinary text,
empty strings, and the dependency-array cell. Spreadsheet applications generally
use that prefix to display a literal string; raw CSV readers show the prefix.

`parse_plan` requires the exported CSV header and one prefix on every data cell,
then removes exactly one prefix before validating task fields and dependencies.
An original apostrophe is preserved, so titles beginning with `=`, `+`, `-`, `@`,
whitespace, or an apostrophe round-trip without losing data. Newlines, commas,
quotes, and non-ASCII characters also round-trip. JSON exports preserve strings
directly and do not add spreadsheet prefixes.

Do not remove the CSV prefixes when opening untrusted exported text in a
spreadsheet. This transport encoding is separate from intake CSV and is not
accepted as customer intake.
