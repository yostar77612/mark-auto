# mark-auto implementation contracts v1 — frozen development baseline

### T14 part A: verified trust anchors and worker error stages (P3-12 / P3-02)

Worker `error` packets retain `job_id`, `type`, fixed `message` and `error_type`,
and add `stage`: one of `prepare_operation`, `load_data`, `build_candidates`,
`run_backtest`, `run_campaign`, `run_operation`, `write_result`, `unknown`.
Non-string or unrecognized stage values normalize to `unknown`; exception
values never select stages. UI error notifications render only the fixed
desktop_strings stage message, with a generic fallback for missing/unknown
codes; raw message, exception text, paths and secrets are never displayed.
Stage progress annotations are optional and contain only normalized codes.
Campaign internals remain one coarse `run_campaign` stage because research.py
is locked. See docs/analysis/t14_p3_notes.md for the boundary details.

downloads and market_providers use tls_trust.build_trust_context: Windows ROOT
server-auth anchors only, CERT_REQUIRED and hostname verification mandatory.
Empty/unavailable/unusable stores use verified platform defaults. provider.py
and the eight G3 source files/profile literals remain unchanged. Offline fake
store tests establish selection, not live endpoint or real-chain acceptance.

### T8 part B: Walk-forward wizard

This supersedes part A's pending/collapsed Walk-forward description below.
Current tab heights are 490 / 438 / 748 px at 1366x768; the original part A
measurements remain historical evidence in the per-run snapshot log.

The Walk-forward tab presents five sequential steps: pool, data, windows,
preview, and consent/run. It reparents existing controls without changing their
objectNames or the preview/run/read/reconcile operations. The legacy outer
section toggle retains its identity/preference key but is hidden; the wizard is
always available. Next refuses invalid steps with catalog text, and the stack
guards direct/programmatic jumps. Standard preview takes three Next actions
when a valid dataset is already loaded. Data selection uses the current imported
dataset; saved pools also require the existing original-data picker.

For N=8..100000 bars, presets fill only the existing typed fields: start=0,
train=max(1,N//4), gap=0, validation=oos=step=max(1,N//8) for Quick/Standard
and max(1,N//16) for Strict. Fold counts are 2/3/4; holdout starts at
train+(folds+1)*width and ends at N; evaluation limits are 22/33/44.
Mode, evidence, ranking, runtime and costs retain their existing values.
Saved pools retain authoritative admission and budget rejection; presets never
increase an admitted pool's quota or bypass the preview worker. Custom alone
shows/enables the raw editor. The same request grammar and source validator
check window steps, and the existing preview operation remains authoritative.

Preview displays four proportional train/validation/walk-forward/holdout segments
(first fold plus final holdout), a Chinese summary table, safety notices and
P0-10 formatted numbers. Raw evidence remains in the existing advanced control.
Invalidation clears the summary and hides the timeline. Run requires a current
preview and explicit one-time consent, including after busy-state reset.
desktop_walk_forward.py and all pinned G3 sources remain unchanged. Snapshot
metrics include all tab heights plus each wizard step's natural content height
without bypassing navigation guards or starting jobs. Evidence:
tests/test_wf_wizard.py and docs/analysis/t8_snapshot_numbers.json.

<!-- CURRENT_STATUS_START -->
## 目前交付對帳（2026-10-10 23:42 UTC）

0.2.2 unsigned preview 已從產品來源 `9d35c7d7` 發布；exact-main Quantlab 12 jobs、Windows native／frozen TLS／安裝升級復原與公開下載驗證均 PASS。M4 依原 §19 條件取得 20 點，現行 **230/300＝76.67%，剩餘23.33%**；其他固定權重與未通過項目不變。

詳細證據、下載、M4 判定與剩餘 D5／D7／D8／M2／M6／M7 分界統一見 [PROJECT_STATE](PROJECT_STATE.md) 與 ACCEPTANCE.json 的 current_snapshot。乾淨 Win10／Win11、真實 ChatGPT 訂閱授權／推論及完整市場分鐘資料權限仍未閉合；不以 Server／mock 冒充。此變更只有文件，不改產品、測試、工作流或已發布安裝檔來源。
<!-- CURRENT_STATUS_END -->

## 以下為保留的歷史契約、決策與檢查點

截至本次對帳以前的210/300、M4 PARTIAL、IMPLEMENTATION_PENDING、失敗／取消／尚未發布等文字保留其原時間與來源；不代表目前終態。原需求、未解除安全底線及非本次明示更新的gate仍有效；歷史失敗不刪除、不追溯改為PASS。

Baseline: `main@1cacce4ee4eef4ce7e8760f8153ef64a74852d22`. Frozen 2026-10-09 before implementation. Source/security audit approved. Fixed acceptance goals cannot be lowered; additive changes below preserve required behavior.

## Decision and evidence

Keep Python and Streamlit. Add sibling `quantlab/` package, not a wholesale rewrite and not a subpackage of `trader`. Core uses Python standard library only (`dataclasses`, `decimal`, `datetime`, `zoneinfo`, `csv`, `json`, `sqlite3`, `hashlib`); UI alone imports Streamlit. Python 3.11+ target; optional Windows tzdata dependency must be documented. Separate `research_app.py` entry point; never invoke archived `archives/legacy_autotrading/gui.py` or `archives/legacy_autotrading/run.py` in research tests.

Evidence: `archives/legacy_autotrading/trader/config.py:6,15–16,79` imports Shioaji and constructs a non-simulation API at import; `archives/legacy_autotrading/trader/__init__.py:1–29` creates executor/shared objects/directories; `archives/legacy_autotrading/gui.py:10–13` imports that configuration/database path and `start_trader` launches `archives/legacy_autotrading/run.py`; `archives/legacy_autotrading/trader/utils/strategy.py:6–12` couples signals to mutable TradeData, database and configuration; `archives/legacy_autotrading/trader/performance/reports.py:18` imports missing backtest module. The historical dependency list (now `archives/legacy_autotrading/requirements.txt`) contains Streamlit 1.45.1 and pandas 2.3.3; it is not a current installation recipe. Preserve legacy indicators as reference, but do not import them through `trader`; reuse only after explicit extraction with regression fixtures. This avoids making unrelated stock/live infrastructure a prerequisite for safe TMF research.

Legacy safety patch is separate: disable unsafe automatic/live entry paths, require nonempty Telegram allowlist, redact credential-bearing SQL logging. Do not modernize every legacy dependency or claim retained legacy execution is verified. Never enable a live client via environment variable alone.

## UI operation registry (P2-A4)

`desktop_ui.execute_ui_operation` retains its worker signature and public import
surface. Its private `_UI_OPERATION_HANDLERS` dictionary has exactly one distinct
module-level callable per `UI_OPERATIONS` entry. The dispatcher rejects operations
outside that immutable allowlist before workspace setup or handler invocation;
campaign provider-mode validation also precedes setup. Each handler and the
dispatcher are limited to 60 source lines. Paper policy setup and journal export
are shared helpers; replay still calls `require_replay_wal` before constructing
`PaperReplay`. The function-local import in `quantlab.desktop_runtime` is retained.

`tests/fixtures/ui_operations_golden.json` records results, events and rejection
messages from the HEAD dispatcher captured before extraction. Its metadata lists
offline limitations and the exact temporary-path, path-derived identity and
elapsed-time normalisations. `desktop_ui_public_names.json` freezes the public
import surface. Each test loads `git show HEAD:desktop_ui.py` under an isolated
module name and exercises old and new implementations in separate fresh temporary
workspaces against the recorded baseline. Successful coverage includes synthetic
analysis preview/run/read/reconcile, fixture and mock-wire subscription campaigns,
subscription reconciliation, accepted paper orders/cancel requests and replay fills,
local daily/history imports, and walk-forward preview/run/read/reconcile. Only
official TAIFEX download requires external network; its consent rejection and
precise offline limitation are recorded. Real transport is barred by a socket
guard. Bounded computation uses existing offline worker fixtures; safety and
receipt validation run normally. Stopwatch durations, import wall time, temporary
paths and formula-derived replay identities are the documented normalisations.
Every exercise patches the process environment with fresh USERPROFILE/HOME,
LOCALAPPDATA/APPDATA and home/XDG paths, restoring it afterwards. The locale is
temporarily C. Auth uses the real empty-file lookup, lock and AuthSession; only
DPAPIVault's host SID/DACL preparation is replaced by directory creation confined
to the temporary root. Encryption/decryption and official auth HTTP requests are
forbidden. Thus empty-vault restore records `host_initialization_required`, not a
sandbox-specific ACL error. The auth golden was regenerated from HEAD's old
dispatcher with this same setup; every other observation remained exact.
All scenarios also replay under clean and synthetic remembered-login outer
profiles, checking that sentinel credentials remain untouched and env is restored.
Host-state audit: these handlers do not construct widgets or query installed
fonts. Inputs specify numeric values, UTC-aware synthetic timestamps, calendars,
seeds and worker budgets; no default CPU-count sizing is used. C locale fixes
formatting and TZ=UTC is set, but Windows timezone is not assumed to follow TZ:
the fixtures use explicit UTC dates instead. Current time only appears in the
documented import metadata and stopwatch fields above. SQLite's actual supported
runtime is retained (including WAL/version guards), with no version spoofing or
version-dependent output masked. Files and durable controls live exclusively in
fresh temporary roots; no existing profile data is an input. Socket guards and
offline transport/worker fixtures cover the network and process boundaries.
The legacy AST-isolation replay test compiles the dispatcher, every registered
handler, registry and shared paper helpers together. Its original assertion still
requires the durable WAL barrier before the actual replay constructor is reached.

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
1. Normal typed繁中 settings/status and strategy mode, clear plan versus paid API distinction. Network/credit-policy acknowledgement not persisted; no auto registration/new authorization/discovery/inference at startup, no copied tokens or third-party cookie access. Remembered login (owner decision 2026-10-17): a normal (non-smoke) desktop start runs one local `restore` job once background work is idle; it reads the DPAPI vault and, only when the active registration is `refresh_required`, performs one refresh with its saved refresh token. Refresh failures keep AuthSession's persisted state (no retry loop). The primary sign-in button is hidden while the active registration is `plan_ready`/`identity_only`; pressing sign-in while connected opens no browser, and while `refresh_required` it refreshes before any reauthorization.
2. Auth operation explicitly allowlisted, bounded IPC and process deadline; official authorization URL transient only, never persisted/logged/result history. No token bytes outside locked DPAPI backend. Parent cancel/close/sleep/workspace switch stops/joins auth and inference before signout/change; a terminal packet alone cannot authorize next work.
3. Strict new-provider descriptor/source/dependency provenance plus durable receipt snapshot reconciliation after success/failure/killedworker. Invalid/unknown outcome freezes before further trial/selection/OOS/holdout. No budget refund/reset from workspace, campaign, model, backup or signout. Genuine engine-source changes invalidate reruns under old immutable identity; do not forge old source hash.
4. Source and frozen offline RS256/JWKS/parser and allowed UI flows, existing full regression, Windows DPAPI/process/native crypto tests, pinned dependency audit and complete applicable native notices. Fixture tests remain explicitly offline; no pass implies actual user grant.
5. Release source tree and payload hash checked, genuine released baseline upgrade/crash/data preservation, clean-client Windows10/11 statuses remain honest BLOCKED until real environments pass.
6. End-to-end real subscription generation requires user-controlled grant and explicit bounded request acknowledgement. Application cannot independently read/enforce account credit settings or server token ceilings; disclose this and never silently enable paid API fallback.

No acceptance threshold or original research identity files are weakened to make tests pass. New module is not merged into0.2.0 market release. Product changes limited to root desktop auth/provider/UI and host lifecycle wiring, generic research descriptor/receipt hook, tests, four pinned desktop-only dependencies, packaging provenance/notices and existing03/05/status documents.

### 0.2.1 跨授權復原反例補驗（02:02 UTC，修復前固定）

同一bootstrap下兩個不同opaque registration，A先預留但未知時，B的status/models/preflight/reserve不得顯示可繼續或送網路；並行兩者只能一個取得預留。暫停不可藉登出／新增授權繞過，不推論兩個subject代表同一人；只在本安裝建立保守的全域安全屏障，各registration的身分與receipt仍分開。任一已登記ledger遺失／毀損／count回退，不能透過另一registration重建或繼續呼叫。明確解除選定的已知pause只在沒有任何active/unknown時允許，不得解除別人的pause、退還未知次數或重置預算。已完成且完整的其他ledger不能被當作未完成而永遠阻塞。這些是原不可繞過復原合約的反例，不更改驗收門檻或增加付費／真帳戶操作。


## 0.2.2 行情與一般操作驗收模組

承接已合併0.2.1；以下行情合約於01:34 UTC隔離實作前凍結，本段納回唯一工程合約。實際CSV/RPT bytes不提交或打包。

# Market-only native tick history module — frozen 2026-10-10 01:34 UTC

Staging only: /tmp/mark-auto-market-history, copied from /tmp/mark-auto-oauth-host. No source checkout edits, commits, release delay, paid/network/model/broker changes. Existing trading/research validators remain unchanged. Scope is the next module after 0.2.1, not a retrospective acceptance change.

## Owned scope
New quantlab/market_history.py; desktop_ui.py and desktop_market.py only for typed local history import/reload controls; new tests/test_market_history.py, tests/test_market_history_ui.py; optional tools/validate_market_history_import.py. Existing UI tests may receive narrowly necessary additions. No account/OAuth/provider logic changes. Source/data/calendar remain local; do not bundle real ticks or derived bars.

## Frozen behavior and tests
1. Stream observed TAIFEX nine-column CSV/comma-delimited RPT, UTF-8 or CP950; maximum64MiB,1,000,000rows,120seconds, cancellation callback checked throughout. Reject unknown/fixed-width schema, wrong columns, nonfinite/nonintegral prices, invalid dates, odd/nonpositive B+S quantity, unsafe paths and selected malformed rows. Do not parse arbitrary JSON as normal market history input.
2. Explicit TX/MTX/TMF actual monthly/weekly contracts using InstrumentRef; MTX displayed as MXF. Preserve all same-second trades and source row order. Exclude/count spreads, unrelated products/contracts and out-of-selected-session ticks; do not merge expiry identities. Single-sided quantity=B+S/2.
3. Typed session records require explicit contract, exchange trade date, local opening/closing dates/times and endpoint inclusion. No perpetual calendar, holiday inference, date+1 attribution or silently cloned TMF calendar. Official product pages support product schedule rules; manually entered dated session attribution remains user-declared/unverified unless independent source manifest is supplied. UI never requires handwritten JSON. Tests cover day/night midnight/holiday attribution, short expiry, overlap and uncovered intervals.
4. Aggregate actual trades into session-open-anchored1m MarketBar values with real timestamp/end/trade_date/session/sourcehash. Explicit inclusive close tick goes into last bucket. No absent minute filled; count gaps, warn incomplete coverage, retain partial state without implying tick completeness. Reuse existing chart_data.aggregate_bars for all8timeframes; daily/weekly completeness remains conservatively unknown without calendar certification. No invented index minute data.
5. Separate managed market-history cache with immutable source/session-policy hashes, normalized bounded bars and counters. Never cache raw64MiB input as oversized JSON. Atomic validated cache, symlink/Windows reparse rejection, collision/unknown-file refusal, verified reload and restart. Local imports remain history/unverified with explicit license warning; no broker/research eligibility or remote authenticity claims. Cancellation/error cannot replace last good import.
6. GUI uses normal file/session/contract controls and background-job execution; Cancel before and during import, repeated import, validation errors and restart tested. Existing market daily/TMF research and other account functionality remain intact.
7. Actual private integration: source CSV/RPT SHA6807f4c3b7f977cb7e5109b1135fe69bbfe18d7c6b71a445e6576bb6be6163a8,34363020bytes, must reproduce exactly300day minutes each TX/MTX/TMF202610 on2026-10-08 and independent daily OHLC. Preserve outright volume differences and distinguish actual-file evidence from synthetic edge tests. Never bundle raw or derived exchange files.
8. Read-only graph/no network tests, focused existing market/chart/UI regressions; ownership diff and output hashes supplied. Tests cannot be weakened/skipped to obtain PASS. Missing source support or environment evidence remains explicit BLOCKED.

## Proposed public boundary
MarketSession(instrument,trade_date,session,open,end,include_end=False,source=official_product_url): frozen validated UTC record. source means reference, not authenticated policy proof.
import_history(path,root,*,sessions,received_at=None,cancelled=None)->HistoryLoad(series tuple,policy_hash,source_hash,counters,warnings,cache_id).
load_history(root,cache_id)->HistoryLoad; list_history(root)->tuple[HistoryLoad,...]. The UI owns choosing exact contract/session records. No default live/network activity.

### 既有普通操作反例，修復前固定

- 真資料回測仍需明確每合約到期日。BacktestForm新增型別化合約/日期table，不推算第三個星期三、不宣称日期已查證，不改核心檢查。載入原mapping/advancedconfig完整保留；重複/非法/未完成列拒絕。同一payload供普通回測和研究。僅允許既有training區間真資料重播，不再消耗模型/OOS/holdout。
- 紙上replay必須使用已鎖定的有效日margin policy，含source/version完整身分，夜盤依exchange trade_date。不能硬編100000覆蓋使用者有效120000。scalar既有caller身分與riskguard保留；schedule mode同一replay路徑遇舊身分必須保留原檔並拒絕，不新建路徑重送、不遷移或清空既有orders。測試多個有效日、缺coverage、version/source/future-row改變、各中断點、重啟與重複操作無額外委託。
- 打包smoke必須保留原七步與manual兩步、offline auth，加獨立history_import真worker/cache重載及三商品×八周期24次原生圖表繪製。synthetic fixture明示、network/model不得呼叫、120秒原上限不變，缺模組/假結果/cache改動/failure均使整體失敗。

所有component與完整回歸後，原生Windows exact-head build/install/真releasedbaseline升級/中斷恢復與下載產物hash核對仍為必要Gate。cleanWindows10/11不得用Server代替。


## 2026-10-10 11:16 UTC — user-authorized AI-route supersession

Official Sign in with ChatGPT subscription integration is REQUIRED. This replaces the older optional/alternative-route wording and local-model delivery requirement above and in Roadmap §19: no local-model feature, Qwen/Ollama/Hugging Face/GGUF download or local inference, and no paid API or credits fallback. Implementation is IN_PROGRESS; no correction-source test or native PASS is claimed. Preserve all earlier evidence, M6 weight10/PARTIAL,210/300, and every unrelated locked gate.

The existing official PKCE/OIDC, DPAPI, worker cleanup, source/receipt provenance, persistent budgets and holdout restrictions remain. Real OAuth grant and bounded subscription requests require owner authorization; mocks cannot certify them. Included-only usage is a user-attested prerequisite with Settings > Usage guidance, not verified server configuration or an application monetary cap. The [official Help Center](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites) states that optional credit use is global and also requires the app limit at100%; an app limit below100% prevents that app's credit use. The reviewed guidance provides no per-request subscription-only flag. Do not infer that signing in alone prevents credit charges or alter owner settings automatically.
# T2-B P0 completion and account presentation contracts

- P0-14: ordinary background completions use one `local_notification` with
  `查看結果` navigation and `關閉`. Success waits five seconds then fades over
  300 ms; failures and partial official-source failures remain until closed.
  The status label is cleared on completion. Disabling local alerts suppresses
  window attention, not the operation result. Error text uses desktop_errors.
- P0-17: operation-specific summaries include synthetic bar counts, aggregate
  backtest net PnL/trades/report count, selected version, paper cash and ledger
  counts. Replay reports this batch's processed bars/new fills and saved cursor.
  These are presentation fields; report hashes and engine inputs are unchanged.
- P0-18: demo policy, loaded policy/snapshot and candidate/builtin fills report
  status, scroll the changed form into view and highlight it for 1.8 seconds.
  Demo status uses actual session count, e.g. `已填入示範政策：4 個交易時段、1 筆保證金設定（合成資料）`.
- P0-19: normal replay completion is green, user emergency stop red, risk/safety
  stop amber. A separate presentation marker is bound to the full account hash;
  stale/unavailable markers never imply normal completion or execution permission.
  Engine kill/reconciliation and risk validation are unchanged.
- P0-20: one paper account card shows ledger cash, position items/quantities,
  order/fill counts, reconciliation and stop state. Counts inside the snapshot
  form explicitly begin with `參考快照`; they describe that external input only.
- Focused offline evidence: `tests/test_desktop_feedback_p0.py`. Full-suite/native
  controller verification remains required; no acceptance weights are changed.

# T2-A P0 correctness presentation contracts

- P0-01: account-card refresh uses `PaperBroker.read_snapshot`, a SQLite
  `mode=ro` / `query_only` transaction with journal replay verification. It
  neither creates a journal nor appends restart events. Normal PaperBroker
  construction retains restart/reconciliation semantics.
- P0-05: `quantlab/desktop_errors.py` owns fixed error codes, Chinese
  explanations and next steps. Desktop exception handlers display catalogue
  text and codes; unknown errors use a generic Chinese message. Exception
  strings, paths and tokens are not display/log input. RedactedEventLog accepts
  only allowlisted optional error codes, including when reading persisted logs.
  History form checks retain specific fixed CSV/RPT, expiry/date, confirmation,
  duplicate and overlap messages through catalogue codes; raw validation
  exceptions still use safe catalogue text. Synchronous UI errors replace any
  previous success notification and remain visible until closed, even when
  attention alerts are disabled. Rejected policies never start a worker or save.
- T2 repair: official market summaries omit the failure count when zero;
  nonzero source failures retain their count and persistent notification.
- P0-06: startup distinguishes an old SQLite runtime, incompatible workspace
  format and the single-instance workspace lock, with Chinese next steps.
  Unknown failures retain a generic message and preserve existing data.
- P0-09: restore is a startup action that may refresh over the network, separate
  from local-only list. The host schedules it only while idle. Restore refresh
  and authorization cleanup failures report `restore_refresh_failed` and
  `authorization_cleanup_failed`; the host persists only those fixed codes.
  Failed restore exposes sign-in again after the worker has joined.
- Regression evidence: `tests/test_desktop_ui_p0_correctness.py` exercises
  three consecutive card refreshes, real restart, unknown exception redaction,
  startup classification, failed restore/sign-in and fixed-code logging.


## T3 A — P0 UI polish presentation contracts

P0-02/03/04/13 preserve objectNames, payloads, eligibility checks, quotas and OOS consumption.
`MainWindow._button(..., role='secondary')` accepts primary/secondary/danger; the existing host stylesheet owns role colors. Each page has at most one primary. Emergency stop, backup restore, order cancellation and row deletion use danger styling and explicit confirmation; existing restore consent remains required.
All input fields have persistent visible captions; bar/day/request/timeout spin boxes show units without changing numeric values. Page captions use AI 策略中心 consistently. Paper policy tables size columns to their headers and contents.
Every disabled action has a tooltip and adjacent prerequisite hint following Qt EnabledChange, including disabled ancestors; the helper never enables actions. Snapshot `primary_button_count` counts only `role == 'primary'`, and `disabled_buttons` records object name, text, tooltip and hint.
Regression evidence: tests/test_desktop_ui_polish_a.py, tests/test_ui_snapshot.py, tests/test_desktop_expiries.py. Offscreen 1366x768: unlabeled inputs 10 → 0 across seven pages; primary counts 0/1/1/1/1/1/1. Before/after artifacts: .tmp-t3/before and .tmp-t3/after. Full worker suite remains controller-owned outside the sandbox.

## T3 B — P0 display and disclosure contracts

P0-07/08/10/11/12 change presentation only. The sole top marker `研究模式・實盤停用` expands to the full research limitations. Repeated page warnings are removed; irreversible OOS consent and enforced risk limits remain intact.
Technical forms, Walk-forward, full candidate evaluation/history, paper policy, reference evidence and manual order parameters live in collapsed `進階` sections. `advanced_sections` stores only section booleans in non-sensitive settings, including market diagnostics and Walk-forward evidence. New profiles default to collapsed. At 1366×768, `tools/ui_snapshot.capture` measures AI 策略中心 at 956 px and 紙上交易與復原 at 1073 px (each ≤1600).
`desktop_presentation.py` owns display number formatting and status translations: amounts use separators and TWD, ratios use percent, other metrics have at most four decimals. Original decimal strings, stored records, hashes and payloads remain exact; tooltips/advanced views retain original values. Unknown status codes show a Chinese diagnostic fallback. Default backtest fee inputs are inside advanced because their exact editable tax ratio has five decimals.
Result selectors and compare lists use strategy family, main parameters, data interval and creation time in Taipei (legacy report file creation time), with numeric collision suffixes. UserRole paths and report IDs are unchanged; hashes remain in tooltips and advanced records. Corrupt metadata gets a readable fallback and remains subject to the original loader validation.
Regression evidence: tests/test_desktop_ui_polish_b.py plus updated backtest/candidate presentation, market acceptance and feedback tests. Full suite/native worker verification remains controller-owned outside the sandbox.


## T3-C ? dependency archive and application icon contracts

P0-15: the legacy requirements file is archived byte-for-byte at `archives/legacy_autotrading/requirements.txt` (SHA-256 `0402de4d2eb719a30c7dd5428e9fcc9db10732fc76ce1419b959719d99f08ec0`). The obsolete root dependency list is absent. README directs installation to requirements-desktop.lock and packaging/build.ps1; current lock dependency audits remain unchanged. Historical commit links remain historical evidence.

P0-16: tools/make_icon.py uses only the standard library, no network, to produce packaging/markauto.ico with 16/24/32/48/64/128/256 px images. desktop_icon.application_icon loads from the module-relative packaging path (also PyInstaller _internal); absent/corrupt artwork falls back to Qt's standard computer icon. QApplication startup and MainWindow explicitly set non-null window icons. PyInstaller embeds the EXE icon and ships the ICO as data; Inno Setup uses it for setup and uninstall display. Shortcut icons use the EXE resource.

Packaging consistency: build_manifest.py records both artwork and generator; payload_inventory.py discovers the new asset automatically without a fixed file list. test_installer.ps1 verifies the installed candidate icon against its source manifest while preserving compatibility with historical baselines. test_packaging.py checks data/source manifest inputs; test_prepared_host_session.py pins the updated lifecycle hash without weakening guards. Regression tests: tests/test_application_icon.py. Actual frozen EXE/taskbar/installer/client Windows appearance remains controller-owned verification. Existing safety, quotas, objectNames and OOS consumption are unchanged.

## T4 — Shared desktop UI text

User-visible text authored in desktop UI modules lives in `desktop_strings.py`.
`ui_text` resolves stable keys with a Traditional Chinese fallback; dynamic text
uses catalog templates and preserves the original formatting. Existing domain
error and feedback catalogs remain authoritative in `quantlab`.

`tests/test_no_hardcoded_ui_text.py` inventories every top-level `desktop*.py`
module and scans every UI module, including f-string text, with an empty TODO
list and empty literal allowlist. Only true docstrings and logging arguments
are exempt. Documented non-UI exclusions are the catalog, CLI TLS diagnostic,
and SHA-256-pinned `desktop_chatgpt_auth.py`/`desktop_chatgpt_provider.py`;
the pinned files are never migrated. Any future literal exception needs a
specific documented reason rather than a module-wide UI exemption.

Regression evidence: `tests/test_desktop_strings.py` checks all UI lookup keys,
fallbacks, formatting, Python 3.11 syntax and live widget lookup. A fresh
`git archive HEAD` baseline and migrated `tools/ui_snapshot.py` capture have
identical `visible_text` on all seven pages at 1366×768; hashes and G3 source
checks are recorded in `docs/analysis/t4_ui_text_comparison.json`.
ObjectNames, payloads, validation, quotas and one-time OOS consumption are unchanged.


## T5 — Desktop theme and style module

- `desktop_theme.py` owns colour tokens (`COLORS`, `STATUS_COLORS`), pixel font sizes,
  spacing and the complete application QSS. `build_app_stylesheet()` resolves these
  tokens; `apply_theme(window)` installs it on the MainWindow (not the QApplication, so independently hosted top-level widgets render as before); widgets other than the window root and the market dashboard keep empty QSS.
- Existing objectNames and `role=primary|secondary|danger` remain stable. Runtime
  status colours use `status=success|warning|danger|neutral`; `set_status()` validates
  the state and unpolishes/polishes the widget. Market rise/fall and notification
  colours retain their original scoped palette. Form feedback uses a temporary
  `feedback` property and restores its previous value after 1800 ms.
- No desktop or tools module may call `setStyleSheet` outside the theme module.
  The AST allowlist in `tests/test_no_inline_stylesheet.py` is empty; the runtime widget allowlist
  contains only `market_dashboard`, which receives its scoped dark sheet from
  `desktop_theme.apply_market_theme()`. QPainter chart drawing needs no QSS exception. Tests cover every button role,
  empty widget stylesheets, live status palette refresh, and existing feedback.
- Visual parity is checked against a `git archive HEAD` copy with
  `tools/ui_snapshot.py --size 1366x768` on both trees using identical Qt settings.
  `tools/ui_theme_diff.py BEFORE AFTER` requires identical metrics, PNG sets and
  dimensions, with at most 0.1% of pixels having any RGB channel delta above 8.
  T5 evidence: `docs/analysis/baseline/t5_theme_1366x768.json` (all 14 PNGs: 0%).
- Presentation only: desktop strings, account decisions, safety validation, quotas,
  OOS consumption and pinned producer sources are unchanged.


## T6 part A ? Desktop page boundaries

`desktop_pages` owns MarketPage (including cache and result chart binding), DataPage,
StrategyPage (including walk-forward controls/callbacks and campaign/candidate actions),
and BacktestPage. Pages use the explicit `PageHost` callbacks and `PageState` object;
they never import desktop_ui or discover a shell through QWidget parents. Existing
MainWindow widget and handler names remain explicit aliases. EquityPlot and the actual
open-lot reference-line helper also live in desktop_pages; their desktop_ui import and
static-method access paths remain available.

Compare, Paper and Settings construction/handlers remain in MainWindow for part B.
The staged MainWindow AST ceiling is 1500 lines; part B must replace it with 400.
Every migrated page class is limited to 500 lines. No business rules or UI text changed.

`tests/test_desktop_pages.py` verifies the boundaries, objectName set, explicit aliases,
host job dispatch, consent resets, shared preview invalidation, and actual result chart
binding (including mismatched-source rejection). Its visual test compares all seven
pages against `tests/fixtures/desktop_pages_before`, captured from an archive of the
pre-change HEAD. Metrics JSON and all 14 PNG pixel buffers are identical at 1366x768,
scale 1, using the snapshot tool's Windows offscreen font/style settings. Baseline
provenance is in `tests/fixtures/desktop_pages_baseline.json`. Both text and stylesheet
AST guards recursively cover desktop_pages and include injected-violation tests.

## T6 part B - Complete desktop page boundaries

ComparePage owns comparison/selection and candidate analysis construction, preview,
consent and recovery presentation. PaperPage owns paper construction, account rendering,
policy/snapshot loading and paper actions. SettingsPage owns settings, backup/log handlers
and ChatGPT connection construction, signals and callbacks. WidgetTools and ViewCoordinator
own shared widget construction and result/view rendering. Page composition, compatibility
aliases and cross-page signal wiring live in desktop_pages.mount. Part A page bodies and
the pre-change visual archive are preserved.

MainWindow owns navigation, global status/notifications, background-job scheduling and
callback dispatch, and shutdown/recovery coordination. Its enforced AST ceiling is 400
lines (measured 371); every page class remains at most 500 lines (largest: StrategyPage,
326). SharedStateBindings contains data descriptors; PageContext exposes explicit host
callbacks without importing or discovering the shell. Public desktop_ui module names,
widget aliases and handler aliases remain available, including late dispatch of patched
public analysis/rendering helpers.

tests/test_desktop_pages.py enforces all seven page boundaries and the final ceilings.
Focused interactions cover comparison dispatch, fail-closed paper and restore consent,
ChatGPT signals, shared analysis state, settings geometry, and result dispatch. All seven
metrics JSON entries and 14 PNG pixel buffers still match the pre-change archive exactly.
No validation, quota, OOS policy, rendered text, objectName or pinned producer source changed.
The full suite is controller-owned outside the sandbox. Part B evidence and the ignored
.t6-work deletion inventory are in docs/analysis/t6_page_split_part_b.json.

### T6 repair - Frame position and semantic parity

Window persistence uses `PageHost.window_position()` bound to
`QPoint(MainWindow.x(), MainWindow.y())`: x/y are frame coordinates, including
restore defaults. `window_geometry()` supplies only client width/height, equal
to QWidget.width()/height(); integer conversion and screen clamping retain the
original behavior. Both settings and market saves must round-trip without frame
drift. `tests/test_desktop_window_position.py` models a client offset of +8/+31
without relying on offscreen window decorations.

Native file/confirmation dialogs and the modeless market-history dialog retain
MainWindow parenting through explicit host callbacks. Pages never discover the
shell through parent/window lookup. The focused audit lists every examined
method and notable substitution in `docs/analysis/t6_semantic_audit.json`:
77 named methods, seven page construction methods, shared-state/callback bindings,
EquityPlot and result snapshot helpers. The frame-position regression and five
dialog-parent substitutions were repaired; other examined routing, defaults,
conversions, references, signal targets and timer lifetimes retain behavior.
Fresh origin/main and repaired snapshots have identical metrics for all seven
pages and identical pixel buffers for all 14 PNGs at 1366x768, scale 1.

### T6 CI repair - Platform-independent snapshot assertions

On every platform, the snapshot regression compares the seven page names and order,
visible text, visible input/button counts, label character counts, unlabeled inputs
and primary button counts exactly against the pre-change archive. The widget
objectName set and AST class line limits remain exact on every platform. The
archive was captured with Windows fonts: byte-for-byte metrics JSON (including
page_height and full_width) and all 14 PNG pixel buffers remain required on
sys.platform == 'win32'; other platforms compare the behavioral facts without
Windows geometry or rasterization expectations. Window-position tests use explicit
frame/client offsets and screen doubles; no Windows native APIs are required.


## T8 part A - Strategy center work areas

StrategyPage contains exactly three catalog-labelled tabs (strategy settings, AI research, Walk-forward validation), initially selecting settings. Each tab has its own scroll content. Strategy selection controls stay in settings; campaign generation, candidate history/evidence and the expandable candidate analysis block live in research. Existing Walk-forward controls remain collapsed by default in validation pending the next run. ComparePage keeps its shared-state analysis handlers and signal bindings for compatibility, while every analysis widget is a descendant of the research tab. No backend validation, preview, consent, quota, OOS consumption or retry logic changes.

The tab widget reserves a stable 740 px work area for previews/results. At 1366x768 the default natural tab content heights are 490 / 438 / 50 px (all <=1100); the strategy shell is 798 px versus 956 before, and ComparePage is 684 px versus 1948 before. `tools/ui_snapshot.py` adds optional `subpages: {tab label: natural content height}` for visible tab containers, visits every tab at its viewport width, and restores selection. Existing top-level fields continue to measure the selected tab. Existing market tabs are measured too.

Evidence: `tests/test_strategy_tabs.py`, the added tab-measurement test in `tests/test_ui_snapshot.py`, and `docs/analysis/t8_snapshot_numbers.json` from a fresh HEAD archive. The existing desktop page parity assertions remain unchanged; only Strategy/Compare image baselines, affected metrics and nine intentional objectName fixture additions change. No existing objectName is removed or renamed. The new helper is automatically registered by the recursive UI-text and inline-style guards. Snapshot artifacts live outside the repository in the disposable T8 capture directory recorded in the numbers file. Full-suite execution remains controller-owned outside this sandbox.

## T8 part C - Result presentation

`desktop_pages/result_widgets.py` supplies KPI cards and read-only tables with numeric sort keys, header-click sorting and a copy action/Ctrl+C exporting all displayed rows with TSV headers in their current order. Missing fields show the catalog's not-provided text, explicit None shows undefined, and a real zero stays numeric. Numeric display delegates rounding/units to the P0-10 formatter, with grouping for other numeric columns. Source reports are never rewritten.

Backtest uses net P&L, PF, descriptive Sharpe, drawdown, closed-lot and position cards plus sortable/copyable fills. PF/Sharpe reason labels are visible only for explicit undefined values. The legacy summary adapter remains hidden for compatibility consumers; raw reports remain in the existing collapsed advanced section. Fill times in the new UI adapter are Asia/Taipei (UTC+08:00); legacy desktop_forms adapters and their existing semantics tests are unchanged. Position presentation distinguishes long, short and flat.

Walk-forward uses the same cards/table in its wizard results area, with one row per fold and no invented portfolio aggregation. Cards show supplied evaluation counts; candidate-level evidence stays in advanced. Paper uses cash, position/order/fill counts, reconcile and stop cards, and three detail tabs; the legacy SummaryCard remains in advanced for compatibility. Paper's new fills widget has its own attribute so it cannot overwrite the shared backtest fills binding. All consent, preview, stop, validation, quota, OOS consumption and no-retry operations are unchanged.

EquityPlot paints date/value ticks, a nearest-sample cursor tooltip and a drawdown sub-chart using the exact same time-to-pixel mapping. `value_at(x_position)` accepts widget-local pixels and returns the nearest supplied (time, equity), or None for empty input. Single points render safely; nonpositive running peaks have undefined relative drawdown instead of fabricated zero. Existing objectNames are preserved; four new names and all snapshot changes are listed in `docs/analysis/t8_snapshot_numbers.json`. Both helper modules are automatically scanned by the recursive UI-text/style guards. No existing test assertion or accessor was changed; only visual/name fixtures were refreshed. Full-suite verification remains controller-owned under the task's sandbox instruction.

## T8 part D - Comparison and final integration

ComparePage presents one saved report per checkbox row using the part C ResultTable. Columns are the P0-12 readable name, family, main parameters, data range, filesystem creation time in Taipei, net P&L, PF, descriptive Sharpe, maximum drawdown and trade count. Headers sort numerically where applicable. Undefined, missing and zero remain distinct through the P0-10 formatter. Hashes/paths remain in tooltips and the collapsed raw report. Unreadable reports retain a named row with missing metrics and remain subject to backend validation.

The hidden `comparison_list` QListWidget remains a bidirectional compatibility adapter. Checking rows selects original saved paths; legacy selection updates checkboxes. Refresh preserves selected paths and sorting keeps checks attached to results. The existing button dispatches unchanged `ui_compare` payloads. Returned metrics display side by side, one column per result, with undefined reasons in tooltips. Existing action objectNames, select/disable callbacks, prerequisite hints, consent and fail-closed validation remain intact. No backend/OOS/retry behavior changes.

Final 1366x768 snapshot heights (HEAD archive / final): strategy center 956 / 798, compare 1948 / 684, backtest 822 / 995, paper 1073 / 1304 px. Strategy settings/research/Walk-forward tab heights are 490 / 438 / 867 px, each <=1100. Compare is <=768 px. These values supersede intermediate heights above. Snapshot tooling continues measuring every tab and wizard step.

Evidence: `tests/test_compare_table.py` and part D in `docs/analysis/t8_snapshot_numbers.json`. The helper is automatically registered in both recursive AST guards. No existing control objectName is removed; aliases/additions are in `docs/analysis/t8_objectname_changes.json`. Existing assertions remain unchanged: only Compare PNG/metrics and the new widget-name fixture entry are refreshed. Python 3.11 compilation, class boundaries, catalog/style guards, focused T8 tests and static quality gate are required. Full-suite testing is controller-owned outside the sandbox. GitNexus refresh/diff checks fail with spawn EPERM; impact and direct source checks are recorded without a clean graph claim.
# T9 part A — verified expiry inputs and demo overview

`quantlab/data_files/taifex_expiries.json` records exactly 12 monthly final
settlement dates, 202510–202609 inclusive, shared by TX, MTX and TMF. It does not
extrapolate. February 2026 remains **2026-02-23**. The official source is
https://www.taifex.com.tw/cht/5/futIndxFSP; supplied retrieval and verification
dates are 2026-10-18. Only monthly rows with a numeric TX/MTX/TMF settlement
price qualify. The PyInstaller payload and source build manifest include this
file. `tools/update_taifex_expiries.py --data-version VERSION` is a manual online
maintenance command; its parser is tested using saved synthetic HTML offline.

The corrected, user-supplied raw HTML SHA-256 is
`e9869a6cc927ec094201d04eee866ea0d3bc7f55fab7a7ea71c09900daa87656`.
It is recorded verbatim, with strict lowercase 64-hex validation retained.
The repair run made no network request and did not retrieve or re-verify the
original HTML; provenance is the supplied digest and the 12 previously verified
rows. Invalid/missing provenance retains the existing manual input fallback.

The **trading calendar is not bundled**: the official 2026 calendar is a
colour-coded PDF that cannot be machine-verified. Existing explicit calendar
and session requirements remain unchanged. The picker fills the original
expiry table or history contract fields; it never changes request builders,
validation rules, stored values or hashes, and never overwrites a manual date.
Out-of-coverage months and weekly contracts require explicit manual metadata.
The source control exposes URL, data version, verification and retrieval dates.
The locked research contract validator continues to accept TMF only: choosing
TX/MTX in the backtest table retains the identical prior rejection. History
imports continue to accept all three products. UI parity tests now load the
shipped data directly, with no synthetic digest substitution. For 202510,
202602 and 202609, picker-filled TMF backtest requests equal manually entered
requests, including JSON UTF-8 bytes and content hashes. Manual 202509 and
202610 requests still match HEAD; these months and weekly contracts never
trigger auto-fill, show the manual metadata explanation, and retain missing
expiry/calendar rejection. History requests match HEAD for TX/MTX/TMF, both
coverage boundaries and day/night sessions. Selection still clears prior session
confirmation; no calendar, trade date, consent or expiry is inferred.

P1-12 uses option (a): a visible research dataset summary shows instrument,
formatted bar count and trade-date range with the exact warning
「合成示範資料，非真實行情」. It requires a current synthetic dataset, independently
of an official trading calendar, and clears on real, missing or invalid data.
Official read-only quote snapshots and their cards remain unchanged.

Repair evidence: `tests/test_t9_expiry_inputs.py` (16 tests),
`tests/fixtures/t9_manual_payloads.json` generated from a fresh archive of HEAD
`db44477ac24573c752484ed357c11689b29deddf`, and the appended repair entry in
`docs/analysis/t9_snapshot_numbers.json`. Default page label counts and heights
are unchanged; no P1-04 reduction claim is made for this expiry/demo subset.
The PyInstaller spec and executed build manifest both include the exact JSON
file. Empty/real/missing/invalid datasets hide and clear the synthetic summary;
synthetic data shows it even without an official calendar. Existing quote series
remain unchanged. New helper is covered by both UI AST guards; all G3 sources
remain byte-identical to HEAD with Git checkout filters applied. Full-suite testing remains controller-owned per
the sandbox instruction. GitNexus impact on BacktestForm reports LOW with two
direct importers (desktop.py, desktop_ui.py); unindexed new helpers report UNKNOWN,
resolved by direct caller reads. Index refresh fails with sandbox spawn EPERM;
no clean refreshed-graph claim is made. No commit, push or PR is performed.

Final local verification: 27 focused/guard tests pass, quality gate reports 0 findings,
and all 282 tracked/new Python files compile under Python 3.11 using utf-8-sig;
each command exits 0. GitNexus detect_changes on this worktree reports 10 changed
indexed symbols and low risk, but the stale index omits new helpers, so this is
not a complete refreshed impact result. All scratch archives and PNGs are outside
the repository; no new repository scratch directory was created.


### T9 part B: P1-06 Taipei date/time inputs

- `desktop_timeinput.py` supplies presentation-only `DateInput`, native QDateEdit/QDateTimeEdit calendar controls, table delegates and UTC hints. Taipei uses `datetime.timezone(timedelta(hours=8))`; Qt controls use an explicit fixed UTC+8 zone. No zoneinfo/tzdata dependency.
- Coverage: backtest start/end/cost effective dates; manual instrument expiry rows; history trade/open/end dates and existing time controls; paper intent creation, quote/session timestamps and trading date; paper policy session open/end/trading dates and margin effective dates; paper action clock and the paper page clock. Campaign and walk-forward ranges are K-bar indices and remain numeric. Snapshot nested records remain read-only and retain original timestamps. Advanced JSON evidence/import remains unchanged.
- Checkbox off means unset (`text() == ""`), including when the disabled picker clock changes. Enabling is an explicit user action. Restored strings, including invalid values, UTC offset spelling and fractional precision, are passed unchanged to existing validators; no loading-time coercion can turn a rejected input into an accepted default. Explicit native datetime edits emit UTC `YYYY-MM-DDTHH:MM:SSZ`.
- Date-only values retain exact exchange/trading/effective date meaning, without shifting to UTC. History session payloads retain their previous UTC `+00:00` spelling; the adjacent hint uses Z. History edits still invalidate dated-policy confirmation.
- Night example: Taipei Jan 2 15:00 to Jan 3 05:00 is UTC Jan 2 07:00 to 21:00. Trading date is the independently supplied policy date; backend `quote_policy` still chooses margin by that date. Taipei Jan 2 07:30 maps to UTC Jan 1 23:30.
- Original field/table objectNames and `.text()` / `.setText()` / `.clear()` accessors remain. Table items retain canonical raw strings; persistent native editors update them through delegates. User text uses `desktop_strings.ui_text`; grey small hints reuse the central theme prerequisite style.
- Evidence: `tests/test_t9_timeinput.py` compares old QLineEdit paths using unchanged parsing/validation functions against picker payloads, canonical JSON and hashes; includes unset/invalid/legacy restoration, both midnight cases, policy margin trade dates, history confirmation and expiry rows. Existing assertions are unchanged; registrations and additive Qt widget inventory are logged in `t9_test_edits.json`.
- Measurements: appended in `t9_snapshot_numbers.json`, before captured from a fresh archive of HEAD and after from this working tree, with isolated profiles. Full existing integration suite is controller-owned outside the sandbox.


### T9 part C — P1-03 onboarding and P1-05 plain language

The sidebar follows data, strategy, backtest, comparison, paper trading, market,
settings. All seven pages stay accessible; prerequisite hints are tooltips.
`desktop_pages/onboarding.py` owns guidance and completion: validated loaded data,
a persisted active candidate or strategy selection, loaded saved backtest results,
comparison selection (or persisted selection), and a read-only, journal-verified initialized paper account (an empty or corrupt journal is pending).
The checklist opens for a fresh workspace, can be dismissed, and reopens from
`onboarding_help`. Only the non-sensitive `onboarding_dismissed` preference is added.
No onboarding action creates trading state or bypasses validation. Five empty panels
have one primary navigation action; existing execution buttons remain usable with
secondary presentation while empty. All existing objectNames remain present.

`desktop_strings.GLOSSARY`, `FORBIDDEN_DEFAULT_TERMS` and
`DEFAULT_TERM_ALLOWLIST` document the plain wording. Proper names Walk-forward,
TMF, AI, ChatGPT and UTC are allowed; there are no forbidden-term exemptions.
Technical catalog spelling is available in the help tooltip, import-kind item
tooltips, and unchanged advanced raw configuration/evidence. Import-kind labels
are Chinese; itemData and worker request values remain the original identifiers.
Tests compare every old logical import-kind request with the new path, including
canonical JSON and content hashes. No validator, quota or one-time consumption
rule is changed; all eight G3 source files remain unchanged in the working tree (clean Git diff; checkout line endings are preserved).

`tools.ui_snapshot.page_metrics` additionally captures all displayed combo options
and table headers. The new focused tests scan all seven default pages and all
three strategy tabs. HEAD archive measurements and current measurements are
appended as T9 part C in `docs/analysis/t9_snapshot_numbers.json`. Exact existing
snapshot assertions are retained with reviewed replacement UI fixtures; all
existing test accessor/fixture edits and reasons are listed in
`docs/analysis/t9_test_edits.json`. Both UI guards discover the new package module
automatically. Existing integration/full-suite execution is controller-owned
outside this sandbox; focused tests and quality_gate are run locally.

GitNexus impact was consulted for MainWindow, ui_text, refresh_views, DataPage,
import_data and snapshot capture. The registered index was stale and some dynamic
page symbols were UNKNOWN; direct source and text references were checked.
A local index rebuild parsed the current tree but registry registration failed
because mark-auto names another test-lab repository. This is not a clean graph
verification; no commit was made.

Final GitNexus detect_changes(scope=all): HIGH aggregate risk across the existing A/B/C working tree, 38 changed files, 56 symbols and six affected processes (paper policy form loading, render-result refresh, and UI theme setup). This analysis is navigation evidence, not a substitute for controller integration tests.

### T9 part D final: P1-04 help and integration

`desktop_help.py` installs progressive disclosure after the existing polish pass.
Every page has one named `*_page_hint` (at most 30 characters). Short field
captions retain the complete original caption in their tooltip; named `?`
QToolButtons next to explanations carry the complete original wording and an
accessible name. Empty-state action buttons retain their original explanation
in their tooltip. The original catalog entries remain intact.

Full workspace/log paths, diagnostic editors, market source/message/indicator
status, VWAP disclosure, trading status and indicator controls remain reachable
in collapsed sections with unique persisted keys (`data:help`, `settings:help`,
`market:help`). Consent disclosure, backup limitations and the irreversible
budget notice remain available in help. Research-mode marker expansion and the
OOS one-time-consumption consent dialog are unchanged. Inputs, worker payloads,
hashes, rejection rules and all eight G3 files are unchanged in part D.

Measured with tools.ui_snapshot.capture at 1366x768, scale 1, isolated empty
profiles; before rebuilt from a fresh git archive of HEAD db44477ac24573c752484ed357c11689b29deddf.

| Page | Section-2 labels | HEAD labels | Final labels | Final height |
|---|---:|---:|---:|---:|
| Data | 75 | 103 | 30 | 949 |
| AI strategy center | 940 | 120 | 98 | 828 |
| Backtest | 460 | 115 | 91 | 1090 |
| Compare | 216 | 70 | 45 | 759 |
| Paper | 636 | 225 | 201 | 1377 |
| Market overview | 233 | 239 | 74 | 913 |
| Settings | 747 | 819 | 306 | 1633 |

All pages are below half the section-2 label baseline and below HEAD label
counts. Compare is <=768 px; every AI-center tab is <=1100 px. Full before/after
metrics are appended to t9_snapshot_numbers.json, budgets are committed in
t9_label_baseline.json, and all existing fixture/test inventory edits are listed
in t9_test_edits.json. Exact fixture assertions were preserved.

Verification: 40 focused T9/guard/boundary tests passed (exit 0); latest help,
text/style and page-boundary rerun: 13 tests passed (exit 0). Quality gate: zero
findings (exit 0). Python 3.11 utf-8-sig compile: all 288 tracked/new Python files
passed (exit 0). No G3 diff, debug prints, or repository scratch artifacts added.
Broad unrelated suites remain controller-owned outside sandbox as instructed.

GitNexus: pre-edit MainWindow MEDIUM, SettingsPage/DataPage LOW, MarketDashboard
MEDIUM; direct callers include mount_pages/MainWindow and snapshot tools. The
registered MCP mark-auto alias collides with another test-lab checkout. Initial
rebuild attempts hit child-process EPERM; with GITNEXUS_MEMORY=off the local graph
rebuilt, but registration failed on that collision. CLI impacts were repeated
with --repo . to bind this workspace explicitly. Aggregate A-D detect_changes
reported CRITICAL (57 symbols, 38 tracked files, 43 affected flows), including
shared ui_text, form inputs, policy loading and result refresh; it is not a
clean all-clear or full test substitute. No commit was made.

Final local `detect-changes --scope all --repo .` exited 1 because sandbox
spawnSync git returned EPERM. The MCP aggregate result above remains limited
by the registered-alias collision; no clean graph check is claimed.


### T9 repair - keyboard expiry entry and glossary compatibility

- The expiry-date table editor retains its calendar and explicit unset control,
  and additionally exposes a focusable QLineEdit for direct keyboard entry.
  Contract entry remains the existing QLineEdit. Typing, calendar selection and
  restored table items use the same raw-string payload and fail-closed validators;
  invalid or incomplete manually typed dates remain invalid rather than being
  normalized. No objectNames, rejection rules, stored values or hashes change.
- T9 help, onboarding and import-choice catalog lookups use literal keys, retaining strict catalog/syntax
  scanning and the existing reachable explanations. No new UI modules or strings.
- History completeness remains explicitly unconfirmed in the plain-language
  warning. Its existing test retains the displayed-text semantic assertion.
- Only the two analysis progress-message golden strings were regenerated through
  the frozen legacy implementation in the existing hermetic workspace. A recursive
  comparison (using the existing portable path normalization) verified no other
  observation, result, structure or hash changes; fixture diff is +2/-2 lines.
  The live legacy/current parity assertions remain unchanged. A new mutation test
  changes only the current preview handler and proves the legacy oracle differs.
- Evidence: tests/test_t9_repair.py, unchanged desktop expiry typing and strict
  catalog assertions, tests/test_market_history_ui.py, unchanged operation registry
  tests; all test edits listed in docs/analysis/t9_test_edits.json. Fresh HEAD
  archive and working-tree measurements appended as T9 repair in
  docs/analysis/t9_snapshot_numbers.json. Default metrics match Part D; comparison
  height remains 759 px. G3 locked files remain untouched. Full existing desktop
  integration suite is controller-owned outside the sandbox per run instructions.
# T10 part A settings and readable logs

P1-09: Settings has exactly four top-level titled sections, in order: 一般,
ChatGPT 連線, 備份與還原, 關於與更新. The existing official
ChatGPTConnectionPanel remains in Settings, collapsed initially; the AI strategy
page shows the same controller status and the existing navigation/sign-in entry.
Existing controls retain their objectNames and handlers, including consent resets.
Workspace, log, manual backup and automatic backup paths are inside collapsed
disclosures. Folder opening is mockable through settings_layout.open_folder and
uses QDesktopServices.openUrl(QUrl.fromLocalFile(directory)). The General path
disclosure retains settings_help_advanced/settings_help_details and its saved
preference. Fresh default settings exposes no absolute paths and eight action
buttons (ui_snapshot metric excludes checkbox inputs).

P1-15: LogTable reads only RedactedEventLog.tail(), whose schema, allowed codes,
privacy rules and recording behavior remain unchanged. Its columns are 時間（台北）,
作業（中文名稱）, 結果. Epoch seconds are converted using a fixed UTC+8 offset,
without tzdata, to yyyy-mm-dd HH:MM:SS. desktop_strings contains every approved
operation and event label. The errors-only checkbox includes only existing error
events. Export uses a mockable save-file function and writes UTF-8 BOM CSV with
the same header and currently filtered rows; cancellation writes nothing. No raw
JSON, epoch, error payload, secret or path is projected into a cell or export.

Evidence: tests/test_settings_sections.py, tests/test_log_table.py;
docs/analysis/t10_snapshot_numbers.json records ui_snapshot measurements and
docs/analysis/t10_test_edits.json records existing test adaptations. New helpers
under desktop_pages are automatically inventoried by both UI text and stylesheet
guards. Full regression execution is controller-owned outside the sandbox.


### T10 part B: keyboard, accessibility and responsive layout

- Minimum supported MainWindow size is **1280?720 logical pixels**, defined by
  `desktop_theme.MINIMUM_WINDOW_SIZE`; restored preferences read the window's actual
  minimum through `PageHost.window_minimum_size`. Production restores keep the
  1280x720 floor even on smaller screens. Disposable geometry-test windows may
  lower their minimum to exercise legacy frame-position and screen-clamp cases.
  Smaller diagnostic windows retain scroll viewport containment on all seven pages.
- Ctrl+1 through Ctrl+7 follow the actual sidebar order: **data preparation,
  strategy, backtest, comparison, paper trading, market overview, settings**.
  Window-scoped QShortcuts remain active while inputs have focus. F5 uses the
  existing refresh_views handler on the first five pages, refresh_market (including
  its network confirmation) on market, and read_logs on settings. Esc calls the
  existing cancel_job handler only while jobs.active is true. Tooltips and window
  What's This help use the strings catalog; no worker or validation rules change.
- The market_panel_toggle tool button shows/hides the existing right panel and
  redistributes the splitter width. Its state is not persisted.
- Interactive controls, including hidden disclosures, wizard steps and tab names,
  receive accessible names from existing translated labels or catalog fallbacks.
  Tab traversal follows visible enabled controls top-to-bottom, then left-to-right
  within rows whose top coordinates differ by at most 8 logical pixels. Exceptions:
  native combo/spin editor children and item/text view internals delegate focus to
  their owning control; hidden or disabled controls are omitted. Navigation stays
  a separate shell control. Traversal is recomputed after show/resize/layout events.
- QLabel text wraps; action buttons use minimum horizontal size policies, allowing
  scrollable content to keep its natural minimum width. Layout tests inspect
  QLabel/QPushButton width and same-parent siblings in layouts at 1280?720 and
  application font multipliers 1, 1.5 and 2. Theme pixel fonts are also scaled on
  the test window only, so explicit QSS fonts cannot silently mask the font probe.
- ui_snapshot scale remains a raster multiplier. `capture(..., images=False,
  window=existing_disposable_window)` additionally supports cheap viewport metrics
  without creating another window, changing app styles, expanding hidden content,
  or rasterising images. The caller owns the window; size/navigation are restored.
- Evidence: tests/test_shortcuts.py, tests/test_accessibility_walk.py,
  tests/test_scaled_layouts.py and docs/analysis/t10_snapshot_numbers.json.
  Full existing regression suite is controller-owned outside this sandbox.

### T10 part C: Traditional Chinese installer

The sole Inno Setup language is chinesetraditional, compiled from the unmodified
pinned 6.4.3 ChineseTraditional.isl. packaging/README.md and THIRD_PARTY_NOTICES.md
record URL/tag/license/translator credits and the exact SHA-256. .gitattributes
preserves upstream bytes. All custom error/dialog messages and the launch
description are Traditional Chinese; Mark Auto product/shortcut identity stays
unchanged. There are no custom tasks or CustomMessages in the original script.

Language files are build-manifest inputs only, not frozen payload files. The
build script has no new download. tests/test_installer_language.py pins the
original security lines and whole non-message script (including uninstall and
verification) against HEAD b6777a86d2bf1167e361de3d52f61aa6f15e7e63. Privileges,
data preservation, fresh payload directories, inventory and recovery are unchanged.
Existing installer readers use explicit UTF-8 BOM-aware decoding; assertions stay.

ISCC was absent from Program Files (x86)/Inno Setup 6 and the build script's
TEMP/MarkAuto-Inno-6.4.3 directory. Compiler/native wizard and lifecycle execution
remain controller-owned. Static checks do not claim Windows wizard acceptance.


## T12 part B: project-local developer setup (P2-B8)

`tools/dev_setup.ps1` supports Windows PowerShell 5.1, `-DryRun` and `-WhatIf`.
It derives all generated locations from PSScriptRoot: `.runtime-sqlite`, `.venv`
and unique temporary downloads below `build/dev-setup-downloads`. It rejects
reparse-point output paths and never targets LocalAppData (MSIX redirection).
The desktop lock requires the pinned x64 CPython 3.13 version; no additional
UI/Qt CI lock is installed. Existing workspace/AppPaths behaviour is unchanged.

Windows OS certificate validation downloads the official HTTPS SQLite artifact
without redirects. The installer's optional `--archive` reuses unchanged archive
SHA256/SHA3-256 and extracted DLL content SHA256 checks before any runtime copy.
Old CLI callers retain online behaviour. Hash failure leaves no installed runtime.
Re-runs probe pinned SQLite source/version, loaded path and hash, and verify the
venv base before hashed pip installation. Existing invalid output is refused;
only a newly attempted failed runtime and owned temporary downloads are removed.
Offline socket-blocked evidence: `tests/test_dev_setup.py` (PowerShell AST and
preview, safety strings, local fake archive failures at each hash stage, CLI
compatibility, git ignores). No real download or native installation is claimed.
No existing test was edited in part B; part A's test-edit inventory remains intact.

## T12 part A: disabled legacy archive (P2-B7)

All disabled legacy package, GUI, CLI and Telegram instructions reside in `archives/legacy_autotrading/`. Earlier legacy source locations in historical evidence above refer to that archived tree; commit-pinned upstream paths remain historical evidence. The root LICENSE and upstream headers remain intact. The product never imports the archive; setuptools and PyInstaller exclude it. Tracked archived Python stays in quality-gate syntax, credential and G1 startup/order checks, and the complete legacy security assertions still run by source extraction only. The root README links to the archive instead of advertising upstream functionality. `.streamlit/config.toml` remains a setting for the active auxiliary `research_app.py`.

Acceptance: `tests/test_repo_layout.py`, `tests/test_legacy_security.py`, `tests/test_quality_gate.py`, `tests/test_packaging.py`; exact pre/post static packaging inventory evidence in `docs/analysis/t12_payload_inventory.json`. This compares recipes and explicit inputs, not a newly built frozen installer. Existing-test edits are enumerated in `docs/analysis/t12_test_edits.json`; file decisions and verification limits are in `docs/analysis/t12_legacy_move_notes.md`.

## T12 P2-B9 documentation layering

README is limited to 150 lines. The Traditional Chinese user manual covers seven pages with disposable offscreen screenshots. Current state documents retain current status and open risks; complete original checkpoint text is preserved in literal history blocks with origin/main SHA, SHA-256 and line count. Historical text is evidence, not current operating guidance. Link and provenance checks are in tests/test_docs_layering.py. No runtime, G3 source or installer payload change is made by part C.

The README history body is the byte-exact 374-line README.md from commit 7be525fcbf8e55d8c699422252fd8dd93f4649a6 (SHA-256 61174a23c71a8078f319256852a6c11907d26a4d6c3913a54191af92bdfffa36). All history headers carry an original-location relative-link banner; only docs/agent/history is excluded from current-link resolution. Hash, count, coverage and available git-object checks remain offline and bounded.


## T13 part A: pinned Ruff enforcement (P2-B5)

Ruff 0.16.10 is installed only from requirements-ruff.lock with --require-hashes.
A three-minute Ubuntu lint/format job is required by the Windows coverage aggregate
and exact-head publication, and its dependency closure joins the strict audit matrix.
Python 3.11, LF output, line length 160 and disabled autofixes are explicit.
The eight G3 sources and entire saved_candidate_pool.py remain byte-unchanged and
force-excluded, along with frozen archive, fixtures and local/generated output.
Exact observed per-file lint exceptions preserve import and evaluation behavior;
see docs/analysis/t13_lint_decisions.md and t13_test_edits.json. Cheap config tests
execute no Ruff or network calls. Part B owns bulk formatting and AST equivalence;
part A's formatter check is expected to report existing source formatting debt.


## T14 part B: measured performance and duration estimate

P3-10/P3-11 add opt-in tools/bench_worker_latency.py and tools/bench_backtest_scale.py,
with at least five repeats, JSON and median/min/max table output. The runtime
retains spawn isolation and all existing validation, limits and timeouts. Only
backup-specific zipfile imports move to their operation paths. G3 and golden
files remain unchanged. See docs/analysis/t14_p3_latency.md and t14_p3_scale.md.

Walk-forward's existing wf_preview_summary label includes display-only duration
wording from desktop_strings. estimated_seconds multiplies positive integer
evaluation count by positive finite measured seconds. Missing/invalid measurements
return None; zero/invalid counts omit duration wording. The named measurement
constant is None because this sandbox rejects real multiprocessing pipes, so
valid previews explicitly show unknown duration, never fabricated numeric timing.
A future measured value must cite real isolated evaluation samples and their
machine/dataset limitations in t14_p3_latency.md. The estimate does not alter
preview identity, journal/evidence, admission, budgets, OOS consumption or consent.
Default empty-workspace layout and objectNames are unchanged; only populated
preview text grows. Snapshot baseline regeneration is unnecessary for that state.

Storage remains canonical typed JSON plus current content/manifest/envelope hashes;
no new dependency or producer profile. Cache/engine migration is design-only;
see docs/analysis/t14_p3_storage_design.md. Real worker timing, hosted fsync,
Linux/Windows comparison and affected-machine live TLS evidence remain pending
with user ownership in t14_p3_notes.md. Full suite and unchanged registry/goldens
are controller-owned under the explicit sandbox test restriction.

## T15: explicit maintenance and developer workspace boundary

P3-04: `quantlab.payload_cleanup` plans direct version-directory removal under a
supplied payload root. Preserve current + newest strictly older version;
every other version is a candidate. Canonical two/three-part versions only;
ambiguous names, missing current, links/reparse points (including descendants
and ancestors), escapes and filesystem errors refuse the entire plan. The UI
derives only the supported frozen install path, never the user workspace.
Immutable plans record identities and are revalidated before each rmtree;
errors stop immediately and may leave a partially deleted candidate. No atomic
same-user race defense is claimed. Default-No confirmation lists all candidates.
Both actions are under Settings → About → version maintenance; the default
disclosure preserves the existing eight-button budget. Snapshot assertions stay
exact; Settings metrics/PNGs are refreshed with before evidence in t15_ui.

P3-05: `quantlab.update_check.check_for_update` returns up_to_date,
update_available or error with fixed message codes. Injected transport returns
raw JSON bytes and companion SHA-256 text; digest verification precedes JSON
parsing and strict version comparison. Release assets are release-manifest.json
and release-manifest.json.sha256 (plain hex, optionally filename). HTTPS only,
no downgrade redirects, verified build_trust_context TLS, eight-second timeout
per request, generic User-Agent, JSON <=64 KiB, sidecar <=256 bytes. Hashes prove
consistency, not publisher identity. Settings starts a background check only on
click, disables its button and renders fixed catalog messages on the UI thread.
Construction never checks. No installer download/execution, files, cookies,
browser launch or telemetry. Existing Releases navigation remains separate.

P3-06: packaging/SIGNING_CHECKLIST.md documents future certificate acquisition,
RFC3161 signing, verification and CI secrets. Nothing is signed today; installer
and build signing behavior are unchanged. P3-08: research_app.py adds only an
st.info developer-workspace notice after its title, with no new imports or other
AST changes. Desktop remains the product; packaging excludes Streamlit.

Evidence: tests/test_t15_maintenance.py and existing text/style/import guards;
docs/analysis/t15_p3_notes.md lists live update-server, real installer-upgrade and
certificate evidence still pending. No G3 sources, quotas, validation, trading,
OOS consumption or existing test assertions change.


## T16 part A: fixed inference outcomes and shared job progress

P3-03: `desktop_chatgpt_states` maps fixed error/stage/receipt codes to success,
quota_exhausted, auth_expired or generic_failure. Unknown/non-string codes are
neutral failures; diagnostic prose is never parsed or displayed. All outcome
copy is in desktop_strings. Quota exhaustion offers no retry action and explains
consumption/limits. Auth expiry exposes the existing primary sign-in flow with
an explicit reauthorization intent; a successful local list cannot short-circuit
that user-requested authorization. Existing consent, join, registration and
browser guards remain in place. Refresh errors/results and subscription campaign
failures/results use these messages. Durable provider receipt statuses classify
campaigns whose worker returned normally after a provider failure. The worker's
existing failure packet gains only an allowlisted error_code; no runtime timeout,
cancellation, quota or validation behavior changes.

P3-07: `desktop_pages.job_progress.JobProgress` is the single shell progress row
shared by backtest, campaign, Walk-forward and download views. It preserves
`cancel_job` and the public progress/cancel aliases. Stages use job_stages'
allow-list with catalog labels and an unknown fallback. Only finite numeric
progress (excluding bool) displays a clamped 0..100 percentage; other events use
an indeterminate bar. Cancellation invokes the existing freeze/recover/cancel
path, disables repeated clicks and explains that consumed quota is not refunded.
JobFeedback accepts one terminal outcome per submitted job, ignores stale job
IDs and duplicate/late terminals, and supplies one completion/cancel notice for
each of these job kinds. It never infers cancellation from a button click; the
manager's authoritative terminal result wins a cancel/finish race.

Evidence: tests/test_t16_presentation.py, updated test_job_stages.py and the
import/text/style guards. MainWindow is 393 lines; ChatGPTConnectionPanel 421.
Default seven-page metrics and all 14 PNGs remain byte/pixel exact; widget-name
inventory is identical, so neither fixture is regenerated. No G3 source or
optimization-plan edits. Real-account inference remains environment-blocked and
must be performed by the user. Full-suite execution is controller-owned outside
the sandbox, per the explicit task instruction.


## T16 part B: market empty state and final target evidence

MarketPage exposes `market_load_sample` and `market_download_official` only while
the market series is empty. `sample_market_series()` reuses
`quantlab.reporting.synthetic_dataset(960)` and projects invented daily bars in
memory; it never writes a cache, dataset, calendar, selection or ledger. Sample
cards and chart source labels explicitly identify synthetic, nonofficial data.
The sample action cannot replace a populated series. A later cache reload may
replace the transient sample through the existing host refresh path.

Official download emits the same refresh intent as `market_refresh` and uses
`MarketPage.refresh_market`: a default-No consent dialog must return Yes before
submitting `ui_market_refresh` with `network_opt_in=True`. There is no network
call or job submission on empty-state construction, sample loading or refusal.
Once data exists, the two actions hide and the existing refresh button appears.
Cards show trade dates and the catalog's not-real-time label; source details use
the provenance date, with precise receipt timestamps retained in diagnostics.
All new UI text uses literal desktop_strings keys. Existing objectNames remain;
the widget fixture adds two action names and two prerequisite-label names.

P3-13 uses the unchanged real `display_result_rows` / ResultTable / display_number
path. A 30-digit Decimal, NaN and infinity fixture verifies bounded display,
missing-value text and four timeline segments. Exact records/tooltips are not
rounded or persisted by presentation. No validation, quota, OOS, timeout,
cancellation or G3 source changes are authorized by this contract.

Evidence: tests/test_market_empty_ui.py, tests/test_t16_presentation.py,
docs/analysis/t16_final_targets.md and its measured JSON. Only the market page's
two snapshot PNGs and metrics change; six other pages remain exact. MainWindow
stays 393 lines. Part B initially recorded tooltip and uppercase-token gaps;
Part C below closes those measured targets. The optimization plan remains
untouched per the final task checklist; proposed append-only rows are in
t16_p3_notes.md for the controller.


### T16 part C: default input explanations and domain vocabulary

Every non-obvious default-visible input across the seven pages has a nonempty
plain-language tooltip from literal ui_text keys in desktop_strings.py.
StrategyForm rebuilds tooltip text with each family switch and payload load.
The 41 default inputs comprise 30 with tooltips and 11 obvious checkboxes whose
stable catalog label keys and individual reasons are explicitly allowlisted in
docs/analysis/t16_final_targets.md. The offscreen test reads that policy, rejects
missing and stale exceptions, and checks all five strategy families.
RPT means comma-delimited history file format (market.__init__.text_71), not an
internal state. The ten domain terms CSV, JSON, MTX, MXF, RPT, TAIFEX, TMF, TWD,
TWSE and UTC remain visible. A live seven-page scan of visible text, combo items
and table headers rejects any other uppercase token or raw hash: internal codes
are zero after this explicit domain classification.
Only tooltips change: no geometry, widget names, public desktop_ui names,
validation, payloads, quotas, OOS consumption or G3 files change. MainWindow stays
393 lines; Part B snapshot images and metrics remain unchanged by Part C.
Evidence: tests/test_t16_tooltips.py (4 tests), t16_tooltip_metrics.json and
updated t16_final_targets.md; sandbox verification covers new/changed focused
modules plus the quality gate, Ruff and all-file Python 3.11 compilation.
