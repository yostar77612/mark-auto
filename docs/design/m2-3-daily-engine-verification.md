# M2-3 daily close and next verified session

PR147 starts directly from main e5a5941 on codex/m2-3-daily-next-session.
The first small commit3b67a10 establishes the DTO/error/action contract.
The owner requires Claude review after green CI; this agent must not merge it.
This completes the daily path deferred by the previous M2-3 R5 slice.

## Behavior

Actual finalized, complete daily buckets claim the existing durable cursor once.
The close phase saves researched ENTRY/owned-lot EXIT identities atomically with
evaluation completion. It never submits or reserves money. The next supplied
verified DAY is the only eligible execution date, open inclusive/close exclusive.
Current quotes determine size and limit price under the existing FeeSchedule,
current account ownership, funds, preflight and risk checks. There is no inferred
holiday, later-day catch-up or promise of an opening-price fill.

Normal calendar waiting preserves an authenticated owner-bound run. A disconnect,
changed owner, restart, user stop, risk or unknown result revokes it. Explicit
AUTO_RECONCILE resolves facts without resuming; AUTO_RESUME is still required
after a fault. A dispatch claim is durable before the original single execution
commit. Interrupted dispatch stays UNKNOWN, retains reservations and never
automatically retries. A pure interrupted daily evaluation may only be discarded
by explicit reconciliation with exact journal provenance and no saved action or
matching order; its cursor remains consumed and automatic execution stays paused.

Closing evidence uses actual SHIOAJI verified bid/ask, complete post-close scoped
observations and exact application-ledger/calendar/fee fingerprints. It does not
claim broker-funds authority. Dated account baselines are committed before new
day legs and cannot be silently repriced after consumption. Old-order economic
changes invalidate the proof. Shared manual book capital/opening history, user
stops and daily loss locks are retained. No current price impersonates prior close.

Mixed stock/TMF waiting still permits completed-bar owned normal reductions in
an actually open market. New entries retain full current all-account admission.
Only background stale marks of explicitly closed accounts may be deferred during
normal waiting; open-account risk monitoring and submission-time guards remain.
Accepted scoped quantity caches survive an unavailable aggregate valuation.

## Verification and limits

All broker tests use the existing native SDK double and fixtures, with no real
keys, CA, broker login or financial query. Real daily research/deployment, raw
minute callback composition, close-only persistence, current-price whole-lot
dispatch, saved daily EXIT, once-only cursors, mixed-market reductions, restart,
owner change, unknown reservation retention and LIVE rejection are exercised.
The original trading_runtime._run_window is used for LOCAL and fake broker SIM,
including actual window creation and owned process/endpoint cleanup.

Independent production guard mutations run in isolated subprocess memory; source
files are never temporarily weakened. Baseline PASS and test-body failures are
required where recorded; setup, loader, cleanup and source mismatches are not
counted as successful kills. Structured results retain exact per-case traces in
the local .gitnexus/verification directory; the adjacent JSON summarizes evidence.
The related modules are selected with tools/affected_tests.py; full discovery is
reserved for CI. Generated inventory/observer baselines form one separate commit.

The seven dedicated new test modules contain196 focused tests. Independent guard
mutations total347/347: daily state91, closing valuation70, manual/day monitors52,
pure-evaluation recovery35, runtime/native daily exits73 and final commitment26.
The runtime73 includes its earlier25 stable owner/engine cases only once. Final
formatted source mutations were rerun; exact hashes are in the adjacent JSON.
Original window startups return0: LOCAL6.075s and fake-SIM3.606s, each2807 widgets,
research attached/released, no real SDK import and owned endpoints removed.
Offline pre-push lint/format, tracked Python syntax and credential gate pass.
The final R8-related result and complete final-head CI are recorded on PR147;
the CI checks remain authoritative. Neither a focused pass nor these startup
checks substitutes for green full CI or the required Claude review.
Real broker automatic acceptance and UI rendering remain owner/desktop-lane work.
M2-7 minute research and M2-9 costs/data are consumed through existing interfaces;
this PR does not implement or claim their acceptance. LIVE remains hard-disabled.
No desktop_app/, G3 lock, SDK pin, PROJECT_STATE, costs.py, workflow, packaging or
layer rule is changed. Existing LOCAL day stepping and protective exits remain.

GitNexus pre-edit shared-state impact includes AutomaticView CRITICAL101,
AppState HIGH86, engine HIGH85 and account monitor HIGH25 upstream dependencies.
These include snapshot/IPC, codec/startup, manual and automatic commitment.
Dynamic receiver edges are confirmed in source; UNKNOWN and missing process
edges are not treated as low risk. No offline FTS extension is downloaded.

## First full CI and focused correction

Full CI run41407107387 on ddb6d68 exposed one shared test failure across Windows
and Linux partitions: an old protective-cache test patched the removed
manual_trading.manual_net_pnl import. Patch the current manual_daily_pnl helper
and inject a non-deferred instrument_unresolved valuation error. Keep the old
must-raise/cache-empty assertions and additionally require the exact injected
error code. Closed/open stale_quote monitor-only handling has its own native
regressions and independent mutations. No production source changes are needed.
The protective/runtime/manual-day modules pass98 tests after this correction;
all generated baselines remain up-to-date on a fresh dry-run.

The broad R8 local selection executed2346 tests. Its earlier runtime fixture
errors were separately corrected and rerun44/44; the later CI correction is
verified above. Combined-suite subprocess/fake-root effects and installer mutex
checks against a preexisting app are preserved as local failures, not claimed
green or hidden by changing assertions. Full isolated Windows/Linux CI is still
required. No user app was closed to make a local installer lifetime test pass.

## Final unknown-without-order classification

An independent review reproduced a bare outcome_unknown exception without a
canonical LocalOrder. The controller previously classified it KNOWN_NO_ORDER,
which could permit later resume despite the unknown financial result. Treat the
explicit unknown code as UNKNOWN regardless of whether a local row is available.
Do not fabricate a reservation or a no-send result, reset the claim or resend.
The new regression fails before this correction and passes afterwards; deleting
this predicate alone kills the test. Final commitment mutations increase to26
and the total to347; the seven dedicated modules contain196 tests.

The final source passes54 native/runtime/commit tests, including this case and
actual saved EXIT. All73 runtime/native mutations are rerun against matching
final source hashes. The original windows are also rerun: LOCAL6.075s and fake
SIM3.648s, both return0 with normal cleanup. All generated baselines remain
current on dry-run. The three combined-harness tool/worker modules pass47 tests
from a spawn-safe UTF-8 script with the configured child interpreter; this does
not change product code or any assertion. Remaining local app-lifetime checks
are isolated-host acceptance in CI, not a reason to close a user's running app.

## Parallel main integration

Main advanced to217fe6a during this task, merging M3-1, M2-9, U1, CI cleanup
and graceful exit. PR147 could not start a new CI run while it conflicted.
Merge45d1a85 preserves both appended contract/inventory sections and both error
catalog additions. Main's maintenance admission, FeeSchedule changes, M3 types,
desktop and workflow files are retained unchanged relative to current main.
The generated observer location repair is isolated in commit5e2f2c4, regenerated
with the required tool because main moved the shared automatic fixture.

Post-merge native daily/runtime/commit/protective verification passes71 tests.
All73 runtime/native guard mutations are rerun against matching merged-source
hashes; the remaining production mutation sources are unchanged. Ruff, syntax
and static/credential gates pass. The original windows return0 again with2807
widgets: LOCAL6.075s and fake-SIM3.606s, research released and endpoints removed.
R8 selects194 related modules against current main; its final result and complete
final-head CI remain recorded on PR147. This PR stays draft until green CI,
then remains open for Claude review; no autonomous merge is authorized.
