# M3-4/5 integration and UI slice

Date: 2026-11-03. Base: `main` at `c447ba4` (fresh fetch verified before work).
Branch: `codex/m3-promotion-flow`. Status: **partial implementation, not an operational auto-trading rollout**.
No M3-6/7 branch files, G3 sources, `BROKER_SDK_VERSION`, or `PROJECT_STATE.md` are changed.

## Delivered

- First contract commit adds the five owner actions, reference-only build request,
  version/hash-bound lifecycle intent, and immutable auto-strategy UI projection.
- Engine state contains default-empty records and promotion evaluations. Legacy
  state payloads without these fields still decode. The new projection adapter
  writes every event through `TradingEngine._persist` as an `AppState` envelope.
  It never attaches the independent `PromotionService` writer to the raw engine journal.
  Fresh lifecycle projections use the current engine sequence; stale projections
  are rejected. Restart pauses running simulation records and clears eligibility.
- Central codec registration covers the new records/DTOs. Derived `init=False`
  fields are not accepted from the wire; `live_available` remains permanently false.
- `list_candidates`, `build_auto_strategy`, and `auto_strategy_command` transport
  paths use the existing authenticated dispatch, envelope account/environment,
  engine version, strategy version, and frozen-hash checks.
- Explicit owner approval records `LIVE_APPROVED` only in broker simulation after
  eligibility and confirmation checks. It calls no financial gateway and does not
  change execution configuration. The existing `permits_new_entries` restriction
  remains BROKER_SIM-only. Retirement refuses outstanding positions/orders rather
  than claiming an unimplemented flatten completed. Resume remains fail-closed.
- Exact observation timestamps are persisted on simulation start/resume. UI checks
  are bound to that timestamp. The existing once-per-(strategy, version, day)
  audit verdict remains immutable; a same-day resume cannot regain eligibility
  through the cached verdict or display the previous epoch's checks.
- Runtime composes the existing read-only candidate catalog and V1 signal source,
  with a trusted training-input injection seam. The default catalog has **no
  authoritative E1 producer** and rejects. No display verdict or fixture is used
  to qualify a production candidate; no OOS/holdout payload is loaded.
- UI adds a reference-only build form, explicit disabled stock types, asynchronous
  candidate loading, a separate frozen-strategy tab, audit-check progress/drift,
  version/hash-bound owner actions, and a dashboard summary. Confirmation defaults
  to Cancel; context changes invalidate pending forms. Close during candidate
  loading returns promptly and waits for its owned worker to finish.
- The walk-forward result entry is visibly disabled until authoritative candidate
  references exist. Strings remain centralized (phase 73, orders 3124–3208).
  Paused status uses warning colour and stage information remains textual.

## Still required before completion

1. An authoritative, source-bound E1 producer. The current catalog intentionally
   returns `candidate_unavailable`; enabling from display results would be unsafe.
2. A bounded fixed-target E2 worker preserving OHLC, trusted minute-data preparation,
   and revalidation before publication. The injected synchronous builder is not
   composed for production and does not establish this acceptance item.
3. Engine-owned signal-strategy admission, submit ownership, protective exits,
   completed-bar scheduling, and reconciled promotion/expiry scheduling. No alternate
   order path was added. Approval-expiry scheduling is not implemented in this slice;
   UI does not claim its 30-day lifecycle is active.
4. UI pre-build fingerprint, complete E2/performance-page comparison, and saved
   optional column customization. The current six columns use available audited
   progress, not invented P&L. Fingerprint appears after a record exists.
5. Authenticated OS-process IPC and Windows/native startup acceptance on a capable
   host, plus full CI. Direct typed dispatch is tested, but is not a substitute for
   authenticated process transport. No completed M3-4/5/6/7/8/9 milestone is claimed.

## Verification

Python 3.12 on an isolated Linux cloud worktree. Qt 6.12.0 and Ruff 0.16.10 were
installed from the repository's exact official hash-locked requirements into
isolated directories; no systemwide change, broker login, CA, or real key use.

Commands use `PYTHONPATH=.:tests`; Qt checks use `QT_QPA_PLATFORM=offscreen`.

- `python -m unittest tests.test_m3_integration -q`: 24 passed, including durable
  projection/restart/CAS failure, exact epoch, legacy decode, IPC DTO/dispatch,
  mismatched account/version/hash, default E1 denial, and zero submit/cancel/amend
  calls for owner lifecycle actions in every environment.
- M3 core group (`test_m3_integration`, `test_m3_candidate_intake`,
  `test_m3_promotion_service`, `test_m3_signal_research`, `test_m3_stage_matrix`):
  123 passed before the final additional zero-financial-call test; that final
  integration module rerun is included above. Independent review additionally
  found and fixed selected-account filtering for non-SinoPac IPC responses and
  misleading running/eligibility labels on BACKTEST and LIVE_APPROVED rows.
  Both fixes have focused regression assertions. Confirmation dialogs also bind
  the exact reviewed AppState version, so polling cannot silently refresh approval,
  retirement, or build consent to a newer snapshot.
- Existing focused group: **146 passed** across `test_trading_application`,
  `test_trading_architecture`, `test_trading_execution_environments`,
  `test_trading_broker_runtime`, `test_trading_broker_sessions`,
  `test_trading_scope_guards`, `test_trading_readonly_coordination`,
  `test_trading_ui`, `test_m3_ui`, and `test_trading_ui_integration`.
- UI/baseline group: **63 passed** across `test_desktop_pages`,
  `test_desktop_text_aliases`, `test_m2_guidelines`, `test_desktop_catalog_split`,
  and `test_repo_layout`. Widget-name fixture adds only the research entry and its
  prerequisite label. Public-name and stylesheet baselines are unchanged.
- `test_m3_ui`: **21 passed**; the final module includes actual Qt window startup over LOCAL durable
  simulation and a BROKER_SIMULATION in-memory SDK double, without financial calls.
  These are offscreen composition checks, not native desktop or real broker acceptance.
- Full-tree pinned Ruff check/format: passed (1,392 files considered by formatter).
  Python 3.11 grammar parsing and current-Python compilation: 1,276 tracked files
  passed. Repository layers, trading architecture, and quality gate: zero findings.
  `git diff --check`: passed. These do not claim a Python 3.11 runtime test.

Actual offscreen captures were inspected at 1366×768 and 1920×1080. The strategy
list and enclosing workspace have zero horizontal-scroll range at both sizes;
1366×768 uses vertical scrolling to reach promotion actions. A build-dialog
capture was also inspected. Captures use explicit synthetic UI fixtures, not E1 proof.

## Limits and failed runs

- `AGENTS.md`, `CLAUDE.md`, and `.gitnexus/run.cjs` were absent. The prescribed
  GitNexus command returned MODULE_NOT_FOUND. Targeted import/caller searches were
  used, not represented as GitNexus output. Critical seams are UiAction/UiCommand,
  AppState/codec/registry, RuntimeBundle.execute, IpcFacade, and server `_dispatch`.
  Relevant tests are listed above; real transport remains blocked below.
- OS-process IPC tests attempted AF_UNIX listener construction and failed with
  `PermissionError: [Errno 1] Operation not permitted`. No test was skipped,
  weakened, or rewritten to hide that restriction; no alternate transport bypass
  was attempted. Existing runtime/context tests remain host-blocked here.
- An early combined run exposed a moved research injection symbol; the existing
  seam was restored lazily and all 69 original intake/promotion tests then passed.
  Early source-profile mismatch during concurrent edits disappeared on a frozen
  tree rerun. Missing test import paths and shallow historical-baseline objects
  were corrected, then the relevant full modules reran green.
- PowerShell and Python 3.11 are not installed in this cloud runtime. The exact
  Windows prepush wrapper/native startup is unrun, not reported as passed.
- `IMPLEMENTATION_CONTRACTS.md` is not changed or uploaded by this slice. This
  report records the integration contract for this limited slice. Publication
  and final review are separate; no merge is performed.

## Publication privacy review

The final changed-file payloads were scanned before publication. Two historical
inventory references contained an unnecessary personal home-directory prefix.
Only those prefixes were replaced with `<local-user-home>`; the relative workspace,
recorded commit/index context, and inventory registrations remain intact. No
credential values or email addresses were found by the targeted token/assignment,
private-key, email, and home-path checks. The static credential gate also passed.
This is a bounded review, not a claim that pattern matching proves all data safe.

Publication must use the final sanitized file tree against the verified main base,
not push the local intermediate commit chain. Earlier local inventory blobs still
contain the original historical prefixes and are not publication inputs.
`IMPLEMENTATION_CONTRACTS.md` is outside this slice and absent from the changed-file set.

## PR #169 first CI run and focused correction

[Run 41600521398](https://github.com/yostar77612/mark-auto/actions/runs/41600521398)
on remote head `3aba6d12b8e480a86cdf263003d5f5dd7f5efc41` failed. Its source tree
matches the originally reviewed slice; the failures are retained as evidence.

- UI Linux 3.12 and offline Linux 3.11/3.12 paper-remaining each reported the same
  five failures. Two assertions detected a fullwidth colon outside the shared
  text catalog. Three found that the new research candidate button and prerequisite
  label had not been admitted to the historical widget/focus/four-state deltas.
- The summary now uses the existing named-value catalog template, preserving its
  displayed text. A narrowly scoped M3 delta admits exactly those two controls;
  the original historical name hash and R7 fixture are unchanged. A new assertion
  pins the exact added rows, disabled button, visible flags, and multiplicity.
- Linux aggregate rejected the unsuccessful producer report. No gate, skip,
  assertion, or historical hash was weakened to accept the failed run.
- Windows 3.12 desktop stopped with a native access violation in unchanged
  `components/help.py::_group_settings_help`, at `action.setText(button.toolTip())`,
  while constructing the automatic-backup test window. An attributable M3 cause
  is not established. The settings-only help group has no direct ownership path
  from the M3 research result button. Linux same-order automatic-backup tests
  passed 8/8; settings-help plus backup passed 11/11. This does not establish a
  Windows pass or prove flakiness. A native Windows base/head reproduction remains
  necessary; no speculative unrelated code change was made.

Focused Linux checks after the correction: no-hardcoded text plus appearance
27 passed; download-import contracts plus R7 characterization 21 passed; M3 UI,
trading UI and desktop pages 67 passed. These groups overlap earlier evidence and
are not added to a cumulative total. Pinned Ruff, affected-file compilation,
layer/trading architecture checks, baseline preview and `git diff --check` passed.
No local full-suite replay was used; the corrected exact remote head still needs CI.

## Repeated CI cancellation: measured LOCAL history work

The unchanged-tree full run
[41606606344](https://github.com/yostar77612/mark-auto/actions/runs/41606606344)
retains two cancellations. Windows 3.11 remaining completed all 4,653 tests in
842.531 seconds with no failures before cancellation during artifact/cleanup.
Linux UI paper-remaining was interrupted near its 15-minute job limit while
processing the WFO tail. No gate was relaxed and no further blind rerun was used.

The matching successful #170 jobs took 700.498 seconds for UI paper-remaining,
469.539 seconds for Windows 3.11 remaining, and 788.707 seconds for Windows 3.12
remaining. #171 took 727.546, 601.544, and 790.626 seconds respectively. #169's
Windows 3.12 remaining passed in 657.875 seconds. Broad differences across shared
modules support runner variability, but do not prove cross-PR CPU contention.

The added M3 integration tests also contribute measurable work: their 24 fresh
real-engine setups add roughly 34–42 seconds in those logs. A local profile of
26 engine constructions attributed 34.892 of 36.196 seconds to the pre-existing
synthetic history generator, which repeatedly resolves the same calendar sessions
for every instrument. This is additional repetition, not slower paper execution.

The narrow correction resolves each immutable calendar session lazily once within
one generator call. It retains the original first-use validation/error order,
empty-catalog behavior, Decimal context, fresh result objects, and all real engine
setup, journal, replay and gateway tests. It introduces no persistent cache.
An ABBA local measurement changed median generation time from 1.102 to 0.292
seconds; wall-clock numbers are observations, not a relaxed test threshold.

Seven new regression cases compare all 20 instruments / 11,440 bars and every
serialized series byte against the original algorithm, bound lookups to one per
day, and check failures plus changed calendars. Independent read-only review
confirmed the oracle AST matches the original executable algorithm and found no
blocker. Focused runs passed: 31 new/history-plus-M3 integration tests; 109 existing
application, execution-environment, broker-session, research-worker, coordinator,
price-band and M3 UI tests; and 74 G3-identity, M2 automatic/daily-runtime and
research-concurrency tests. Counts are separate runs, not a cumulative total.
Ruff, compilation, layers, trading architecture, static gate and mechanical
baseline preview passed. Full CI and native Windows acceptance remain pending.

`runtime/build.py` is outside the 30-file G3 lock. Those files and
`saved_candidate_pool.py` remain unchanged. The v2 current producer digest
correctly includes the new build.py bytes; old-source evidence continues to
invalidate under the existing rules. No historical profile, source-validation
algorithm, workflow, timeout, coverage assignment, skip or existing assertion was
changed. The import-based affected-test tool identifies a broad transitive set;
only the direct generator/engine and sensitive integration paths were run locally,
with complete regression coverage still delegated to CI.
