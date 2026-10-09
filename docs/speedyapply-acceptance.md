# SpeedyApply replacement acceptance record

Private local integration, verified on macOS arm64 with Python 3.13.13, Playwright 1.59.0 and its bundled Chromium 147.0.7727.15. The evidence below concerns fictional offline forms. No live employer application or submission was performed.

## Ordered implementation gates

1. **Original package preserved.** `third_party/speedyapply/2.28.0/original.xpi` contains all 27 original archive entries and notices. `inventory.json` records each entry's hash and size. The source manifest identifies 2.28.0. XPI SHA-256: `f7202224224735d17c8bf9ed8d091034848c8614a6d99cf84c02021bb0692571`. Source/provenance are preserved separately; no open-source licence is asserted.
2. **Old baseline measured before replacement.** Original suite: 60 passed, 1 opt-in test skipped, 84.76 seconds. Baseline source commit: `2a4eb755272b6abc67a9c1efd0d7ab7a9b3ae7d3`. Four-site benchmark captured before removing the old engine; raw samples and fixture hashes are in `speedyapply-old-benchmark.json`.
3. **Reproducible pinned extraction.** The build verifies original XPI and content hashes before extracting the actual 28 registry functions and their helper closure. It preserves regex flags, query/fragment rules and the DOM selector. Rebuilding is deterministic, and a different XPI fails. Original startup, UI, authentication, subscription, sync, scoring, premium generation and backend code are absent from the loaded graph.
4. **Local runtime and controls.** Manifest V3 content scripts are available in HTTPS frames; an adapter starts only after desktop selection of a unique matching frame. Member calls and mutations pass through run controls; native setter calls, synthetic activations, continuation and submission are gated. Timers, observers and listeners are owned by the run. Missing selectors have a 20-second deadline. Existing conflicting values are preserved; unsupported actions require manual review.
5. **Desktop integration.** Python communicates directly with the extension worker through Playwright. Commands bind run, tab, document and generation token. Worker restart retains bindings without replaying adapter start or mutating commands. SQLite remains authoritative; employer credentials remain in the OS keychain and are supplied only to recognized authentication.
6. **Profiles and migration.** Optional name/phone components, GPA/current attendance, language proficiency and explicit eligibility preserve unknowns. Original document bytes and MIME types are retained; changing either document's bytes invalidates prior verification even if its path is unchanged. Exact scoped approvals replace broad vendor guesses. Pending legacy checkpoints are invalidated once, while history and submission-attempt flags remain. New/resumed automation uses a separate bundled Chromium session directory; old browser directories are retained.
7. **Adapter acceptance.** All 28 actual functions are exercised, including profile writes, validation failure, unknown answers, existing-value conflicts and their fixture's continuation/submission branch. The per-adapter record is below. Shared tests cover repeated rows, rerenders, frames, shadow controls, uploads, review, interruption and isolation.
8. **Network capture and speed measurements.** The network test observes page/context requests and enables CDP's Network domain on the actual extension-worker target. The benchmark uses identical versioned fixtures, identical profiles and the same bundled Chromium executable for both engines. Raw outputs are retained.
9. **Old engine removed.** `core/automation/engine.py` now contains the extension-backed engine. The old generic loop, `workday.py`, `ats.py` and their superseded tests/fixture are removed. Shared browser ownership, cookies, privacy, storage, GUI, queue, tracker and assistant regressions remain. No automatic fallback exists.
10. **Final regression result.** Build determinism/version rejection/MV3 checks: 3 passed. Final engine, profile, storage, desktop, browser and assistant regressions: 45 passed in 108.19 seconds, including the opt-in upload workflow with a fictional profile. Final full suite: **128 passed, 1 opt-in test skipped, 341.31 seconds**. Together with the final regression run, all **130 unique Python tests** were exercised successfully; the counts overlap and must not be added. `speedyapply-validation.json` records the results. Static Python compilation, JavaScript syntax checks and `git diff --check` also passed.

## Explicit 28-adapter record

Each row represents three parametrized tests: actual detection/filling/stopping; invalid/unknown/conflicting values; and intercepted continuation or explicit manual handoff. Each basic fixture has three verified fields, except the additional Workday repeated-row fixture has ten. A pass covers these representative branches, not every employer-specific variant or every input offered by an adapter.

| Adapter | Actual fill + stop | Validation / unknown / conflict | Continuation fixture |
|---|---|---|---|
| Workday | Pass | Pass | Next intercepted |
| Greenhouse | Pass | Pass | Submit intercepted |
| Lever | Pass | Pass | Submit intercepted |
| SAP SuccessFactors | Pass | Pass | Manual handoff |
| iCIMS | Pass | Pass | Next intercepted |
| Workable | Pass | Pass | Submit intercepted |
| Rippling | Pass | Pass | Submit intercepted |
| Breezy | Pass | Pass | Submit intercepted |
| JazzHR | Pass | Pass | Manual handoff |
| Ashby | Pass | Pass | Submit intercepted |
| SmartRecruiters | Pass | Pass | Next intercepted |
| Paylocity | Pass | Pass | Submit intercepted |
| Freshteam | Pass | Pass | Manual handoff |
| Dover | Pass | Pass | Submit intercepted |
| Pinpoint | Pass | Pass | Manual handoff |
| Comeet | Pass | Pass | Submit intercepted |
| Gusto | Pass | Pass | Submit intercepted |
| Polymer | Pass | Pass | Submit intercepted |
| ADP | Pass | Pass | Next intercepted |
| Jobvite | Pass | Pass | Submit intercepted |
| UltiPro | Pass | Pass | Submit intercepted |
| Tesla | Pass | Pass | Submit intercepted |
| TikTok | Pass | Pass | Submit intercepted |
| Eightfold | Pass | Pass | Submit intercepted |
| SEEK | Pass | Pass | Next intercepted |
| BambooHR | Pass | Pass | Submit intercepted |
| Phenom | Pass | Pass | Submit intercepted |
| Dayforce | Pass | Pass | Next intercepted |

The four manual entries are the tested vendor branches' behavior; the runtime does not invent a generic navigation fallback. Phenom is detected by its DOM marker, and UltiPro exercises shadow-root controls.

## Cross-cutting acceptance

- Workday: two employment and two education rows, exact values, resume without duplicates, extra-row handoff, and a dynamically added language dropdown plus explicit fluency; separate multi-section labeled review, including changed values that must block submission.
- Greenhouse: rerenders, conditional and delayed controls, scoped approved answers, explicit sponsorship facts through the original question helper, existing values, PDF/Word upload handling, unsupported accepts, differing bytes with the same filename, and cover-letter text/file support.
- Controls: pause/cancel during filling; bounded missing selectors; stale document/generation rejection, simultaneous application isolation, and same-document navigation cleanup; embedded application frame selection and ambiguous-frame handoff; worker restart without duplicate filling.
- Submission: default disabled, per-application authorization (including a final button labeled “Apply”), checkpoint before click, immediate content-script recheck with a changed-form rejection, recognized visible employer receipt, hidden/ambiguous receipt rejection, and no retry of an existing submission attempt. Vendor saved-application events never establish success.
- Desktop/storage: profile migration, existing scoped approvals, retained history and attempts, keychain-only credentials, named profiles, queue sequencing, tracker/CSV, browser locks/cookies, Gemini consent/privacy and a real PySide → service → extension → intervention → resume workflow.

## Network evidence

The final capture in [speedyapply-network-capture.json](speedyapply-network-capture.json) records all 28 adapters. Only intercepted fixture document URLs were requested by pages. **Zero SpeedyApply/Supabase requests and zero extension-worker network requests** were observed during normal fixture autofill. The worker's CDP Network domain was enabled before any adapter started. The audit now waits for worker registration before attaching, fixing the startup race discovered in the preceding run.

## Benchmarks

Five runs per engine/site, timing the engine call after the fixture loaded. Each engine filled 3/3 fields and required zero answer/error interventions on all four fixtures. A deliberate “section verified; continue manually” notification is excluded from the intervention count because `auto_advance` was disabled for both engines. These small-form measurements exclude browser startup, network latency, sign-in and live employer behavior.

| Site | Old median | Local adapter median | Time change | Correct fields | Interventions |
|---|---:|---:|---:|---:|---:|
| Workday | 1.524 s | 1.085 s | -28.8% | 3/3 both | 0 both |
| Greenhouse | 1.655 s | 0.976 s | -41.0% | 3/3 both | 0 both |
| Lever | 1.641 s | 0.852 s | -48.1% | 3/3 both | 0 both |
| Ashby | 1.631 s | 2.657 s | +63.0% | 3/3 both | 0 both |

See `speedyapply-old-benchmark.json` and `speedyapply-new-benchmark.json` for raw samples, runtime versions and matching fixture hashes. The Ashby adapter retains a delayed submit-control path that the runtime waits to settle; this fixture is slower than the old engine. There is no claim that every adapter is faster.

## Reproduce

```sh
npm ci --prefix extension --ignore-scripts
npm run build --prefix extension
npm test --prefix extension
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python tools/benchmark_adapters.py --iterations 5 --output /tmp/intern-bot-benchmark.json
```

The opt-in supplied-profile upload test needs `INTERN_BOT_ACCEPTANCE_PROFILE=/absolute/path/profile.json`; it still uses only an intercepted fictional page. It is skipped without that explicit input. For this acceptance run, it was also exercised successfully using a fictional Ada Example profile and PDF supplied through that variable; no personal resume was used. The historical engine is available through the baseline Git commit for independent comparison, not as an application fallback.

## Limits

Live employer acceptance remains outstanding by design. These fixtures do not establish exhaustive coverage of employer customizations, CAPTCHAs, every dropdown/rich widget, every row layout or every review/receipt format. Unrecognized controls, ambiguous frame matches, unknown facts, uncertain uploads and unverifiable review summaries require manual intervention. The current environment is macOS; other operating systems are unverified. The preserved proprietary source is intended for the user's private personal repository and has not been relicensed for public redistribution.
