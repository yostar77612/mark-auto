# M2-2 implementation and verification

Implementation in progress. No real SDK login, credential resolution, CA or broker
order is authorized evidence. Root coordinates full discovery, actual LOCAL/fake
SIM startup, push and CI after backend/UI integration.

## Manual intent contract slice

The immutable wire types carry accepted context/epoch/environment/account and
opaque shared-connection generation/revision. They convey untrusted intentions,
not an execution grant or StrategyRecord. Existing UiCommand fields and UiState
defaults remain compatible with historical messages. Quantities are canonical
integer shares/contracts; instruments expose lot_size/quantity_step for whole
stock lots and futures contracts. All money remains Decimal.

The read model distinguishes app-owned virtual capital from unknown broker
financial facts. Preview cash/risk/fees and sources are computed by the backend;
the GUI does not recompute risk. stop_price estimates sizing and does not establish
protection. UNKNOWN pending views retain the original request_id; default submit
and diagnostic flags remain false. Dispatch and execution are subsequent slices.

Pre-edit own GitNexus: UiAction/UiCommand/UiState each CRITICAL,74 upstream and38
direct importers; registry.initialize HIGH,19 upstream and6 direct callers.
Warnings were reported before editing. New manual symbols returned UNKNOWN/not
found; source searches confirmed no existing definitions/callers before addition.
This is not a claim that graph process enumeration is exhaustive: initial index
reported capped flow candidates; source/codec/application tests remain required.

Focused results so far:

- Before-change test_trading_execution_environments:2/2 PASS,2.445s,
  `.tmp/m2-2-execution-environments-before.log`. This confirms the old controlled
  LIVE-positive flag behavior that the M2 central guard must supersede explicitly.
- New test_manual_contracts:4/4 PASS,0.004s; new intents/old defaults roundtrip,
  malformed input rejection, Decimal/scope and UNKNOWN/unprotected provenance.
- Changed Python Ruff check/format: PASS. Later checks recorded as run.
- Existing Sinopac contract module:4/4 PASS; docs layering:8/8 PASS; strict
  repository layers:0 findings. Layout:29/29 PASS with PYTHONUTF8=1. The initial
  combined check omitted UTF-8 and hit cp950 subprocess decoding; its original
  failure is retained in .tmp/m2-2-dto-related.log, not concealed as a source fix.
- Final fields include a distinct suggested_capital (unconfirmed app allocation,
  not actual balance), optional scalar price_tick with authoritative price bands,
  and last_result carrying exact request identity after pending clears.
- TEST_SIM_ORDER without manual_order prepares only a backend-chosen minimum TMF
  DIAGNOSTIC_TMF preview, zero SDK mutations. Confirmed matching form executes
  through the canonical path; GUI does not choose the diagnostic price or risk.
- After incremental refresh the persistent MCP handle still reported newly
  indexed DTOs missing. A fresh official CLI context found them, and CLI impacts
  gave ManualTradingView/ManualInstrumentView MEDIUM70 upstream/2 direct. The
  test method has UNKNOWN static callers; direct source and unittest discovery
  establish its actual test invocation. The same installed GitNexus LocalBackend
  as the CLI is invoked in a fresh scratch process to retain complete JSON for
  detect_changes, avoiding the CLI formatter's displayed-list cap. No tool/source
  package is changed and no second graph tool is used.
- The incremental graph review returned129 symbols/8 files/601 flows,CRITICAL,
  with no partial/truncated flag, but inspection found an empty symbol id and a
  missing registry.initialize anchor. This is not accepted as a complete gate.
  Raw .tmp/m2-2-dto-detect-complete.json is retained. Forced single-worker rebuild
  completed exit0; fresh full detect returned140 symbols/8 files,LOW,0 empty ids,
  registry.initialize restored and no partial/truncated flag. This does not waive
  the CRITICAL shared-contract impacts or prove absent flows; source/codec/layer
  checks remain required. Source/test semantics were not changed for the index.

## Graph bootstrap and foundation-merge process record

The initial restricted-token index attempt exited1 on child spawn EPERM. The
next attempt exited1 because copying the runner/log into an uninitialized
.gitnexus made the new storage unowned. All task-created bootstrap files were
preserved in `.tmp/m2-2-graph-bootstrap`; nothing was deleted. With log/runner
outside the storage, elevated local index completed exit0,19738 nodes/52274
edges/629 flows at db2335f. No FTS/vector repair or package install was used.

Normal merge db2335fd42f9d333857a37d29fdfea0ed8b36bb8 adopted connection DTO
commit986f7c. This merge was mistakenly auto-committed before the own precommit
detect check. This is an acknowledged process gap, not retroactive compliance.
History is preserved. Postmerge own compare against b0f2128 completed57 symbols
in6 files,LOW with no partial/truncated flag. All six merged files were confirmed
byte-identical to986f7c with git diff --exit-code. The source owner's actual
earlier gate is separately retained at m2-connection/.tmp/m2-dto-detect.json
(7 symbols/6 files,LOW); it is not described as our precommit check.

All subsequent merges use --no-commit and own complete detect before committing.
The restricted-token CLI status could not read current git identity, reporting
detached/empty current commit; direct git and MCP metadata confirm own db2335f.
This status limitation does not authorize skipping an actual freshness check.

The subsequent af262ab environment/fake-fixture normal merge was held with
--no-commit. Only two append-only documentation hunks conflicted; both sets of
decisions/contracts were retained. The seven incoming source/fake files remain
byte-identical to af262ab. Own force-refreshed complete precommit detect reports
26 symbols/10 incoming files/6 connect flows,HIGH,0 empty ids and no
partial/truncated flags. HIGH risk remains warned, not waived. Individual fake
modules passed: immutable environment2,SDK facade11,price bands16,tick stream4;
strict layers0 findings. No native engine or actual SDK session was started.

## Central LIVE guard slice

One pure domain orders_enabled predicate admits only typed LOCAL and
BROKER_SIMULATION. Engine execution/exit, ExecutionService commit/cancel, gateway
inspect/execution and all three SDK mutation sinks consume it. Explicit immutable
facade environment, not a native simulation flag, controls the final SDK check.
LIVE STOP_NEW still records the local halt but never dispatches cancel. No risk,
funding, ownership, durable-intent, OOS or deadline check is removed.

Own pre-edit impact warns HIGH for engine.exit_lot (6 direct callers), LOW for
the other resolved engine/service/gateway/dispatch methods. SDK sinks and the
error table have UNKNOWN static callers; text/source confirms gateway submit/
change, strict SDK tests and error catalogue composition, rather than treating
empty edges as safe. New policy/test names were absent in graph and source.

New test_live_order_guard:6/6 PASS in0.006s. It exercises the real TradingEngine
with a test-owned in-memory journal and explicit fake adapter, direct service
and SDK calls, contradictory LIVE flags/readiness/CA, stop/cancel/flatten, and
SIM-positive delegation with original2500ms query/10000ms order budgets. No
native engine, credential, SDK import/login or actual order is involved.

The original environment oracle with guarded source failed only its formerly
allowed LIVE submission. Its independent D1 baseline keeps the full SIM flow and
requires zero LIVE delivery after the existing genuine fixture research steps;
the module now passes2/2 in0.608s. Broader application/full/native runs belong to
the coordinator; the focused results do not claim first-round completion.

Additional focused results:32 adapter tests,11 SDK facade tests and the3 existing
AST/catalogue cases passed; unique commit caller, locked risk/reservation/durable
intent/fence ordering and original submit inventory remain exact. Strict layers
reported0 findings and changed Python Ruff check/format passed. Complete own
forced-index detect:44 changed symbols/13 files,LOW,0 empty ids and no partial or
truncated flag. This does not waive the separately warned HIGH exit_lot impact.

The frozen78e1f83 shared-owner/resources backend was adopted with --no-commit.
Two append-only documentation conflicts retain both intents; existing central
SDK guards remain present. Own prebuilt forced-index complete detect reports220
symbols/32 files/28 flows,CRITICAL,0 empty ids and no partial/truncated flags.
The risk is warned, not waived. Current own LIVE wall tests6/6 and incoming tiny
shared-session fake tests3/3 pass. No new index/native/Qt tests are run during
the coordinating agent's isolated full8 window; subsequent source work remains
uncommitted until its own complete review is possible.

## Revoked shared execution consumer and preview units

The strict offline regression first failed three assertions and one signature:
detached/closed execution views still reached the native mutation methods,
active SIM calls did not hold the lifecycle lock, and price-only updates required
an unintended quantity argument. The repaired view holds the existing operation
lock from active-consumer validation through each of the three SDK calls. The
base immutable-environment LIVE guard still runs; native SIM/signed/CA flags do
not override it. Query and order budgets remain 2500/10000 ms.

The pinned 1.7.9 stub permits optional price/quantity. Price-only update omits
the quantity keyword entirely, verified by a strict fake rejecting that keyword.
Preview quantity_unit and lot_size are appended defaulted fields; actual core
previews supply the instrument specification, and unknown units remain unknown.

Pre-edit graph: SharedFacadeView LOW (one direct caller), ManualPreviewView
MEDIUM (two). Dynamic SDK update_order/SDKClient and new methods are UNKNOWN;
source/text confirms gateway._change delegation, protocol use and the absence
of these new overrides. This is not interpreted as unused or low risk.
Five new consumer cases and the existing DTO/shared-session/LIVE/SDK cases pass:
29 tests in 0.013 seconds. RED and GREEN logs remain in ignored .tmp. These are
pure in-memory fakes, with no SDK import, native client, Qt or engine process.
The pending manual core is deliberately not part of this small source commit.

## Manual core freeze candidate

Focused evidence: 68 tests PASS in 2.369 seconds. This comprises 19 new strict
offline SDK/shared-session/adapter/engine/service cases, existing adapters 32,
consumer revocation 5, manual DTO 4, LIVE guard 6 and the two execution AST
guards. No real SDK module/client/login, credentials/CA/order, native engine or
Qt window is involved. Runtime/IPC and actual startup remain coordinator work.

The original exhaustive submit inventory first failed with exactly the new
manual_trading._submit -> engine.submit caller. Its independent baseline adds
only that sixth caller and documents its purpose. The unique state-bearing
ExecutionService.commit caller remains TradingEngine.submit, and the unchanged
AST binds locked risk preview/rejection, reservation, durable SUBMITTING and
fence. The original automatic daily-baseline and OOS/deployment checks remain;
new tests explicitly observe no strategies and no DailyBaselineEvidence.

New cases cover two-phase backend-only diagnostic preparation, one native submit
and known-reference cancel, UNKNOWN identity/reserves/no retry, cancel/full-fill
race without an opposite order, native price-only amendment after entry TTL,
actual fill/fee/position adoption, manual stop estimates without automatic
orders, scope/generation invalidation, restart/reconcile/explicit resume without
capital reset, stop-latch/bare-resume refusal, quantity/tick/risk refusal,
external native quantity/price changes, healthy-cache requirements, stock
canonical shares/native lots and partial cancel, and conservative T+2 owned
stock exit while cross-day new risk remains stopped. Durable event replay
asserts sale fills never appear without their unsettled receivable reservation.

App-owned virtual capacity and estimated fee provenance remain separate from
unavailable broker financial facts. TMF cash uses 35050 per-contract exchange
margin plus named costs, not the larger futures notional. See
[stock evidence](m2-2-stock-exit-evidence.md) and the owner decisions for the
deliberately limited derived-stock exit contract. The current implementation
does not invent a missing manual closing baseline to open risk on a later day.
A never-used confirmed empty book may align its initial session after complete
fresh empty reconciliation. Any order/request, restart halt, loss lock or
STOP_NEW excludes that initial-only alignment; it cannot reset history.

Pre-edit graph warns HIGH for submit and quote, with unresolved dynamic call
boundaries explicitly retained. Existing event reducer/availability/control
methods were reviewed before edits; new symbols were UNKNOWN/absent and source
confirmed, never treated as an all-clear. Full fresh indexed all/staged change
analysis precedes each source/baseline commit; complete runtime/full/CI evidence
must still be supplied after composition.

## Readiness, interrupted intent and LIVE follow-ups

Three strict regressions were first RED: stale-session controls appeared ready,
a receipted order was not linked to its earlier pending manual request after
restart, and a proven pre-submission append failure remained pending forever.
The repaired projection uses the existing active-session, verified quote,
current actual limit and capability policy. It leaves cancellation readiness
independent of entry quote/session rules. Restored pending submit requests link
only by their exact durable canonical key. A complete valid replay with no
durable order and no recorded order id proves the earlier manual intent never
reached the sole SDK submit call; only that case becomes known rejected with
manual_not_submitted. A durable SUBMITTING/UNKNOWN order is never cleared by an
empty cache and is never automatically resent. Original admitted scope remains.

An additional two-account regression proves enabling a stock book after the
existing futures book's STOP_NEW keeps the global stop, both book histories and
the 100000 cap. The final settings regression was first RED, then verifies the
existing SAVE_SETTINGS action can lower a bucket without authorizing the old
confirmed capital for new risk. manual_allocation_exceeds_settings explains the
constraint; book capital/history and legal reductions are retained.

The expanded tiny matrix passes 37 tests in 0.450 seconds: manual core 24, LIVE
wall 8 and actual shared-session consumer 5. LIVE cases include direct manual
command routes with contradictory flags and a real engine replay/read-only
recovery from SUBMITTING to a known report, with zero native Order/place/update/
cancel calls. The separate existing domain/grid/SDK/session/coordinator group
passes 107 tests in 8.419 seconds after the precise independent D1 oracle update;
its original restricted-token attempt failed on test-owned temporary paths and
is not counted as product evidence. No timeout, skip or source limit changed.

All follow-up Python passes Ruff and diff whitespace checks. Graph evidence is
refreshed before commits after the coordinator's isolated smoke prefix. These
focused results do not claim the final full suite, Qt startup, IPC integration
or CI, which the coordinator runs against the eventual merged source.

## Confirmed-request preflight result follow-up

Read-only UI integration review reproduced a permanent pending state: confirmed
submission could fail stale_quote before recording any request, leaving the UI's
correct UNKNOWN latch with no matching result that could ever resolve it. The
same issue affected preflight-rejected price amendments and stale engine CAS.
Three real core-chain regressions were first RED with mismatched last_result
request identities (.tmp/m2-p1-red.log), then GREEN after durable absent-key
rejection. The quote test advances a real strict-SDK fixture from an allowed
preview to a stale quote within preview lifetime, refreshes account evidence,
and verifies zero additional native placement plus durable restart/replay.

The expanded group passes 47 tests in 0.612 seconds: core 30, DTO 4, production
mutation wall 8 and shared-consumer mutation guards 5. Added cases cover exact
scope/result identity, preflight amendment refusal, stale engine version, old
wire omission/default false, deny-only true codec roundtrip, delayed same-key
original, existing UNKNOWN immunity, invalid native scope, writer-fence failure
and LIVE refusal. The initial combined invocation included one misspelled test
module and is retained as a harness import error, superseded by the corrected
47-case run. Ruff and git diff whitespace checks pass.

No actual SDK/login/order or native engine was used. Runtime/Composite/server
outer-CAS forwarding and actual IPC regressions are separately owned by the
runtime agent; these focused results do not claim that integration or final
full/startup/CI. Fresh graph analysis is required before this follow-up commit.

Final pre-index confirmation: 47 cases pass in 0.700 seconds, including refusal
to certify a request without an existing confirmed manual book. The two
canonical submit-caller/fenced-commit AST guards also pass in 1.845 seconds;
the earlier wrong-class invocation was a harness lookup error, superseded by
that exact corrected run. No new submit or commit caller was introduced.
