# Intern-Bot local extension

This Manifest V3 package contains all 28 actual adapter entry points extracted from the user-supplied SpeedyApply 2.28.0 Firefox package. It is bundled for this private personal repository. It is not an open-source relicense of SpeedyApply.

The desktop loads this directory into its isolated bundled Chromium session. No extension-store installation, SpeedyApply account, subscription, Supabase, sync service, or local HTTP server is required. The original vendor extension startup, UI, authentication, cloud calls, premium generation and broad saved-answer matcher are not included in the loaded dependency graph.

## Rebuild

```sh
npm ci --prefix extension --ignore-scripts
npm run build --prefix extension
npm test --prefix extension
```

Node is needed only to rebuild/test the pinned generated bundle. Normal desktop operation uses the checked-in files. The build verifies both the original XPI and extracted content hash and rejects any other input version. It preserves the adapter registry's regex flags, query/fragment rules and DOM selector. `generated/build-report.json` records the dependency closure and mutation instrumentation. All original bytes/notices remain in `third_party/speedyapply/2.28.0/original.xpi` and the original content script.

## Local controls

`background.js` exposes `internBot.command` only in the extension worker's execution context, used directly by Playwright. It discovers frames without profiles, selects exactly one match, and binds each command to run, tab, frame document and a fresh token. `storage.session` stores bindings only. Profiles, files, approvals and credentials are not written to extension storage. Chromium MV3 worker restart support requires the pinned Playwright 1.59.0; a local wake page can restart the worker, and mutating commands are never retried automatically.

`runtime.js` starts only the selected adapter inside the extension's isolated content-script world. AST instrumentation routes member calls, native setters, and property writes through per-run controls. Timers, observers and listeners belong to that run and stop on pause/cancel/navigation. The 20-second section wait cap produces a handoff. Direct native submission calls, button clicks and synthetic activations become pending actions. Python verifies the section and persists any submission attempt before authorizing an action; the content script rechecks the document immediately before clicking.

The adapter chooses selectors. The desktop supplies exact scoped approved values using the existing answer resolver. Vendor guesses cannot supply consent, employment eligibility, EEO answers, dates, or contact values. Unsupported controls, extra rows, ambiguous forms/frames, missing selectors, uncertain uploads and unrecognized review summaries require manual intervention. Exact approved answers and cover letters can also use the shared guarded writer.

Uploads retain original bytes, filename and MIME type. The runtime verifies bytes and a recognized visible upload receipt. A selected file or matching filename alone is insufficient. Old uploads without independent evidence require review. Old resume deletion behavior is replaced with conflict handling.

Small vendor defects are adapted explicitly: empty education selection, absent date formatting, and observer helpers that failed to notice an already-satisfied condition. No remote code is loaded. The original source remains unchanged.

See `../docs/speedyapply-acceptance.md` for measured coverage and limits.
