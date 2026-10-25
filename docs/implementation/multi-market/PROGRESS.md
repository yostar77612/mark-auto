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

- Finish final independent combinations and final-source fault regressions; broker settings/readiness, controlled composition, corporate actions and two-leg expiry rolls are implemented and locally exercised.
- Run the full 30-minute native load, physical-screen checks at required layouts/scales, local build, v1 regression and all 50 evidence rows. External human/broker checks stay pending with reasons.
- External: actual Shioaji read-only login, broker simulation, account/CA/eligibility evidence, controlled real trading (prohibited this mission), independent user comprehension and clean Windows certification must remain separate from local evidence.
- SDK support will be based on official documentation and a pinned contract, not guessed field names. API credentials are neither requested nor searched.

## Next concrete actions

Finish fresh-scope/evidence regression, freeze production sources, run full v1+v2 regression and native 30-minute load, create a recoverable local commit, build and inspect the frozen desktop at required scales, then reconcile every acceptance row with exact-source evidence. In parallel finish PR94 main installer validation without affecting v2 sources or original user data.
