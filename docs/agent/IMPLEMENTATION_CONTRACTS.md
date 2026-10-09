# mark-auto implementation contracts v1 — frozen development baseline

Baseline: `main@1cacce4ee4eef4ce7e8760f8153ef64a74852d22`. Frozen 2026-10-09 before implementation. Source/security audit approved. Fixed acceptance goals cannot be lowered; additive changes below preserve required behavior.

## Decision and evidence

Keep Python and Streamlit. Add sibling `quantlab/` package, not a wholesale rewrite and not a subpackage of `trader`. Core uses Python standard library only (`dataclasses`, `decimal`, `datetime`, `zoneinfo`, `csv`, `json`, `sqlite3`, `hashlib`); UI alone imports Streamlit. Python 3.11+ target; optional Windows tzdata dependency must be documented. Separate `research_app.py` entry point; never invoke existing `gui.py` or `run.py` in research tests.

Evidence: `trader/config.py:6,15–16,79` imports Shioaji and constructs a non-simulation API at import; `trader/__init__.py:1–29` creates executor/shared objects/directories; `gui.py:10–13` imports that configuration/database path and `start_trader` launches `run.py`; `trader/utils/strategy.py:6–12` couples signals to mutable TradeData, database and configuration; `trader/performance/reports.py:18` imports missing backtest module. `requirements.txt` already contains Streamlit 1.45.1 and pandas 2.3.3. Preserve legacy indicators as reference, but do not import them through `trader`; reuse only after explicit extraction with regression fixtures. This avoids making unrelated stock/live infrastructure a prerequisite for safe TMF research.

Legacy safety patch is separate: disable unsafe automatic/live entry paths, require nonempty Telegram allowlist, redact credential-bearing SQL logging. Do not modernize every legacy dependency or claim retained legacy execution is verified. Never enable a live client via environment variable alone.

## Ownership and dependency order

- A owns `quantlab/core.py`, `data.py`, associated `tests/test_data.py`; publish core first. Package `__init__.py` remains side-effect free.
- B owns `strategies.py`, `backtest.py`, engine/golden tests. Depends on core, never data I/O or UI.
- C owns `research.py`, DSL/campaign tests. Depends on core + public B functions; provider never receives broker ports.
- D owns `paper.py`, recovery/risk tests. Depends only on core, optional pure cost helpers from B; journal is its authoritative state.
- E owns `reporting.py`, `research_app.py`, `__main__.py`, integration tests, documentation and safe dependency manifest. Depends on public interfaces, never private fields.
- Coordinator alone edits shared packaging/CI/README and resolves contract changes. No two workers own same file. Every unavoidable interface change updates this contract before callers change.

## Shared value and serialization contract (`core.py`)

Use frozen dataclasses, explicit validation, stable exception `ValidationError(ValueError)`. Public API arguments are keyword-only after main payload. Datetimes must be timezone-aware UTC; trade_date is ISO `YYYY-MM-DD`; contract ID is `TAIFEX:TMF:YYYYMM` (explicit expiry, no continuous symbol). Price fields are Decimal points; orders/fills require integral one-point ticks; settlement reference may have distinct precision. Quantity is strictly integer (reject bool), never negative except signed positions. Money is Decimal TWD. JSON decimal values are strings, timestamps ISO UTC ending `Z`, enums lower-case strings, keys sorted, UTF-8; no NaN/Infinity. IDs and hashes derive from canonical JSON, never `hash()` or random UUID in deterministic output. Runtime wall-clock metadata is excluded from reproducibility hash.

Required public records (extra fields require defaults):

- `Instrument(contract_id: str, multiplier: Decimal=Decimal('10'), tick_size: Decimal=Decimal('1'), expiry: str|None=None)`.
- `Bar(timestamp: datetime, end: datetime, trade_date: str, session: str, contract_id: str, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: int, source_id: str='')`. `timestamp` is event-interval start; `end` is availability time. Session enum `day|night`; include source-specific endpoint convention in manifest, not inferred from interval alone.
- `Dataset(bars: tuple[Bar,...], manifest: dict, quality: dict)`. Manifest includes schema_version, source_type (`official_local|synthetic|proxy`), source_url, source_filename/hash, imported_at, product, coverage, encoding/schema, timezone, calendar_version, aggregation_version, license_note, validation_status; explicitly do not imply redistribution permission.
- `CostSpec(commission_per_side: Decimal, tax_rate: Decimal, slippage_ticks: int, tax_rounding: str, effective_from: str, version: str)`. Costs mandatory and nonnegative. Rounding policy named and recorded; unverified broker tax rounding must carry an assumption warning. Paid commission is all-inclusive per side unless explicitly decomposed, avoiding double-counting exchange fees. Supply versioned schedules where periods span rate changes.
- `StrategySpec(strategy_id: str, family: str, parameters: dict, rules: dict, schema_version: int=1)`. Content hash defines immutable version, display ID is not identity.
- `Signal(timestamp: datetime, contract_id: str, target_position: int, reason: str)` is generated after `Bar.end`, not executed on signal bar. Strategy cannot create broker orders.
- `Fill(fill_id: str, order_id: str, timestamp: datetime, contract_id: str, side: str, quantity: int, price: Decimal, commission: Decimal, tax: Decimal, reason: str='')`. Slippage affects fill price and is separately attributable, not deducted twice.
- `BacktestConfig(initial_cash: Decimal, costs: CostSpec, max_position: int=1, same_bar_policy: str='conservative', seed: int=0)`; include risk limits/schedule IDs in serialized run config. Invalid/missing schedule or unsupported instrument fails closed.
- `BacktestResult(manifest: dict, signals: tuple[Signal,...], fills: tuple[Fill,...], ledger: tuple[dict,...], equity: tuple[dict,...], metrics: dict, rejects: tuple[dict,...], warnings: tuple[str,...])`. Ledger includes matched lot/round-trip detail; open positions remain explicit and marked, not silently closed. `metrics` unavailable values are null plus reason, not infinity.
- `canonical_json(value)->str`, `content_hash(value)->str`, `to_dict(value)->dict` shared by every module. SHA-256 content hashes. Imported manifests must be validated, never trusted merely because they contain a hash.

## A: data interface and minimum behavior

`import_taifex(path: Path, *, kind: str, calendar: SessionCalendar, contract_id: str|None=None, encoding: str|None=None)->Dataset`

`aggregate_ticks(ticks: Sequence[dict], *, timeframe_minutes: int, calendar: SessionCalendar)->Dataset`

`SessionCalendar(sessions: Sequence[dict], *, version: str)` consumes explicit interval records `{open,end,trade_date,session,contract_id?,source}`; `lookup(timestamp, contract_id)->dict` rejects uncovered dates. Official holiday/calendar imports may build these records; do not invent a perpetual calendar from weekdays or midnight. Contract-specific expiry closure has precedence. Import daily session records as session bars; never manufacture minute OHLC from daily data. Official CSV/RPT schema must be observed from actual official sample; unsupported schemas fail with column details. Safe local-only imports first, with row/file-size limits, explicit Big5/UTF-8 handling, malformed row quality report, price/volume checks, stable sorting, duplicate identity policy. Preserve same timestamp distinct trades. No pickle/eval/automatic URL fetch or zip extraction needed for MVP.

Provide small source-attributed official-format fixtures where redistribution is permitted; synthetic fixtures labelled synthetic. Unknown historical margin/calendar/tax treatment remains a blocking warning for claims requiring it. No private or purchased data committed.

## B: strategy/backtest interface

`builtin_strategies()->tuple[StrategySpec,...]`

`validate_strategy(spec: StrategySpec)->None`

`generate_signals(bars: Sequence[Bar], spec: StrategySpec)->tuple[Signal,...]`

`run_backtest(dataset: Dataset, spec: StrategySpec, config: BacktestConfig)->BacktestResult`

Five families must each have distinct trigger tests and explanatory UI labels, not five parameter sets of the same rule. Parent confirmed no prescribed names; fixed list: trend (fast/slow average crossing), mean reversion (deviation band entry and mean exit), channel breakout (previous N bars high/low excluding current), momentum (N-bar return threshold with bounded holding period), volatility compression expansion (prior quiet-range condition then causal breakout). No look-ahead, negative lag, full-session volume at session open, future contract liquidity or warmup zero-filling. Warmup suppresses signals.

Chronology: process pending next-event orders using next tradable bar open; apply deterministic adverse slippage; process explicit stop/target with gap-aware fills and conservative ambiguity handling; mark account; make close-bar decision. On same-bar conflict, record ambiguity and conservative result. No guarantee that OHLC implies executable liquidity. Max one pending target per strategy/instrument decision. Target flips close then open with each leg's cost. Prevent position changes on missing/invalid data. Real contract roll is two fills with fees, never PnL on adjusted continuous prices; if roll unavailable block rather than stitch.

Accounting identity: equity = cash + unrealized PnL; for futures do not subtract full notional as purchase cash. Realized PnL from signed lot matching times multiplier minus costs. Daily settlement MTM must not double count prior realized/unrealized changes; unsupported settlement mode must be labelled. Maintenance-margin simulation and effective-date changes must be supported or explicitly excluded from verified scope. Full run manifest binds source commit, engine/config/spec/data/calendar/cost hashes, seed and execution assumptions.

Minimum golden corpus independently hand-calculated: long/short 20,000→20,010 gross ±100 TWD; multiple/partial lots; fees/tax; overnight; next-bar lag; gap stop; simultaneous stop/target; expiry; explicit roll; missing data; invalid half-tick; insufficient funds/margin; 3 identical output hashes. Negative-data and causal-prefix tests mandatory. Metrics derive from ledger/equity; daily returns use explicit trading dates and disclosed annualization, with empty/constant series handled.

## C: restricted AI/campaign contract

`validate_dsl(payload: dict)->StrategySpec`

`Generator.generate(context: dict)->dict` and `Generator.improve(context: dict)->dict` protocol; `FixtureGenerator` defaults to no network and returns deterministic candidate payloads. `CompatibleProvider` accepts explicit model/base endpoint/timeouts/config and an injected transport callable; implementation supports an OpenAI-compatible schema only behind explicit endpoint, opt-in network flag and enforced call/token/spend budget; zero-cost default, no default paid endpoint/call. Actual network/provider verification is BLOCKED until separately authorized. No live credentials, network access or spend in tests. Real-model status is `not_verified` until actually exercised under separate authorization; fixture success cannot be branded a real LLM evaluation.

DSL finite typed JSON AST, maximum bytes/depth/nodes/lookback/parameters. Operators whitelist numeric constants, allowed OHLCV fields, indicators, nonnegative lag, comparisons, `and|or|not`; reject arbitrary expressions, unknown keys, functions, imports, file paths, URLs and negative shifts. Rules never override hard risk controls. Only causal indicators from approved registry. Regex filtering alone is insufficient.

`run_campaign(dataset: Dataset, *, config: dict, generator: Generator, output_dir: Path)->dict`. Campaign locked config contains train/validation/OOS/holdout boundaries, family list, trial/iteration/runtime/resource budgets, seed, fixed ranking rule/thresholds, cost/config hashes. Starting budget proposal: five families × up to three candidates = 15 total trials; at most two improvement iterations per family; all attempts including invalid/errors consume and persist budget. This replaces earlier three-family proposal to meet user's five-family goal. No strategy performance threshold invented after looking at results. Platform success may yield zero selected candidates.

Loop explicitly records generate → validate → evaluate training/validation → bounded improve → select frozen candidate → OOS → final holdout. Generator receives train/validation summaries only, never OOS/holdout bars, results or feedback. Final holdout read once per locked campaign/candidate set; persistent consumed marker prevents repeated unseen claims across restarts. Every failed/rejected/cancelled attempt has parent_id, sequence, spec/output hash, provider/mode, prompt-template hash, split hashes, status, cost/time, metrics, warnings. Avoid deriving features across invalid split boundaries; purge overlapping holding windows and disclose warmup access. Trial ranking cannot silently use holdout results.

## D: paper contract

`RiskLimits(max_position: int, max_order_quantity: int, max_daily_loss: Decimal, max_quote_age_seconds: int)` and `RiskDecision(allowed: bool, reason: str)`; mandatory account/cash/margin/session/instrument checks.

`PaperBroker(journal_path: Path, *, instrument: Instrument, costs: CostSpec, limits: RiskLimits)`:
- `submit(intent: dict, *, quote: dict, now: datetime)->dict`
- `cancel(order_id: str, *, now: datetime)->dict`
- `apply_event(event: dict)->dict`
- `snapshot()->dict`
- `reconcile(snapshot: dict)->dict`
- `set_kill_switch(active: bool)->None`

Intent fields: client_order_id, strategy_hash, contract_id, side, quantity, order_type, limit_price?, created_at. SQLite transaction persists intent/state before paper execution; unique client ID with different payload is conflict, same payload is idempotent. Persist every ACK/fill/cancel/reject with unique event ID and original payload; duplicate exact event ignored, mismatched duplicate rejected; deterministic sequence or explicit quarantine for ambiguous ordering. Balances/positions recover by journal replay, with snapshot cross-check. UNKNOWN blocks new orders until successful reconciliation; do not auto-resubmit. Cancellation and fills can race; partial fills remain accounted for. Reconnect/restart checks orders/fills/positions/cash, discrepancy is an exception, not silent overwrite. Kill switch blocks new orders and does not liquidate; removing it requires explicit operation and reconciliation state.

`LiveBroker` interface exists only as methods raising `LiveTradingDisabled`; no credential reads, SDK imports, outbound connections or flag enabling live. Broker-specific capabilities and unavailable account qualification remain documented. Paper runs and synthetic fault fixtures are not proof of real-broker compatibility.

## E: report/UI interface

`comparison_rows(results: Sequence[BacktestResult])->list[dict]`

`export_report(result: BacktestResult, output_dir: Path)->dict` returns safe local paths for JSON manifest/ledger/metrics and CSV fills/equity, with reproducibility hashes. User-supplied filename/path components never escape output root; CSV formula injection escaped for text fields.

Streamlit tabs: local data import + quality; five strategies + assumptions; run/backtest ledger/chart; campaign/history; compare/select immutable version; paper account/risk/journal/reconciliation. Default page prominently says offline research/paper, synthetic/proxy/official data visibly distinguished. Selection changes research/paper candidate only; never starts legacy trading. Ranking metric, costs, sample count, OOS/holdout status and no-trade outcomes visible. All metrics trace to selected run/hash. Load result from disk on restart. Repeated button reruns do not duplicate campaign trials or paper orders. Validate error/empty/malformed flows and session reload. Headless CLI shares service functions, supports demo + import + backtest + campaign + compare; UI logic is thin.

## Fixed acceptance baseline: user Phases 0–5

Progress is evidence-based completed items, not elapsed time or test count; no partial credit for mocks presented as integrations. Freeze denominator before implementing. Each phase comprises five equal subitems; a subitem is either PASS or not PASS (BLOCKED/FAILED/NOT_RUN retain zero). A phase cannot be declared passed until all its mandatory checks pass. Overall percentage = sum of passed subitem weights. Safety failure blocks release regardless of score.

- Phase 0 Audit/architecture 15%: (1) source inventory and SHA, (2) security findings with evidence, (3) read-only dependency/entry-path audit, (4) architecture/ownership/contracts, (5) baseline/acceptance manifest. 3 points each. This phase records findings; repairs belong to Phase 1.
- Phase 1 Safe engineering foundation 15%: (1) legacy safety fixes, (2) pure import/no secrets/no network isolation, (3) isolated test entry point, (4) offline CI configuration, (5) regression tests proving safeguards. 3 points each.
- Phase 2 Data/backtest 25%: (1) official local import/schema/quality, (2) versioned session/calendar/expiry handling, (3) causal backtest/accounting execution, (4) costs and independent golden scenarios, (5) deterministic complete manifests and repeatability. 5 points each.
- Phase 3 Strategies/AI research 20%: (1) all five distinct causal strategy families with hand-check fixtures, (2) strict DSL validation/rejection corpus, (3) generator/evaluate/improve campaign with honest provider provenance, (4) enforced persistent budgets and all-trial records, (5) OOS/holdout isolation and consumed marker. 4 points each.
- Phase 4 UI/registry 10%: (1) end-to-end import/run Streamlit UI, (2) immutable registry/comparison/selection, (3) traceable metrics and exports, (4) empty/error/repeated-action tests, (5) restart persistence. 2 points each.
- Phase 5 Paper/delivery 15%: (1) durable idempotent paper journal/restart/reconciliation, (2) fault matrix and risk/stale/margin/kill tests, (3) disabled-live capability contract and security rescan, (4) final operating docs/manifest/limitations, (5) final full offline suite, functional UI verification and fresh-checkout/CI reproducibility. 3 points each.

Real-money activation, real broker certification, paid data/model calls, production returns, untouched future performance and real-world uptime are outside the development percentage. They must stay separate `NOT_VERIFIED/BLOCKED` readiness fields, never counted as completed by stubs. If data/license/calendar evidence prevents a required official-data check, engineering can continue but that subitem remains zero. Publication/PR/merge requires parent's verified authority.

## Additive implementation clarifications

- BacktestConfig fields: initial_cash, costs, max_position, same_bar_policy, seed, initial_margin_per_contract, margin_version, maintenance_margin_per_contract, cost_schedule, margin_schedule, instrument_expiries, roll_events, settlement_mode, settlement_events, source_commit. Defaults preserve earlier signatures; absent required real-data schedules fail closed.
- Shared records snapshot nested JSON containers immutably; serialized dictionaries are detached copies.
- Engine explicitly supports scheduled real-contract roll, daily MTM, and final expiry reference settlement with declared cost assumptions. It never turns adjusted continuous prices into fills.
- PaperBroker adds constructor-pinned risk_sessions and margin_schedule; quotes cannot redefine trusted dates, sessions or margin. Missing policy prevents orders.
- Generator and backtest operations run in bounded worker processes; actual platform memory-limit capability is recorded. HTTP transport defaults off and does not follow redirects. Real provider credentials and model evaluation are not part of fixture test evidence.
- Optional replay orchestrator uses selected strategy hashes, persisted cursor and idempotent event IDs; unsupported intrabar protective rules reject rather than silently diverge.
