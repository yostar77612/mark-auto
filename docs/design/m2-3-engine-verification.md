# M2-3 engine verification: completed minute bars

This R5 slice implements BROKER_SIMULATION completed 1m/5m cycles. Daily 1d
submission in the next trading session remains next-round work. Typed broker
daily entries fail explicitly with automatic_daily_execution_pending; views
show the block and PAUSED status. LOCAL daily research and explicit day advance
remain available. No desktop_app files or strings are changed.

M2-4 PR143 passed35 checks at4350f05 and merged as6d50129. M2-5 PR145 passed35
checks at2ae7d37 and merged as2ffee2d. This branch starts directly from that main;
its first small contract commit is f18d4de. No PR is stacked on another PR.

## Execution and recovery

Completed final, non-incomplete bars produce one durable evaluation cursor per
strategy/version/instrument/interval/bar-end before signal evaluation. Conflicting
or incomplete minutes cannot form a complete bucket. Entry and normal exit
signals run only on that completed-bar claim. Timer pumps retain stop, expiry,
holding deadline and forced-exit work. Disabled/retired versions still protect
their owned lots. Paused-period bars are not replayed after explicit resume.

The materialized engine, journal, authenticated SDK owner and confirmed virtual
SIM books are shared with manual trading. Automatic entries do not manufacture
ManualRequest, broker balances or RemoteSnapshot. Every account owner shares
cash, entry fees, margin, pending reservations and stock T+2 receivables. All
costs use FeeSchedule. The existing trusted research format is reused; research,
deployment and typed commitment compare the same effective spec/calendar/fees.
Changing margin provenance or fee values, even at the same version, invalidates
old evidence. Minute research itself belongs to M2-7; synthetic test research
only exercises the evidence contract and is not minute-backtest acceptance.

Runtime validates current connection generation/revision, selected signed account,
actual current-generation diagnostic permission and fresh market/reconciliation
facts. A prior daily preflight PASS cannot authorize a new SDK generation.
The final submission guard revalidates and holds the current owner lock across
the existing bounded SDK call. Lock order is engine → owner inside execution;
outer runtime controls use bundle → engine → owner. The validator never acquires
the bundle lock from an engine-held path. Forced cancellations use the same gate.

AUTO_RECONCILE consumes only fresh worker observations and never resumes.
AUTO_RESUME is explicit and distinct from manual RESUME. Startup always pauses
automation; interrupted claims and ambiguous forced attempts remain unresolved.
Unknown results preserve reservations and identity, never automatically resend.
Only correlated known reports can resolve them; unlocated orders remain pending.
Reconciliation can run after service close without granting any new exposure.

Account observations retain one validation authority. A failed account stops all
new entries and clears the aggregate entry cache, while independently validated
fresh accounts can still support protective reductions. Empty batches, SDK
failure, relogin or owner-epoch mismatch cannot reuse this scoped proof. A
same-epoch writer-version race discards its uncommitted batch while preserving
an earlier still-fresh complete observation under the existing contract.

## Market and position boundaries

The stock/index terminal callbacks remain chained after existing alerts. They
enqueue immutable completed bars and perform no engine/SDK work inside the
market callback. The terminal has no TMF watch identity, so TMF uses the existing
execution consumer's independent tick queue on the same authenticated SDK.
Pure compose_minute/finalize_minute produce its bars; tick loss and epoch change
pause entries. There is no second LiveMarketService draining the same queue.

Stock hours are09:00–13:30; TMF08:45–13:45, with its actual expiry contract
closing13:30. Calendars project only the existing verified DAY dates and add no
holidays or night trading. The earliest/latest envelope is only for ledger-date
synchronization; admission, exits and today's order counts use instrument hours.
Sources: [TWSE](https://www.twse.com.tw/zh/products/system/trading.html) and
[TAIFEX specification, page3/Article8](https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/1130201142.pdf).

Near/next contracts come from actual SDK metadata, never inferred months. The
manual default resource remains one contract. Both NEAR and EXACT typed new
entries are blocked on settlement day; known reductions remain independent.
Unattested exchange-reference margins use labelled50000 TWD for automatic TMF.
Only a trusted resource margin_source beginning BROKER_VERIFIED attests a broker
margin. Retained contracts keep their provenance across renewal. Internal SIM
allocation can be configured before book confirmation without querying funds.
Adopted M2 books cannot lose their confirmed allocation; pure manual ledgers
retain their earlier lower-allocation/stop-entry contract without resetting cash.

Intraday force time pauses entries before any completed-bar decision. Accepted
exit orders must be canceled and observed terminal before replacement, at least
30 seconds apart through actual close minus2 minutes. UNKNOWN is never retried.
A late-started force window still stops entries after the retry cutoff; after
close, a remaining lot is an explicit overdue exception. Existing protective
orders are not silently erased or considered fills.

confirm_automatic_baseline accepts the existing DailyBaselineEvidence only from
a trusted provider, with exact account attribution, calendar/fees/source identity
and current cached reconciliation. It does not infer a prior close, clear dated
loss locks, call unsupported financial queries or resume trading. Production
owner close evidence and M2-7/9 data remain external dependencies.

## Validation and delivery limit

Final frozen-source relevant tests:354 new and398 existing pass; the final
canonical-format combined run is752/752 in46.931s. affected_tests.py
selected175 transitive modules; only relevant modules run locally, with full
discovery delegated to final-head CI. Original _run_window LOCAL5.343s and
fake-SIM3.453s both return0, open a visible real window, attach/release research,
close owned hosts normally and remove endpoints. SIM startup is connected and
unallocated, not a running-strategy demonstration. Real native fake SDK tests
separately prove completed-bar orders, account isolation and recovery.

Individual in-memory, fresh-process mutations cover pure rules77, shared
capacity79, automatic decisions94, runtime90, scoped protection25, native engine33,
resources25, close evidence15 and daily boundary8:446/446 killed. Detailed cases,
source identity and startup reports accompany this file in JSON. One obsolete
capacity mutation anchor was repaired after scoped-cache refactoring; no product
guard or test assertion was removed. Final relevant baselines, graph and static
results are recorded there before push. CI status must be read from the PR.

The concentrated baseline commit registers seven modules, four new observation
rows and two optional-component fields in old test doubles; all old assertions
are preserved. After final formatting, the same baseline batch corrected one
new observation's line offset. Baseline layer tests21 and observer/tool consumers49
pass. Python3.11 syntax1130 files, Ruff lint, quality0 and layers0 pass. Prepush
exits1 solely on the unchanged main M3 document code-fence CRLF format difference
at line155; no unrelated document normalization. No full local discovery runs.

R5: the first M2-3 draft started09:13:15 Taipei; at10:36:06 the elapsed82m51s
exceeds1.5 × the55min estimate. Keep this tested minute execution slice mergeable.
The complete daily close → saved signal → next verified session dispatch needs
another estimated2–3h plus validation. It requires separate observation and
submission phases, durable signal identity, next-session expiry and explicit
resume semantics; treating session_closed as success would be incorrect. This
report does not claim complete M2-3 or second-round product acceptance.

LIVE stays hard-disabled at every entry, cycle, force and retry path. No real
SDK import, credentials, CA activation, G3, SDK pin, PROJECT_STATE, costs.py or
desktop source changes. UI and M2-7/9 are separate lanes; real broker automatic
acceptance remains an owner task after those dependencies are ready.
