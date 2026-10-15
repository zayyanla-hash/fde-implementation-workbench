# Vercel deployment

**Public URL:** https://fde-implementation-workbench-ascend4.vercel.app

Target: `ascend4/fde-implementation-workbench`. GitHub source: `zayyanla-hash/fde-implementation-workbench`.

The public site serves the redesigned onboarding UI at `/`, with the prior invoice demo retained at `/invoice/`. `vercel.json` runs `python3 scripts/build_site.py`, serves the generated `public/` assets, and deploys the existing invoice functions plus `api/onboarding.py`.

## Persistence and validation

The hosted app stores each visitor's raw snapshot in IndexedDB under the current browser origin. Reads, imports, task changes and exports are checked by the Python domain rules in `src/workbench/hosted.py`. Generated task IDs, dependencies and acceptance criteria must match the customer intake. Existing title/owner/status/blocker edits remain supported. Import and update responses commit in a browser transaction only if the revision has not changed since validation. Corrupt storage is reported and never silently reset.

Plans are not shared between people, devices, browser profiles or deployment domains. Clearing browser site storage removes the plan. There is no central database, login, secure audit trail or live customer integration. The local Python server still uses SQLite.

The public endpoint uses a 1 MB JSON body limit, rejects duplicate JSON keys, checks same-origin requests, and keeps no visitor state in process memory. Fifty synthetic customers is the hosted demo cap. These bounded controls are not a production qualification.

## Validation and release

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/workbench/static/app.js
node --check src/workbench/static/browser-store.js
python3 scripts/build_site.py
git diff --check
```

68 tests cover the original workflows plus 18 hosted adapter tests. Browser verification must exercise the actual deployed import, rejected dependencies, saved changes, reload, and both downloads.

Deployments are staged as production builds with `vercel deploy --prod --skip-domain`. Verify the staged health/API responses with `vercel curl --deployment <url>` before promoting that exact build using `vercel promote <url>`. Production's canonical alias is public; preview and immutable deployment URLs use Vercel Standard Protection.

Vercel project links and environment files are ignored. Do not commit `.vercel/`, `.env*`, local SQLite files, or generated `public/` output.

## Git integration status

Source is pushed to `zayyanla-hash/fde-implementation-workbench` main. Vercel Git connection returned an access error for that repository; the authenticated CLI deployed this release directly. Future pushes do not trigger automatic releases until the GitHub integration is granted access. Direct CLI deployment remains available without changing account permissions.
