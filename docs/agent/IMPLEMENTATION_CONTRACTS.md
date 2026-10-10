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

## Resumed product acceptance v2 — frozen before fixes (2026-10-09 22:30 UTC)

Owner explicitly requires continuation from main5943b6e; no restart, paid resources, live trading or weaker gates. One module branch `agent/desktop-acceptance-v2`, candidate0.1.2. Prior fixed200-point acceptance remains unchanged; D6 publication is now evidence-backed, while clean-client gates cannot gain points from preparing tools.

Required cases before implementation:
1. Clean-client kit must validate genuine Win10 22H2 x64 or Win11 x64 client OS, native architecture, standard-user operation, absent developer tools and clean isolated app/data state. Existing Server CI remains separately labeled. No external Windows image/license assumptions, no security-warning bypass. Missing manual/full-feature evidence blocks full product acceptance.
2. Actual released0.1.1→candidate0.1.2 upgrade must verify each version's own manifest/source hashes and app version, retain user data, refuse active-app update/uninstall, and complete restart/uninstall. Same-payload0.0.0 fixture remains limited packaging evidence only.
3. Actual bounded free local model must produce restricted DSL through the product CompatibleProvider/HTTPTransport path, with model source/revision/hash/license, inputs, failures, elapsed time and budgets recorded. No generated code execution, fixture fallback or fake model result. Train inputs only; OOS/holdout do not enter generation context. A smaller model failing is evidence, not permission to replace its result manually.
4. Official-history integration must use downloaded source bytes/hashes, independently evidenced session/contract calendars and complete bar coverage. Short verified data may prove engineering integration but cannot justify formal strategy ranking or investment performance.
5. Paper recovery must freeze on conflicting duplicate events, transport uncertainty, stale quotes and storage failures; repeated/reordered callbacks and crash/replay recovery cannot create extra orders. Offline fault injection is not evidence of real broker/feed reconnection.
6. Exact candidate source must pass regression, native UI, quality/history-secret scan, dependency audit, Windows installer lifecycle and release-integrity gates. Compare emitted manifest/digest with actual downloaded EXE. Signing/protection limitations remain explicit, not silently marked enabled.

Ownership: clean-client worker owns packaging/test_installer.ps1, clean_windows tools and related tests; model worker owns minimal research prompt/context and validator/tests; data worker owns official-history validator/tests; paper worker owns paper/replay and their tests. Coordinator owns version/build/workflows, integration and existing documentation. No overlapping edits without coordination. Failures are fixed against the frozen cases, never removed/skipped to obtain PASS.

### Bounded actual-model experiment ledger (predeclared per experiment)

Experiment1: official0.5B/free JSON,3calls; experiment2: official1.5B/free JSON,3calls; experiment3: same1.5B/structured registry schema on newly declared12-day technical splits,3calls. All previous failures remain preserved; no profitability threshold changed. Final separate improvement-loop acceptance: same1.5B, structured trend, one improvement, synthetic engineering fixture only,2calls, no real consumed holdout reuse. Total cap11actual calls, total model downloads1,608,720,768bytes below2GiB; no further model selection or performance chasing. Different experiment datasets/protocols prohibit causal claims of improved investment performance.

## 市場優先桌面新增合約（2026-10-10 00:15 UTC，實作前凍結）

使用者22:52 UTC新增正式需求；原200點不變，新增100點，逐項二元PASS，FAIL/BLOCKED/NOT_RUN為0，安全缺陷否決發布。原170/200=85%；新增初始0/100=0%；整體初始170/300=56.67%，剩43.33%。這是驗收加權非工時估計。分數不得用資料不足、畫面存在或mock成功取代。

M1真實來源/首頁/自選20；M2多週期互動K線20；M3全部指定指標15；M4一般表單AI/回測/比較/Paper/風控20；M5訊號與成交圖層5；M6合規AI操作模式10；M7繁中深色/DPI/偏好10。每項完整標準見05 Roadmap第19節；舊D5/D7/D8仍需clean client證據。

首批只新增唯讀市場型別/官方資料適配、聚合/指標與Qt圖表元件；不更改TMF交易核心、放寬研究資料品質或引入旧trader。TX/MXF/指數市場顯示不代表其交易回測已支援。官方小台每日代碼MTX對應UI MXF必須明示。正常功能不得要求使用者手寫JSON。

資料/指標固定：每bar綁實際symbol、exchange trade_date與session；分鐘以sessionopen錨定，不跨休市。日依交易日合併已知日夜盤，週ISO交易日週，缺漏/未收盤保留partial與來源，不補造。日資料不能變分鐘。SMA n完整bars；EMA以n樣本SMA seed再alpha2/(n+1)；RSI Wilder14，以n差值seed，全平50、無跌100；MACD12/26/9與hist=MACD-signal；KD9/3/3 seed50/50，平幅RSV50；Bollinger20/2母體std；VWAP sessionreset，OHLCV typical-price估計且明示，零累積量None。每項缺值/warmup不填0，不讀未来。參數/週期改動重算。

Golden cases含跨午夜/假期/到期短盤、乱序duplicate/缺bars/partial、不同contract絕不混合；prefix因果、手算/獨立公式指標、零量與平價，圖層signal/fill分開且hash一致。新模組測試與全核心回歸，Windows打包證據及實際畫面/交互後才給分。


# 0.2.1 official ChatGPT desktop integration contract
Frozen before host/core integration, 2026-10-10 01:00 UTC.

Scope: wire reviewed root desktop_chatgpt_auth/provider/ui into existing single-worker desktop lifecycle; optional official subscription mode alongside existing fixture/local/manual modes. Preserve research stdlib boundary, existing field validation, immutable budgets/holdout, and real trading disabled. No actual authorization, credentials, inference or paid request by this engineering task. User-owned official grant and live Windows behavior are separate external gates.

Required before engineering acceptance:
1. Normal typed繁中 settings/status and strategy mode, clear plan versus paid API distinction. Network/credit-policy acknowledgement not persisted; no auto registration/login/discovery/inference/refresh at startup, no copied tokens or third-party cookie access.
2. Auth operation explicitly allowlisted, bounded IPC and process deadline; official authorization URL transient only, never persisted/logged/result history. No token bytes outside locked DPAPI backend. Parent cancel/close/sleep/workspace switch stops/joins auth and inference before signout/change; a terminal packet alone cannot authorize next work.
3. Strict new-provider descriptor/source/dependency provenance plus durable receipt snapshot reconciliation after success/failure/killedworker. Invalid/unknown outcome freezes before further trial/selection/OOS/holdout. No budget refund/reset from workspace, campaign, model, backup or signout. Genuine engine-source changes invalidate reruns under old immutable identity; do not forge old source hash.
4. Source and frozen offline RS256/JWKS/parser and allowed UI flows, existing full regression, Windows DPAPI/process/native crypto tests, pinned dependency audit and complete applicable native notices. Fixture tests remain explicitly offline; no pass implies actual user grant.
5. Release source tree and payload hash checked, genuine released baseline upgrade/crash/data preservation, clean-client Windows10/11 statuses remain honest BLOCKED until real environments pass.
6. End-to-end real subscription generation requires user-controlled grant and explicit bounded request acknowledgement. Application cannot independently read/enforce account credit settings or server token ceilings; disclose this and never silently enable paid API fallback.

No acceptance threshold or original research identity files are weakened to make tests pass. New module is not merged into0.2.0 market release. Product changes limited to root desktop auth/provider/UI and host lifecycle wiring, generic research descriptor/receipt hook, tests, four pinned desktop-only dependencies, packaging provenance/notices and existing03/05/status documents.

### 0.2.1 跨授權復原反例補驗（02:02 UTC，修復前固定）

同一bootstrap下兩個不同opaque registration，A先預留但未知時，B的status/models/preflight/reserve不得顯示可繼續或送網路；並行兩者只能一個取得預留。暫停不可藉登出／新增授權繞過，不推論兩個subject代表同一人；只在本安裝建立保守的全域安全屏障，各registration的身分與receipt仍分開。任一已登記ledger遺失／毀損／count回退，不能透過另一registration重建或繼續呼叫。明確解除選定的已知pause只在沒有任何active/unknown時允許，不得解除別人的pause、退還未知次數或重置預算。已完成且完整的其他ledger不能被當作未完成而永遠阻塞。這些是原不可繞過復原合約的反例，不更改驗收門檻或增加付費／真帳戶操作。
