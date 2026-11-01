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
