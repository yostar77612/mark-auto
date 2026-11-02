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

The seven dedicated new test modules contain195 focused tests. Independent guard
mutations total346/346: daily state91, closing valuation70, manual/day monitors52,
pure-evaluation recovery35, runtime/native daily exits73 and final commitment25.
The runtime73 includes its earlier25 stable owner/engine cases only once. Final
formatted source mutations were rerun; exact hashes are in the adjacent JSON.
Original window startups return0: LOCAL5.432s and fake-SIM3.030s, each2784 widgets,
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
