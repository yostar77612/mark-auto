# Main integration authorization — 2026-10-25

The owner subsequently requested `合並進main`, authorizing publication of this
verified branch, a pull request and merge after CI. This supersedes the earlier
local-only remote-write restriction for this integration; all prohibitions on
real financial operations, credential discovery and Sitecore work remain.

Integration baseline is main `6c2ea528122f4a69cf415e59052fac4fc6233bff` (PR95).
Three overlapping bootstrap files were reviewed. Production `desktop.py` and
`packaging/markauto.spec` retain the already verified v2 bytes, including PR95's
early-worker dispatch. `tests/test_desktop_runtime_bootstrap.py` takes the exact
main version, retaining its stricter literal-hook reader and additional negative
test. Its seven cases passed locally. No production runtime bytes changed in
this merge. The historical full-suite and package receipts below retain their
original commits; fresh remote CI is required for the integrated head.

Integrated local checks: Ruff 0.16.10 lint/format passed (677 formatted files),
646 tracked Python files passed Python 3.11-target AST syntax on Python 3.13.11
(not an actual local 3.11 execution), static/history and v2 architecture gates
reported zero findings, and Git whitespace checks passed. Runtime bootstrap
7, desktop bootstrap 3, worker-import 3, optional packaging 9 and documentation
8 cases passed. The first optional-packaging attempt failed with 11 permission
error entries in the execution host's default temporary directory; rerunning
unchanged tests with TEMP/TMP inside the writable task workspace passed. No ACL,
system protection, assertion or timeout was changed.

### PR96 first remote attempt — failed, preserved

PR96 head `75c21cb5992770dc7b19ed24b92ea348de1598e3`, offline run
`40199547226`, exposed portability/integration gaps and is not acceptance.
Linux core reported AF_UNIX address-length failures, unavailable baseline Git
objects in shallow checkouts, a direct crash-driver import-path failure, and
missing `packaging.requirements` in offline dependency profiles. Windows core
remaining jobs reached their unchanged 15-minute limits after the v2 workload
was added; their partial runs are not passes. All five original job logs are
preserved under the external task audit `main-integration-pr96/failed-job-*`.

Repairs in progress: secure short POSIX socket lifecycle with strict client
validation and unchanged Windows pipe behavior; complete baseline checkout and
hash-locked packaging dependency; a fourth whole-module Windows trading shard
with exact independent union coverage and unchanged per-case/job deadlines;
explicit repository-root import setup in the direct fault-fixture child. No
test is removed or skipped to hide these failures. A fresh complete PR run is
required before merging. Sitecore, original data and financial operations
remain outside this integration.

Local repair evidence: 88 focused CI/worker/coverage contracts passed, including
the original five CoreShardRunner cases (7.767 seconds; original 15-second
child bounds unchanged). The fourth report is mandatory and missing, duplicate,
reclassified, skipped, wrong-attempt and wrong-source reports are rejected.
Actual crash/recovery combinations passed 4/4 in 52.591 seconds: both owned
children were OS-killed, the real lease wait was 31.9975 seconds, reservations
remained and restart never resent. An isolated `python -I` direct-script probe
independently reproduced the original missing application import and confirmed
the repaired fixture loads without opening a journal. Raw logs and import proof
are retained in the integration audit. These focused results do not replace the
pending complete repaired-head CI or claim fresh brokerage/native-load evidence.

IPC repair focused evidence: 12 actual Windows independent-engine tests passed
in 9.200 seconds; six endpoint isolation/cleanup contracts passed in 3.668
seconds. POSIX-only owner/mode fault injection on Windows is not an actual
Linux transport run. The first restricted-tool startup attempt failed after
15.079 seconds with zero executed cases, an empty startup log and an owned
child; exact-child cleanup and evidence were preserved. A subsequently exclusive
ordinary-user run passed without changing its 15-second deadlines. The exact
cause of the initial failure is not proven. Production changes now include the
reviewed Unix socket lifecycle; the old bf5141e runtime-equivalence claim above
does not apply to these new bytes.

The first installer run `40199547250` also failed before freezing: its complete
3.13 suite ran 3531 cases in 1757.097 seconds, with two failures, ten baseline
Git errors and 33 original platform skips. It exposed the same missing baseline
and direct crash-fixture import, plus one Windows short/long-path spelling
assertion in optional packaging. This failed report is preserved separately and
is not an installer pass. Build history provisioning and canonical-path fixture
repair are required; scheduling the growing complete regression separately from
freeze/lifecycle work is under review without raising the 35-minute job bound or
removing a required regression.

Installer repair is now locally verified: 46 focused phase/packaging/version
contracts passed in 4.913 seconds, including missing/duplicate/reordered IDs,
failed fixtures, unknown skips, wrong run/attempt/workflow/head/source/runtime,
stale evidence and tampered logs. Actual private Python 3.13.16/SQLite 3.54.0
discovery found 3556 unique IDs and exactly the original 33 declared Windows
applicability skips; this is independent discovery, not 3556 fresh test passes.
The same desktop lock versions/METADATA and pinned SQLite DLL were verified.
The CI regression producer and build each retain a 35-minute bound. Only a
fresh successful same-workflow/run/attempt/source/runtime full-suite receipt
with every expected case permits freezing; local builds still execute the
original complete suite directly. See `packaging/DESKTOP_REGRESSION.md`.
The repaired source is ready for complete remote validation; the first failed
attempt and all prior source-attributed evidence remain unchanged history.

Final integrated pre-push checks passed: Ruff 0.16.10 lint/format (682 scanned
files), static/history gate zero findings, v2 architecture zero violations,
Python 3.11-target AST syntax for all 650 tracked Python files (executed on
3.13.11, not a local 3.11 runtime claim), native PowerShell parsing of all 14
tracked scripts, and staged whitespace checks. Lint first caught four E402
imports in the direct crash fixture after path setup; those application imports
were moved inside its `main` without disabling lint rules. The final actual
crash-combinations run passed 4/4 in 49.609 seconds, including a real 31.5345
second lease wait and no resubmission. Complete repaired-head remote CI and
installer evidence remain pending; only those new results may authorize merge.

## Current final local engineering receipt — implementationbf5141e

Updated 2026-10-25T13:24:35.882146+00:00. **45local engineering cases passed;5external pending.** Formal acceptance230/300 unchanged. No real brokerage client/login/credential search/order, no Sitecore/original data change, no remote v2 write.

Implementation `bf5141ec3e3b4e4a7559342e29ebbdfb7fccf29f`; portable source `552cff8bab8079ae99ba576f6c9883ece06390c5fc8f929edf83086becd560ea`. bf5141e普通權杖完整分區3511項：3469通過、42項原有平台跳過、0失敗／錯誤／預期失敗／意外成功；完整發現3530項，另19項保留ef04核准歷史通過及bf5141e依賴影響審查，未在bf5141e重跑。

Native150/200 and actual frozen GUI were executed at193; their80 measured production inputs are byte-identical at bf5141e by `runtime-193-to-bf5141e-equivalence.json` and rehash verification. They were not rerun at bf5141e. The fresh bf5141e frozen build separately passed1012payload/68v2sources/8legacy verification, SDK1.7.9 no-login probe, isolated engine restart, TRAINING normal/crash/timeout and help/loopbackTLS. Its original40s synthetic frozen GUI/worker smoke passed29.8433303s with all7steps, no user-state access, and verified owned-worker cleanup, not real-model/account certification. Actual193 Native1800 passed1800.051394s with180000quotes conserved, p9553.4619ms and all original memory/lag gates. Details and exact raw paths: [EVIDENCE.md](EVIDENCE.md), [ACCEPTANCE.json](ACCEPTANCE.json), [START_HERE.md](START_HERE.md).

External only: U01human comprehension,L02real readonly broker,L03actual broker simulation,L04real five-day/closing-baseline provider,L06separately authorized controlled live validation. Defaults remain LOCAL/day-only and broker readonly; no setting grants qualification. The main95installed/data-preserving task is separate. A later docs-only commit does not replace tested bf5141e code; portable/EXE/archive bytes must remain fixed.

The historical19 privilege run is ef04only plus explicit bf5141e impact, not19 new bf5141e executions. Both full reports remain FAILED:193(3467PASS/42SKIP/1FAIL/2ERROR) andc101(3466PASS/42SKIP/1FAIL/2ERROR). The new full uses standard successful-Case ownership and original discovery order, with fixture-owned Qt destruction after original assertions. Two actual ownership proofs and32 original module cases were executed on dirtyc101/portable552cff, matching committedbf bytes, not rerun atbf. They prove lifecycle cleanup, not the exact historical Core15/WinError5 cause or a permanent fix for all intermittent failures. Earlier failures/skips/source snapshots remain history. No remaining local feature gap is asserted after completedbf gates; external recovery steps are in BROKER_READINESS.

---

## Preserved chronological progress before final receipt

# Multi-market v2 implementation progress

## Scope and recovery

- Owner-authorized local implementation; no remote push, merge, release or messages for this mission. No real brokerage operations, login or credential discovery. Never touch Sitecore.
- Worktree: `C:/Users/mark.tsai/Desktop/markauto/multi-market-v2`; branch `feat/multi-market-v2-local`; baseline `4095c3e9fdd2e91f1423d6d1bf76466834cdb417` (main PR93 plus independently tested calendar-scope repair PR94).
- Authoritative specification: `docs/design/multi-market-trading-platform-v1.md`, copied byte-for-byte from the user's untracked original in `.repo`; original remains untouched.
- Original worktrees `.repo`, `auto-import`, `ui`, `winio` and user data remain preserved. This v2 stores local simulation data separately; it does not migrate v1 research or paper data.
- Persistent Goal active. Existing installer task is explicitly exempt from the new mission's remote-write restriction (owner clarification). PR94 merged as main `c392286910ac65a981a0763e17767cd6199fb7dc`; main CI run `40141396361` passed 30/30; installer run `40141396339` completed successfully. Verified download, installation and actual auto-import acceptance are now being completed separately under workspace `main94-validation-20261025`. The multi-market branch remains local only.

## Current milestone

P0–P8 local implementation is integrated. Final independent acceptance, full regression, fixed-source native load and packaging are in progress. `ACCEPTANCE.json` contains all 50 original cases: the last review recorded 40 local snapshot passes, five requiring further local evidence and five requiring independent human/external brokerage evidence. This is not final acceptance.

| Area | Owner / files | Current action |
|---|---|---|
| Domain | v2_domain: `quantlab/trading/domain/`, domain tests | Immutable typed models, explicit calendars, holding/eligibility, fees/risk, restricted strategy rules |
| Ports/adapters | v2_adapters: `ports/`, `adapters/simulated/`, `adapters/shioaji/`, adapter tests/readiness | Fault-injectable remote state and documented SDK mapping; no live calls |
| Presentation | v2_ui: `desktop_trading/`, additive string keys, UI tests | Six workspaces and complete typed application controller boundary |
| Application/storage/runtime | root | Transactional event ledger, fencing, reconciliation, execution/exit coordination, process boundary, composition and acceptance integration |

## Decisions

1. Add v2 modules and an explicit entry point; v1 startup, producer profiles, journal readers, source hashes, one-time OOS budgets and permanent v1 live prohibition remain authoritative.
2. Local simulation is the default and uses explicit synthetic, versioned trading calendars. Synthetic calendar coverage never asserts official exchange coverage.
3. Monetary values are Decimal, wire values decimal strings, timestamps aware; quantity carries SHARE/CONTRACT units. No inferred real futures month or zero-cost fallback.
4. Initial same-account/instrument deployments permit one active strategy owner; transfers require explicit reconciled events. Strategy changes create new versions and preserve existing lot policies.
5. Codebase-memory skill applied. `list_projects` and `check_index_coverage` returned `Transport closed`; bounded source reads/rg are the fallback, with no claim of complete graph coverage.

## Validation and external dependencies

- Baseline sources/contracts inspected. Worktree created without resetting, deleting or staging the user's original draft.
- Domain 44 tests passed; adapters 28 tests passed; layer checker 7 passed; original v1 frozen paper/replay 40 passed. Per-case adapter evidence: workspace parent `multi-market-audit-20261025/adapter-validation/results.json`.
- Actual Qt widgets: 15 tests passed; true application/Qt integration: 5 passed, including 13 synthetic trading days, exits/costs/performance, restart and restricted JSON drafts. These are offscreen tests, not physical display certification.
- Application: initial 25 cases passed after fixes; expanded 27-case run has one obsolete success/no-op expectation for an unknown external flatten request. Implementation now explicitly refuses it; owner is strengthening the assertion to require refusal and unchanged remote state. Final expanded run still pending.
- Native Windows independent process IPC: 11 tests passed (HMAC, bounded invalid requests, account/version boundaries, multiple clients, ownership, independent UI lifetime, clean shutdown/handle release).
- Five-second native load calibration passed with 100 candidates, 20 subscriptions, 5 active strategies and 500/500 quotes. This is NOT the required 30-minute acceptance; p95 refresh 272.54 ms motivates quote-only rendering optimization before the real run.
- Official Shioaji 1.7.9 wheel hash and real no-login Order models verified in an isolated SDK directory. No SDK client, login or brokerage command was executed. Evidence: workspace parent `multi-market-audit-20261025/sdk/contract-no-login.json`.

## Integration fixes already made

- Scope event identity by account, reject changed duplicate payloads and terminal-order revival; quarantine gaps/unknown external active orders rather than assuming successful cancellation.
- Persist the simulated remote exchange separately after submission, including UNKNOWN, and retain reservations across restart/restore. A restored outbox is never blindly submitted.
- Account cash and strategy allocation have separate limits; retain pending entry cash when a partial owned lot exits. Recalculate nonlinear minimum fees and remaining risk instead of prorating them.
- Use one cumulative per-order local fee authority for both simulator and application; preserve explicit unsettled sale receivables and calendar-based simulated T+2 settlement.
- Mark all owned exposures again before new commitment, preserve daily-stop dates, and keep legal protective exits independent of cancellation failures.
- Explicitly reject same-day unqualified stock exits; preserve old lot policy on new strategy versions and require validated transfer destinations.
- Independent engine uses authenticated local named pipes, DPAPI-protected generated control keys and bounded bytes-only typed messages (no pickle). Window close leaves the engine alive; engine shutdown is separate and acknowledged with its final read model.
- SQLite constructors and backups explicitly close handles; backup copies exclude transient ownership leases and checkpoint before publication. No ACL/security setting changes or cleanup suppression.
- Application Decimal calculations use the same fixed context as Domain. UTC wire timestamps, explicit trade dates and quantity units remain authoritative.

## Latest integrated evidence and corrections

- `trading-suite-202.json/.log` preserves the subsequent 202/202 unchanged-source snapshot (0 failures/errors/skips, CPython 3.13.16 / SQLite 3.54.0). It includes real OS-kill recovery with an actual 32.4-second lease wait. Final-source all-project regression remains pending after the corrections below.
- Non-LOCAL contract review found and fixed hard-coded exit/performance environment labels, synthetic source labels and missing shared port DTO registration. Typed broker composition now injects calendar, fee schedule and instrument catalog without connecting or arming execution. Non-local execution requires an explicit cost schedule; account allocation takes the stricter adapter and shared-pool limit.
- Shared `run_cycle` now evaluates reports, risk, holding deadlines, protection and entry rules for every execution environment without fabricated fills or clock advancement. Local `execute_day` composes the same rules with explicit simulator fills and day-end behavior. A fault-capable local port verifies both broker-environment tags, including two-leg roll order, fees and policy origin; these are NOT brokerage executions.
- Explicit non-local session synchronization fixes stale replay dates. All configured accounts require an attested prior-close valuation on the same v2 net-mark/cost basis before new risk. No zero or cash/lifetime-PnL substitute is invented. Reconciliation of account facts stays separate from baseline confirmation; old dated loss locks persist and legal protective exits remain independently executable. Sixteen session/baseline cases passed; the real broker closing-value supplier remains external validation.
- Research teardown now waits for clean child exit inside the original fifteen-minute budget, rather than misclassifying ordinary Windows teardown beyond 500ms as failure. A fixed 800ms diagnostic reproduces the failure before repair and passes afterward; cancellation, deadlines, identity/profile checks and owned-child cleanup remain enforced.
- Physical high-scale inspection found wizard navigation below the screen. Main window and all six wizard pages now fit the actual QScreen available geometry without shrinking fonts, preserving scrolling and keyboard focus. UI 27 + true-facade integration 10 + text-contract 27 cases passed after repair; final native DPR evidence is still required.
- Original PR94 installed GUI successfully completed real HTTPS auto-import (1,140 bars, zero missing intervals), invalid-calendar preservation, download-only preservation, successful retry with exact prior pair in history and actual GUI restart. Pointer restored byte-for-byte; all original 183 files/directories verified unchanged. Evidence: workspace `main94-validation-20261025/MANUAL_PROGRESS.json`. The independent original 40-second smoke remains failed and is being diagnosed under the old task, without changing limits.
- Native packaging review found inherited PATH could collect unrelated Poppler ICU libraries. Final local builds will use a private runtime plus Windows-only process PATH and report actual dependency provenance; no system PATH changes or hand-deleted payload dependencies.
- `multi-market-audit-20261025/trading-suite-185.json` records 185/185 passing tests, no skips, on an unchanged source snapshot. It is retained as historical evidence; final-source tests will be recorded separately.
- True process-kill recovery cases cover interruption before sending and after remote acceptance, wait through the actual 30-second lease, retain UNKNOWN/cash/risk and never resubmit automatically. Separate new cases cover a newly configured stock future, mixed intraday/swing ownership and protective exit while an unrelated account has an UNKNOWN order.
- Independent review found that mobile/manual position differences needed explicit quantities in the UI and fresh execution-time confirmation. The UI now shows signed local/broker quantities, difference, sellable quantity, order references and observation time. Observed external positions are never silently adopted or sold.
- Fresh scope confirmation blocks exits against an externally reversed position. A true facade/widget test proves managed BUY 1 changed externally to SELL 1 cannot produce another SELL and expand the short. Unrelated unresolved accounts do not block a separately confirmed legal protective exit.
- Current fees/specifications revalue durable reservation floors. A new strategy version cannot silently net an opposite existing policy-owned lot. Deployment verifies the full current research fingerprint; changed producer sources require new-entry research, preserving old positions and historical evidence.
- Research runs in an owned cancellable process; engine safety commands remain responsive during stalled research. The native research worker, IPC and adapter fault tests are retained under the audit directory.
- Pinned private builder: CPython 3.13.16, SQLite 3.54.0 and all 18 hash-locked desktop dependencies. No system Python replacement, association, PATH or security setting changes. Build preparation and hashes: `multi-market-audit-20261025/local-build-preparation.json`.
- An earlier 30-minute probe was deliberately aborted after the review found fixable acceptance gaps. Evidence is retained as `native-load-30m-interrupted.json`, explicitly NOT a pass. A fresh full 1,800-second run will use final unchanged sources and original performance limits.
- Native Windows overview was visually inspected and saved under `multi-market-audit-20261025/screenshots/`; actual six-workspace, wizard and 150%/200% application-scale checks are still pending. Offscreen widget tests are not described as physical-screen certification.

## Work still actively underway

- The first whole-project integration run executed all 3,377 cases in 2,688.854 seconds. Its raw 11 failures / 21 error entries / 42 existing platform skips are preserved as `full-regression-6dd4-diagnostic.json/.log`; this is explicitly not a passing result. Nineteen unique existing symlink cases require Windows privilege (one has two failing subcases); other failures identified real compatibility/fixture gaps and were repaired below.
- Restored `quantlab/errors.py` to exact baseline bytes and moved additive errors to `application/errors.py`, preserving every legacy catalogue count/hash/golden. Legacy error/guidance and strengthened v1/v2 submission guard regressions passed 35/35.
- Preserved the legacy page-service inventory exactly, including all six original counts and patch points. V2 market history is now an explicit bounded typed constructor resource, rather than opportunistic test mutation; unrelated v2 fixture field names no longer masquerade as legacy shell aliases. Seventy focused resource/broker/worker cases passed; additional malformed/duplicate/reversed history rejection passed with ownership clocks injected consistently.
- The v1 two-call-site and intent-writer oracles remain unchanged. The authorized v2 boundary has its own exhaustive five-call-site/unique-commit inventory plus risk/reservation/durable-intent/fence order and real rejection/no-extra-submission tests. The engineering scope is recorded in `UPGRADE_CONTRACT.md`.
- Whole-suite wizard failures were isolated to a shared QApplication exit state left by an earlier legacy startup test. The integration fixture now uses a real outer application loop and its actual active modal, retaining the original assertions and five-second bounds. The minimal failing order became passing, then the legacy startup + 29 widget + 10 true-facade cases passed 40/40; production UI was not altered for this fixture repair.
- Offline preview had a genuine lifetime gap: a later readiness refresh could re-enable Releases. Preview-only lifetime availability and direct-handler guards now keep it offline across queued callbacks. Both new cases and all five original preview cases passed, while explicit normal-app maintenance actions remain available.
- The original SQLite hook literal and legacy version-resource assertions are preserved by appending the early worker hook as a separate static list. Exact two-hook ordering and rejection of dynamic expressions remain independently checked; no legacy expected value was changed to obtain a pass.
- Windows permission completion is being prepared as an exact partition: the same nineteen pre-existing symlink cases only in a user-approved one-shot elevated process, every other discovered case in an ordinary process, disjoint union checked and original platform skips retained. No ACL/developer-mode/security change is proposed; no case is removed or relabelled as a pass. Previous 19/19 privileged evidence from `winio-audit-20261024` is retained as historical evidence, not a claim that this final source/runtime has already passed.
- Old installer follow-up is now separately owner-authorized as PR95, head `23b1a2e983d9db619d4c2f7d100ec82530dee3c9`, containing only the five bootstrap/packaging files. Its exact remote tree matches local `07c52d9`. Native complete smoke passed 34.2136484 seconds under the original 40-second cap, with every step, 22 evaluations, two folds, helper and cleanup intact. PR95 full CI/main installer acceptance is still underway; no multi-market code was pushed.
- Finish final independent combinations and final-source fault regressions; broker settings/readiness, controlled composition, corporate actions and two-leg expiry rolls are implemented and locally exercised.
- Run the full 30-minute native load, physical-screen checks at required layouts/scales, local build, v1 regression and all 50 evidence rows. External human/broker checks stay pending with reasons.
- External: actual Shioaji read-only login, broker simulation, account/CA/eligibility evidence, controlled real trading (prohibited this mission), independent user comprehension and clean Windows certification must remain separate from local evidence.
- SDK support will be based on official documentation and a pinned contract, not guessed field names. API credentials are neither requested nor searched.

## Next concrete actions

Finish fresh-scope/evidence regression, freeze production sources, run full v1+v2 regression and native 30-minute load, create a recoverable local commit, build and inspect the frozen desktop at required scales, then reconcile every acceptance row with exact-source evidence. In parallel finish PR94 main installer validation without affecting v2 sources or original user data.

## 2026-10-25 10:40 recovery checkpoint

- User approved and completed exactly one UAC partition: `partition-privileged-ef04cd4-final.json` proves all 19 unchanged legacy symlink cases passed, zero skips/failures/errors, elevated=true, exact ef04 source digest unchanged. No ACL, developer-mode or protection changes. Do not launch a second UAC without fresh authorization.
- The ordinary ef04 partition executed all 3,365 remaining cases in 2,412.332 seconds: 11 failure entries, 102 error entries and 42 original platform skips. Raw JSON/log are preserved; this is NOT a pass. The audit runner's deep disposable profile created Windows path-limit errors; 83 of 85 profile-related error blocks have explicit WinError 3/206 evidence. Two others and timing failures remain separately investigated.
- Ordinary short-profile focused tests proved capital read-only and both user-state-preservation scenarios pass. The initial restricted-token focused attempt produced WinError 5 and remains failed evidence; the normal-user-token repeat fixes that access issue but exposes four original 40-second terminal timing failures. The original time limits, worker isolation, cleanup assertions and expected outcomes remain unchanged. Domain owner is profiling the actual bottleneck; no blind full rerun.
- Native ef04 UI at measured DPR 1.5 and 2.0, physical frame budget 1366x768 and 11pt, displayed every wizard page and reachable navigation. Actual stock workflow: create, validate, research, deploy, reconcile/resume, BUY 1000 on 2026-10-29 with sellable=0 and EXIT_BLOCKED, hold five trading days, reduce-only SELL 1000 on 2026-11-05, net 129 and paid costs 71, no remaining positions. A second interface loaded the same engine state. Both QA interfaces and the owned private engine were then closed normally. Raw evidence: `native-ef04-visual-summary.json`, entry/exit/restored DTOs and screenshots.
- That visual test found a real metric-source defect: displayed drawdown 5492 came from TRAINING research rather than this execution's recorded valuation path (170). This prevents final acceptance. UI owner is adding a typed durable per-version recorded-equity track, shared liquidation arithmetic, honest unknown history for old records, restart/failure tests and a clear label; no research result or risk limit is rewritten.
- Ef04 local frozen candidate passed exact raw-source/inventory/license/hash checks, real frozen training normal/crash/timeout/cleanup, two native independent engine startups/readiness persistence and original help/TLS caps. Portable ZIP is retained as a superseded diagnostic candidate after the newly found performance defect; do not call it final or install it as final.
- Old installer PR95 was separately authorized, full PR CI passed and merge to main succeeded at `6c2ea528122f4a69cf415e59052fac4fc6233bff`. Main offline run40152818019 has 30/30 successful jobs. Installer run40152818029 static/build/release all succeeded and published `desktop-preview-40152818029-1`. Exact main release is downloaded under `main95-validation-20261025`; all asset/provenance/source checks and installation preparation are underway. Main checkout was fast-forwarded; original untracked master draft remains unchanged. No v2 source was pushed.
- Next: finish targeted timeout and UI-thread diagnosis, integrate the performance correction, refresh the final regular-test context with a short isolated profile, run unchanged full regression and the strict real 1800-second native load, rebuild and visually verify frozen v2; install/test exact main95 with original-data hashes. Retain the ef04 privileged proof with explicit dependency-impact evidence if subsequent changes only affect unrelated v2 paths; never misstate different source digests as identical.

## 2026-10-25 11:08 recovery checkpoint

- Normal-token, short-profile regressions isolated the remaining two saved-pool cases: both original cases passed in 7.806 seconds; the single earlier 145-character WinError5 rename did not reproduce. Keep that observation as unresolved transient contention evidence, not a permanent root-cause or ACL-fix claim. Full final regression remains required.
- Legacy UI operation workers now avoid Qt/page imports while resolving their explicit registrar. Process-local role plus actual multiprocessing-parent confirmation prevents parent import-cache poisoning; default registrar, JobManager class and MainWindow class/AST remain unchanged. Actual spawned worker rejects accidental GUI construction, while parent-first registrar lookup still creates the real GUI. Twenty-three compatibility/import/architecture cases passed. Of the seven original source-smoke cases, six passed together; the final case passed alone in 36.7717 seconds with unchanged source and the original40-second/22-spawn/63-save assertions. Its earlier run overlapping heavy research is retained as failed evidence. Final strict timing tests must run without competing test/build workloads.
- The first performance correction passed 103 related functional cases plus 87 finishing cases (including import graph, 11 meaningful performance behaviors, widgets and text). Independent read-only review then found a real transfer-price race: deferring cashflow-neutral attribution until the next mark wrongly assigns post-handoff price changes to the sender. UI owner is now fixing ownership and valuation attribution in the same durable transfer event and adding changed-quote/restart/append-failure coverage. Do not freeze, build or claim final acceptance before that fix passes.
- Exact official main95 installer was installed successfully into `is-42455`; EXE SHA256 `5d67533a74340571824e49b3c10c406e2d2ba5418c012810a4ca3b680d447435`, all978 inventory rows and exact physical file set verified. Both older `is-VG4DC` and `is-D95FT` payloads remain unchanged. Native installed complete smoke passed in 38.286565 seconds, returncode0, timed_out=false, owned cleanup verified; original40-second cap and every step retained. After installation and smoke, all183 original files, directory set and pointer bytes still equal the preinstallation backup; credentials excluded. Actual UI download/restart inspection is being prepared in fresh main95 isolated state.
- Next: finish main95 fresh actual UI flow and restore pointer byte-for-byte; finish/review atomic transfer repair; commit the final local v2 source with exact new test inventory, then run a single short-profile ordinary full regression and a separate strict1800-second native load. Rebuild/verify/inspect final frozen v2 only after the engineering defects are closed. No v2 remote publication or Sitecore access.

## 2026-10-25 11:24 integration freeze preparation

- Main95 actual installed GUI has now completed real HTTPS TAIFEX auto-import:1140bars, validquality, missing0, exact archive/member identities and expected complete day/night calendar. Actual normal close/relaunch visibly loaded1140 again; active dataset/calendar hashes unchanged. Both GUI processes closed normally. Original workspace pointer restored byte-for-byte and all183 original files/directories verified unchanged after actual GUI. Exact evidence and screenshots live under main95-validation-20261025. This completes the authorized old installer repair acceptance on this host; clean-machine certification remains separately described, not asserted.
- Atomic version handoff correction passed104 final integrated cases and independent original-race plus restart-before-quote reproductions. Correct results: sender428/DD170, receiver-299/DD299, aggregate129; partial realized profits stay with executed-order attribution. UI separately labels attributed net-liquidation PnL. Durable owner/tracks share one append; write failure keeps both previous values. Old missing valuation tracks remain unknown.
- All worker/performance owners are idle and have frozen their sources. Reviewed scope:19 files including additive performance model/tests, guarded worker imports and documentation; no v1 research core/profile/golden changes or test deletion. Prepare one local recovery commit, then refresh exact final test context. Do not perform build/research/other40-second workloads concurrently with the full ordinary suite. Run1800-second native load separately and keep its window foreground; earlier interrupted/failed probes remain evidence, never passes.


## 2026-10-25 runtime integration recovery

- Frozen baseline22d ordinary partition finished:3384run/3336passed/42existingplatformskips/2failures/4errors,3026.525seconds. This is not a pass. Exact source remained7f6a427dfdb814904b9c2e82a943b3cfc4c6f46493e5753aa7494aaed176a1de. Raw report/log and six-failure classification remain in the audit directory.
- Remaining defects: original15-second synthetic shard startup; two short-path Windows rename denials (one diagnostic bypassed the shared rename authority); parent cp950 subprocess decoding because UTF8was configured after interpreter startup; one original40-second WFO startup delay; one Qt finished-delivery test under earlier shared application state. Original assertions/timeouts/platform rules remain unchanged. All subsequent runners start with-Xutf8/PYTHONUTF8before interpreter startup.
- Final acceptance exposed a genuine standard-host gap: nonLOCAL modes and broker-account selection were not wired through normal desktop/runtime composition. A separate local staging worktree v2-runtime-wiring (branch feat/v2-runtime-wiring-local, base22d) preserves the frozen baseline while completing explicit profile/context routing, asynchronous read-only connection, normalized query cache, bounded host pump and durable public version fencing. No real SDK client/login/order or credential discovery is permitted in local validation.
- Read-only query/reconciliation is separated from execution: collect normalized reports outside the book lock; discard if commands changed the book; reconcile authoritative reports without synthetic fills; observe risk without submitting/canceling. Read-only STOP remains available. UI unknown broker facts stay unknown.
- Real SDK1.7.9 source supports contracts.get/info/tick_bands. Native constructorless checks prove types/enums/API availability only; info-instance fields remain official-source evidence, not an authenticated runtime result. Generic Decimal price bands are being integrated so stock-future price-dependent ticks do not require a post-account-opening code change.
- Exactly one user-approved UAC partition remains historical19/19ef04evidence with explicit impact review. No second UAC has been launched. Main95installation/native download+restart/original183file+pointer verification is complete; only local multi-market development continues. Sitecore and original user data remain untouched.
- Next: functional targeted integration, unchanged timing diagnostics in an exclusive window, final-source ordinary full partition, native150/200desktop QA, strict foreground1800-second load and exact-source frozen build; then all50acceptance rows. Genuine broker/human/environment checks stay external.


## 2026-10-25 runtime integration verification

- New context/CLI/Qt integration passed102cases including18newcases and all30original UI cases. A definite fixture defect was observed: deleteLater/processEvents retained75top-level/3220child widgets; explicit DeferredDelete cleanup now proves each owned C++window is destroyed and zero widgets remain. Original3-second drain/assertions are retained; production QThread was not changed. Logs:staging/t/context-ui-static-final.log and ui-event-before/after-cleanup.log.
- Runtime/context/cache/broker first integration passed21new+23existingfunctional cases plus stampfailure/restart. Independent source review then found old nested broker timestamps could be renewed by cache receive time, and a dedup return could bypass expiry/session rollover. These are real defects and the earlier21/23results do not certify their repair. Shared normalized account validation now checks identity/environment/envelope time/nested account time; both manual and background reconciliation use it. Session synchronization precedes dedup. Cache owner is adding the same authority to publication/getters.
-11focused application cases now pass: fresh observations, no duplicate journal churn, expired/future/nested reports, session rollover, actual manual query validation, STOP during stalled query, daily-loss stop without cancel/submit, duplicate quarantine, nonLOCAL exit pending actual fill, and immediate presentation UNKNOWN after expiry without mutating the book. Successful reconciliation retains typed volatile observations; display never renews financial truth while waiting for the next pump. Raw:workspace/t/readonly-facts-final.log.
- Frozen functional combination before these review fixes ran60cases/59pass/1newfixturefailure in194.216s. The failure injected paid costs without corresponding net-realized accounting; the corrected new fixture passed without changing the10001expected loss. The preceding61case run had2honest source_invalid_evidence rejections while other owners edited producer sources; both original performance cases passed after code stopped changing. None is relabelled as a whole-suite pass.
- Win5 observer ran the unchanged historical range case5times plus complete pinned WAL ABBA diagnostic:6/6pass,746native rename attempts,4realWin5transients recovered by unchanged retry in2.8–3.4ms, no exhausted retry. Diagnostic replay now uses the existing shared rename authority; original export failure assertion still requires a failure. A new injected contention case proves exact snapshot retry/count/hash without repeating commits. UTF8prelaunch restored unchanged exact tracked-layout and actualPowerShell parser cases:3/3pass with no reader decoding warning. This does not identify a third-party lock holder for the earlier exhausted100ms event and does not claim an ACL fix.
- Price bands passed100functional cases including actual application research/deploy/entry/holding/exit and144relatedarchitecture/import/legacyguards in earlier source scopes. Independent review found stock has no SDKtick_bands authority:1.7.9supports that API for futures/options only. Stock owner is adding explicit source-attested public ISIN classification and versioned official exchange common-stock/plain-TWD-ETF grids, rejecting unknown/scalar/mismatched profiles. Local synthetic specs and original170/71/129execution oracle stay unchanged. External provenance/actualbroker checks remain pending, not inferred from configured metadata.
- Next: finish cache/stock-resource integration and freeze allcode; one focused integrated pass, exclusive original15/40second timing profiling, fullfinalordinarypartition and historical19permission dependency audit, then native/frozen/1800secondload/all50evidence. Goal remains active; no v2remote write or Sitecore access.


## 2026-10-25T14:07:55+08:00 final source integration

- All runtime/domain/UI owners are frozen and have no test/GUI/build processes. Staging integration executed178cases;20unique cases failed solely because the new external audit runner lacked the Windows __main__ guard (21failure entries including two subtests). Raw failed report/log retained. The guard was repaired; all20affected original cases passed82.942seconds with producer source unchanged. This is two focused runs, not a fabricated whole-suite pass. Full final discovery/run is still required.
- Time-dependent valuation now reports UNKNOWN for an entire open strategy version when any quote/position facts are unconfirmed, including pure time expiry without a new version or quote stamp.90focused cases passed including6newfreshnesscases and all30original UI cases. Realized PnL, costs, historical attribution/drawdown and the original170/71/129oracle are retained.
- Exclusive unchanged core-shard15-second case passed5.9996seconds including its two child subcases. Transparent profiling measured the real before/after scans below2seconds per child and did not reproduce the old15-second failure; no scanner/timeout was changed. Exclusive original40-second join-failure case passed29.772seconds, all7smoke steps and cleanup/evidence assertions retained; source before/after exactly70b050e4549e24a735726559d541ac515e68ef74d269c96a6a1ba58542809777. Raw observations preserve the intentionally failed product smoke as required by that injected-failure test. Neither observation erases the earlier full-run timing failures.
- Discovered and closed frozen SDK gap: the default18dependency offline build excludedShioaji, so another venv could not enable a frozen executable. A separate explicit broker-enabled portable recipe now uses existing hash-locked1.7.9wheel, verifies every SDK/native/metadata file, preserves the original default Analysis/SQLite/early-worker hooks, excludes standalone CLI/server, and has a genuine EXE no-login probe to run after freezing.37focused packaging compatibility cases passed. Private source-runtime SDK probe passed but explicitly remains frozen=false; it is not frozen acceptance. No realclient/login/CA/asset operation occurred. The package includes a clear Traditional-Chinese launcher/readme and its own relativeData/platform-v2 root, preserving v1 data and legacy entry behavior.
- Full Ruff check/format passed674files, Python3.11syntax passed644trackedPython sources before the last gate-only hardening. Static gate and architecture now return0findings. ActualSDK import is explicit only inside adapters/shioaji/sdk_loader.py:load_pinned_sdk; process spawning only has a narrow research-gate exception for runtime/context_client.py. Original research/std-library/desktop/dynamic-execution restrictions remain.73original+newboundary/bootstrap/packaging cases passed; independent source audit then found metadata mutation/reflection escape in the new loader allowance. AST parent-use checks now permit only version reads or explicit module return and reject mutation/alias escape/reflection/client construction;18focused original+adversarial cases passed and architecture remains0violations. The original v1 immutable source/profile/journal comparison passed.
- One restricted-token static-test attempt failed in its sandbox temp permissions; rerun used the known normal-token/short-profile environment. One selector referenced a nonexistent module; the exact existing desktop_bootstrap/runtime_bootstrap modules were subsequently executed successfully. These harness failures are retained and do not alter product assertions or permission policy.
- Load report publication now reuses the existing bounded atomic-write authority, isolated from optionalQt; transient sharing and permanent denial tests both passed. Persistent denial cannot publishPASS or destroy prior evidence. The report helper is included in load source hashing.
- Next order: create a local recovery commit, fast-forward the owned primary v2worktree, inspect actual production-composed source UI at150/200including new contexts, build/verify the exact frozen candidate, run separate strict1800second foreground load, then the final full ordinary partition in one exclusive window. Native QA precedes full regression so any layout/frozen repair is included in the final source run. Finish all50evidence rows and historical19permission impact audit after successful checks. Multi-market remains local-only; main95installed/data-preserving acceptance is already complete; Sitecore remains untouched.

## 2026-10-25 native and frozen 93a checkpoint

- Local recovery commit `93a967c44bca1ef363aaa358366cb5c117b2a2e4` was fast-forwarded into the owned primary branch. No remote write. Actual source-production windows at measured Windows DPR1.5/2.0 and physical1366x768/11pt passed six wizard pages and reachable six workspaces. Actual LOCAL stock flow entered1000shares on2026-10-29 with day0/sellable0/EXIT_BLOCKED, exited after5tradingdays on2026-11-05, net129/cost71/recorded-equity drawdown170. Source UI reopen and real frozen EXE restored the same isolated strategy/history. Disconnected simulation/LIVE contexts displayed unknown financial facts and no copied LOCAL balances; empty unverified lists never certify real broker flatness. Evidence `native93-visual-summary.json`,23PNG hashes, entry/exit DTOs and geometry metrics.
- Genuine broker-enabled portable build passed:1012payload files,68exact raw v2sources,8exact legacy producers, launcher/archive/hash/Qt-license checks. Real frozen SDK1.7.9/native core loaded without client/login/CA/asset operations. Actual frozen research normal/crash/timeout cleanup passed original30s supervisor; two engine startup/readiness/restart runs passed35s supervisor; original help15s and isolated TLS20s passed. Evidence `frozen-build-93a967c/` and `dist/broker-enabled/`. This remains a local candidate, not remote CI, a clean-machine certification or broker validation.
- First30min load stopped456.224s after45620/45620quotes with p95~65.6ms/memoryPASS but F5-start assertion failure. A second instrumented unchanged trial stopped758.003s after75800/75800quotes. It conclusively recorded WindowDeactivate, Qt/OS foreground mismatch and no shortcut activation; all756previous refreshes started/rendered/completed,0queryfailures. Original failed receipts retained with unchanged source and verified normal engine shutdown. The old first failure lacked focus evidence and is not retroactively assigned a proven cause.
- Independent native diagnostic proved140active F5clicks succeed and3inactive-window clicks reproduce the failure. MasterU06 requires actual local button response; it does not require foreground ownership or F5. Narrow correction adds a real accessible Market refresh button connected to the existing production refresh, retaining F5 unchanged. The benchmark clicks this actual button and measures request, successful render and operation completion; failed/mismatched/duplicate responses cannot count as latency successes. Original1800s,100quotes/sec,100candidates/20subscriptions/5strategies,p95<=300ms,64MiB growth,1MiB/min tail slope and1s quote-lag limits remain unchanged. Six sample/fault cases passed; genuine native button/keyboard integration is in progress. No production trading/SDK/risk behavior changed.
- Historical approved19symlink cases remain ef04 executions with exact93a dependency-impact report; no new UAC. Full final ordinary regression, final button-based native load and refreshed frozen candidate remain required after this narrow integration. The original main95installation/data proof stays complete; Sitecore and original data remain untouched.

## 2026-10-25 full 193 execution and test-fixture corrections

- Code commit `193b784612e037df344dc91eb7e8c7dbb0daba80` passed the actual Windows1800-second button load:1800.051394s,180000sent/acknowledged/applied quotes,1796successful rendered completions,0query failures,p95=53.461900ms,maximumquote scheduling lag0.016535s. UI/engine memory growth and tail slopes pass unchanged64MiB/1MiB-per-minute limits. Source identities remained exact and normal engine shutdown was verified. Raw `load1800-193b784.json`; the preceding5s calibration is explicitly onlySHORT_VALIDATION_PASS, not30min acceptance.
- Final193broker-enabled frozen build again verified1012payload files/68exactv2sources/8exactlegacyproducers and SDK1.7.9no-login native probe. Originalresearch30s/engine35s/help15s/TLS20s supervisor caps passed; real frozen UI restored129net/71costs and its new Market button was physically operated. Source193Market page was physically inspected/operated at measured1.5/2.0DPR,1366x768physical budget/11pt; scrolling retained context and readable values. All owned interfaces and engines were closed normally.
- Complete193discovery is3530unique cases,3511ordinary plus the fixed19historical permission IDs. Full ordinary run used normal non-admin token/prelaunchUTF8/freshshortTEMP `t/q`; initial `t/p` reservation was refused before any test because old data existed, and it was preserved. The full run executed3511cases in2475.264s:3467passed,42original platform skips,1failure and2errors in two subcases. Source before/after exactly `fef4ac14132228016ccdd6d1f1c4c80f20121d5819d8813f88b9d6c6fe9224df`; this failed whole-suite receipt is preserved and is not relabelledPASS.
- The six older22d failures/errors all passed in this complete193run, including original15s core case2.803700s, original40s terminal join-failure case29.742827s, saved-range guard0.968858s, exact root layout0.187770s, pinned WAL ABBA10.289651s and original broker-reference UI0.091593s. Original assertions/timeouts, retry100ms/sevenattempts and all existing permission guards remain unchanged. This does not identify a third-party holder for an earlier transientWin5 and does not claim an ACL change.
- AST-only inventory audit proved one extra observation and no service/alias/copy or old-observer difference: the new optional SDK test used `self.contract` for a hash patcher, colliding with a conservative legacy widget-name scan. Rename only its three references to `self.sdk_hash_patch`; preserve historical BASE/download delta and every exact inventory assertion. All15original inventory/interface tests and9SDK package cases then passed.
- Both controlled nonLOCAL subcase errors were exactly old3argument private `_dispatch` calls against the upgraded2argument RuntimeBundle interface. Update only test setup to bind the same real injected engine/facade to RuntimeLaunch/RuntimeBundle and a separate actual version Ledger. Original entry/fill/protect/performance/environment assertions remain; wrong-account, configuration identity, persisted highwater and no-extra-checkpoint assertions were added. Normal native token verification passed both module cases plus6realIPC host guards (8/8). An initial mistakenly restricted-token guard run failed named-pipe readiness/cleanup; its log and exact-owned-process cleanup are retained separately. Product code was not modified to accommodate this test setup.
- Next: local test-only recovery commit, prove all193runtime-load inputs unchanged, refresh whole-source context, rebuild the matching local candidate and rerun the complete ordinary partition in a fresh shortest profile. Reuse the native193load only with explicit exact runtime-file equality, not a false new execution claim. Final all50documentation remains blocked until the new whole-suite receipt passes. No remote v2write, real broker login/order, original-data overwrite or Sitecore access occurred.

## 2026-10-25 complete c101 regression and fixture ownership correction

- The complete ordinary c101 run executed3511cases in2711.327seconds with unchanged source `59387fc7fed62e049f98a055052768808f8973d13a0aa3b2aee8b2932c020274`:3466PASS/42original platform skips/1FAIL/2ERROR. Raw `partition-regular-shortest-c101f45-final.json/.log` remain FAILED. The original Core stdout-reader join exceeded15seconds; the connection diagnostic returned1 after38.883seconds but its original temporary report was removed; one221evaluation saved-journal case exhausted the unchanged Windows rename authority withWinError5. None is relabelled a pass or assigned an unproved antivirus/ACL cause.
- Sequential one-case audit observations retained every original assertion and deadline: Core two actual children completed with native exit1/0 and unrestricted/non-admin token; the full10case connection ABBA completed32.373855seconds; the original221evaluation journal case completed575renames with2transientWin5 recoveries under the original100ms/seven-attempt authority. A separately labelled first-denial background owner snapshot returned no owners after promotion; it does not establish absence or causality. Source review found no retained writer handle or unguarded cooperative writer in that snapshot path. No ACL/security change, second UAC, evaluation replay or budget refund occurred.
- A concrete external audit-runner defect was found: both `discovered` and `selected` retained every successful TestCase through the whole run. The new audit runner constructs the identical suite and releases those redundant lists, restoring standard unittest ownership; IDs/order/fixtures/failure-and-skip ownership and all15/40second gates remain unchanged. Historical runners and reports remain intact. This alone was not sufficient to destroy native Qt objects and is not claimed as the cause of the historical errors.
- An actual original pre-Core Qt test proved its closed MainWindow and9inactive QTimers survived Case collection. Two fixture cleanups now explicitly destroy only their owned window via targeted DeferredDelete after all original close/invisible/jobs assertions, and require the window plus every owned timer to be natively invalid. The shared helper imports Qt lazily. Analysis recovery composes this final cleanup on its existing registration line, preserving its original cleanup method and exact137source observer. Historical BASE/download delta and expected inventory results remain unchanged.
- Both bounded actual ownership modes passed with verified owned-process cleanup: retained7.493567seconds and released4.958424seconds, native matching windows0 and valid timers0 even while Case/wrapper references remain. These are offscreen QObject-lifetime proofs, not new physical-screen or broker tests. The two complete original modules passed12/12 and5/5; all15original page-service/inventory tests then passed. Exact fixture-source portable SHA256 is `552cff8bab8079ae99ba576f6c9883ece06390c5fc8f929edf83086becd560ea`; production application/SDK/risk/producer sources have not changed.
- Evidence: `core-flake-observer-c101/harness-ownership/actual-retained-1.json`, `actual-retained-v2-1.json`, `actual-released-v2-1.json`; `fixture-modules-analysis-18e06b66/`, `fixture-modules-restart-25087ce2/`, `fixture-modules-inventory-f5bce7ba/` under the outer audit directory. Independent source review confirmed original assertions/deadlines, callback order, lazy imports and unchanged inventory observers. Earlier prepared763case prefix and five-process CI projection are not executed or claimed as passing full coverage.
- Repository-wide Ruff check/format passed676files; Python3.11target syntax parsed646trackedPython files with0errors (not a claim of3.11runtime execution). The static gate and trading architecture gate both report0findings/violations. Git whitespace checks passed. The fixture composition and new external runner each received independent source review; the latter preserves standard result ownership and every original case/fixture/deadline.
- Next: save this local test-fixture recovery commit, refresh the exact full context and current build, rehash the80measured native runtime inputs and historical19dependency review, then execute the same3511ordinary cases in original order with standard Case release. Final acceptance remains blocked until that complete unchanged-source report passes. All multi-market work remains local-only; original user data and Sitecore remain untouched.
