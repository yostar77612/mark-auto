# v2 engineering and compatibility contract

This local mission is authorized by the owner on 2026-10-25. Its scope permits a
new multi-market engine and controlled connector implementation, while prohibiting
real financial operations, credential discovery, remote writes and Sitecore work.

The owner's subsequent 2026-10-25 instruction `合並進main` authorizes pushing
the verified v2 branch and merging its pull request after integration checks.
Only the earlier remote-write restriction is superseded; real financial
operations, credential discovery and Sitecore work remain prohibited.

## Impact and entry points

The eight frozen v1 sources, historical producer profiles, OOS one-time budgets,
paper journals and result readers remain unchanged. The new entry point is
`desktop.py --platform-v2`; `--trading-root` selects an explicit isolated lab.
The owner's 2026-10-26 follow-up unifies the normal and --platform-v2 desktop
entries. Both now embed the original research session and ChatGPT presenter in
the six-workspace window; callbacks route inside the window rather than launch a
second desktop. Existing research paths, login references and safeguards remain
authoritative, while the independent v2 trading engine retains its own book.

Trading Domain, Application, Ports, Adapters and Runtime live under
`quantlab/trading`; Qt presentation lives under `desktop_trading`. The composition
root `trading_runtime.py` alone launches the independent engine. A byte-only,
authenticated local named pipe transports registered immutable DTOs, Decimal
strings and UTC timestamps; no network trading service or pickle is used.

## Distinct v1 and v2 execution contracts

The permanent v1 live prohibition remains unchanged. The v2 Shioaji adapter has
separate capabilities, account/environment references, CA evidence and explicit
execution gates. It defaults disconnected, read-only and execution disabled.
Settings/readiness checks only inspect explicit local metadata and references;
they do not read financial credentials, log in or submit/cancel/amend orders.
No success in local simulation authorizes a real operation.

All v2 execution reuses the application commit path and one domain risk authority.
UI/AI requests cannot construct trusted validated orders. New risk is checked
against the current quote, account/capability versions, daily latch, reservations,
strategy allocation and shared platform budget within the single writer. Unknown
outcomes retain exposure and require query reconciliation; no automatic resend.

## Data and rollback

V2 local simulation has separate `trading-v2.sqlite` and
`simulated-exchange-v2.sqlite` journals. Neither reads nor migrates v1 research
data. Local data, capabilities, fees and calendars are explicitly synthetic;
they never assert official exchange coverage or actual broker qualification.
Training evidence ends before the simulated paper decision time. Future completed
bars cannot enter a live decision snapshot.

Schema 2 adds optional fields with defaults and rejects unknown wire classes or
versions. Durable events form a verified hash chain. Backups checkpoint before
publication and omit transient leases. Restoration always starts stopped and
reconciles the remote account before explicit resume; old outboxes never replay.
Rolling back the UI does not roll back broker assets or discharge open-order
responsibility. Keep the v1 application available and stop new v2 risk before an
upgrade or rollback.

## Evidence boundaries

`ACCEPTANCE.json` tracks the original 50 cases. Local fault tests, actual Windows
IPC, native UI, broker SDK model checks, broker simulation and real trading are
separate evidence levels. Original formal acceptance remains 230/300; this work
does not change that score. Human usability, real account permissions, actual CA,
broker simulation and controlled real trading cannot be inferred from a double.

Financial arithmetic uses the shared fixed Decimal context. An AST dependency
gate checks actual import direction, including relative and known dynamic imports.
The existing v1 test/quality gates and timeouts remain unchanged.


## Execution inventory and catalogue compatibility

The owner explicitly authorizes the separate v2 execution architecture in this
mission. This does not broaden the v1 permanent-live-disabled contract. The v1
AST oracle continues to require exactly the original two paper submit callers
and the same two intent writers, with risk rejection before the intent write.
Its original expected sets and historical catalogue hashes are unchanged.

`tests/test_paper_lock_b2.py` independently enumerates all five v2 submit call
sites (coordinator entry, engine exit, both lifecycle roll legs, and the sole
adapter submission in `ExecutionService.commit`). The exhaustive production
scan includes the v2 Qt tree and composition entry point. Every new site fails
this inventory until reviewed. The sole state-bearing execution commit caller
is `TradingEngine.submit`; ordinary argument-free SQLite transaction commits are
not order execution. Separate AST guards bind that call to the writer lock,
domain risk preview/rejection, reservation construction, durable SUBMITTING
intent and live ownership fence before any adapter submission. Real application
fault tests additionally verify that daily loss and expired ownership prevent
adapter submission. No v2 UI or AI path receives an adapter execution capability.

`quantlab/errors.py` is restored byte-for-byte to baseline 4095c3e. V2 messages
live solely in `quantlab/trading/application/errors.py`, which copies legacy
rows into a read-only combined catalogue and rejects shadowed legacy codes.
Importing v2 does not mutate legacy ERROR_TABLE, labels, enum or pickle paths.
The legacy catalogue, rendering and source-hash tests remain exact, with separate
v2 composition assertions. This is a scope separation with replacement coverage,
not a scan exclusion or an expansion of the old golden expected sets.

## Source worker import boundary

Source Python workers resolve the existing `desktop_ui:execute_ui_operation`
registrar under a process-local import role. The role also requires a real
multiprocessing parent, so a registrar lookup in the GUI process cannot cache
child-only window bases. Ordinary parent imports retain the real Qt types,
public aliases, handler globals and monkeypatch behavior. Operation children
load the same handler authority without Qt or page imports; attempting to
construct a window in such a child raises explicitly.

The JobManager and MainWindow class source/AST, default registrar, operation
inventory, single-job isolation, durability, 22 smoke evaluation children,
63 saves and original 40-second deadline remain unchanged. Real child and
parent-first-import tests verify both sides. Historical elevated results retain
their original source identity; final-source dependency/AST impact review is
separate evidence and does not claim the elevated cases ran on new bytes.

## Explicit optional v2 SDK import boundary

The optional broker dependency is loaded only by the visible local
`import shioaji` in `adapters/shioaji/sdk_loader.py:load_pinned_sdk`. Importing
this adapter module is inert; the function requires the exact pinned version
and returns the module without constructing a client. Runtime composition calls
it only inside the explicit read-only connection operation. Startup, metadata
readiness, source research, LOCAL simulation and default offline packaging do
not call the loader. No importlib indirection hides the dependency from scans.

This is a narrow v2 composition contract, not a general SDK import exemption.
Legacy forbidden imports/calls, permanent v1 execution prohibitions and domain
stdlib boundaries remain in force. The research gate owns the exact path and
function exception; independent tests continue rejecting SDK imports elsewhere.
SDK loader tests additionally verify inert import, missing dependency, exact
version refusal and absence of client construction. SDK import/package probes
remain distinct from external-account login and broker verification.
