# ADR 0006: Strategy intents before order planning and simulated execution

日期: 2026-10-19
狀態: Accepted (design decision only; implementation requires separate approval)

## 背景

This ADR records the B7 design, not an implemented intent layer. At base
`b5c300da1e21932849623a9f8044addb0def6c12`, no equivalent intent-layer ADR or
five-intent model exists. [Signal](../../quantlab/core.py) carries an integer
`target_position`; [generate_signals](../../quantlab/strategies.py) computes
desired targets from price history, independently of actual engine holdings.
[Backtest _run](../../quantlab/backtest.py) already queues those signals for a
subsequent tradable open. The existing Paper order/journal intent in the
[engineering contract](../agent/IMPLEMENTATION_CONTRACTS.md) is an execution
request, not the strategy intent defined here.

The conceptual reference is the local shioaji-pro-app copy, commit `2b656ca`,
`docs/adr/0005-portfolio-first-strategy-runtime.md`. Its ADR 0005 is distinct
from this repository's [ADR 0005](0005-decimal-and-content-hash.md), which
documents Decimal and content hashes. Only the reference's intent separation
and bar ordering are borrowed; its broker executor and multi-asset vertical
slice are not authorized here. The borrowing list section 0 and section 3/B7
require design review before changing the engine. Value for multi-instrument
strategies or richer target-position control is conditional on a confirmed
requirement; single-instrument TMF already has next-open execution.

### Dependency and review evidence

B1 is `e7ed03ed3382d359c0527aaa6ca0f376e95e12a7`. The main integration snapshot
containing B1 is `d479811eca089c70bcfb112433fe9e4ac10b23df` (`origin/main` at
review); it is a linear integration, not a separate merge commit. Both
`git merge-base --is-ancestor e7ed03e HEAD` and the same check against
`origin/main` exit 0, as does `git merge-base --is-ancestor d479811 HEAD`.
The local `main` ref still points to `17b5b1b`; it is stale and is not the
integration evidence. B5 (`a1cc158`) and B6 (`b5c300d`) precede this item.
The controller must create exactly one separate B7 commit from this base;
this task leaves the design changes uncommitted.

Source verification: `rg -n 'validation_failed|ERROR_TABLE|ErrorCode'
quantlab/errors.py` and `git show origin/main:quantlab/errors.py` confirm the
actual B1 identifiers `ERROR_TABLE['validation_failed']` and the derived
`ErrorCode.VALIDATION_FAILED`. [exception_code](../../quantlab/desktop_errors.py)
already maps `ValueError` (including `ValidationError`) to `validation_failed`.
There is no `intent_conflict` catalogue key. The generic validation code is
suitable for this design, so no new code is requested or added.

### GitNexus impact evidence (2026-10-19)

The borrowing list warns that the historical index was 17 commits behind and
requires re-analysis. After confirming this worktree's git root, `gitnexus
status` instead reported no lane-local index. `gitnexus analyze` failed with
sandbox `spawn EPERM` during heap respawn. Re-analysis was retried with the
supported `GITNEXUS_MEMORY=off`, `NODE_OPTIONS=--max-old-space-size=8192` and
`gitnexus analyze --index-only --skip-fts --name lane-d --workers 1`. After a
worker startup warning, graph analysis continued and wrote a local database,
but the command exited 1 when the sandbox denied the global
`C:/Users/Mark/.gitnexus/registry.json.tmp.*` write. Local metadata still has an
empty `lastCommit`; a subsequent lane-path impact query reported the repository
unregistered. Thus a fresh usable lane index was not verified. No FTS/vector
extension was downloaded, no other graph tool was used, and generated local
index files are not deliverables. The controller must complete registration
and refresh outside the sandbox before claiming fresh-index coverage.

As bounded fallback evidence, GitNexus MCP `impact` ran upstream queries with
explicit `file_path` on the registered `C:/Users/Mark/Desktop/Mark auto` index
at `17b5b1b` (the index's actual commit, not a claim of current main):

| Symbol and disambiguating file | Reported impact | Interpretation |
| --- | --- | --- |
| `Signal`, `quantlab/core.py` | 69 affected, 39 direct; CRITICAL | Shared record/import surface reaches strategy, research and desktop consumers; no edit is authorized. |
| `generate_signals`, `quantlab/strategies.py` | 8 affected, 2 direct; HIGH | Direct consumers include `_run` and `PaperReplay.__init__`; execution changes require both backtest and replay review. |
| nested `execute`, `quantlab/backtest.py` | 7 affected, 1 direct; HIGH | `_run` -> `run_backtest` reaches UI, CLI and research paths. Graph labels this a lower bound with 17 unresolved receiver call sites; absence of more edges is not proof of no impact. |

`git diff 17b5b1b HEAD --exit-code -- quantlab/core.py quantlab/strategies.py
quantlab/backtest.py` exits 0, confirming the three cited source files match
that index snapshot. Direct source reads and `rg` verified all mapping-table
identifiers and ordering. This limits the fallback to unchanged symbols; it
does not substitute for a fresh graph, compiler, tests or controller QA.

## 決策

The future pipeline is **strategy -> intent -> order planning -> risk ->
simulated execution**. Strategies only emit intents; they cannot place orders,
mutate holdings, bypass risk, or access a broker. The planner resolves targets
against a single immutable post-mark position/cash snapshot. Risk validates
the resulting plan before any simulated execution is queued; risk failure
cannot leave partially queued strategy orders. Planning must be deterministic
and independent of source call order. This ADR introduces no new order path;
live trading permanently disabled.

### Validation and period identity

A decision period is the supplied bar interval `(Bar.timestamp, Bar.end)` plus
its explicit `contract_id`; emission `timestamp` is availability time, `Bar.end`,
not a wall-clock execution time. A future synchronized multi-instrument runtime
would need an explicit shared period/calendar contract before implementation.
No missing bar may be synthesized to make an instrument tradable.

Validate the whole period's intent batch before planning. Conflicting intents
for the same instrument and same period fail validation with **NO implicit
priority**: no last-writer-wins, entry-over-exit, target-over-signal, or source
ordering. Conservatively reject multiple strategy intents for one such key,
even equal targets, until a separately reviewed composition rule exists.
For example, `EntryIntent(quantity=Decimal('1'), side='buy')` and
`TargetQuantityIntent(quantity=Decimal('0'))` for the same key reject the
batch without changing state or queuing either order. A single target's
close-then-open reversal is one planned intent, not a conflicting pair.

The future validator raises `ValidationError` with the fixed catalogue code
`validation_failed` (represented by `ErrorCode.VALIDATION_FAILED`), using B1's
`ERROR_TABLE` and existing fixed rendering/logging path. Do not derive codes
from arbitrary exception text or expose raw strategy text. A narrower NEW code
`intent_conflict` would require its own future catalogue change and tests if
later desired; it does not exist today. Existing engine maintenance, roll,
protective-stop and settlement events are not strategy intents and must retain
their explicit event policy; that policy cannot resolve strategy conflicts.

### Non-importable type sketch

This code block describes future immutable records only. It is not runtime
code, an importable module, or a new DSL implementation.

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class EntryIntent:
    contract_id: str
    quantity: Decimal
    side: Literal['buy', 'sell']
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class ExitIntent:
    contract_id: str
    quantity: Decimal
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class ReduceIntent:
    contract_id: str
    quantity: Decimal
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class TargetQuantityIntent:
    contract_id: str
    quantity: Decimal
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class TargetWeightIntent:
    contract_id: str
    weight: Decimal
    reason: str
    timestamp: datetime
```

All timestamps must be timezone-aware UTC; contract IDs remain explicit expiry
contracts. Quantity, weight, price and money values use finite Decimal, never
float. Entry quantity is positive; Exit quantity is the full absolute holding
in the consistent snapshot and must match it; Reduce quantity is positive and
strictly less than the absolute holding. Exit/Reduce cannot open or reverse a
position. TargetQuantity is signed with zero meaning flat. For current TMF,
quantity must be integral Decimal, never fractional lots or bool; a future
adapter must validate before losslessly converting to existing integer order
quantities. The sketch does not change `Signal`, `Fill` or their validators.

TargetWeight is signed desired exposure divided by positive marked portfolio
equity. It requires separately approved valuation, margin/leverage bounds and
deterministic lot rounding; a TMF compatibility adapter must reject it until
those rules exist. Neither acceptance of this type sketch nor a weight of zero
authorizes new execution capability. Reasons are audit descriptions, never
executable instructions or priority selectors.

### Existing next-open semantics mapped to the design

Every identifier below occurs in the linked current source; intent names denote
future design, while existing reason literals remain stable audit output.

| Existing semantics and source symbols | Intent/order interpretation | Compatibility constraint |
| --- | --- | --- |
| `core.Signal.target_position`; `strategies._generate_signals` | `TargetQuantityIntent.quantity = Decimal(Signal.target_position)` | Preserve signed target changes, including zero; no new repeated triggers. |
| `core.Bar.end`; `_generate_signals`: `Signal(b.end,b.contract_id,target,reason)` | Intent emission time is bar availability | Do not execute using this bar's earlier open. |
| `backtest._run`: `pending`, `by_time`; nested `execute(...,at_open=True)` | Planner queues orders for the next available tradable open | Require `pending.timestamp <= b.timestamp` and `b.volume > 0`; no later bar means unfilled, never a forced close. `at_open` chooses fill timestamp; the caller supplies the reference price. |
| `_run`: `target_close` passed to `execute` with `b.open` | Target delta produces exit/reduce order; reversal closes first | `ExitIntent` or `ReduceIntent` may express the same action explicitly in a future strategy; existing signals remain TargetQuantity. |
| `_run`: `target_open`, `position`, `execute(...,entry=True)` with `b.open` | Remaining target delta produces entry/increase order | Preserve current quantity limits and entry-margin rejection after closing. |
| `_run`: `roll_map`, `roll_close`, `roll_open`, `old_bar.open`, `new_bar.open` | Explicit scheduled roll orders, not fresh strategy entry/exit intents | Both real contracts need simultaneous tradable bars; reset `pending`; preserve new-leg rejection accounting. |
| `_run`: `forced`, `maintenance_liquidation`, `b.open` | Engine risk liquidation order at next tradable open | Existing forced branch clears pending targets; this is an explicit safety policy, not intent priority. |
| `execute`: `slippage_ticks`, `after_equity`, `total_slippage`; `calculate_costs`: `commission_per_side`, `tax_rate`, `ROUNDINGS` | Slippage/spread/commission/tax cost stage remains unchanged | Adverse slippage against supplied reference and immediate open-to-fill spread/slippage loss remain; there is no separate bid/ask spread fee to invent. Keep Decimal and versioned rounding. |

### Reference ADR 0005 bar-order comparison

The following compares the reference's required ordering with current
`backtest._run`, not with a claimed new implementation.

| Reference step | Verdict | Current source evidence and explicit difference |
| --- | --- | --- |
| Fill prior-period planned orders at this bar open | equivalent for target fills; differs for a general planner | `pending.timestamp <= b.timestamp`, `b.volume > 0`, `execute(...,b.open,...)`; `pending` is one Signal, not a separately validated order plan. Scheduled roll runs first; `forced` supersedes pending under existing explicit engine policy. |
| Update position, fills and cash | equivalent | `execute` appends `Fill`, deducts expenses and updates `lots`, `ledger`, `cash`; `position()` reads lots. Rejected entry leaves no new lot. |
| Mark at close before strategy decision | equivalent for accounting; differs in intermediate events | `_run` computes `upnl=unrealized(b.close)` and appends `equity` before consuming `by_time[b.end]`. Protective `stop`/`target` executes earlier using OHLC (`at_open=gap`); settlement may update basis/cash or finalize before the mark. Reference's short sequence does not specify these events. |
| Strategy reads consistent post-fill, post-mark holdings | differs | `signals=generate_signals(dataset.bars,spec)` occurs before the execution loop. `_generate_signals` maintains desired `states`/`entered`, not `lots` or actual fills; `rule_exit_or_conflict` flattens simultaneous long/short rules today. Stops or rejected entries need not agree with that desired state. No position-aware strategy callback exists. |
| Emit, validate, plan, risk-check and schedule next open | equivalent for causal queue timing; differs for staging/validation | After mark, `_run` sets `pending=signal` from `by_time.get(b.end,[])`. Quantity/margin checks occur at execution; there is no atomic intent conflict validator or planner. The loop could overwrite multiple signals; current generation normally emits at most one per contract/bar. A future adapter must reject conflicts rather than copy that overwrite behavior. |
| Shared multi-asset snapshot and availability mask | not-applicable to current supported strategy scope | `active_contract`, `groups`, `roll_map` allow explicit two-contract rolls; multiple contracts without a roll schedule reject. This is not a shared portfolio strategy runtime. |

Consequently, a pure Signal-to-TargetQuantity adapter can preserve current
single-instrument timing, but cannot claim the full stateful reference pipeline
already exists. A future position-aware runtime changes semantics and requires
separate review and evidence. Intrabar stops, explicit settlement, final
unfilled signals, zero-volume deferral and roll/forced handling must not be
silently collapsed into an unconditional next-bar fill rule.

## 後果

### Impact assessment and implementation approval boundary

Design-only now: no Python, engine, runtime or fixture changes. The G3 eight
locked files must have empty diff against the B7 base. A future implementation
requires separate approval before changing any of them:

| Locked file | Potential implementation impact (not authorization) |
| --- | --- |
| `quantlab/core.py` | Intent records/adapters and quantity validation would need an approved interface change, or a new module with an unchanged core. |
| `quantlab/strategies.py` | Intent emission adapter; actual post-fill state access would require a new sequential strategy interface. |
| `quantlab/backtest.py` | Planner/risk staging, batch conflict validation and an explicit period queue would need engine changes. |
| `quantlab/research.py` | Review engine-source hashes, candidate evidence and campaign bindings if engine/interface versions change. |
| `quantlab/provider.py` | Review bounded strategy-output schema if intent syntax is exposed; unchanged if the adapter remains internal. |
| `quantlab/data.py` | Review period identity and availability/calendar inputs for multi-instrument support; unchanged for current TMF bars. |
| `quantlab/assistant/adapters/chatgpt/auth.py` | No intended functional change; verify provenance/budget bindings if new versions are introduced. |
| `quantlab/assistant/adapters/chatgpt/provider.py` | Review provider schema/provenance only if bounded output grammar changes; no intended auth or network change. |

Also preserve `quantlab/saved_candidate_pool.py` profile blocks. Existing
`engine_golden` (4 cases), `ui_operations_golden`, research hashes and
`analysis_id` content-hash bindings are **unchanged for single-instrument TMF**
in this documentation task. No golden values, `tests/fixtures/**`,
`docs/analysis/t*_*.json`, `PROJECT_STATE.md`, `ACCEPTANCE.json` or acceptance
scores change. [ADR 0005](0005-decimal-and-content-hash.md) still governs hashes:
`backtest._run` hashes adjacent `source_hashes` and the result payload;
`research.run_campaign` binds `engine_source_hashes`; analysis plan identities
bind canonical content. A future engine source edit can change those hashes
even with numerically identical fills. It must version and review bindings and
revalidate eligibility; never rewrite historical evidence or silently rebind an
existing `analysis_id`. Numerical compatibility and byte identity are distinct
claims for that future task.

Retaining desired-target signals avoids a costly core migration for today's
single-instrument TMF. Adopting explicit intents later makes conflict rejection
and richer portfolio planning reviewable, at the cost of new interfaces,
deterministic snapshot/period rules and regression coverage. Multi-instrument
or richer target-position value remains conditional; no claim of implemented
support follows from this ADR.

### Safety and verification boundaries

No eval, exec or new Function; no dynamic code execution. Strategies remain
finite AST rules with existing validation bounds. OOS one-time consumption,
irreversible budget, fail-closed validation and no implicit retries remain.
Timeouts are not loosened: Paper 30 s, smoke 40 s, 15 min per job. Live trading
remains permanently disabled and no new order path is introduced.

The unchanged [B5 ADR format test](../../tests/test_adr_glossary.py) parses this
record using the existing three-section format. Documentation layering and
repository-layout checks remain authoritative for links and file placement;
no new test or CI cost is required. Runtime golden replay and the eventual
single controller-created B7 commit remain controller verification steps.

Local verification uses the controller-specified shared interpreter and Ruff
from the worktree root, with `QT_QPA_PLATFORM=offscreen` and `PYTHONUTF8=1`:

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p test_adr_glossary.py` | 4 passed; unchanged B5 format and safety assertions. |
| `python -m unittest discover -s tests -p test_docs_layering.py` | 8 passed, including relative links. |
| `python -m unittest discover -s tests -p test_repo_layout.py` | 5 passed. |
| Ruff 0.16.10 `check` and `format --check` | Exit 0 after formatting the documentation code block. |
| Python 3.11 compile check | The single type-sketch block compiles in memory; no changed Python files require compilation. No sketch execution. |
| `python tools/quality_gate.py` | Exit 0, 0 findings. |
| `git diff b5c300d --exit-code --` protected sources, fixtures, analysis JSON, state and acceptance files | Exit 0; all protected paths unchanged. |

Deliverables are this ADR plus the minimal append-only engineering-contract
note expressly required by the common task rules; no design sketch file or
test modification is added. Broader runtime replay and final commit-count QA
are not claimed by these local documentation checks.
