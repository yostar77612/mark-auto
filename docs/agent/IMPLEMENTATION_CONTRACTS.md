# mark-auto implementation contracts v1 — frozen development baseline

### LB-B10: journaled paper order lines and re-price

PaperBroker.amend(order_id, price=Decimal, amend_key, quote, now) only changes
the limit price of accepted/partial limit orders with remaining quantity. Quantity
cannot be supplied. Decimal finite positive instrument-tick validation and monotone
UTC timestamps precede the journal append. It uses submit's single _risk entry;
replacement excludes the original reservation to avoid double-counting exposure.
The persistent manual_order_lock is checked first for submissions and amendments,
before reconciliation and kill gates; only explicit journaled unlock clears it.
Event replay is extracted into _reduce_event without changing legacy state hashes
or the lazy additive manual lock field in snapshots.
Kill, reconciliation, loss halt, session, quote, margin and all other risk gates
remain authoritative. Rejected amendments write nothing. Every successful amend
counts toward the SAME 20 reservations per 60 seconds, including the original
submission; exact retries do not count. Amends never create/close FIFO lots or
alter consecutive losses, and cannot bypass the latched loss halt.

The additive journal op is amend, identity amend:<amend_key>, with canonical string
price and request payload. Exact key retries are no-ops; conflicting reuse fails.
Different keys apply by SQLite journal sequence (last writer wins). The reducer
updates intent.limit_price and pending_amend, retaining accepted/partial status.
A matching sequenced simulated event type amend with amend_key removes that marker.
An interrupted/unacknowledged amend remains pending: reconciliation compares the
full orders (including price/marker) and refuses pending amendments. Restart sets
reconciliation_required as before. A simulated acknowledgement followed by explicit
matching reconciliation restores consistency; amend itself never clears the latch.
Schema/config version 4 and old reducers/hashes remain unchanged for old operations.
The frozen pre-change journal fixture tests replay compatibility without migration.

CandlestickChart.set_paper_snapshot accepts copied synthetic_paper_only dicts.
Only accepted/partial limit orders with positive remaining quantity for the exact
chart contract project horizontal side/remaining/price labels. The chart imports
no execution or network objects. Paper-only gesture callbacks emit Decimal prices;
pixel coordinates cross to Decimal strings before tick rounding (half up). Drag
does not optimistically move a line. Esc/release outside writes nothing; failures
retain the last snapshot and display an error. Hosts must provide a new verified
snapshot after success. Trace-bound backtest/replay series clear paper affordances.

The existing ui_paper_cancel worker envelope carries action=amend; no operation
allowlist or timeout changes. Consent, paper mode and exact current snapshot are
required. The adapter rejects a pre-existing reconciliation/kill latch BEFORE
opening a session, then reconciles only the verified constructor restart and
journals amend plus its simulated acknowledgement. Interrupted writes require
investigation/reconciliation, never blind retry. The market host disables replay
and result-trace interaction; the paper confirmation, quote form and paper clock
supply consent and risk inputs. Existing generic worker failure notifications apply.
No G3, profile, OOS, budget, acceptance score or PROJECT_STATE changes.
Amend replay is isolated in _reduce_amend; the chart snapshot adapter and Decimal
price bounds live in desktop_order_lines, preserving reducer and chart size limits.
The append-site enumeration keeps order creation confined to submit.
Evidence: tests/test_lb_b10_paper_orders.py (offline, offscreen, no show/style).

### LB-B9: display-only product-key convergence (after LB-B8)

`quantlab.product_keys.converge_key(symbol, enabled=True)` uses exact,
case-sensitive tables: TX and TXF map to TXF; MTX and MXF map to MXF;
TMF maps to TMF. Each prefix accepts the bare root, R1/R2 continuous aliases,
or exactly one month letter A/B/C/D/E/F/G/H/I/J/K/L (January..December)
and one year digit 0..9. The explicit 01..12 month table agrees with
taifex_expiries.load_expiries/lookup_expiry; tests cover every shipped month.
TAIFEX:TX/MTX/TMF:YYYYMM display identities also converge (years 0001..9999).
Recognition does not assert settlement/calendar coverage or resolve a decade.
Options never converge: TXO, weekly option roots, strikes and call/put suffixes
remain intact. Weekly futures identities are also excluded. Unknown, empty,
None and non-string keys pass through unchanged, as does every disabled input.
An enabled value other than an actual bool raises ValueError.

DrawingStore saves and edits under the exact original instrument SHA256 file;
load_exact exposes that owning collection. load(enabled=True) returns the
deterministic original-key-sorted union for the product. Repeated drawings from
different owners remain separate. The existing 200-drawing bound applies to the
union; overflow returns empty without modifying files. Shared views are read-only;
callers editing drawings must use load_exact/save for the original instrument.
Discovery uses <instrument SHA256>.key JSON sidecars containing only the original
display identity; legacy code aliases are enumerated without migration. Invalid
metadata cannot redirect a drawing lookup (its filename must match the key hash).
Original B8 drawing JSON and its schema remain unchanged. Switching or looking up
never creates, rewrites, migrates or deletes any file. On/off/on is byte-lossless.

Market diagnostics exposes the catalog-only market_converge_annotations checkbox.
Market preferences persist converge_annotations as a strict bool, default True
for old payloads; malformed values raise ValueError before state mutation, caught
by the existing settings restore boundary. The host binds DrawingStore below the
settings profile's display_profile directory and refreshes overlays on contract,
timeframe and preference changes. Backtest/research inputs and hashes never depend
on this preference. No G3, trading, quota, OOS, timeout or profile-block changes.
Evidence: tests/test_lb_b9_product_keys.py. Existing tests/oracles/expiry data stay
unchanged; only the import registry and additive widget inventory are updated.

### LB-B8: chart-drawings-v1

`quantlab/chart_drawings.py` is a pure standard-library display model. Frozen
HorizontalLine, TrendLine, Ray and Box objects contain only Anchor values:
timezone-aware UTC datetime (zero UTC offset) and finite positive Decimal price.
Integers/bar indices, naive/local timestamps and float prices are rejected.
Projection uses half-open supplied bar intervals [timestamp, end); missing,
date-only or uncovered timestamps do not guess a bar. Transient containing-bar
ordinals are never serialized. Prices and stored anchors survive all eight
timeframes unchanged. Rays extend from start through end; boxes use opposite
corners. Painting clips geometry to the price viewport and keeps the market's
price scale. The host explicitly selects the instrument's drawings; set_series
preserves them across aggregation changes, while set_drawings emits no requests.

DrawingStore writes dedicated `<display-profile>/chart_drawings_v1/` files named
by instrument SHA256, outside research/data/results/hash-bound roots (resolved
paths checked). Schema version 1 has sorted canonical JSON keys, string Decimal
prices and ISO UTC Z timestamps. Limits: 200 drawings per instrument, 262144 bytes
per file; invalid/truncated/unknown-version/unknown-kind files load as empty
without changing their bytes. Saves validate first, flush/fsync a same-directory
temporary file, then atomically os.replace; failed writes preserve the old file.
DrawingHistory supports add/move/delete and bounded undo/redo, MAX_HISTORY=100;
empty operations are no-ops, new actions clear redo. These display objects and
files never enter backtest/research inputs, manifests or reproducibility hashes.
No trading, budget, OOS, timeout, profile or G3 changes. Evidence:
tests/test_lb_b8_drawings.py (offscreen QImage, no show/style or network).

### LB-B3: market-indicators-b3-v1

The additive `atr`, `supertrend`, `sar`, `obv` and `ma_channel` functions use
isolated precision-28 Decimal arithmetic and the existing observation limits.
The seven earlier formulas and goldens remain unchanged. None observations reset
history, consistent with the earlier indicators; nonfinite/bool observations and
invalid parameters raise ValueError. OHLC lengths/ranges are validated; volumes
are nonnegative integers up to 10^15. Resource bounds raise IndicatorResourceLimitError.

- `atr`: Wilder smoothing, seeded by SMA of first N true ranges; first TR is
  high-low, later TR=max(high-low, abs(high-previous close), abs(low-previous close)).
  Default period 14; N-1 leading None values, including after a missing bar.
- `supertrend`: Wilder ATR period 10, multiplier 3 by default; basic bands are
  midpoint +/- multiplier*ATR. Bands carry until tightened or crossed by previous
  close; strict current-close crossings reverse trend. First mature ATR seeds
  uptrend on its lower band; N-1 leading None values. Missing OHLC resets all state.
- `sar`: Wilder AF step 0.02, maximum 0.2. One leading None; second close >= first
  seeds uptrend at first low, otherwise downtrend at first high. Initial EP includes
  both bars. Project SAR+AF*(EP-SAR), clamp to previous two lows/highs, reverse on
  strict penetration using old EP; reset AF on reversal and increase on new EP.
  Missing OHLC restarts the seed. Parameters require 0 < step <= maximum <= 1.
- `obv`: zero seed without warmup; add/subtract current volume on higher/lower
  close, hold on equal close or zero volume. Missing close/volume resets to None,
  with the next valid bar seeding zero. All-zero volume is flat Decimal zero.
- `ma_channel`: SMA envelope period 20, percent 2 by default; middle*(1 +/-
  percent/100), N-1 leading None, reset on missing values. Percent is nonnegative.

Chart overlays are SuperTrend, SAR and all three MA channel bands; ATR and OBV
are panels. Catalog labels include all parameters (OBV has none). Each resource
failure is isolated using the existing failure message. Version-1 preferences
with the original seven keys remain accepted and acquire disabled defaults for
the five additions; unknown keys and malformed original shapes remain rejected.
No trading, budget, OOS, timeout, profile, acceptance-score or G3 behavior changes.
Evidence: tests/test_lb_b3_indicators.py and tests/test_lb_b3_chart.py.

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

### LA-B1: fixed error catalogue and worker log codes

`quantlab/errors.py:ERROR_TABLE` is the sole literal code-to-message table.
Every code is defined once, matches `^[a-z][a-z0-9_]*$`, and has a nonempty
explanation and action. `ERROR_LABELS` is only a compatibility projection;
`ErrorCode` is derived from the same keys. Display rendering remains
`quantlab.desktop_errors.error_message()`. No new codes are introduced.
The B1 snapshot pins all 64 pre-existing explanation/action pairs and rendered
messages from commit `17b5b1b` byte-for-byte using canonical UTF-8 JSON SHA-256.

JobManager forwards worker error codes to `RedactedEventLog.append(error_code=)`.
Missing or unrecognized IPC codes normalize to `operation_failed`; the log
continues to accept only catalogue codes and fixed schema fields, never raw
exception messages, types or payloads. Logging remains optional and storage
failure cannot interrupt job completion or cancellation. Existing exception
messages, ValidationError and RecoveryError pickle paths, and unknown-input
fallback classification remain unchanged; locked core validation is untouched.

Evidence: `tests/test_error_catalog_b1.py` checks AST duplicate keys (including
updates), enum/key equality, the baseline snapshot, literal display references,
absence of another literal message table, and fake-worker-to-JSONL propagation.
It uses no Qt windows, child processes, network or sleeps. Ordinary test discovery
automatically includes it in the core/remaining CI shard. The import-graph scan
also includes the changed catalogue module.

### LA-B2: persistent manual order lock and daily-loss definition

Daily pnl (the signed loss measure) is `(cash + unrealized mark-to-market of
open lots) - day equity baseline` for the pinned session `trade_date`: realized
plus unrealized PnL, including paid costs. New orders block when
`pnl <= -max_daily_loss`. Each trade_date establishes a fresh baseline: cash
when flat, or cash plus carried lots marked at a versioned opening reference
known by the first session open. Overnight lots without that reference cannot
establish a baseline and block with `overnight_daily_loss_baseline_required`.
The quote must match pinned session/margin policy; UTC midnight is not the day boundary.

`PaperBroker.submit()` is the single new-order gate through `_risk()`, including
manual UI and strategy-driven PaperReplay orders. Quantity caps include pending
reservations when measuring worst position exposure; rejects never append an
`intent` event. Existing limits, reasons, live-disable and timeouts are unchanged.

`set_manual_order_lock(bool)` journals `manual_order_lock` with boolean `active`;
new orders reject with stable reason `manual_order_lock`. It neither cancels
working orders nor liquidates positions. Unlike the kill switch, which replay
start and confirmed UI submit can disable after reconciliation, this manual latch
survives restart, reconciliation, replay start/stop and a new execution session.
Only an explicit journaled unlock clears it, requiring a reconciled account and
no UNKNOWN/submitting orders. The UI exposes lock through the existing paper
kill operation with an explicit lock payload, and reconcile/unlock through the
existing reconciliation operation with an explicit unlock payload. All new text
comes from desktop_strings; stop_presentation displays the manual stop state.

For compatibility the snapshot key `manual_order_lock` is additive and appears
only after the first lock/unlock event. Absence means unlocked. No schema/config
hash changes or legacy-state normalization occurs; old journal hashes and
snapshots replay exactly. Connections are transaction scoped (no broker close
method or persistent connection). Evidence: tests/test_paper_lock_b2.py.

### LA-B12: copyable, allowlisted local diagnostics (after B1)

`quantlab.diagnostics.build_diagnostics()` is a pure builder: no filesystem,
clock, network, job submission or workspace writes. Its explicit `now` input
makes snapshots deterministic. Settings exposes Refresh diagnostics and Copy
diagnostics inside the existing collapsed version-maintenance panel through
desktop_strings keys, preserving the default Settings text and metrics. Copy rebuilds the displayed snapshot
and passes that exact string to the clipboard; no file export or upload occurs.

The field allowlist is app_version (the package constant); workspace (presence
only: available/unavailable); data.source (TAIFEX/TWSE/research/synthetic),
data.mode (history/eod/realtime/delayed/offline), latest_bar_timestamp (canonical
UTC ISO timestamp), latest_bar_trade_date (canonical date), age_seconds (computed
nonnegative integer or unavailable); job.operation (existing OPERATION_LABELS
keys with ui_ prefix), job.stage (JOB_STAGES), job.state (active/idle);
last_errors (newest first, error_code plus ERROR_TABLE's fixed explanation);
errors_status (available/unavailable), and an optional truncation marker.
Unknown strings never pass through: operation/source/mode become unavailable,
stages become unknown, error codes become operation_failed. Only literal True
selects available/active. Invalid dates/times become unavailable. Daily bars
without event timestamps retain their trade date and unavailable timestamp/age;
no midnight event time or market freshness guarantee is invented.

The UI adapter reads the selected in-memory market series, shared job state and
an optional bounded 32 KiB tail of desktop-events.jsonl (last 200 lines). Missing,
unreadable and malformed logs do not block diagnostics. JobFeedback retains up
to 32 normalized worker errors in memory, including when logging is disabled;
matching code/explanation entries already in the log are not repeated by the
adapter. No arbitrary log record or worker packet is displayed. The builder
keeps at most 32 errors and drops oldest whole entries to fit a fixed 4096-byte
UTF-8 ceiling, adding `[truncated]` while preserving valid JSON and all sections.

Excluded regardless of input source: account/registration/job identifiers,
tokens, bearer/authorization headers, refresh tokens, cookies, email, workspace
or home paths, URLs, attribution, arbitrary metadata, exception messages,
exception str/repr, types and tracebacks. Redaction is a fixed-field and enum
projection, never regex scrubbing of arbitrary text. Prices/money are omitted.
No broker/order path, timeout, budget, OOS rule, G3 file/profile, acceptance
score or PROJECT_STATE change belongs to B12. Evidence:
`tests/test_diagnostics_b12.py`; no shown windows, network, subprocess or sleeps.

## B6: golden source, review and precision metadata

Only engine_golden.json cases and ui_operations_golden.json complete operation
observations are counted as golden entries in tools/list_unverified_goldens.py.
Each adds source (hand-computed / existing-behaviour / cross-checked / derived),
review (unreviewed / reviewed / independently-verified), and precision. Engine
money is Decimal-exact; UI observations compare exactly after the fixture's
existing documented normalisations, including Decimal-exact money. No float
money tolerance is introduced. These fields never alter application results.

The engine's existing file-level provenance at 17b5b1b identifies independently
hand-calculated synthetic arithmetic, hence all four sources are hand-computed.
Per-case arithmetic evidence (multiplier 10 TWD/point): long_ten_points is
(20010-20000)*10=100; short_ten_points_loss is -(20010-20000)*10=-100;
short_ten_points_profit is -(20000-20010)*10=100. All three have zero costs.
For two_lots_costed, gross=(20010-20000)*10*2=200, round-trip commission
=5*2*2=20, tax=(20000+20010)*10*2*0.00002=16.0040, net=163.9960.
This preserves historical provenance, not a new independent review attestation.
All entries retain unreviewed status until per-entry reviewer evidence is added.
UI observations are existing-behaviour: their capture provenance and T13's
same-dispatcher comparison establish regression evidence, not an independent
financial oracle. No UI observation is labelled hand-computed/cross-checked.

Unverified means source outside hand-computed/cross-checked OR review other
than independently-verified. Both text and --json reports give per-fixture and
total counts offline; malformed metadata fails rather than disappearing.
The inventory is scoped, not a claim about every repository fixture.
Out of scope, bytes unchanged: desktop_ui_public_names.json (API surface),
desktop_widget_names.json (objectName inventory), desktop_pages_baseline.json
(layout baseline), wfo-storage-*.gz and wfo-storage-manifest.json (storage/load
corpus). These structural inventories and generated storage inputs are not
independent numerical golden oracles. docs/analysis/t*_*.json are historical
analysis/change records, not golden inputs, and remain unchanged.

Consumer edit record: tests/test_ui_operations_registry.py uses
golden_observations() at its two comparison load sites to strip exactly the
three new entry metadata keys before comparing payloads. No expected value,
normalisation, operation assertion or engine consumer changes. The cheap
metadata test pins canonical pre-existing fixture content to 17b5b1b digests,
checks enums/counts/CLI in-process without subprocesses, and defaults into the
remaining core shard through existing discovery. Full deep equality with
17b5b1b was also checked before delivery, removing only those three keys.

### LD-B7: strategy intent design boundary

[ADR 0006](../adr/0006-strategy-intent-pipeline.md) accepts a design only:
strategy -> intent -> order planning -> risk -> simulated execution. Strategies
would emit intents only; same-instrument, same-period conflicts fail closed
without implicit priority, using B1's existing `validation_failed` /
`ErrorCode.VALIDATION_FAILED`. No intent types or planner are implemented.
The Signal adapter mapping preserves next-open timing; current precomputed
signals do not read actual post-fill positions. Stateful/multi-instrument
implementation needs a separately approved task and G3/hash/golden review.
All locked sources, saved-candidate profiles, golden values, research and
analysis identity bindings remain unchanged. Live trading stays permanently
disabled; finite AST, OOS consumption, irreversible budget and all timeouts
remain in force. B1 ancestry and source/impact evidence are recorded in the ADR.
### LC-B4: persisted appearance preferences

`desktop_theme.THEMES` exposes `dark` and `light`, with identical COLORS key sets.
The existing `COLORS` and no-argument stylesheet builders retain the original
dark tokens and byte-identical QSS. `appearance.theme` defaults to `dark`;
`appearance.rise_fall` defaults to `red_up` (Taiwan), with `green_up` reversing
the pair. These named keys use the existing SettingsStore envelope and preserve
other settings. Missing, unknown or corrupt preference values read as defaults;
corrupt files are preserved, never repaired by the appearance loader.

Settings > General > Advanced contains named theme/convention combo controls.
Changing either saves immediately and calls `apply_theme(window)` without a
restart. Preferences belong to each window, not process-global mutable state.
The market preference payload's historical `theme: dark` field remains an inert
compatibility field; the named global appearance keys select the rendered theme.

`up_down_colors` is the common convention source. Default candles retain
`#ff6575/#35cf9b`, market cells/cards `#f58b8b/#76d6b0`; result P&L labels retain
the theme's danger/success token shades. Only financial values reverse, while
warning/error/safety statuses retain their semantic meaning. Financial table
items carry a separate sign role, preserving numeric sorting. Chart background,
grid, text, reference/marker and overlay palettes resolve through the active
window theme; chart legend text follows the convention through catalog keys.

Default snapshots and visible layout are unchanged; controls live inside the
existing collapsed settings disclosure. No baseline replacement is required.
`tests/test_b4_appearance.py` checks both themes offscreen, including the existing
accessibility naming/focus walk, layout truncation, and WCAG 4.5 label contrast.
The existing accessibility walk has no contrast helper/threshold; B4 adds its
own standard contrast check without altering existing tests or thresholds.
Real-DPI verification at 150%/200% remains **EXTERNAL / pending**; offscreen
checks are not real-DPI screenshots or physical display evidence.

Lane verification at base/HEAD `17b5b1b155d2fe40e98c0665a6b0d75ed4526b22`:
focused B4 suite 8/8 (exit 0, 3.836 s total; seven-page walk 1.242 s),
import-graph suite 4/4 (exit 0), Ruff 0.16.10 check/format-check (exit 0),
quality_gate (exit 0, zero findings), and Python 3.11 py_compile for all 12
changed Python files (exit 0). The unchanged public-name oracle is invoked by
the B4 suite. All 14 default snapshot images compare pixel-exact; metrics match
the existing baseline (exit 0). G3/profile files, guard logic, PROJECT_STATE,
optimization-plan and ACCEPTANCE files have no changes. The sandbox temp ACL
fixture uses the existing sandbox_ui helper; product I/O is not patched.
Full-suite/Linux CI exit codes are **pending controller verification** under
the lane's focused-test-only rule. Changes remain uncommitted as instructed;
the controller owns the single B4 commit and its required co-author trailer.


## LC-B11: display-only privacy mode

One window-owned `desktop_privacy.PrivacyState` controls all seven pages. The
one-click, accessible `privacy_toggle` shares the existing research-banner row;
it defaults off. Settings use `privacy_mode`, accepting only JSON boolean true;
missing or corrupt values fall back to off. Existing settings validation remains
fail-closed. All new labels live in desktop_strings.py.

`mask_money(value)` always returns four bullets (`••••`), including None, zero,
negative, non-finite and arbitrarily large inputs. `mask_account_id(value)`
returns four bullets plus the last four characters only when the ID is longer
than four characters; IDs of length zero through four are fully masked. The
suffix is characters, not digits; no prefix or original length is retained.

Scope: money/account columns in research results, comparisons (including
transposed comparisons), fills, paper positions/orders/fills and market account
tables; KPI and summary cards; market price cards; equity value axes/tooltips;
candlestick prices, crosshair OHLC/change, reference labels and fill prices/costs.
The money classification includes desktop_presentation.AMOUNTS plus equity,
price/average/limit/fill/stop prices, OHLC, cost/fees, pnl/balance and initial and
maintenance margins. Account identifiers use account_id. Symbols, timestamps,
order status, quantities and ratio metrics retain their original table text.
Legends containing only indicator names/periods remain unchanged.

All read-only detail/export-preview editors redact structured money/account
fields recursively. Unknown non-JSON preview text is hidden entirely while on;
summary-card nested records are likewise hidden conservatively. Editable request
forms retain their raw input values. The cached original display is restored
exactly on a second toggle. Toggling uses already-present widgets and cached
renderers, without refresh_views, worker jobs or database queries.

Export decision: exported FILES ALWAYS retain unmasked raw data. Privacy is for
screen display and table clipboard copies only, not file sanitization. A visible
notice beside the toggle explicitly says exported files retain unmasked original
data (`privacy.exports_raw`). No separate masked-file export is introduced.
The preview is masked independently. Tests compare actual report export bytes
with privacy off/on and assert the notice text.

Original display strings/tooltips are cached in Python attributes outside Qt
model roles. Sensitive display, tooltip and accessibility text are replaced;
UserRole sort/model data are unchanged. Raw business records, hashes, cache keys,
DBs and export serializers never receive a masked value. Default-off formatters
use their original output paths. The privacy toggle sits in the window chrome, so the seven *_viewport.png
files of the default snapshot baseline were refreshed in a separate fixture-only commit (metrics.json and
the *_full.png files are unchanged).
Live trading and all existing admission, budget, OOS and timeout gates are untouched.

Validation from lane-c (2026-10-19), base HEAD
`205aa138ce6a224ce461322b4fd335a382e874a1`:

- Shared Python unittest discovery, test_b11_privacy.py: 8 tests, exit 0,
  approximately 1.4 seconds total. No show, setStyle, network, subprocess or sleeps.
  Includes the unchanged public-name oracle, seven-page widget enumeration,
  immediate toggles and repopulation, roles, source hashes, previews, comparisons,
  chart builders, settings corruption, accessibility naming/focus and raw exports.
- test_import_graph.py: 4 tests, exit 0; test_no_hardcoded_ui_text.py: 5 tests,
  exit 0. New module registered additively in both inventories and root layout;
  stylesheet scan discovers new desktop modules automatically.
- Ruff 0.16.10 check / format --check, Python 3.11 py_compile of changed Python
  files, quality_gate and git diff --check: exit 0.
- G3 paths plus quantlab/saved_candidate_pool.py: git diff 17b5b1b empty.
  PROJECT_STATE.md, optimization plan and ACCEPTANCE scores are unchanged.
- test_repo_layout.py: 4 pass; tracked-root assertion cannot include the new
  untracked module until the controller stages it. An intent-to-add attempt was
  denied by the sandbox's shared worktree index.lock ACL. No test was weakened.
- GitNexus status found no index. analyze generated local graph data but could
  not register it (sandbox denies the global registry write); the explicit lane
  query consequently reports repository not found. Direct source review used.

Controller handoff: the controller ran the broader groups locally and an independent QA judged the commits;
the default raster snapshot comparison passes against the refreshed viewport baseline.

### LB-B13: bounded paper replay pacing and durable pause

ReplayPacer accepts only integer speeds 1x, 2x, 5x, 10x, 50x and 100x
(maximum 100x). Speed is session-only presentation state: it changes the timer
wait between operations (1000/speed milliseconds), never simulated timestamps,
signals, prices, fills, cursor decisions or binding. There is one bar per paced
worker operation at EVERY speed, no worker sleep and no catch-up burst. A busy
worker or another active job prevents another tick. Effective throughput may be
lower on slow storage. The existing Paper 30 s timeout, smoke 40 s timeout and
15-minute job cap are unchanged; the hard worker deadline still applies to slow
storage or a single expensive bar. Pacing never extends it. The legacy unpaced
ui_paper_replay operation remains start/step(max_bars)/stop; its smoke request
(max_bars=25, cursor=25, kill_switch=True) is unchanged.

Pause is durable in the existing replay table: active=-1 means paused, 0 stopped,
1 active. No columns, table versions, binding inputs or journal formats change.
Old five-column databases open unchanged; the legacy-schema fixture checks the
original binding formula and cursor. snapshot exposes paused and active separately.
Pause is allowed only for active, incomplete replay; double pause, stopped pause
and complete pause raise ValidationError. start on paused raises before touching
the broker, and step while paused neither consumes a bar nor appends journal rows.
resume requires paused, reconciled, identified account with kill OFF. It restores
active=1 at the exact cursor, with no broker journal write. Resume when unpaused
raises. Pause leaves kill unchanged (normally OFF), and never clears a safety
latch. stop still journals kill ON and sets active=0, including from paused.
Completion remains cursor-based; stopping preserves the cursor. Existing int
1..1000 step validation and kill/reconciliation break conditions are unchanged.

The paper page defaults to the original unpaced one-shot worker and unchanged
result payload. The speed selector defaults to unpaced; selecting 1x..100x opts
into the controller. Speed, pause/resume, stop and status controls all live in
the existing collapsed diagnostics panel; idle page metrics remain unchanged.
The legacy snapshot shape is unchanged unless paused, when paused=True is added.
One confirmed request supplies a fixed policy and verified snapshot; subsequent short workers use each returned snapshot
and the existing explicit reconciliation boundary after broker restart. These
worker restarts/reconciliations retain their normal audit events. Core pacing
and pause/resume themselves never add audit rows; identical core runs at all
speeds and a step-10/pause/fake-wait/resume run have identical full snapshots,
fills, cursors and journal hashes. The UI applies a requested pause/stop after
an in-flight one-bar operation, then schedules no ticks while paused. A new
session inspects durable state before ticking; a saved pause requires Resume.
The selected max_bars bounds the session total, then an explicit short stop
operation turns kill ON. Errors/cancellation/close halt the timer; the existing
freeze and reconciliation paths remain authoritative. No live or broker network
path is introduced. No public desktop_ui names or locked source files change.

Evidence: tests/test_replay_b13.py uses an injected fake monotonic clock, no real
sleeps, no shown windows or application style changes. It checks speed/hash
invariance, old schema, durable pause transitions, safety gates, one-bar per-op
work at 100x, paused UI, cancellation and the unchanged public-name oracle.

### DOC-E1: in-memory GUI startup stage timing

`quantlab/startup_timing.py` records completed intervals with an injected clock
(default `time.monotonic`). Names are exactly application, bootstrap, workspace,
window and ready; all other values raise a fixed ValueError without echoing input.
Durations are finite, nonnegative seconds. Construction reads the clock once;
each retained mark reads it once; snapshots and overflow read it zero times.
The first eight entries are retained; overflow adds `[truncated]`. Snapshots
copy entries and retain no absolute timestamps, arbitrary details or paths.
The recorder performs no file, logging, environment or network I/O at import
or during measurement, and creates no threads or timers.

`desktop.py` imports the recorder after its existing GUI/runtime dependency
imports. Measurements start there, excluding interpreter launch and those
earlier imports. application ends after QApplication/icon/application metadata;
bootstrap after workspace-location discovery and instance locking; workspace
after prepare_workspace; window after MainWindow construction/show; ready after
startup hooks and the existing guard timer setup, before smoke/event-loop entry.
window includes desktop_ui import time; ready does not assert first paint or
background/network readiness. Existing timeouts and safety gates are unchanged.

B12 diagnostics adds `startup_timing` (explicit `unavailable` without a recorder).
The existing 4096-byte UTF-8 ceiling and whole-entry truncation remain in force;
oldest errors are removed first, then whole timing entries if needed. The same
snapshot text is displayed/copied in the existing collapsed maintenance panel.
There are no new widgets, objectNames or default-view fixture changes. The only
B12 expected-key change adds this section; no existing section is removed.
Evidence: `tests/test_startup_timing_e1.py` covers exact fake-clock intervals,
allowlisted names/privacy, bounds, no I/O, JSON sizing and offscreen display/copy;
`tests/test_diagnostics_b12.py` retains its previous assertions plus the new key.
No G3/profile, OOS, budget, timeout, live-order, acceptance-score or project-state
change is part of E1. The controller creates the single item commit; its message
should explain the additive B12 JSON key expectation. No commit is created here.

### DOC-E2: external display compatibility checklist

[Display compatibility](../qa/display-compatibility.md) is a documentation-only
external checklist, linked from README. Every item is EXTERNAL / UNVERIFIED;
no 150%/200% DPI run is performed by this item. Unchecked DISP-01 through DISP-07
cover 100%, 125%, 150%, 200%, mixed-DPI monitors, 1366x768 and Windows text size
across the seven catalog-named sidebar pages and the catalog-named maintenance
panel. The results table is empty and requires tester/date/Windows build/commit
identity and observations. Existing manual offscreen images are automated-only
evidence, not a substitute for physical-display inspection. Automation cannot
claim visual completeness; final confirmation is the user's and remains pending.
No code, tests, snapshots, protected sources/profile blocks, state, acceptance
score, gates, OOS consumption, budgets or timeouts change. Live trading remains
permanently disabled. The controller creates the single item commit.

### DOC-E3: release-notes document template and verification ledger

[Release-notes template](../release/RELEASE_NOTES_TEMPLATE.md), linked from the
README documentation index, is a document template only: no released version,
download link, GitHub Release or tag is created. Its always-present
"Verification scope and ongoing tracking" table carries ten unfinished
PROJECT_STATE rows as UNVERIFIED, with unique stable RN-prefixed ledger IDs.
Display references retain E2's existing DISP-03 and DISP-04 identifiers rather
than inventing replacement checklist IDs. Summary, upgrade/migration and known
limitations sections have bracketed placeholders; later evidence must identify
tested scope and commit without closing unattempted work.

This item changes documentation only. PROJECT_STATE and ACCEPTANCE remain
unchanged; formal acceptance stays 230/300. Physical displays, real inference,
installer/client lifecycle and other ledger work remain unverified. No UI
baseline refresh is needed. Live trading remains permanently disabled; locked
sources/profile blocks, fail-closed gates, OOS consumption, irreversible budgets
and all timeouts remain unchanged. No OOS/final-holdout data may enter AI
conversations, tool returns or prompts. The controller owns the single commit;
lane changes remain uncommitted. ID uniqueness is checked directly from the
template table without adding runtime code or tests.

### DOC-E4: PR template and contributor guide

The [PR template](../../.github/pull_request_template.md) records Change,
Verification and Risk in that order. Unchecked verification rows require exact
commands, exit codes and evidence; risk checkboxes cover G3 ownership,
gates/OOS/budgets/timeouts, permanently disabled live trading and the unchanged
230/300 acceptance score. Unverified work must remain explicitly unverified.

The [contributor guide](../CONTRIBUTING.md), linked from README, documents the
eight G3 files, protected profile blocks, owner approval, pinned Ruff 0.16.10,
Python 3.11, quality-gate exit 0 and per-module test discovery. It preserves UI
catalog/error-table rules, the OOS/final-holdout AI boundary, irreversible budgets,
timeouts and PROJECT_STATE ownership. Workflow links name the existing
quantlab.yml and windows-desktop.yml definitions without claiming CI success.

This item changes only documentation: no root allowlist, code, tests, fixtures,
G3/profile sources, state, acceptance scores or safety thresholds change.
No Release or tag is created. The controller owns the single item commit;
lane edits remain uncommitted. No UI baseline refresh is needed.

### DOC-E5: terminology and tooltip writing policy

The [terminology and tooltip guide](../user/TERMINOLOGY_AND_TOOLTIP_STYLE.md),
linked from README, preserves all twelve glossary pairings and distinguishes
writing policy from existing catalog observations. Its T16 table quotes the
recorded 89 tooltip widgets, 41 default-visible inputs, 30 with tooltips,
11 obvious controls without and 0 non-obvious inputs without; these are scoped
measurements, not a claim of complete product coverage. Examples and observed
wording variations identify verbatim desktop_strings values; no strings change.

New or revised explanatory tooltips require plain complete sentences, a
120-character rendered bound, glossary-backed terminology and accurate units,
defaults, prerequisites and execution scope. New UI text uses desktop_strings
with literal ui_text keys; error text retains the B1 ERROR_TABLE. The existing
test_t16_tooltips module must pass unmodified. Documentation checks and direct
catalog/JSON comparisons verify the guide without a new runtime test.

This item changes documentation only. No UI baseline refresh is needed.
G3/profile sources, PROJECT_STATE, ACCEPTANCE scores, gates, OOS consumption,
irreversible budgets and timeouts remain unchanged. Live trading remains
permanently disabled; OOS/final-holdout data never enter AI conversations,
tool returns or prompts. No Release or tag is created. The controller owns the
single item commit; lane changes remain uncommitted.

### DOC-E6: pre-implementation design documents

Before a UI or behavior implementation, use the
[design template](../design/TEMPLATE.md) to record Problem, Goals/Non-goals,
Design, Safety constraints, Test plan and Rollout/Verification status.
The [C5 market-dock workspace design](../design/c5-market-dock-workspace.md) is
IMPLEMENTED (item U3-C5); the user's final real-App visual confirmation remains
pending. It names existing source/test paths
and requires accessibility and snapshot review before future UI acceptance.

E6 changes documentation only; no UI baseline refresh is needed for E6.
ADRs, G3/profile sources, PROJECT_STATE, ACCEPTANCE scores, gates, OOS consumption,
irreversible budgets and timeouts stay unchanged. Live trading remains
permanently disabled; no order path, dynamic execution or credential handling
is added. OOS/final-holdout data never enter AI conversations, tool returns or
prompts. Formal acceptance remains 230/300. No Release or tag is created;
the controller owns the single item commit and lane edits remain uncommitted.
### TASK A1-D1: offline agent tool contract v1

The [agent harness contract](../AGENT_HARNESS_CONTRACT.md) and
[JSON schema](../agent-app-tools-v1.schema.json) establish exactly four layers:
research.read, paper.read, ui.navigate, research.run. Declarations and inputs
are closed; effect is explicitly read or mutation. Registration fails atomically
on missing/unknown effect, unknown capability, unknown field or malformed input
schema. A mutation requires a required nonempty string idempotency_key. The
only mutation declaration is a test-local fake; all mutation dispatch is denied.

quantlab.agent_tool_contract implements the closed standard-library JSON/schema
validator and resource bounds. quantlab.agent_tools owns the default-deny
Registry; unknown tools/capabilities, missing grants, bad model JSON and unsafe
returns produce only B1 agent_tool_refused with empty params. No input, context
or exception text is echoed. Model output cannot become code, a handler, a grant
or partition provenance. Resolved declarations are copies; the production
registry is frozen. No UI/provider/broker dependency or executable ui.navigate
or research.run handler exists.

The single read contract exerciser, research.list_training_status, accepts only
host-supplied in-memory snapshots with trusted training provenance. It filters
partitions before counting/paging and positively projects only completed and
training observations. D3 storage adapters and research metrics are not added.
OOS, final holdout, unknown/missing partitions, guards, names, raw files, paths,
credentials and arbitrary fields are never copied to returns. Host adapters must
derive training-only counts from approved evidence, never mixed-period totals.
Strict typed output validation refuses malformed visible rows and extra fields.

The D11 success envelope is ok/items/truncated/limit/next_cursor: at most 50
rows and 8192 UTF-8 bytes; input JSON at most 4096 bytes. Cursors index only
visible training records in a stable host snapshot. Truncation is explicit,
exhaustion has a null cursor, and oversized returns refuse without silent loss.
The sentinel oracle recursively scans every output field from every registered
read tool, all fixture pages and empty/protected-only contexts. Its negative
control removes partition filtering and catches leaked OOS row-count 31337.
Sentinel fixtures also include prices, returns, metrics, trades, equity, guard
contents, credentials, tokens, drive/POSIX/UNC paths, user names and raw content.

Verification: focused D1 tests, import graph, repository layout, documentation
layering, B1 catalog, function lengths, catalog placeholders and ADR glossary;
Ruff 0.16.10 check/format, Python 3.11 compile and quality gate. The B1 test adds
only the new registry entry before checking the original 64-message count/hash;
all historical assertions remain. Other existing tests receive additive entries
only. ADR 0006 code-fence line endings were locally normalized for Ruff, with no
Git content diff. No UI/default-page baseline changes or fixture refresh needed.

G3 files and all saved_candidate_pool.py bytes, PROJECT_STATE.md, the product
optimization plan and ACCEPTANCE.json remain unchanged against e0e604f. Live
trading permanently disabled; no new order path and no existing gate, timeout,
budget, threshold or OOS-consumption change. Broader suite and the single final
A1-D1 commit are controller responsibilities; this lane leaves work uncommitted
per the explicit process instruction. The full suite is not run in this sandbox.

GitNexus status found no lane-local index. The initial analyze hit sandbox spawn
EPERM; the explicit lane query reported repository not registered. No extension
download or alternate graph tool was used; exact source review and tests provide
the local evidence, without claiming fresh graph coverage.
The retry with GITNEXUS_MEMORY=off, index-only, skip-fts and one worker completed
local analysis but could not write the global registry.json temporary file
(sandbox EPERM); the lane therefore remains unavailable to registered queries.

### TASK A1-D2: agent harness threat model and evidence integrity

The [threat model](../AGENT_HARNESS_THREAT_MODEL.md), linked from the D1
contract, records trusted core/AST/DPAPI/journal modules, untrusted model output,
manual imports, remote-compatible API responses, skill text and saved results.
Every boundary names its control and residual risk. The three mandatory claims
cite existing definitions and tests: model code never executes, strategy output
passes AST validation before strategy use, and credentials never cross from
DPAPI into harness/model outputs. Authorized auth still uses tokens internally;
DPAPI at rest is not an OS/process-memory sandbox. Raw bounded candidate output
may enter the local audit record before validation without becoming executable.

tests/test_agent_harness_d2.py resolves every backticked evidence path and
qualified definition, requires the mandatory claim references, proves removing
references or corrupting a path/symbol fails, and scans the document for private
paths/usernames/secret shapes. Its strategy attack cases call existing validators
only. tests/test_agent_harness_d7.py adds offline skill/saved-result injection
regressions at the existing D1 boundary; it adds no skill loader or permissions.
D3/D11 leakage evidence is the existing D1 recursive all-tool sentinel oracle
and its partition-filter-removal negative control; a full D3 suite is not claimed.

No runtime modules, strings, error codes, UI or fixture baselines change.
Live trading stays permanently disabled with zero production mutation tools.
No gate, OOS consumption, budget, timeout or threshold is changed. All G3 sources
and saved_candidate_pool.py remain untouched, as do PROJECT_STATE.md, the product
optimization plan and ACCEPTANCE.json. Changes are left uncommitted as required;
the controller owns the single task commit and broader CI verification.

Local verification: D2 6 tests, D7 2, D1 11, strategy 6, documentation layering 8,
import graph 5 and repository layout 6 all pass. Ruff 0.16.10 check, changed-file
format --check, Python 3.11 py_compile and quality_gate pass (0 findings).
Repo-wide format --check reports only the known ADR 0006 checkout line-ending
false alarm; that file is untouched. Protected-path diff against e0e604f is empty.
GitNexus status found an incomplete stale lane index; analyze with index-only,
skip-fts and one worker rebuilt locally but failed global registry writing with
sandbox EPERM. The lane query was unavailable; no fresh graph coverage claimed.

### TASK A1-D3: bounded offline saved-result and paper reads

`quantlab.agent_read_tools.READ_REGISTRY` registers exactly nine D3 tools through
the D1 Registry: list_saved_results, get_backtest_summary, get_backtest_trades,
get_backtest_equity, compare_results, get_data_quality_summary,
get_strategy_params, get_paper_positions and get_paper_orders. All effects are
read, with research.read or paper.read grants. The original D1 training-status
contract exerciser remains separate and unchanged. No UI wiring is introduced.

Every D3 declaration specifies maxItems=50, pageSizeCap=50 and
maxSerializedBytes=8192. The closed declaration schema adds only these optional
bounded fields; the [schema](../agent-app-tools-v1.schema.json) mirrors runtime.
Registry accepts a host-owned output schema while retaining the original strict
default. D3 validates a closed per-tool row schema before the shared D11 envelope.
Above-cap inputs, oversized serialized output, malformed JSON and invalid cursors
return only existing B1 agent_tool_refused with empty params, never partial data.
Paging indexes the immutable verified sequence, preserves order, and ends with
truncated=false and next_cursor=null. Numeric money and deltas use Decimal.

ReadContext is a host-only trust boundary. Its immutable TrainingEvidence tuple
must come from approved training-only results and binds each exact content hash
to its in-sample dataset hash and aggregate quality counts. Model arguments and
saved partition labels cannot supply provenance. Unapproved legacy, OOS, holdout,
mixed-period and unknown results are refused even when present under saved_root.
Hosts must never populate this evidence from mixed totals or consumed guards.
The adapter supplies no provenance inference or OOS/holdout reader. It does not
change the saved report format or create a new AI cache/export artifact.

Only lowercase SHA256 IDs resolve to saved_root/id/result.json. Validation occurs
before file access; symlinks and resolved escapes fail closed. A single binary
read is capped at 32 MiB; duplicate JSON keys and nonfinite constants are refused.
Envelope content hashes and reporting.validate_result_payload's nested immutable
strategy/config/dataset bindings are checked before projection. Each stored
ledger/equity sequence is capped at 100000 entries. Corrupt, missing, oversize or
malformed data yields the same B1 refusal without traceback, path or partial leak.
Hash integrity is not authentication; host evidence remains essential.

Summary and comparison return only the fixed METRICS whitelist. Comparison takes
exactly result_id and other_id plus paging controls, requires distinct approved
IDs and returns second-minus-first deltas. Quality returns only in-sample
observations/missing/duplicates/has_gaps. Strategy parameters are projected from
the hash-validated immutable strategy using the existing PARAMETER_CONTRACTS
signal keys; risk settings, rules and arbitrary strings are excluded. Trade
pages contain ordinal, quantity, prices and net PnL; equity pages contain ordinal,
validated timestamp and equity. No raw IDs, names, paths, warnings, guards,
credentials, tokens, dataset rows or arbitrary file strings are copied.

Paper reads use only PaperBroker.read_snapshot's read-only SQLite connection,
never construction or an execution session. They require synthetic_paper_only,
hash position/order labels, and expose only bounded quantities and fixed status
enums. No tool makes provider or network calls. Live trading stays permanently
disabled; zero mutation declarations or new trade execution paths exist.

Evidence: tests/test_agent_read_tools_d3.py covers deterministic concatenated
pages, summary size on a large fixture, exact declarations/caps, distinct-ID
comparison, path refusal before open, symlink refusal, corrupt/oversize files,
strict model JSON, Decimal deltas, immutable parameters and journal hash/spies.
The recursive sentinel oracle checks all nine outputs and pages with OOS and
holdout fixtures, aggregate count 31337, value 987654.321, guard contents, paths,
usernames, raw file content and credential/token markers. Its negative control
removes the approved-partition filter and proves both metric and count leakage
fail the same oracle. Socket and provider spies assert zero calls; AST scanning
rejects dynamic execution, process and UI imports. Tests use inherited temporary
directory ACLs so the Windows restricted token can access its own fixtures.

Only new D3 tests and additive import-graph assertions are added; no existing
test is weakened. No G3/profile, PROJECT_STATE, optimization plan, ACCEPTANCE,
gate, budget, timeout or threshold changes. No UI baseline refresh is required.
Work remains uncommitted; the controller owns the single A1-D3 commit and broader
suite. GitNexus local indexing completed but global registration failed with
sandbox EPERM; the lane query was unavailable. No extension downloads or alternate
graph tools were used; direct source review and tests supply the local evidence.

Local verification: D3 9 tests, D1 11, D2 6, D7 2, import graph 6, repository
layout 6, documentation layering 8, B1 catalog 8, function lengths 2 and catalog
placeholders 1 pass. Ruff 0.16.10 check and changed-file format --check,
Python 3.11 py_compile and quality_gate pass (0 findings). Protected-path diff
against e0e604f is empty. The full unit suite is left to the controller under
the task's sandbox rule; no broader-suite pass is claimed.

### TASK A1-D11: central bounded tool returns

`quantlab.agent_return.bounded_return` is the sole success-envelope constructor
for all registered D1 and D3 handlers. It is pure and deterministic, accepts only
JSON-safe lists after host authorization and positive projection, and rejects
nonfinite values, bytes, paths, invalid Unicode and invalid limits. Existing
MAX_LIMIT=50, MAX_RETURN_BYTES=8192 and MAX_INPUT_BYTES=4096 stay authoritative.
No existing limit, budget, gate, threshold, OOS consumption or timeout changes.

Successful envelopes include items, count, total, limit, truncated, next_cursor,
reason, field_truncations and ok. Counts and fingerprints cover only the visible
training/synthetic-paper rows, never protected records, mixed totals or guards.
Item overflow has item_limit; byte overflow has byte_limit and cuts only between
items. Metadata, cursor and both canonical UTF-8 and ordinary JSON serialization
fit the existing byte cap. Non-progressing single-row overflow refuses via B1's
existing agent_tool_refused code with empty params; no second error table exists.

String fields over MAX_FIELD_CHARS=256 have explicit page-relative item/field
component/truncated markers. Field loss sets truncated even on the final page,
with field_limit and null cursor when no additional rows remain. The helper does
not change inputs. Item pagination reconstructs uncapped fields without gaps or
overlap. Opaque cursors bind offset, full visible source (including capped string
suffixes) and request scope using SHA256. Stale/tampered/cross-scope cursors and
legacy offsets refuse through the same B1 code. Hashes check consistency, not
authentication; authorization remains mandatory on each read. Limits are strict,
never coerced or clamped, so no clamped flag is necessary.

The [harness contract](../AGENT_HARNESS_CONTRACT.md) and its JSON schema now
describe this envelope. Existing D1 schema/cursor assertions and D3 pagination
and sentinel traversal are updated only for this intentional contract change;
all original test cases and safety assertions remain. D3 sentinel traversal now
requires successful reads for granted research tools and explicitly checks B1
refusal for paper tools without journal evidence, rather than scanning refusals
as though they were pages. Import graph entries add only the central helper edge.

Evidence: tests/test_agent_return_d11.py covers all item boundaries across many
sizes, CJK byte paging, explicit field markers, determinism/purity, unsafe JSON,
invalid limits, cursor integrity, all-handler AST/registry routing, zero mutation
declarations and D3 byte-truncation propagation. The whole-envelope sentinel
oracle covers count and total; removing the training filter demonstrably leaks
total=31337 and fails that same oracle. Existing D1/D3 fixtures cover OOS/holdout
values, metrics, prices, trades, equity, guards, credentials, paths and raw files.

No new UI text, error code, root file or default-view change is introduced; no
baseline fixture refresh is needed. Live trading remains permanently disabled.
G3 files, all saved_candidate_pool bytes, PROJECT_STATE.md, ACCEPTANCE.json and
the product optimization plan remain untouched. Work is left uncommitted as
explicitly required; the controller owns the single A1-D11 commit and full suite.

Local verification: D11 9 tests, D1 11, D3 9, D2 6, D7 2, import graph 6,
repository layout 6, documentation layering 8, function lengths 2 and catalog
placeholders 1 pass. Ruff 0.16.10 check, changed-file format --check, Python 3.11
py_compile and quality_gate (0 findings) pass. Protected-path diff against
e0e604f is empty. No full-suite result is claimed under the sandbox instruction.
GitNexus local analysis ran with index-only/skip-fts/one worker, but global
registration failed with sandbox EPERM; the lane query reported repository not
found. No extension download, alternate graph tool or fresh graph claim was made.

### TASK A1-D7: local read-only research prompt packages

Initial assessment confirmed no loader, front-matter schema or local prompt
directory. The existing test_agent_harness_d7.py remains unchanged: it tested
injection at D1's boundary, not local skill loading. New prompt packages live
only in docs/skills: interpret-backtest, check-overfitting-risk,
compare-two-results and check-data-quality. Their contract is documented in
[Local research skills](../AGENT_SKILLS.md).

quantlab.agent_skills implements a strict hand-written Markdown front-matter
parser with exactly name, description, allowed_tools and output_format.
Single-line values use duplicate-free strict JSON strings/list syntax, never
general YAML or dynamic evaluation. Unknown/duplicate/missing keys, invalid
names/types, empty bodies, invalid UTF-8 and files over 16384 bytes fail closed.
Names match their filename stems; catalogs have at most 128 files and reject
invalid or duplicate entries atomically. Whitelists contain only registered
effect=read tools with research.read/paper.read capabilities. Unknown tools,
mutation tools and other capabilities fail validation independently.

The directory is application-registered without a model-selectable root.
Traversal/absolute names are rejected before file access; symlinks and Windows
reparse points in file or directory components refuse. Reads are binary-capped
and containment-checked. list/read use D11's single bounded_return constructor,
strict limit/cursor inputs and snapshot-bound cursors. Body chunks are at most
256 characters and reconstruct the entire prompt through pagination. Listing
contains no paths. Prompt packages themselves must not contain secrets or user
data; the loader has no other user-file, dataset, credential or provider reader.
Concurrent malicious filesystem replacement remains a host-directory protection
responsibility, as documented in the contract.

The host activates a skill with already-existing grants and routes model tool
requests through the immutable SkillSession.call entry point while active.
Effective capabilities intersect existing grants, read capabilities and the
registered whitelist's capabilities. A whitelist miss refuses before registry
dispatch even when that tool exists. D1/D3 then independently enforce effect,
capability, strict JSON schemas, training provenance and positive projection.
Every public refusal reuses B1's existing agent_tool_refused with empty params;
no second error table or grant API exists. Registration and activation remain
host-only operations. No new model tool can alter skills, grants or evidence.

Authority claims and fenced code remain inert text, without parsing them as
permissions or executing them. Shipped prompts contain the disclaimer that AI
interpretation may be wrong and nothing is applied or ordered automatically.
They contain no actionable trading instructions, parameter application, protected
partition revelation or mutation tool references. No UI is introduced; no new
UI string keys, root files, widget names or baseline refresh are needed.

Evidence: tests/test_agent_skills_d7.py adds ten deterministic tests covering
the parser matrix, byte/catalog caps, unknown/mutation/non-read tools, runtime
whitelist refusal, unchanged grants/registry/whitelist under authority claims,
an inert fenced sentinel-file program, path and symlink refusal, D11 pagination,
strict JSON and shipped prompt lint. Its AST scan rejects dynamic execution,
process/importlib/pickle and UI imports. It routes D3's real sentinel fixture
through an active skill for every tool and result page, recursively checking all
output fields for protected metrics, prices, trades, equity, counts, guards,
credentials, tokens, paths, usernames and raw file markers. The negative control
removes provenance filtering and proves the same oracle fails for protected
metrics and row count 31337. Existing tests remain unchanged except additive
permitted-edge registration in tests/test_import_graph.py.

Live trading remains permanently disabled. No G3 file, saved_candidate_pool
byte, gate, OOS consumption, budget, timeout or existing threshold is changed.
PROJECT_STATE.md, ACCEPTANCE.json, acceptance scores and the optimization plan
remain untouched. Work is uncommitted as instructed; the controller owns commit
creation and final commit-count verification, including the task id A1-D7.

Local verification: new D7 10 tests (under 2 seconds), existing D7 2, D1 11,
D2 6, D3 9, D11 9, import graph 7, repository layout 6, documentation layering
8, B1 catalog 8, function lengths 2 and catalog placeholders 1 pass. Ruff 0.16.10
check, changed-file format --check, Python 3.11 py_compile and quality_gate
(0 findings) pass. Protected-path diff against e0e604f is empty. The full suite
is left to the controller under the explicit sandbox rule; no pass is claimed.
GitNexus status identified an incomplete index; refresh with index-only/skip-fts
failed with sandbox spawn EPERM and the lane query reported repository not found.
No extension downloads, alternative graph tools or fresh graph claims were used.
### U1-C2: compact onboarding workflow chips

GettingStarted uses one QHBoxLayout for the five clickable workflow chips and
the existing dismiss button. Its maximum height is 40 logical pixels. With the
shared interpreter and offscreen Qt, both themes measure a 30 px size hint
(810 px width), reclaiming 258 px against the e0e604f 288 px baseline recorded
as BASELINE_E0E604F_HEIGHT in tests/test_onboarding_c2.py. Tests enforce the
40 px bound without asserting platform-specific font or page measurements.
No claim of visual quality or high-DPI acceptance follows from these metrics.

Each onboarding_go_<page> button includes the existing localized page caption
and onboarding.done/onboarding.pending text, derived from the same five-entry
completed tuple. Role onboardingChip and state done/pending select theme QSS
tokens; no widget-specific color literals are introduced. Minimum chip widths
preserve their full size hints. onboarding_status_<page> QLabel objects remain
as hidden automation compatibility mirrors with their original numbered status
text; the button is the visible status and navigation target. All existing
widget names remain in desktop_widget_names.json; no new names require entries.

Refresh now applies restore_visibility, so any completed step or persisted
dismissal hides the bar and its layout item contributes zero height. Dismissal
updates only onboarding_dismissed through the existing settings load/save
round-trip; unrelated settings survive. Hosts without settings retain dismissal
in widget memory. Missing optional host controls use empty defaults. The existing
onboarding_help callback clears persisted dismissal and reopens an incomplete
workflow; completed workflows remain hidden. Its glossary tooltip, WORKFLOW_ORDER,
navigation hints, per-page empty guidance and completion-file semantics remain
unchanged. No desktop_ui exports, locked G3 source, candidate profiles, monetary
calculations, execution paths, limits, timeouts or acceptance scores change.

Evidence: seven new focused tests pass in 0.11 s locally without shown windows,
style switching, sleeps, network or child processes. Existing T9 onboarding,
UI operation registry, catalog placeholders, import graph, hardcoded text,
inline stylesheet, function lengths, B8 drawings, desktop polish/banner and
B2 live-disabled tests pass unchanged. Accessibility walk passes in dark and
light themes. Ruff 0.16.10 check and format --check, Python 3.11 compilation,
and tools/quality_gate.py pass. GitNexus status found no lane index; analyze
failed with sandbox spawn EPERM and the explicit lane impact query reported
repository not found. Fresh graph coverage is unverified; direct source reads
and tests provide the available evidence.

The five requested desktop smoke modules were attempted unchanged; Windows
temporary-directory ACL errors prevent sandbox validation. Controller reruns
are required. No baseline files are edited here. The controller must refresh
tests/fixtures/desktop_pages_before/01_viewport.png through 07_viewport.png
for the compact bar in a separate fixture-only commit. A fresh disposable
capture confirms all seven full-page PNGs and metrics.json remain byte-identical;
only those seven viewport images require refresh.
The item is left uncommitted for the controller's single item commit.

### U1-C1: compact application header

`desktop_pages/app_header.py` owns the single `app_header` at central-layout
index zero. Its maximum height is 48 logical pixels; focused offscreen tests
verify its size hint also stays within 48 in dark and light themes at 1366x768.
Default label widths and the complete row's size hint fit that width. These
are measured layout bounds, not claims about visual quality or high-DPI QA.
The permanent read-only badge uses literal `ui_text('header.live_disabled')`,
preserving the research-mode/live-disabled wording. `research_mode_status`
remains the explanation checkbox for unchanged automation; it controls only
`research_mode_explanation`, never the badge or any trading capability.

The existing `status` label moves from the bottom line into the header, with
the same object and all existing writers. The privacy export warning remains
visible in the header. No information from those lines is dropped. The actual
`appearance_theme` combo is moved from the settings disclosure, retaining its
existing B4/B11 callback, load_appearance/store keys, convention and apply_theme
path. No second preference attribute is introduced. PrivacyState gains only
an optional compact layout adapter; the header uses that same state/toggle,
enabled() and existing table refresh/persistence path. Its default adapter
remains compatible with existing callers. Interactive controls have accessible
names and tab order follows privacy, explanation, theme.

Data context reads existing host _dataset_ready and market _quote_series/
_series/provenance through getattr defaults. It adds no data store or I/O.
Source exchange, source date and freshness are visible; attribution and receipt
timestamp are available in the tooltip. Cached data stays stale. Age greater
than the existing paper_risk_limits().max_quote_age_seconds (30 seconds), future
receipts, unknown timestamps or unknown thresholds also show stale/unverified.
This is a display marker only: historical snapshots never imply real-time or
execution eligibility. The quote-age risk limit itself is unchanged.

Job presentation reads JobProgress.running, JobFeedback.terminal and the
existing terminal notification's danger/neutral presentation for idle, running,
failed and done; no second job-state field is added. A callable datetime clock
is injected (default aware UTC). Fixed-clock tests exercise the exact age
boundary without sleeps; the presentation timer stops on header/host close.
Bare SimpleNamespace hosts build and refresh without optional state. The
header contains only the existing privacy/explanation checkboxes and theme
combo, with no network request, broker import, live order or enable-live control.

Evidence: five focused tests pass in about one second locally, with no shown
windows, application style changes, network or subprocesses in the new tests.
Import graph, recursive UI-text/inline-style scans, catalog placeholders,
unchanged public exports, function lengths, B8 drawings, B2 live-disabled and
existing banner/polish tests pass. Accessibility walk passes in dark and light
themes. Ruff 0.16.10 check and changed-file format check, Python 3.11 compilation
and tools/quality_gate.py pass. The G3 eight files, all candidate-pool code,
PROJECT_STATE, optimization plan, limits/timeouts and acceptance scores have no
changes. Existing test assertions are unchanged; registration edits are additive.

GitNexus status found no lane index; analyze failed with sandbox spawn EPERM,
and the lane-specific query reported repository not found. Graph coverage is
unverified. All five requested desktop smoke modules were attempted unchanged;
Windows temporary-directory ACL errors prevent sandbox validation and require
controller reruns. A disposable snapshot capture proves metrics.json and all
seven full-page PNGs remain byte-identical. The controller must refresh only
tests/fixtures/desktop_pages_before/01_viewport.png through 07_viewport.png for
the consolidated header, in a separate fixture-only commit. No baseline files
are edited here. All item changes remain uncommitted for the controller.

### U1-C4: shared asynchronous status presentation

`desktop_pages/async_status.py::AsyncStatus` has exactly four states, selected
through `set_state`: loading, empty, error and stale. Invalid states raise
ValueError before changing presentation. Literal desktop_strings keys supply
default state text and action captions. The state property selects theme QSS;
the widget, label and action have accessible names without showing a window.
Both parentless construction and bare SimpleNamespace hosts are supported.

Empty guidance accepts caller text/action and explicitly hides an absent action.
One permanent click connection dispatches only the latest callback; repeated
state updates cannot accumulate signal connections. Only actionable empty
guidance has the primary role; inactive actions and retry/refresh are secondary.
Error presentation accepts only codes found in quantlab.errors.ERROR_TABLE,
displaying that code, explanation and recovery action. Unknown codes display
fixed generic text without echoing the input. Exception and message parameters
are never rendered in error state, including accessibility and tooltip fields.
Retry is explicit, with no automatic loop. Stale age is caller supplied; missing
age produces a fixed stale message, never a fabricated timestamp.

The five onboarding empty boxes use AsyncStatus with their original empty_*
and empty_*_action objectNames, literal onboarding.empty.* / onboarding.next.*
keys and callbacks. GettingStarted.refresh, emptiness predicates and existing
run_campaign/run_backtest/compare_results/paper_submit role switching are
unchanged. Maintenance reuses its existing queue, worker and polling timer;
the shared widget adds no timer, thread or worker. Its existing status attribute
remains the component's label. Log emptiness is projected inside the existing
table viewport. The advanced backtest result-empty message uses the component
and hides when a saved result loads. read_job optionally reads existing
JobProgress.running and JobFeedback.terminal without changing either or starting
work. It does not infer terminal failure from arbitrary message text.

Seven focused tests pass in under one second locally, with no shown windows,
application style switching, network, subprocesses or sleeps in new tests.
They exercise both themes, all B1 codes, secret exception suppression, callback
replacement, stale age, existing job projection and real page/widget inventory.
Existing onboarding, log, maintenance, public-name registry, header, catalog,
import graph, hardcoded-text, inline-style, function-length, B8 drawings, B2
live-disabled and polish-B tests pass. Accessibility walk passes in both themes.
Ruff 0.16.10 check/changed-file format check, Python 3.11 compilation and the
static quality gate pass. Existing result-host tests and polish-A snapshot
capture hit Windows temporary-directory ACL errors; polish-A's four other
tests pass. All five desktop smoke modules were attempted unchanged and also
require controller reruns outside the sandbox. GitNexus indexing failed with
spawn EPERM and the explicit lane query reported repository not found; fresh
graph coverage is unverified. These are measured checks, not visual-quality QA.

No protected G3 source or saved_candidate_pool code differs from e0e604f.
No monetary calculation, live-order path, fail-closed gate, OOS/budget rule,
timeout, PROJECT_STATE or acceptance score changes. Existing test assertions
are unchanged; inventory/registration changes are additive. All changes remain
uncommitted for the controller's single item commit.

No baseline PNG or metrics file is edited. A disposable capture compared with
the checked-in baseline differs in metrics.json and 01_full.png/01_viewport.png,
02_full.png/02_viewport.png, 03_full.png/03_viewport.png,
04_full.png/04_viewport.png, 05_full.png/05_viewport.png,
07_full.png/07_viewport.png under tests/fixtures/desktop_pages_before.
The controller should refresh those files in its separate fixture-only commit:
the current integrated layout has changed page heights, and settings now shows
the explicit log-empty message. 06_full.png and 06_viewport.png match the
checked-in baseline. Snapshot differences include inherited lane UI changes;
this comparison does not attribute every changed pixel to C4.


## UI-1 C3: shared PanelCard (2026-10-20)

PanelCard is defined once in desktop_pages/widgets.py, without a host dependency
or a new desktop_ui public name. Six existing market sections and two existing
paper advanced form sections use it. Existing inner widgets and objectNames
remain. The four shared chrome objectNames are additive in the widget inventory;
no new module is introduced. widgets.py is included in the import graph scanner.

The fixed title bar uses PANEL_TITLE_HEIGHT (19). Its section-title label uses
Qt's QGroupBox title renderer, preserving the old section text without adding a
QLabel to the explanation-character budget. The plain title has an accessible
catalog fallback when empty. The named controls container has a fixed size policy
and a right-aligned layout; add_control preserves insertion order across widths.
content_layout() keeps content widgets directly parented to the card, allowing
existing help relocation code to move a complete section through parentWidget().
There is no collapse control, settings write, timer, broker import or order path.
Paper cards live inside the existing collapsed policy/snapshot sections; default
paper text, geometry and raster output remain identical to the archive.

Repair findings: the initial content QWidget caused help relocation to strand
market section titles, adding visible text. Its 36-pixel title bar also squeezed
the chart by 17 pixels, causing the unchanged history smoke color-sampling check
to fail for the two-candle timeframe. Direct content parenting and the compact
fixed title height resolve both symptoms. A disposable workspace probe calls the
unchanged _history_smoke_ui and _market_smoke_ui: all 24 history product/timeframe
render checks pass, and the market helper reports 100 rendered bars. desktop.py
and its smoke assertions are unchanged. The new regression assertion checks the
actual help-relocation parentage and whole-section title visibility.

set_theme_property selects centralized app/scoped-market QSS. Title foreground
and background use the original text/background tokens, preserving e0e604f group
title contrast in dark and light and exceeding 4.5. apply_theme re-polishes panel
chrome. widgets.py contains no hardcoded hex colors. Tests build both pages with
bare SimpleNamespace hosts without show(), setStyle(), subprocesses or sleeps.
The stylesheet hash expectations are re-pinned for the new selectors; their exact
equality assertions and every existing layout/accessibility assertion remain.

Validation: test_panel_card_c3, test_help_reachability, test_desktop_market,
test_market_empty_ui, test_b4_appearance, test_t16_tooltips and the dark/light
accessibility walk pass. Ruff 0.16.10 check, changed-file format check, Python 3.11
compilation and tools/quality_gate.py pass. The requested history, terminal,
isolation, market-smoke, desktop_pages and desktop_ui modules were attempted;
Windows sandbox temporary-directory ACL errors prevent completion. Their full
subprocess/interaction runs still require controller verification. GitNexus
reports an incomplete local index; analyze --skip-fts fails spawning its worker
(EPERM), and the explicit lane-path context query is unregistered. Direct source
inspection and the available runtime checks provide local evidence instead.

A disposable seven-page raster capture compared every baseline file. Only these
files need controller refresh in a separate fixture-only commit under
 tests/fixtures/desktop_pages_before: metrics.json, 06_full.png and
06_viewport.png. The sole page metric difference is market page_height 950 -> 953;
all default visible text, label counts and other page metrics match. All other
PNGs, including both paper PNGs, match byte-for-byte as decoded images. No
baseline fixture is edited here. These claims describe measurements, not visual
quality.

Protected G3 files and all saved_candidate_pool.py content have empty diffs
against e0e604f. No monetary calculation, gate, OOS/budget rule, timeout, live
flag, PROJECT_STATE, optimization plan or ACCEPTANCE score is changed. Changes
remain uncommitted for the controller's single C3 implementation commit.

## UI-1 C9: table readability and model-derived tab counts (2026-10-20)

SavedResultsTable's five metric columns and SideBySideTable's transposed result
columns use desktop_theme.align_table_item for right/vertical-center alignment,
including missing/undefined/masked values and matching headers. The single
NUMERIC_FONT_FAMILY token selects a fixed-pitch monospace font through this same
helper. Text cells and headers stay left/vertical-center aligned. LogTable has
three text columns (formatted Taipei timestamp, operation, result), so none is
treated as a numeric measure. No column, header label or row is added or removed.

Saved financial cells retain ResultTable's B4 treatment. Transposed net_pnl cells
now call set_financial_item with the original value, preserving financial_sign
and centralized up_down_colors under both themes/conventions. Zero/undefined
remain neutral. No new colors, formatters, rounding, float conversions or changes
to DisplayRole/UserRole are introduced. Existing privacy adapters still mask
money text and tooltips while keeping alignment and original sorting roles.

The three existing paper table tabs retain objectNames and indices. bind_tab_count
listens to model insertion/removal/reset, reads table.rowCount(), and formats the
existing title through literal ui_text('tables.tab_count') and display_number.
Empty tabs show [0]; there is no parallel count state. Elision is disabled. The
callback ignores deleted Qt wrappers during teardown. No host/settings dependency,
new desktop module, widget objectName or desktop_ui public name is introduced;
the existing widget inventory and automatic text/style module scans still apply.
The touched source/test paths are added to the import-graph scan.

Eight cheap in-memory tests cover baseline cell bytes, column alignment/font,
both B4 themes/conventions, privacy, Decimal sorting/check selection, direct
model edits, a bare SimpleNamespace paper host and Qt destruction. The additive
table_values_e0e604f.json fixture records headers/text/DisplayRole/UserRole from
the actual e0e604f table modules (loaded only for fixture generation). Existing
tests and assertions are unchanged. No new test uses show, style changes, sleeps,
subprocesses, networks or platform font/geometry measurements. No new page metrics
capture is added to the tests; existing captures use snapshot_cache.default_metrics.

Local checks: focused tests, log-table, UI operations/public-name registry,
catalog, import graph, hardcoded text, inline stylesheet and function limits pass.
The accessibility walk passes in dark and light; the research-mode banner tests
pass unchanged. Ruff 0.16.10 check, changed-file formatting, Python 3.11 compile
and quality_gate pass. Full compare-host and real desktop terminal/isolation/
history/market/walk-forward smoke checks encounter sandbox temporary-directory
ACL errors or their pre-existing environment skips; controller reruns are needed.
B4's baseline-text assertion correctly detects the three new [0] tab titles;
its fixture comparison needs the controller refresh before that module can pass.
GitNexus status is stale/incomplete, analyze --skip-fts fails spawning a worker
(EPERM), and the explicit lane context lookup is unregistered. Source reads and
runtime tests supply the local implementation evidence instead.

A disposable 1366x768 capture compared all seven pages without editing fixtures.
Only these files under tests/fixtures/desktop_pages_before need controller refresh
in a separate fixture-only commit: 04_full.png, 04_viewport.png (numeric compare
headers), 05_full.png (paper tab counts), 07_full.png (left-aligned log headers),
and metrics.json (paper visible tab text and subpage keys). Other decoded PNGs
match; all other page metrics match. These are measurements, not quality claims.

Protected G3 sources and all saved_candidate_pool.py content have empty diffs
against e0e604f. No live/broker path, gate, OOS/budget rule, timeout, credential
handling, PROJECT_STATE, optimization plan or ACCEPTANCE score changes. Leave
this implementation uncommitted for the controller's single C9 commit.

### TASK A2-D4: session-only read-only research assistant

Initial assessment confirmed no conversation panel and no UI wiring for D3.
The new AssistantPanel lives inside Settings' existing collapsed maintenance
area. No default page text, layout, label count or baseline image is intentionally
changed. The widget-name inventory adds only five sorted assistant names. The
current lane has no PanelCard or AsyncStatus implementation to reuse. No new
desktop_ui public name or MainWindow method is introduced.

quantlab.assistant_chat.ChatDispatcher owns a private frozen registry created
only by agent_read_tools.create_registry. Its callable tool surface is exactly
the nine D3 TOOL_NAMES, all effect=read. Unknown, mutation, operator and quota
names refuse before dispatch using B1 agent_tool_refused. Explicit /tool name
JSON commands render only the D3/D11 bounded_return envelope, including paging
metadata; full raw saved results are never rendered or implicitly forwarded.
The host constructs ReadContext independently of input. Existing GUI results
have no trusted training evidence, so the mounted panel grants none rather than
inferring authority from current datasets, saved partition labels or model text.
Trusted host adapters can supply an already-bound context; model arguments cannot
widen it. Legacy results fail closed. No broker execution session is constructed.

Offline fixture replies are exact, fixed catalog strings and require no provider
object or network. Both source selector and reply labels identify this source as
not real AI. ChatGPT labels always say unverified. All assistant reply paths,
including refusals and cancellation, append the same Chinese catalog disclaimer:
AI interpretation may be wrong; nothing is automatically applied or ordered.
QPlainTextEdit.appendPlainText renders markup/code literally and supports copying;
there is no renderer, code runner, apply button or transcript persistence path.
Enter, Ctrl+Enter and the accessible Send button share the submit boundary.

ChatGPT is an optional, unverified single-prompt inference route. Each send first
opens an Ok/Cancel consent dialog, default Cancel. Denial leaves the input and
transcript unchanged and makes zero provider calls. Accepted requests transmit
only that input, with store=False, no history, dataset, automatic tool output or
function declarations. No model-generated follow-up request is executed. This
does not invoke the strategy provider, campaign quota reservation, candidate
saver, backtest, campaign or Walk-forward. The child resolves only an opaque
DPAPI credential reference through the unchanged pinned transport, checks the
existing account-ready barrier and uses verified TLS/no redirects/no retries.
Provider exceptions and invalid/oversize/ambiguous terminal responses become
fixed B1 refusals; no exception string crosses IPC or enters diagnostics/logs.

ReplyProcess follows desktop_runtime's spawn/gate/process-tree ownership model,
reusing its Windows process-tree primitive. No GUI worker thread is added. The
parent owns a 30-second deadline and bounded termination/join; network stall is
10 seconds. Hide/tab-switch and top-level close cancel the reply, close handles,
stop polling and retain only a fixed refusal/disclaimer in session memory.
Existing paper/smoke/job timeouts and every budget/gate/OOS rule are untouched.

Evidence: tests/test_assistant_d4.py adds ten offline tests (about one second).
It covers exact tools/frozen declarations, no-handler mutation rejection,
deterministic golden text, disclosures on success/error/cancel, literal markup,
keyboard/accessibility, per-call consent, bounded byte overflow, host-only
evidence, legacy refusal, operator/save/quota sentinels, mock process cleanup,
single-prompt payloads, credential exception redaction and no transcript writes.
OOS/holdout prices/counts/markers and credential markers are planted in actual
saved fixtures and scanned through every tool and UI output. A deliberately
broken provenance filter and a planted sentinel both fail the same scan.
AST assertions forbid dynamic execution and persistence/operator calls.

Local checks: D4 10, import graph 8, UI operation registry 6, hardcoded-text 6,
repository layout 7, catalog placeholders 1, inline styles 3 and function-length
guards 2 pass. Ruff 0.16.10 check/changed-file format, py -3.11 py_compile and
tools/quality_gate.py pass (zero findings). G3 sources, all saved_candidate_pool
bytes, PROJECT_STATE, optimization plan and ACCEPTANCE have empty diffs vs HEAD.
No existing test is weakened or removed; inventory tests are additive only.

The unchanged terminal, smoke-isolation, history, market and Walk-forward smoke
modules were attempted; Windows restricted-token temporary-directory ACL failures
prevent full local smoke verification (some existing platform skips also apply).
Controller native smoke and screenshot verification remain necessary; no baseline
fixture refresh is requested. No live ChatGPT inference was attempted or claimed
verified. GitNexus analyze failed with sandbox spawn EPERM and its lane query
reported repository not found; no graph substitute or extension download was used.
Changes remain uncommitted; the controller owns the single A2-D4 commit.

### TASK A2-D5: assistant timeline, folded summaries and code copying

Initial assessment confirmed D4's collapsed maintenance-area assistant existed,
but had no timeline, thinking fold or code-copy control. The existing assistant
now owns desktop_pages.assistant_details widgets. No default page, public
desktop_ui name, MainWindow method, PanelCard or AsyncStatus is changed (the
latter two components are absent in this lane). The widget inventory adds only
assistant_thinking and assistant_timeline; no baseline refresh is requested.

Each explicit /tool call passes once through the unchanged D4 dispatcher and
appends one row: registered tool name, projected JSON parameters, result item
count/truncation summary, and elapsed seconds formatted to three decimals.
Timing uses an injectable time.monotonic clock. Exceptions, unknown tools and
refusals show only B1 agent_tool_refused and ERROR_TABLE's explanation; unknown
names and rejected parameters are never echoed. Parameters have a fixed
240-character cap, project only known fields and conceal opaque cursors.
Credential keys and arbitrary argument keys never enter summaries. Only D3's
already bounded, training-provenance-filtered return enters result details;
the transcript records a fixed reference to that row rather than the payload.
Tool input is no longer repeated verbatim in the transcript.

Rows and code widgets retain only the newest 40 entries. Transcript history
retains 40 bounded entries, and the current thinking summary is bounded to
8192 characters. Each detail body is bounded to 16384 characters. Tool results
and thinking start collapsed; native checkable buttons support click and Space.
All labels explicitly select plain text, and all bodies use QPlainTextEdit;
HTML, markup and code remain inert literal characters. Summary headers contain
counts rather than full results. Fenced code blocks have accessible,
keyboard-focusable copy buttons using only QClipboard.setText, preserving the
block's indentation, blank lines and final newline. No execution/apply/send
action exists. Privacy mode copies only the masked displayed text.

B11 bind_text/render callbacks refresh every assistant document and parameter
label on toggles, reusing mask_money and mask_account_id. Money, account ids,
paths and result identities are masked; free-text replies, thinking and result
documents fail closed to a mask under privacy. Original bounded source remains
in session-only Python presentation state, outside Qt text/data/accessibility
roles, like B11's raw source handling. B11 attach_previews now defers to an
existing owned renderer, preventing a second raw preview cache from retaining
old assistant document text. The existing B11 tests pass unchanged.

Only explicit summary_text fields from reasoning items in the unchanged pinned
provider's terminal response are surfaced by assistant_runtime; opaque or
encrypted reasoning data is ignored. No request for hidden reasoning is made.
Thinking is labelled unverified/model-generated in the catalog. No-summary
responses preserve D4's original response shape. Malformed/oversized summaries
fail closed. The fixture source still says not real AI, and ChatGPT inference
remains unverified. Per-call explicit consent, the single-prompt payload,
DPAPI-only credential references, and all runtime deadlines are unchanged.

tests/test_assistant_d5.py adds nine offline tests using real D4/D3 saved
fixtures with planted protected values. Coverage includes monotonic timing,
B1 exception redaction, bounded parameter projection, click/keyboard folding,
privacy toggles with unmasked negative controls and no raw Qt caches, exact
QClipboard code text, summary-only reasoning extraction, consent denial with
zero transport calls, fixed row/widget/history counts, and AST exclusion of
dynamic execution/operator/persistence calls. Protected-data and credential
scans cover every actual tool row and transcript; planted OOS and credential
negative controls fail the same scanner. Existing D4 tests continue to prove
the exact frozen read-only surface, operator/quota sentinels, per-call consent,
model-facing payload isolation and protected-fixture filtering.

Local validation: D5 9, D4 10, B11 8, import graph 8, hardcoded UI text 7,
inline styles 3, repository layout 8, catalog placeholders 1, function limits 2
and UI operation registry 6 pass. Ruff 0.16.10 check, changed-file format check,
Python 3.11 compilation and quality_gate (zero findings) pass. The
unchanged terminal, smoke-isolation, history, market and Walk-forward smoke
modules were attempted but hit Windows restricted-token temporary-directory
ACL failures; native smoke and visual confirmation remain controller checks.
No live inference or visual acceptance is claimed. GitNexus analyze failed
with sandbox spawn EPERM and the lane query reported repository not found;
no alternate graph or extension download was used.

Live trading remains permanently disabled; no operator, mutation, quota or
credential reader was added. G3 sources, all saved_candidate_pool bytes,
PROJECT_STATE, optimization plan and ACCEPTANCE remain untouched. No gate,
budget, OOS rule, timeout or existing test was weakened. Changes remain
uncommitted; the controller owns the single A2-D5 commit.

### TASK A2-D8: research permission menus and session-only confirmation intent

Initial assessment confirmed the frozen D4/D3 read surface existed without
permission menus. desktop_pages.assistant_permissions now owns two synchronized
native QComboBox menus: below the assistant input and inside the existing
collapsed connection management area. Both say research actions and offer exactly
read-only and confirm each time through literal desktop_strings catalog keys.
The accompanying plain-text label explicitly states that confirmation still
permits only read tools in this release, cannot start research/backtests or
Walk-forward, save candidates or consume quota, and never enables live trading.
ChatGPT inference remains unverified and every network call still requires its
existing separate per-call consent. Offline fixtures remain labelled not real AI.

Restart policy: every new ResearchPermission instance starts read-only, even if
the saved value is confirm_each_time. Confirmation requires fresh explicit
selection in the current session. The additive assistant_research_permission
preference uses the existing SettingsStore, preserves all prior settings and
does not change any existing schema/key. Missing settings attributes are valid
for SimpleNamespace hosts. Corrupt/unknown saved values cannot grant anything;
save failure leaves the session read-only, preserves the original file and
displays only the B1 agent_tool_refused explanation. Permission changes emit
the fixed assistant_permission_changed logging event and a normalized mode;
no settings contents, paths, credentials or exception strings enter that event.

ChatDispatcher checks the current declaration and closed tool name set before
dispatch. Read-only refuses every non-read/unknown request with the B1 code and
no handler invocation. Confirm-each-time routes each such attempt through the
existing Ok/Cancel dialog, with Cancel as default, then still refuses: this
release deliberately has no executable mutation route. Approval is never saved,
cached or reused. Registry.resolve/call remain independently read-only, and
freeze still prohibits late registration. No operator or trade tool is added.

tests/test_assistant_d8.py adds six cheap offline tests. They exercise keyboard
menu synchronization/accessibility, exact choices and release label, real
SettingsStore persistence/restart downgrade, corrupt/unknown/legacy state,
missing attributes, frozen fake-mutation registration and denial with fresh
dialogs (Cancel and repeated approval), sanitized logging, source/catalog mode
and AST execution scans. Existing D4 safety oracles run in both modes: every
callable tool is read-only and frozen; patched backtest/campaign/Walk-forward,
candidate-save and quota entry points remain untouched; protected saved fixture
sentinels and the negative control, model-facing payload isolation, inert HTML,
DPAPI reference isolation and denied consent with zero provider calls all pass.

Local validation: D8 6, unchanged D4 10 and D5 9, import graph 8, hardcoded text
8, repository layout 9, catalog placeholders 1, inline stylesheet 3, function
limits 2 and UI operation registry 6 pass. Ruff 0.16.10 check and changed-file
format check, py -3.11 compilation and quality_gate (zero findings) pass.
The unchanged terminal, smoke-isolation, history, market and Walk-forward smoke
modules were attempted; Windows restricted-token temporary-directory ACL
failures prevent full native smoke verification. Controller smoke/visual checks
remain necessary; no live inference is claimed verified. GitNexus analyze failed
with spawn EPERM and its impact query could not find this worktree; no alternative
graph tool or extension download was used.

All new controls stay in existing collapsed areas; no default-page baseline
refresh is requested. The widget-name fixture adds only the two permission menu
names. UI-1 PanelCard/AsyncStatus are absent; the existing page header is retained.
No new desktop_ui public names, root-level modules, gates, OOS rules, budgets,
timeouts, scores or existing-test exemptions are introduced. G3 sources, all
saved_candidate_pool bytes, PROJECT_STATE, optimization plan and ACCEPTANCE have
empty diffs. Changes remain uncommitted for the controller's single A2-D8 commit.


### TASK A2-D9: explicit read-only connection test (inference unverified)

Initial inspection confirmed no test action or button existed. The optional,
already collapsed connection panel now has a keyboard-operable named button.
It requires the active account, a discovered selected model, a ready known
account barrier and an idle host. Quota/eligibility pauses and pending requests
show the existing B1 reason and disable it. Its catalog wording discloses a
small quota cost, read-only intent and unverified inference. Every press opens
the per-call Ok/Cancel network dialog (Cancel is default); no checkbox or prior
approval substitutes for it. Denial dispatches no job or provider call.

ConnectionController's new test action uses the existing quiesce, bounded job,
IPC, cancellation and actual-worker-join path. The request has a 30-second
runtime; public PlanHTTPTransport and SSEParser retain verified TLS, byte,
stall and response bounds. The fixed payload contains only the selected model,
read-only instructions and `Reply with OK.`; no research context, tools,
conversation, credentials, OOS or final holdout can enter this payload. Only an
opaque credential reference enters the worker; credentials stay in the pinned
DPAPI path. No retry, campaign quota reservation or operator route is added.

A completed response displays the neutral catalog message `connection responded`
and explicitly says inference is still unverified. Model text is discarded,
never rendered, logged or executed by the probe. Usage is projected to three
bounded integer token counts only; unavailable/interrupted usage is explicitly
unknown and may have consumed quota. Unknown errors use generic B1
operation_failed; known failures use the existing B1 code and mapped message,
never exception text. A dedicated TestConnectionEvent carries probe usage,
preserving the byte-for-byte legacy event schema and UI operations golden.
Changing selected model/account, changing active account, or signing out clears
the prior result to stale/untested. invalidate_campaign_usage remains unchanged.

New tests/test_connection_d9.py adds six cheap offline tests for prerequisites,
paused reasons, keyboard accessibility, fresh dialogs, denied consent with zero
provider calls, worker/quiesce/join/cancel barriers, injected deadlines, one-call
failure/no retry, B1 redaction, token usage/unknown display, model/account/signout
invalidation, exact payload and sentinel scans with a planted negative control.
All tests use fake transport and no real process or network. Existing unchanged
D4 (10), D5 (9) and D8 (6) safety tests also pass: the frozen complete assistant
registry has only read tools, operator/candidate/quota entry-point sentinels stay
untouched, OOS/holdout/credential scans exclude protected fixtures with negative
controls, denied consent reaches no provider, HTML is inert plain text and code
is copyable only. The assistant remains a research assistant and offline fixtures
remain labelled not real AI; live ChatGPT inference is never claimed verified.

The new module is registered in test_import_graph and covered by the desktop
package UI-text, stylesheet and repo-layout inventories. The widget-name fixture
adds only chatgpt_test and chatgpt_test_status. No default-page baseline refresh
is requested: the controls stay inside the existing collapsed connection area.
Existing header behavior is retained; UI-1 PanelCard/AsyncStatus are absent.
MainWindow remains 396 lines; ChatGPTConnectionPanel and the helper stay below
500 lines. desktop_ui has no new public names. No gate, OOS rule, budget,
timeout, existing test, golden, score or acceptance evidence is weakened.

Validation: D9 6, D4 10, D5 9, D8 6, import graph 8, UI-text 9, stylesheet 3,
repo layout 10, placeholders 1, function budgets 2 and UI operations registry 6
pass. Ruff 0.16.10 check and changed-file format check, Python 3.11 compilation
and quality_gate pass. The unchanged terminal, smoke-isolation, history, market
and Walk-forward smoke modules were attempted but hit restricted-token Windows
temporary-directory ACL failures. Controller smoke and visual checks remain
unverified; no live network test was made. GitNexus analyze failed with spawn
EPERM and the lane query reported repository not found; no other graph tool or
extension download was used. G3 files, all saved_candidate_pool bytes,
PROJECT_STATE, optimization plan and ACCEPTANCE have empty diffs. Changes remain
uncommitted for the controller to create exactly one A2-D9 commit.
### TASK A2-D6: local skill completion and training-only content references

Initial assessment confirmed D7 SkillLoader and four local docs/skills packages
were present, but neither slash nor at-sign completion existed. The existing
collapsed Settings maintenance assistant now owns assistant_completion's inline
list. Slash at input start lists the four loaded names; whitespace-delimited @
lists approved saved results and their bound training datasets. Mid-word a/b
and a@b do not activate either list. Up/Down navigate, Enter/Tab insert only,
Escape closes, and focus remains/returns to the input. Hidden-widget QTest
events exercise the same explicit open state. Selection sends nothing and runs
no skill, model or operator. Skill invocations remain inert prompt text.

SkillLoader.completion_list isolates malformed files, retaining the B1
agent_tool_refused codes in catalog_errors and the completion accessible
description. Strict D7 list/read/activate remain atomic and unchanged. Names,
directory ancestors, reparse points, containment and byte/count bounds are
validated before reading. The root is still host-registered docs/skills, never
chosen by input. Missing directories produce an empty list and the B1 code.
The UI loader uses only READ_REGISTRY; mutation/unknown tool declarations are
excluded, and skills grant no capabilities or extra tools.

The existing D3 list_saved_results adds optional include_datasets integer 0/1
(default 0, preserving its original output). Value 1 adds only the content-bound
data_hash after the same training evidence and saved-content validation. No new
tool is registered: the complete frozen assistant surface remains exactly nine
read declarations. Dataset references mean datasets bound to approved saved
training results, never arbitrary files or current dataset/OOS labels. The
desktop host still supplies no inferred legacy provenance, so its legacy or
empty store correctly lists nothing.

Each popup row contains a 12-hex identity plus a fixed catalog one-line summary
marked unverified, with an accessible name. No saved label, body, metric value,
trade, equity series, dataset row or quality count enters a row or reference
expansion. QListWidget and the existing QPlainTextEdit paint literal text.
At most 20 suggestions are displayed, filtered before slicing. Catalog reads
are capped at four D3 pages of 50. An incomplete/oversized/invalid catalog fails
closed rather than resolving a seemingly unique prefix from a partial list.

On explicit submit, @result:hash and @dataset:hash require a unique 12-64 hex
prefix in a freshly validated D3 catalog. Result resolution calls only D3
get_backtest_summary; dataset resolution calls only get_data_quality_summary
for its bound result. Their payload values are discarded. Only the canonical
full identity and fixed unverified summary can enter the single-prompt request
or transcript. Unknown, stale, ambiguous or unsupported references return the
new single-table B1 agent_reference_not_found with no fallback. No saved JSON,
partition claim, model text or permission selection can create evidence.

Per-call ChatGPT consent precedes even reference resolution on remote submit;
denial leaves input/transcript intact and reaches no provider. Existing DPAPI,
single-prompt/no-history, inert model output, copy-only code, read-only tool,
operator/quota refusal and OOS/holdout protections remain in force. The offline
fixture still says not real AI, and live inference remains unverified.

Eight cheap tests in test_assistant_d6 cover keyboard insertion without show,
prefix/count/accessibility, malformed/mutation skills, traversal and reparse
read confinement, missing catalogs, empty/legacy stores, D3-only resolution,
stale/protected/ambiguous hashes, protected-value scans with a planted negative
control, consent denial and summary-only requests. D4 operator/quota and frozen
registry oracles are also exercised. test_error_catalog_b1 adds the new message
assertion before the unchanged historical-count and byte-hash assertions;
this legitimate new text does not relax the historical catalog lock. Module
inventory assertions and test_import_graph registration are additive, and normal
CI unittest discovery includes the new test file.

All controls remain inside the existing collapsed assistant. No default-page
baseline refresh is requested; the widget-name fixture adds only the sorted
assistant_completions name. Existing header behavior is retained; PanelCard and
AsyncStatus are absent. desktop_ui exports and MainWindow are unchanged, and
the new classes remain below the class-size limit.

Validation: D6 8, unchanged D7 10, D3 9, D4 10, D5 9, D8 6, D9 6, B1 8,
import graph 8, hardcoded UI text 10, repo layout 11, inline styles 3,
placeholders 1, function budgets 2 and UI operation registry 6 pass. Ruff
0.16.10 check, changed-file format check, py -3.11 compilation and quality_gate
(zero findings) pass. Repository-wide format check reports only the known
unchanged ADR 0006 CRLF checkout issue. The unchanged terminal, isolation,
history, market and Walk-forward smoke modules were attempted and hit Windows
restricted-token temporary-directory ACL failures. Native smoke and visual QA
remain controller checks; no live inference is claimed verified. GitNexus
analyze failed with spawn EPERM and the lane query reported repository not
found; no alternate graph or extension download was used.

G3 sources, all saved_candidate_pool bytes, PROJECT_STATE, optimization plan,
ACCEPTANCE and default-page fixtures have empty diffs against the starting
HEAD. No live trading, operator/mutation path, gate, OOS rule, budget, timeout,
score or existing test exemption is added or loosened. Work remains uncommitted
for the controller's single A2-D6 commit.

### TASK A2-D10: discovered assistant models, effort and reported context

Initial inspection confirmed the connection model selector/discovery existed,
but the assistant had neither its own model selector, an effort selector nor a
context display. assistant_models now owns these controls inside the existing
collapsed Settings maintenance assistant. No default page changes or baseline
refresh are requested. Widget-name fixture additions are only assistant_model,
assistant_effort, assistant_models_empty and assistant_context_usage. Existing
header behavior is retained; PanelCard and AsyncStatus are absent in this lane.

Model rows come only from ConnectionController.models/model_labels, originally
populated through discover_models/parse_models. No model names, limits or effort
levels are inferred or hardcoded. The pinned parse_models currently preserves
only slug/display_name, so real discovery does not advertise effort metadata:
the disabled selector therefore says not provided. The optional host catalog
metadata seam model_metadata[slug].reasoning_efforts accepts only bounded inert
strings and populates only those advertised values plus unspecified. It makes
no additional discovery call and cannot create model rows. Model changes reset
effort to unspecified and synchronize the existing connection selector, retaining
its D9 test-status reset and campaign-usage invalidation signals. Preference
restore accepts only current discovered models and their advertised efforts;
removed, corrupt and unsupported preferences safely fall back. Settings contain
only model/effort preferences, with no authority or credentials.

Every remote submit still asks per-call consent before reference resolution or
provider invocation, then validates MODEL syntax and current catalog/effort
membership. Stale/invalid selections return the existing B1 agent_tool_refused
message and cannot start a worker. An empty model catalog shows the empty state
and disables send, including keyboard submission. The offline fixture remains
labelled not real AI and performs no inference or discovery call.
The existing public PlanHTTPTransport.stream path carries an explicitly selected
reasoning.effort; unspecified omits reasoning. The worker validates the bounded
selection snapshot again. No auth/provider source is changed, no new endpoint,
operator, quota reservation, candidate saver, tool declaration or retry exists.

Context remains not provided unless a completed response explicitly supplies
context_usage used/limit integer counters. Ordinary input/output/total token
counts do not establish context capacity and are never converted to a guessed
percentage. Only these two bounded counters cross IPC. Percentage uses exact
integer half-up rounding and clamps to 0..100; absent/invalid usage never shows
0%. Every display says provider-reported, unverified. Selection/account changes
and new sends clear old context; replies for a previous model/account cannot
populate the new selection's usage. Live inference is not claimed verified.

Eleven cheap offline test_assistant_d10 tests cover discovered-only rows, missing
and malformed metadata, keyboard/accessibility, resets, empty/bare hosts, stale
send validation, safe preference restore, rounding/clamping, missing/old context,
public transport payloads, consent denial, literal output and sentinel scans
with planted negative controls. Existing D4 tests still enumerate the frozen
read-only surface, patch operator/quota entry points, plant OOS/holdout/secrets
in fixtures and check payload/transcript exclusion and AST execution bans. The
only D4 change supplies a discovered fixture model for its remote consent and
keyboard tests, as newly required by D10; no assertion is removed or weakened.
Inventory checks register the new package module additively; existing package
scans cover inline styles and UI text. desktop_ui exports and MainWindow are
unchanged; new classes remain below the size limit.

Validation: D10 11, D4 10, D6 8, D5 9, D8 6, D9 6, import graph 8,
hardcoded UI text 11, repo layout 12, inline styles 3, placeholders 1, function
budgets 2 and UI operations registry 6 pass. Ruff 0.16.10 check and changed-file
format check, py -3.11 compilation and quality_gate (zero findings) pass.
Repo-wide format check reports only unchanged ADR 0006's known CRLF checkout
issue. Unchanged terminal, isolation, history, market and Walk-forward smoke
modules were attempted and encountered restricted-token Windows temp-directory
ACL failures; controller native smoke/visual verification remains outstanding.
No live network verification was attempted. GitNexus status found no lane index;
analyze failed with spawn EPERM and its MCP query reported repository not found.
No alternate graph tool or extension download was used. Routing used GitNexus
and local work; no repository-independent external research was needed.

G3, all saved_candidate_pool bytes, PROJECT_STATE, optimization plan, ACCEPTANCE
and default-page baseline files remain unchanged against starting HEAD. No gate,
OOS rule, irreversible budget, timeout, score or test exemption changes; live
trading stays permanently disabled. Changes remain uncommitted for the
controller to produce exactly one A2-D10 commit.

### TASK A2-D12: saved run manifests and comparison

Assessment: PARTIAL at entry. `quantlab/backtest.py` already embeds the complete
strategy specification (`strategy`) and its immutable content revision
(`spec_hash`), dataset identity (`data_hash`, `dataset_manifest` and its hash),
cost identity (`cost_hash`, `config.costs`, `config.cost_schedule`),
`engine_version` (`quantlab-event-v1`), engine/source hashes, source commit,
configuration and seed. ADR 0005 defines the content-hash strategy revision;
there is no need to introduce a second mutable revision identifier. Existing
presentation reads result.manifest, and D3 reads strategy/data identity. Only
dedicated manifest reads, field comparison and human-readable details were
missing. backtest.py has an empty diff against the starting HEAD.

`get_result_manifest` and `compare_result_manifests` are appended to TOOL_NAMES
and registered before freeze. Both declare effect `read`, capability
`research.read`, the existing item/byte caps and closed argument schemas.
The D1 schema vocabulary adds only the fixed lowercase SHA-256 pattern;
the checked-in schema remains identical to the runtime contract. Manifest row
schemas are closed, required and typed; the D3 handler validates them through
the D1 validator before bounded_return and the frozen registry's envelope
validation. Unknown IDs return B1 `agent_reference_not_found`; malformed
hashes are rejected by the input schema before filesystem reads. Existing
records lacking trusted training evidence return `agent_tool_refused`.

Reads use D3's exact saved envelope, checksum/nested-binding validation and
host-only TrainingEvidence bound to data_hash. Nothing runs an engine or
recomputes manifest values. Hash validation is integrity checking, not inference
or a new run. Historical desktop results have no trusted training evidence:
the GUI intentionally cannot infer it from labels or current data. They remain
unavailable until a trusted host supplies evidence; this item adds no bypass.

The positive projection exposes spec_hash, data_hash, cost_hash, engine_version,
commission_per_side, tax_rate, slippage_ticks, tax_rounding and effective_from,
including indexed cost schedule entries. Numeric strings and integer values
retain their saved representation. Free-form strategy IDs, cost-version labels,
source commits, usernames, paths, credentials, dataset metadata, metrics, raw
records and partition totals are excluded. Engine versions accept the existing
quantlab-event-v numeric family; unsupported arbitrary text fails closed.
Missing optional fields are explicit nulls. Required immutable bindings still
must pass unchanged validate_result_payload; this item does not relax legacy
validation. All fields sort lexically, with zero-padded schedule indices.
Comparison returns both values, `same`/`different` and a per-field
`non_comparable` warning for differing data_hash, cost_hash or engine_version.
Warnings never turn a valid comparison into an error. Both tools page through
the existing bounded_return, with explicit truncation and scoped cursors.

`assistant_manifest.ManifestDetails` lives in the existing collapsed Settings
maintenance assistant, using the same frozen dispatcher. A refresh lists only
approved saved IDs (a capped catalog explicitly indicates truncation). Native
keyboard controls select a result, read its details or compare two results.
The read-only table displays left/right values together, marks differences
with text and bold type, and has a next-page button for bounded manifest pages.
Optional missing values display `not recorded`. All labels use literal ui_text
keys, QTableWidgetItem paints plain text, and the title uses PlainText. No HTML,
code execution, provider call, consent bypass or authority is added. Existing
UI-1 header behavior is retained; PanelCard/AsyncStatus are absent in this lane.
desktop_ui exports and MainWindow are unchanged; new classes stay below the
class-size budget. Default-page fixtures are untouched; no baseline refresh is
requested. The widget-name fixture adds only the eight manifest object names.

Seven new cheap offline D12 tests cover saved verbatim values, closed output
schemas, frozen read-only surface, input hash rejection, not-found, legacy
refusal, deterministic comparison, non-comparable warnings, byte/item paging,
cursor scope, missing optional fields, literal text, keyboard access, bare
hosts, provider/operator/quota sentinels and protected-data scans with planted
negative controls. Existing D3/D4 fixture argument builders add the second ID
for the new compare tool; no assertion is removed or weakened. New modules are
registered additively in import/layout checks; package scans cover UI text and
inline styles. Import graph expectations add only the manifest dependency.

Validation: D12 7, D1 11, D3 9, D4 10, D5 9, D6 8, D8 6, D10 11,
import graph 9, UI text 12, repo layout 13, inline styles 3, placeholders 1,
function lengths 2 and UI operations registry 6 pass. Ruff 0.16.10 check,
changed-file format check, Python 3.11 compile and quality_gate (zero findings)
pass. Repo-wide format check reports only unchanged ADR 0006's documented CRLF
checkout issue. Unchanged terminal, isolation, history, market and Walk-forward
smoke modules were attempted and hit restricted-token Windows temporary-folder
ACL failures; their native subprocess checks and visual QA remain for the
controller. Live ChatGPT inference remains unverified and was not attempted.
GitNexus status found no lane index; analyze failed with spawn EPERM and lane
query/impact reported repository not found. No alternate graph or extension
download was used. Routing used GitNexus and local work; external research and
ChatGPT delegation were unnecessary for these repository-owned contracts.

G3 sources, all saved_candidate_pool bytes, result schema/validator,
PROJECT_STATE, optimization plan, ACCEPTANCE and default-page baselines have
empty diffs against the starting HEAD. Live trading stays disabled; no operator
or mutation tool, gate, OOS rule, irreversible budget, timeout, score or test
exemption changes. Work remains uncommitted for the controller's exactly one
A2-D12 commit.

## UI-3 C5: market dock workspace (2026-10-20)

MarketWorkspace in desktop_market_workspace.py owns three equivalent dock panels:
`cards`, `watchlist`, `chart`, with `market_dock_<id>` objectNames. It reparents
existing content and retains all public widget references and original names.
Title dragging and keyboard menus dock to top/left/center/right/bottom or reorder;
C on a focused title collapses/reopens the same content object. Collapsed titles
show [+]. The layout menu exposes presets, save as, named restore/delete and reset.
All controls have catalog names/descriptions/tooltips and tab focus; shared theme
properties and a centralized QToolButton focus selector cover both themes.

Exactly three presets are supported: overview (cards above, watchlist/chart/side
190:740:230), chart_focus (collapsed cards, 120:810:230), watchlist_focus
(460:470:230). Applying twice is idempotent. Reset always restores overview.
Safety/source/stale/live-disabled labels remain outside every collapsible panel.
No order or live path is added.

LayoutStore in desktop_market_layout.py stores a separate versioned JSON file at
`<settings parent>/display_profile/market-layout-v1.json`, next to DrawingStore.
There is one persisted read at page mount; missing settings use memory only.
The exact document keys are version/current/layouts. Each layout has version/panels,
with exactly the known three IDs and area/position/size/collapsed fields. Areas
are allowlisted; positions are strict integers 0..2; sizes strict integers clamped
to 80..2000; collapsed is boolean. Names are bounded to 64 trimmed characters,
path separators/control characters/simple reserved names rejected; at most 20
names and 128000 input bytes. Names are dictionary keys only. Bad UTF-8/JSON,
missing/incomplete/unsupported/extra-field metadata falls back to overview, without
modal UI or touching the bad file. Invalid named entries do not poison valid peers.
Only explicit named save/delete writes; same-name save overwrites. A same-directory
temporary file is flushed/fsynced then os.replace commits it atomically. Write or
replace failure preserves prior bytes and memory, cleans temporary files and shows
only the B1 operation_failed_local message. No exception text/path is displayed.

Layout operations never emit refresh/sample/preferences/render signals or invoke
consent, host jobs, market/cache loading, series setters, chart.set_series or layer
binding. Instrument/timeframe, watchlist order/selection, indicator preferences,
chart bars/overlays and chart identity remain unchanged. No observations, secrets,
research content or data hashes enter layout JSON or any AI handoff. Research,
cache, result, selection and paper artifacts stay byte/hash-identical. The refresh
consent flow/default No and network_opt_in payload are unchanged.

Cheap synthetic tests in test_market_workspace_c5.py cover schema/fallback,
persistence isolation, atomic faults, identity, all preset/action operations and
50 preset changes with destruction. Accessibility and scaled-layout modules pass.
No new test shows a window, resets application style, sleeps, networks or spawns
processes. Existing snapshot assertions remain; the market title/menu additions
were refreshed in desktop_pages_before/metrics.json, 06_full.png and
06_viewport.png by a separate fixture-only commit. The controller ran the full
startup smokes outside the sandbox (they pass), and the two new root modules are
tracked so the root-file inventory passes. GitNexus's lane index could not be
built in the sandbox (spawn EPERM); the stale main graph plus source reads
provided limited navigation evidence. Real-App visual check remains
PENDING USER FINAL CONFIRMATION. G3/profile blocks, PROJECT_STATE, acceptance
scores, gate/budget/OOS rules and all timeouts are unchanged. The work is committed by the controller.

C5 final verification: ruff 0.16.10 check and changed-file format checks pass;
Python 3.11 compilation and tools/quality_gate.py pass. The new modules also
pass the strict desktop AST/credential scans; the gate
inventory includes both modules. All 11 focused C5 tests pass, together with
accessibility, scaled layout, existing dashboard/empty-page, catalog, import,
inline-style, public-name and frozen-source checks. Direct unchanged synthetic
rendering helpers pass 100 market bars and all 24 history combinations. A final
1366x768 disposable raster comparison changes only the two market PNGs and market
metrics: page_height 953 -> 974, button_count 11 -> 15, label_char_count 74 -> 81.
The live-disabled notice is intentionally moved to the source row, outside the
existing indicator-side disclosure as well as all three workspace panels.
B4's exact baseline assertion passes after the separate fixture-only refresh commit,
which changes only the two market PNGs and the market metrics. Real-App visual
check remains PENDING USER FINAL CONFIRMATION.

C5 watchlist sizing repair: the retained watchlist content and its workspace panel
have minimum widths derived from the content size hint. Layout requests update
these constraints after font/theme changes; splitter allocation and every preset
respect them without changing serialized preset ratios or market state. This
prevents remove/reorder button clipping and may widen the default watchlist.
The controller should review `desktop_pages_before/06_full.png` and
`desktop_pages_before/06_viewport.png`; the controller refreshed both PNGs in the
fixture-only baseline commit, and the real-App visual check remains PENDING USER
FINAL CONFIRMATION.

## UI-3 C10: shared-source chart pop-out (2026-10-20)

The existing market chart panel title menu exposes a localized, keyboard-reachable
pop-out action with a tooltip. PopoutController owns at most one independent
ChartPopout; activating again restores/raises it. Empty data remains an empty
read-only chart. The main chart object, objectName, drawing store and C5 panel
are retained. No default page layout/text/control-count change or snapshot
baseline refresh is intended; widget-name inventory additions are additive.

The follower reads MarketDashboard._series directly through series_store, with
identity preserved even when the dashboard replaces the store. Rendered bars,
immutable overlays/panes, trace and annotation records are shared by identity
from the authoritative chart. No aggregation, fetching, data provider, refresh,
sample, consent, job or network path exists in the pop-out. Exact source/strategy
binding remains exclusively in MarketPage.bind_result_layers; a rejected binding
clears the follower's layers too. Source/status, stale/error disclosure and the
live-disabled notice remain visible. Paper snapshots have no order callback.
Zoom/pan/crosshair are independent display state; follower gestures never change
the main chart's viewport. Display changes and completed dashboard renders update
the follower synchronously, including indicator changes and early empty/error
returns. The display signal also follows later annotation/snapshot changes.

Close (including Escape and the accessible close button) is idempotent. It
disconnects only the two follower subscriptions, drops the controller's window
reference, detaches the closed dialog and releases its dashboard reference.
There is no deleteLater or retained deleted wrapper. MainWindow explicitly closes
the follower on accepted shutdown; dashboard close/destruction closes it before
child chart teardown. Reopen constructs a fresh follower. There are no pop-out
timers or event filters, hidden/minimized polling, or recurring child searches.

Geometry is saved only on visible, non-minimized close, at the independent
settings key `market_popout` with x/y from frame x()/y() and width/height.
SettingsStore.save remains the existing atomic writer; other sections, including
legacy and main-window geometry, are merged unchanged. Move/resize events write
nothing, and hidden/minimized close writes nothing. Restore rejects bool, string,
NaN and missing coordinates without coercion; size is bounded to the chart minimum
and available screen size. Coordinates inside an injected available secondary
screen (including negative x) select that screen. Otherwise placement clamps to
the host screen, with a default rectangle when a bare host has no screen service.
Legacy settings without the key load without modifying the store. Persistence
failures show only B1 operation_failed_local, without exception text.

Cheap synthetic offscreen tests cover shared state/source identity, empty data,
selection/timeframe/indicator/quote updates, exact-source mismatch clearing,
independent viewport, connection counts, no timers/host operations, reference
release/reopen, owner destruction, actual MainWindow close, frame round-trip,
secondary screens, malformed geometry, atomic settings/legacy retention, bounded
move writes and unchanged C5 layout bytes. No added test shows a native window,
resets application style, sleeps, networks or launches a subprocess. G3/profile
blocks, research data/hashes, acceptance scores and all gates/timeouts are unchanged.

GitNexus lane analysis failed with sandbox spawn EPERM. Impact navigation used
the registered main index (21 commits stale), followed by direct source reads;
fresh graph coverage is not claimed. Existing market/isolation/history smokes
hit temp-directory ACL errors and their existing Windows skips inside the
sandbox; the controller ran them outside it and they pass. The new root module is
tracked, so the tracked-root layout test passes. The item is a single C10 commit.
Multi-monitor visual behaviour remains PENDING USER FINAL CONFIRMATION.
## U2-C7: keyboard command palette (2026-10-20)

Entry points: desktop_pages.shortcuts.install_shortcuts owns the unique Ctrl+K
QShortcut and one reusable CommandPalette popup. palette_commands.command_table
is a pure immutable metadata table (ids, literal catalog keys, localized labels,
ASCII aliases, handler names and page rows), with no Qt or provider imports.
The popup is a hidden-by-default window-owned QWidget, never a modal exec loop.
It has no timers, event filters, deferred deletion, recent-command storage or
data/credential/catalog lookup. Child editors hold explicit palette references;
they never discover a shell through parentWidget/window calls.

Invariants: the closed 13-command allow-list contains seven page jumps, existing
refresh_current_page, active-job-only cancel_job, the existing header theme combo
and PrivacyState checkbox, and two focus-only actions. Import/backtest actions
navigate then focus the existing import_data/run_backtest buttons; they never
click a button, invoke a job or replace its confirmation/validation connection.
No instrument command is offered. No order, replay, restore, lock, kill, analysis,
sign-in, provider, quota or walk-forward command is registered. Labels contain
only catalog text, never account/cash/private symbols or research data. Existing
theme/privacy handlers retain their existing settings behavior; the palette
itself persists nothing. Live trading remains permanently disabled.

Keyboard behavior: case-insensitive localized-label/ASCII-alias substring search,
stable empty-query order, disabled idle cancellation with catalog reason, disabled
empty-result row, Up/Down selection, Enter dispatch, explicit filter/list Tab
order, Esc/Ctrl+K close and prior-focus restoration. The popup closes before
dispatch; repeated Enter and absent selections do nothing. All command targets
are resolved again at execution and idle cancellation is rechecked. Missing
optional host targets are omitted, including on a bare SimpleNamespace. Labels
use PlainText; list items use Qt's plain-text delegate and accessible text roles.
Every new control has a catalog accessible name and additive inventory entry.
Ctrl+1..7, F5 and idle/active Esc behavior remain covered by unchanged tests.

Evidence: tests/test_command_palette_c7.py adds cheap offscreen keyboard, pure
table, exact allow-list, delegation counts, disabled/empty/repeated activation,
focus/lifetime, literal markup, privacy and actual-window tests. Actual-window
tests patch the existing button guard to decline and assert zero job starts,
consent dialogs, connection requests, generation, analysis and HTTP transport
entries after every command. They also scan confined settings for sentinels.
No new test calls window.show, QApplication.setStyle, network or subprocesses.
Package modules are included in import, text, stylesheet and layout guards.

No default-page baseline or screenshot fixture is changed; no controller fixture
refresh is required for C7. The widget-name fixture only gains the four new names.
MainWindow/public exports and page classes are unchanged. Protected G3 files,
saved_candidate_pool, gates, thresholds, timeouts, PROJECT_STATE, optimization
plan and ACCEPTANCE scores (230/300) retain empty diffs. The item is a single
commit. Offscreen unit evidence is distinct from real desktop smoke: the sandbox
could not run the smoke modules (temporary-dir ACL errors), and the controller
ran them outside the sandbox where they pass. No visual or real-broker
verification is claimed; the user's final visual check is pending.

Local validation: all 13 C7 tests pass, as do unchanged shortcuts, header C1,
async C4, panel C3, accessibility walk, desktop theme and UI operations/public-name
tests. Catalog, import, hardcoded-text, inline-style and layout checks pass.
Ruff 0.16.10 check and changed-file format --check, Python 3.11 compile and
tools/quality_gate.py (zero findings) pass. Desktop pages' three structural
tests pass; its interaction tests and desktop_ui encounter the sandbox ACL
errors above. GitNexus analyze fails with spawn EPERM; the server has no lane-ui2
index, so direct source inspection/runtime tests supply local navigation evidence.


## U2-C8: bounded notification history and toast center (2026-10-20)

Entry points: desktop_pages.notification_log.NotificationLog is Qt-free and
stores at most 100 immutable entries in a deque (configurable only within
1..200). Id and sequence increase monotonically; eviction removes the oldest
entry first. Terminal identities have an equally bounded duplicate cache.
MainWindow.poll_jobs calls NotificationCenter.record_event immediately after
JobFeedback.accept and before specialized handlers. Compatibility notify_local
calls during that event cannot create a second center entry. JobFeedback retains
its previous behavior for all hosts, including bare namespaces. Tolerant module
helpers begin_event/record_event/end_event are no-ops without a center.

Standalone NotificationCenter owns three reusable Toast QLabel slots. A real
window uses two slots plus its independent legacy banner, limiting visible
notices to three in the existing bottom layout, pushing content instead of
overlaying primary controls. Slots have
NoFocus and WA_ShowWithoutActivating, fixed internal result/close links and
escaped message text. Further events stay in the center only. Ctrl+Shift+D
dismisses all displayed slots independently of job cancellation. Single-shot,
parented 5000 ms timers start when slots become visible; hiding, closing or
window close stops them. Errors never auto-expire. Widgets are hidden/reused;
no deleteLater, parent event filters or timer findChildren loops are introduced.
The existing window-owned _CloseWatcher performs toast shutdown; header timer
and close-watcher ownership are unchanged.

The additive header button shows the model unread count, with a catalog
accessible name. Ctrl+Shift+N also opens the in-layout center. Opening marks
retained entries viewed and resets the badge. Rows show time, catalog kind and
severity, and safe message newest first. Up/Down selects, Enter invokes the
existing _notification_link page mapping, Delete dismisses one entry and Esc
closes the center before the existing job-cancel shortcut can dispatch. The
center also has open, dismiss, clear-all and close buttons. Clearing changes
only in-memory presentation objects and never removes files or event journals.
No history is persisted. Rebuild visits at most maxlen rows.

Privacy boundary: safe_summary calls the unchanged completion_summary using
only structural counts and validated bar counts. Account identifiers, cash,
amounts, hashes, analysis identifiers, replay values and research evaluation
values never enter stored text, even with privacy off. Thus enabling privacy
cannot reveal previously retained values. Paper submit/cancel reports carry an
explicit catalog paper/simulated label. Failed jobs and partial market refresh
failures persist in history and remain unread after toast dismissal. Errors use
ERROR_TABLE.get(code) and the same async.error catalog template as AsyncStatus;
unknown codes fall back to operation_failed. No exception or arbitrary worker
message is stringified. Center compatibility text accepts catalog values;
arbitrary messages fall back to a sanitized operation summary. The historical
numeric synthetic-demo summary remains supported. No retry callback runs on push.
The separate legacy notification label retains the original caller-supplied
presentation wording, HTML escaping, danger/neutral status, result/close links,
notification_timer (5000 ms for non-errors), notification_fade/opacity and
_notification_operation contract. The checkbox retains its previous banner
suppression semantics; the center still records completions and failures.
Bare hosts without labels, timers, fade objects or a QWidget safely no-op for
missing presentation objects. QApplication.alert is called only for QWidget hosts.
Legacy compatibility takes priority over replacing its text with B1 center text.

Evidence: tests/test_notifications_c8.py supplies cheap synthetic/offscreen
model eviction, deduplication, event coverage, focus/modal, timer, dismissal,
keyboard, badge, navigation parity, B1/retry, sentinel negative-control, markup,
privacy, bounded-work, window-layout and close/lifetime tests. An additive
notification_feedback_c8.json golden fixture records unchanged completion and
stop outputs for every pre-existing operation. quantlab/desktop_feedback.py
itself has no diff. Package modules are registered in import-graph/layout and
automatic UI text/stylesheet scans. The widget-name fixture is additive only.

Protected G3 sources, saved_candidate_pool, timeouts, gates, PROJECT_STATE,
optimization plan and ACCEPTANCE scores have empty diffs. No order, cancel,
amend, kill or broker path is introduced. The item is a single feat(desktop)
implementation commit; nothing is pushed, tagged or released by the lane.

Local validation: 14 new tests and unchanged feedback P0, header C1, async C4,
shortcuts, panel C3, accessibility, theme, public-name registry, catalog, import,
text/style, layout and function-length checks pass. Ruff check/changed-file
format, Python 3.11 compile and quality_gate pass. Required terminal/isolation/
history/market/walk-forward smoke and desktop pages/UI modules were attempted
but encountered sandbox temporary-directory WinError 5 ACL failures (and existing
environment skips); the controller reran the real-desktop smoke and the desktop
pages/UI modules outside the sandbox and they pass. GitNexus analyze failed with
spawn EPERM in the sandbox and the MCP server had no lane-ui2 index, so graph
evidence is limited to source reads.

The default header gains a notification button, so tests/fixtures/desktop_pages_before/01_viewport.png
through 07_viewport.png were refreshed in a separate fixture-only commit. Page content and
metrics.json are unchanged by this item (reviewed before refreshing).
No automated visual-quality or real-broker verification is claimed. The user's
final visual check remains pending.

Repair-round evidence: the unchanged test_t16_presentation.py reproduced all
26 missing-center errors, then passed all 15 tests after the repair. Additive
C8 tests cover bare-host notify/close behavior, exact banner message/status,
timer/fade compatibility and the combined visible-notice cap. B4 appearance
(8 tests), shortcuts (2), feedback P0 (7), header C1 (5) and async C4 (7) pass.
Unchanged desktop_ui and desktop_pages runs hit WinError 5 temporary-dir
ACL errors inside the sandbox; the controller's runs outside it pass. A separate disposable metrics-only
capture shows zero differences across all seven pages for visible_text,
button_count, label_char_count, visible_input_count, unlabeled_inputs and
primary_button_count. This is mock/offscreen structural evidence, not visual QA.
The only intended default header addition is the catalog notification button
(`notification_button`, unread badge text from notifications.badge, initially
count zero). The seven viewport PNGs were reviewed and refreshed by the controller
in the fixture-only baseline commit; metrics.json is unchanged.

## U2-C6 — paper account tab counts and simulated P&L distribution

Entry points: PaperPage wires desktop_pages/paper_tabs.build_tabs and calls
refresh_tables from the existing _show_account refresh. quantlab.paper_tab_data is
Qt-free and exports account_counts, working_order, scaled_fractions,
position_rows and event_rows. No execution, broker or network dependency is added.
PaperPage remains below 500 lines; MainWindow and desktop_ui public names are
unchanged. The item is a single feat(desktop) implementation commit; no push, tag
or release is performed by the lane.

The four read-only tables retain existing position/order/fill object names and
add paper_events_results, paper_account_tabs, paper_account_tab_bar and the
positions header name paper_positions_pnl. Paper-only order titles become
label [active/total] after account projection. Accepted, partial, submitting,
cancel_pending and unknown orders are non-terminal; filled, cancelled and
rejected are terminal. Every account order is retained, including incomplete
records, so chart snapshot, table total, account count and order KPI agree.
Missing collections and None are safe. Legacy initial/bare-host table editing
retains the single-count contract until an account is projected. Compare and
results continue using the unchanged bind_tab_count adapter. PaperTable's
resetting flag suppresses intermediate model notifications and emits one
refreshed signal after each set_rows; direct row resets still update counts.
No timer, event filter, deferred deletion or recurring widget discovery is added.

The positions P&L header and basis tooltip explicitly describe simulated,
unrealized P&L before costs. Only existing last_mark_price, FIFO lot prices and
quantities, entry fills' explicit multipliers and order contract identities
are used. A complete single-contract position must match its lots; missing
marks, prices, multipliers, lots or contract matches produce the existing
missing-value placeholder and no bar. Nothing is fetched or inferred from an
unrelated quote. Arithmetic and scaling use Decimal; only pixel widths convert
to float. Fractions are abs(pnl)/max(abs(pnl)), with zero and missing values
handled explicitly. The QStyledItemDelegate paints model-role fractions and
theme-driven semantic up/down colors. There are no widgets per row. SortItem
numeric roles, numeric alignment and monospaced fonts are retained; fractions
travel with their items during sorting. Privacy uses desktop_privacy for
position quantities and P&L display/accessibility/tooltips; bars are not painted
in privacy mode. Tab titles contain record counts, never account IDs or amounts.
Raw CSV/JSON exports and guarded submit/cancel/amend handlers are unchanged.

Events project at most 200 structural journal records from the existing
paper_journal_export.json (input bounded to 4 MiB), supplied account event
metadata, or existing fill events when no journal is available. Only sequence
and allowlisted operation codes are shown. Arbitrary identities, messages,
payloads, secrets and research data never cross into display text. Missing or
oversized exports fall back without broker access. QTableWidget text remains
literal PlainText (including markup characters); no HTML renderer, mutation
action, shortcut or order callback is attached. Existing copy remains available.
Tab/table accessible names, Ctrl+Tab, tab-bar arrows, row navigation and
ElideNone are covered without showing windows in the new tests.

Mock/offscreen evidence: test_paper_tab_data_c6.py tests Qt-free projections,
zero/positive/negative/mixed/equal scaling, missing marks and prices, complete
cost-basis matching and bounded metadata privacy. test_paper_tabs_c6.py tests
fixed-seed accounts with 34 orders/2 working, KPI/chart/table/title consistency,
None refreshes, preserved card and status outputs, sorting, privacy roles,
keyboard navigation, literal markup, read-only actions and lifetime constraints.
34/1000/5000-row resets emit one title update each; 5000 P&L rows create O(1)
QWidgets. These are structural/offscreen checks, not visual-quality evidence.
The unchanged C9, B10, paper-lock, theme, accessibility walk, shortcuts, header,
async status, panel, public-name, catalog, import/layout/style and size tests pass.
The unchanged desktop-pages boundary tests pass. Ruff 0.16.10 check and changed
file format checks, Python 3.11 compile and tools/quality_gate.py pass.

The required terminal/isolation/history/market/walk-forward smoke modules,
test_paper, paper exports and full desktop pages/UI modules hit the documented
sandbox temporary-directory WinError 5 ACL failures (some existing smoke skips
also remain); the controller reran them outside the sandbox and they pass.
GitNexus status reported no lane-local index and analyze failed with spawn EPERM,
so navigation evidence is direct source inspection, without an invented graph result.

G3 sources, saved_candidate_pool profiles, timeouts, gates, PROJECT_STATE,
optimization plan and ACCEPTANCE scores have empty diffs. Existing tests are
unchanged except additive registration checks; no test is removed or weakened.
Widget-name fixture additions are additive. The paper page's visible tab
text/geometry changed, so the controller reviewed the metrics and refreshed
tests/fixtures/desktop_pages_before/metrics.json and 05_full.png in a separate
fixture-only commit (05_viewport.png was already refreshed by the C8 fixture commit). The metadata file
tests/fixtures/desktop_pages_baseline.json is unchanged. No visual quality or
real-broker verification is claimed; the user's final visual check remains pending.


## S-R2 - desktop smoke harness extraction

The offline harness resides in desktop_smoke/__init__.py. desktop.py retains
only parse_args, acquire_instance_lock, prepare_workspace, run_gui, main and the
two production startup helpers. It is 360 lines versus 1290 at 4c72a30. All
fifteen harness definitions, including run_smoke with nested complete_smoke, are
moved intact. Compatibility imports preserve object identity on desktop,
including the workflow's _auth_smoke_dependencies import. Both fresh import
orders succeed. No core-to-desktop dependency or circular import is introduced.
The item is a single refactor commit with a Co-Authored-By trailer.

Preservation evidence: tools/extract_desktop_smoke_r2.py compares full AST
canonical dumps against 4c72a302b833d73ab9caf1c9385dd84210d56b4b, without state
normalization; docs/analysis/r2_ast_preservation.json records identical hashes
for every moved definition and every retained production definition, with no
differences. test_t11_part_b retains SMOKE_DIGEST, HANDLERS_DIGEST,
FINALLY_DIGEST and the body[3:] slice; all three original digest checks pass.
Smoke semantics, report schema, step order, catalog keys and deadlines are
unchanged (global 120 seconds, per-step 40 seconds, Paper 30 seconds). No
widgets, timers, lifetime operations, styles or public desktop_ui names change.

Existing-test path/target changes are limited to:

- test_t11_part_b.py reads run_smoke's AST from desktop_smoke/__init__.py;
  run_gui lifecycle fingerprints still read desktop.py.
- test_desktop_market_smoke.py and test_desktop_walk_forward_smoke.py read
  harness source from desktop_smoke/__init__.py. Every assertIn literal and
  timeout is retained byte-for-byte.
- test_desktop_history_smoke.py and test_desktop_smoke_isolation.py direct
  injected fixture/result assignments to desktop_smoke through __import__.
- test_desktop_walk_forward_smoke.py directs injected checker assignments to
  desktop_smoke; its other injection logic and assertions are unchanged.
- test_desktop_smoke_terminal.py and test_desktop_walk_forward_terminal.py
  assign injected cleanup to both desktop and desktop_smoke. The former keeps
  run_gui's terminal cleanup injection; the latter reaches the moved harness.
  Startup fixture injection in test_desktop_smoke_terminal targets
  desktop_smoke. Original-function reads retain the identical compatibility
  exports.

Registry and packaging changes are additive: test_repo_layout allows exactly one
additional directory, desktop_smoke. test_import_graph includes its Python files
and maps package __init__ to the importable package name. UI-text and inline-
stylesheet scanners include the package. packaging/build_manifest.py adds
desktop_smoke/*.py; test_packaging adds an assertion proving every package
source is inventoried. packaging/markauto.spec still analyzes desktop.py.
test_desktop_smoke_package.py adds cheap identity, injection-global, production
shape/size, evidence-coverage and static freeze-import reachability checks. No
new lint exemption is needed; pyproject.toml remains unchanged.

packaging/payload_inventory.py is unaffected: it recursively inventories actual
frozen output rather than selecting source files.
docs/analysis/t12_payload_inventory.json remains historical T12 comparison
evidence; it is not a rebuilt R2 payload inventory. The frozen-installer build
and its smoke are not part of this change.

The five new regression tests, eleven T11 tests, import graph, text/style scans,
startup timing, icon, UI correctness, dev setup, locked-source lengths and
public UI registry checks pass. Ruff 0.16.10 check and format --check on all
changed Python files, Python 3.11 compileall, both fresh import orders and
quality_gate (0 findings) pass. The exact tracked-layout test enforces the
directory registry including desktop_smoke; its registry assertion is unchanged.

G3 files, saved_candidate_pool.py, desktop_strings.py, PROJECT_STATE, acceptance
scores, baseline PNG/metrics/widget-name fixtures and protected documents have
empty diffs. No baseline refresh is required. Live trading remains permanently
disabled; OOS consumption, irreversible budgets and fail-closed gates are
unchanged.

## S-R7: private stages for desktop composition and rendering

S-R7 is a single refactor-only commit, ordered after S-R2 and before S-R1. The
characterization base and recorded starting HEAD are
`8d84b2617855c624d3d1c275fe6fa61583c85a2a` (S-R2). The five target bodies
at this base match their pre-R2 versions. The base literals were captured by
running those original sources before comparing the extracted implementation.

`mount_pages` delegates to private registration, construction, alias and state
copy stages. Their side effects retain their original order, including the
service update and final signal connections. The comment "Late dispatch
preserves patching and the shell's single background-job slot." stays with the
callback lambdas. Lambdas still look up shell methods when called.

Market construction uses module-private build stages, passing the original
layouts and local widgets between stages. Widget creation, signal wiring, names,
tab order, accessibility metadata and initial values remain identical. Chart
painting passes the local painter, font metrics and coordinate functions between
private stages; it introduces no timer, retained painter, child search, deferred
deletion or long-lived Qt object. Painter stack counts and four synthetic raster
fixtures cover empty, bars, indicator/drawing/result layers and paper order
lines. Native raster hashes are checked on Windows; stack counts and the
synthetic behavior contracts are platform independent.

Snapshot extraction separates settlement validation, FIFO reconciliation,
remaining-lot validation and line construction. Its Decimal context, rejection
sentinels, caught exception types and conservative original-entry price policy
remain intact. The module function, PageHost field and SharedStateBindings alias
remain patchable. Refresh extraction keeps dataset, result, history, candidate
and recovery stages in order, retaining existing error boundaries.

`tests/test_r7_function_lengths.py` checks all five AST spans and every new
stage's private verb-phrase name and 80-line budget. Running its target budget
against the base produces five failures (297, 292, 212, 166 and 148 lines). Its
script entry point emits counts, helper inventories and LF-normalized source
SHA256 values without importing Qt. `tests/test_r7_characterization.py` pins
ordered mount assignments/constructions and callback keys as literals, late
patch dispatch, full-window attributes, public AST names, eight snapshot cases,
four refresh states, downstream call/error behavior, focus metadata and one
independently callable stage per target. The synthetic capture support is in
`tests/r7_characterization.py`; base literals are in
`tests/fixtures/r7_base.json`. The tests use a fixed clock and confined profile,
do not show windows or set application style, and add no subprocess or sleep.
The import-graph and repository-layout tests add only test inventory checks.

Production edits are restricted to desktop_market.py, desktop_charts.py,
desktop_pages/mount.py, desktop_pages/result_layers.py and
desktop_pages/views.py. MainWindow, desktop_ui public names, strings, widget-
name fixture, existing snapshot baselines, G3 sources and
saved_candidate_pool.py are unchanged. No UI text key or acceptance score
changes. Live trading remains permanently disabled; fail-closed gates, one-time
OOS consumption, irreversible budgets, Paper 30-second, smoke 40-second and job
15-minute limits remain unchanged.

The seven-page 1366x768 offscreen capture has byte-identical before/after PNGs
and metrics. No baseline fixture refresh is required. The user's final visual
check remains pending.

### S-R7 AST and source evidence

| Target | Base lines | New lines | Base/new extracted stages | Largest new stage |
| --- | ---: | ---: | ---: | ---: |
| desktop_pages/mount.py | 297 | 12 | 0 / 11 | 70 |
| desktop_market.py | 292 | 41 | 0 / 11 | 57 |
| desktop_charts.py | 212 | 37 | 0 / 5 | 50 |
| desktop_pages/result_layers.py | 166 | 47 | 0 / 5 | 48 |
| desktop_pages/views.py | 148 | 8 | 0 / 5 | 40 |

Stage counts exclude pre-existing nested functions. Source hashes normalize
checkout line endings to LF (the same convention as the locked-source test).

| Changed production source | SHA256 (UTF-8, LF) |
| --- | --- |
| desktop_pages/mount.py | `27e729421f125d88c4acc82f4b52a8459121224eddbbeecef35dcf76e1e2b531` |
| desktop_market.py | `4a40956d487b4fd87b755f71597c8139dfc539117e813db7d296b31c273e8a3d` |
| desktop_charts.py | `4212088a0d7cab416b1c371701bc6f6f64d9db98aedbd844fbafd207b13e1fb5` |
| desktop_pages/result_layers.py | `91ed9b02480db90ba0035e1402914f764f245596d5eb38298b7146a40d3e5ee4` |
| desktop_pages/views.py | `dcaba54b4e3e0304310134ba48c7ca93153ae355015d3bf91f92b1e69efd0bd9` |

### S-R7 before/after page capture hashes

Both captures use the recorded base above and the extracted source hashes above,
respectively. Every row has identical before and after bytes.

| Capture | Before SHA256 = after SHA256 |
| --- | --- |
| 01_full.png | `d145bbd9d63f220ceca18b611410dd2d2106945454eb97beed78d3064d20e5fd` |
| 01_viewport.png | `f3a1fcfac026a008d5ba8586ed1a69daee08c0d71f40c457224620d2abe9d42c` |
| 02_full.png | `1ee8c901d67f93721ddcd6868b777f5e8b673a030b46a26f2f4e532979af2774` |
| 02_viewport.png | `9f35ba1d5366cf0f9f7756ad872012d955088568dc802d5e9cc66493d3af3612` |
| 03_full.png | `a8e8a41297642a9902660e8394bb590e9a64445044820dd29c0208ca5f40817d` |
| 03_viewport.png | `436467e1732bc0af2adaab071bff1da846d541a4cc7d65c6e6e40b95e6f37ca0` |
| 04_full.png | `a135cc17e18eff2680e7d13af6418cbddca1ce3d4880acb53c97ddeaf7bc0bf1` |
| 04_viewport.png | `422e973f13e3795bbe826b7e11ea423036f4d1d9143224d7b792aa89721ae793` |
| 05_full.png | `7267ee0d34523c7681ec8fec4c6123e35349cf601304b25d9a78174233141493` |
| 05_viewport.png | `cb41461f55d78d4ce078de67b5256575dedba11ea904b711266f07cbeec2eb2e` |
| 06_full.png | `15d9d437ff2e4b248fa40cea86f0a2fe53ea34117d876cfadefcbb7267f6f4fe` |
| 06_viewport.png | `2ca64917146f72b6d7a639615740ade715beece21467f6b68fe93649ad721af2` |
| 07_full.png | `447e166fa4aa152dd6d5921cb849e9445fb5d6a668d3a46c08df24d0324f5b92` |
| 07_viewport.png | `ee1380c474cc97d1f53948e964a741052637ec082eb6a4ce80cf8d69a6fbe7eb` |
| metrics.json | `b939266ca7d21be4964d8d90da07181dca1a20e00210fc642b6338e6777c8577` |


### S-R1: page service inventory and stage-1 characterization

R1 delivered a single additive stage-1 item after R2 (`8d84b26`) and R7
(`71c9112`): inventory, characterization, and a typed declaration.
`tests/fixtures/page_services_inventory.json` records the ordered 80 service
entries (66 mount registrations plus 14 MainWindow.page_services entries), 130
shell aliases, 84 state copies with owning pages, consuming HostMethod and
callback-read sites, and 127 statically enumerable test patch sites covering 43
names. The patch-site inventory conservatively includes matching page/helper
receiver assignments as well as shell patches; receiver expressions identify
each site.
`tests/page_services_inventory.py` regenerates it from AST without importing
the application. `python -m tests.page_services_inventory` writes the fixture.
Counts were regenerated from the R7 base and match the 66/130 planning counts.
Mount string-literal registrations remain 66 before and after; all 130 aliases
remain. Injection, callback replacement, and alias removal were not delivered.

The PageServices public member names are listed in the service inventory. The private opt-in
`_page_services` factory extends the existing host module; it is not wired into
MainWindow or page construction. Shell wrappers call getattr at invocation time;
module wrappers reuse MainWindow.page_services' late global lookup. The
ui_operations field retains the original UI_OPERATIONS frozenset identity, and
the private operation-handler mapping retains its keys and function identities.
No desktop_ui import is introduced into desktop_pages. MainWindow remains 378
lines and gains no public names. No dependency or lockfile is added.

`tests/test_page_services_r1.py` checks complete AST inventory equality, ordered
service names and counts, runtime callback key sets and late dispatch. One real
offscreen MainWindow is reused without show/style or event loops. The
actual MainWindow/JobManager single-slot gates are exercised with only process
launch mocked: one start succeeds and the second is refused, with one manager
start and one launcher call in either service ordering. These tests are mock-
launch evidence, not a real worker subprocess claim. The existing desktop walk-
forward terminal, isolation, history and market smoke modules remain the
separate real-subprocess checks.

MainWindow inherits SharedStateBindings: shell assignment to an inventoried
StateField also updates page_state, while the owning page's original widget
attribute remains unchanged. Namespace-only test hosts lack these descriptors;
their mount-time state copies do not follow later shell assignments. Both base
behaviors are characterized, including bars/family, refresh_market/import_data
and method aliases. _busy currently has no page reader; its registered binding
and typed view are characterized explicitly. PageState contains neither the
shell nor a shell-bound method. Existing HostMethod declarations, bindings.py,
mount.py, desktop_ui.py and page bodies retain their behavior and source.

Widget-name and desktop_pages_before fixtures are byte-identical; no baseline
refresh or UI text change is required. G3 sources and saved_candidate_pool.py,
PROJECT_STATE, acceptance scores, all existing consumer tests, and timeout
limits are unchanged. Live trading remains permanently disabled. The import
registry adds only coverage of the host and new test/helper files.

### S-R8: developer research workspace moved into tools

S-R8 is scoped to a single move-only commit. The user's decision was "move, do
not archive". The developer-only workspace is `tools/research_app.py`, outside
the product and installer. Its supported command is `streamlit run
tools/research_app.py`, run from the repository root so `.streamlit/config.toml`
continues to supply server/privacy settings. The conditional script bootstrap
prepends the repository root before importing quantlab; its standard-library sys
import is inside the conditional, preserving the exact eight top-level imports.
All five function definitions are byte-identical to the base, including the
main.body[2] developer notice. Only the module docstring and script-path
bootstrap changed in the moved source.

The UI tests changed only their two paths, maintenance coverage changed only its
source path, the root layout allowlist lost only the old filename, and the Ruff
F401 exemption moved with the source. Live contributor, user, packaging and
example documentation uses the new path. Historical evidence was preserved. The
quality gate selects every tracked Python source for syntax and secret checks;
research=True still applies only to quantlab. No gate change was needed. The
additive test_moved_workspace_keeps_tracked_python_scan_rules injects valid
Streamlit source, invalid syntax and a credential signature through scan and
pins the existing flags and new file label. Existing AppTest assertions, import
and developer-notice pins, packaging exclusions and timeouts are unchanged.

Packaging manifest patterns, PyInstaller data inputs, installer payload lists,
CI definitions, group/shard tools, dependency locks, desktop/core source, G3
sources, saved_candidate_pool.py, snapshot/widget fixtures, PROJECT_STATE and
acceptance scores are unchanged. The moved workspace matches no product manifest
glob or PyInstaller data input. Live trading remains permanently disabled. This
item changes no desktop UI and requires no baseline fixture changes.

Source comparison base: `6bdb88349d16ce25c03122118ef923997e80c86e`. Base source
SHA-256: `4f46f2473d330b6431fe0aef2d2fc54f7067eface793db43bf2147541ad9b2f3`.
Moved source SHA-256:
`5019d8dfe99555aab95b15c2cf6c9109a81104608937b7e5609937c8b03b9247`. Both
compared files use LF; the complete function-definition comparison is exact.
Ruff 0.16.10 check and format --check on the five changed Python files exit 0.
`py -3.11 -m compileall -q quantlab desktop_pages tools tests desktop.py` and
`py -3.11 -m py_compile tools/research_app.py` exit 0.
## F1 - Rejected-import gap diagnosis

F1 adds quantlab/data_gap_report.py and desktop_pages/data_gaps.py. The item is
scoped to a single commit. The report projects only the existing validator's
session_coverage_gaps coordinates: contract_id, trade_date, session, start and
end. It never reads bars, research results, OOS/holdout payloads, filenames,
paths or arbitrary exception strings. It orders by calendar trade_date and
segment start, retains at most 500 rows with a bounded heap, and reports the
remaining count. Malformed, missing and empty quality inputs produce no gaps.
Only B1 ERROR_TABLE codes are accepted; unknown codes use operation_failed.

The import worker applies the existing validate_dataset rejection before any
dataset/calendar store write. This closes the previous raw-import boundary
where invalid quality could be persisted even though downstream validation
rejected it. Validation rules, quality errors and the existing validator's
exception text are unchanged. Validated-dataset imports retain their existing
market-series checks. Accepted data objects, hashes, manifests and serialization
are unchanged. An existing progress packet carries only the bounded gap
projection; worker protocol types, consent paths and terminal failure handling
are unchanged. Old-job packets cannot update the report.

DataPage creates the read-only table and per-contract/day timeline lazily for
rejections with gaps. Success and explicit page reset clear rows, timeline
coordinates and accessible segment text. Starting a new import also clears the
previous report. Table groups list every retained contract. Calendar trade dates
stay YYYY-MM-DD; segment timestamps show explicit Taipei +08:00 time. Painting
uses sorted coordinates, palette colors, hatching and borders; the accessible
name and full textual segment equivalent do not rely on color. All new UI copy
uses literal ui_text keys in a new trailing ZH_TW.update block. The fix explanation
lists re-downloading that day through the existing refresh consent flow,
supplying the missing segment and choosing another range. No fix button, job,
network access, data repair or order-capable call is added.

Only allowlisted structural values reach the new widgets in either privacy
state. Paths, filenames, arbitrary error messages and unrelated OOS/holdout
metadata are omitted in both states. No timer, event filter or deferred deletion
is added. Parent ownership is explicit. No new objectName or desktop_ui public
name is added. UI, style, import-graph and layout inventories cover the new
package modules. Default snapshots, widget-name fixtures, theme stylesheet and
appearance digests are unchanged; no baseline refresh is required.

The eight cheap offscreen tests in test_data_gaps_f1.py cover the October 7
08:46-08:47 Taipei missing-minute fixture, unchanged rejection message,
accepted-object byte serialization, no rejected store writes, shuffled order,
10,000-gap bounds, malformed and unknown-code fallback, contract grouping,
privacy states and unrelated OOS-bearing metadata exclusion, lazy construction,
success/reset clearing, deterministic image rendering and stale-job filtering.
Existing B1 catalogue, B2 paper-lock, public registry, function budgets, catalog,
import, style and layout checks pass, as do the data, desktop-page and real
desktop smoke modules. Offscreen structural checks do not establish visual
quality; the user's final visual check is the authority.

G3 files and saved_candidate_pool, PROJECT_STATE, acceptance scores, default
fixtures and timeout constants have empty diffs. Live trading remains permanently
disabled, fail-closed paths are preserved, and no validation threshold or consent
control is loosened. Existing tests receive only additive inventory assertions.


## F2 - Saved equity and drawdown overlay

F2 is scoped to a single commit. desktop_pages/compare_equity.py adds a native
read-only overlay in the existing collapsed comparison details area, created on
the first saved-result selection. Default page widgets, snapshots and the
widget-name inventory are unchanged. No fixture refresh is required.
SavedResultsTable retains its columns and checkbox adapter; SideBySideTable
content and columns are unchanged.

saved_row projects only saved in-sample dates and equity into a private display
cache during the existing refresh. Selection and deselection read that cache;
painting performs no file access, strategy calculation, provider request or job
start. Explicit non-training partition markers are excluded, and auxiliary
OOS/holdout fields are never projected. Malformed or empty equity yields an
empty placeholder. Non-finite observations are omitted and counted. Decimal
arithmetic computes peak-to-trough drawdown and rebasing before float painting
coordinates.

The two panels share date bounds and ticks. Each series uses its daily closing
observation, rebased to 1.0 at its first observation when positive; the label
states that convention. Dates are aligned without filling missing days. Gap
identities survive reduction. At most eight selected series are displayed with a
cap note; each curve paints at most 2,048 points, prepared outside paintEvent.
Labels and line patterns identify series alongside color. The canvas reuses
desktop_charts' footer layout helper without changing its public behavior.

The accessible name and summary identify the series count and date range. Mouse
and arrow-key readouts report only displayed series on observed dates. Legend
names pass through safe_text and all names, curve geometry and readout values
are concealed in privacy mode. Privacy toggles refresh the new text through the
existing privacy binding. All new copy uses literal ui_text keys in a trailing
ZH_TW.update block. No buttons, timers, animation, drag editing, event filters
or deferred deletion are added. Parent ownership is explicit.

The cheap offscreen test_compare_equity_f2.py covers known drawdown, non-finite
counts, corruption, shared axes, different starts, gaps, rebasing, selection
updates, lazy allocation, privacy states, excluded auxiliary data, the series
cap and 100,000-point reduction. Raising mocks protect the saved-read and engine
boundaries. Import, layout and UI/style inventories include the new module.
Protected engine/provider files, saved_candidate_pool, desktop_ui public names,
gates, timeouts, consent controls, theme, scores and PROJECT_STATE are
unchanged. Live trading remains permanently disabled and no order path is added.
The user's final visual check remains pending.

## F3 - Walk-forward estimates and failure guidance

F3 is scoped to a single commit. The existing evaluation upper-bound count and
duration projection in desktop_pages/wf_wizard.py are reused without changing
quantlab/wf_estimate.py, its conservative factor, planning or validation rules.
The same summary label appears above consent on the final confirmation step and
returns to the preview step when navigating back. The five-step flow and header
remain unchanged. Consent, busy gating and the 15-minute job limit are
unchanged.

The pure failure_hint function projects explanation and action from the sole B1
ERROR_TABLE catalogue, covering every catalogue code. Its advisory wrapper says
possible cause and explicitly states that no automatic retry occurs. Unknown or
missing codes use operation_failed, matching notification history; event codes
take precedence over result codes. Error/failed packets and failed, error or
blocked terminal results display the hint in the existing step message label.
Preview invalidation and a new run clear that label. It has an explicit
accessible name. No widget, button, retry action, job or order path is added.

Hints accept only allowlisted codes, never exception text, result values, paths
or user names. This fixed projection is identical in both privacy states and
excludes auxiliary OOS/holdout data. Literal ui_text keys are appended in a
trailing ZH_TW.update block. Existing widget names, default-page content,
snapshot fixtures, theme, desktop_ui public names and protected sources are
unchanged. Live trading remains permanently disabled.

tests/test_wf_guidance_f3.py covers catalogue completeness and fallback,
notification consistency, privacy states, OOS/holdout exclusion, failure packet
and result handling, clearing, accessibility, 0/1/1000 evaluation arithmetic,
invalid-count fallback and summary placement before consent with busy gating.
Existing test_wf_estimate.py and test_wf_wizard.py retain their assertions. The
user's final visual check remains pending.

## F4 - Background notification coverage audit (PRESENT)

F4 is a single audit-only commit. The existing C8 notification center covers
every desktop start_job operation; no product code, mapping, catalogue or widget
is changed. tests/test_notifications_f4.py derives the operation inventory from
dispatch call sites, including conditional backup operations and the paper
dispatcher, and rejects unresolved dispatch expressions. Its table covers every
operation on success, failure and cancellation, including analysis, walk-
forward, campaign, comparison, paper and manual backup operations.

Automatic backup terminal outcomes reach the existing center through
MainWindow.poll_jobs before AutomaticBackupPanel.handle_job_event updates its
bookkeeping. The audit exercises that shared ingress for success, failure and
cancellation. Market refresh success and partial-provider failure use the same
toast/history path. Failure entries allow only B1 ERROR_TABLE codes; unknown
codes fall back to operation_failed. Cancellation remains informational.

The audit covers duplicate job IDs, begin_event/end_event suppression, generic
unknown-operation fallback, structural safe_summary projection, private payload
and auxiliary OOS/holdout exclusion in both privacy states, notifications while
another page is current, and read-only entry navigation. It also covers unread
badges, the existing local-toggle exceptions for completion/error, the toast
cap, nonmodal presentation, maxlen-100 history, hidden-toast timer inactivity,
hide and close cleanup, and window-owned center shutdown. No test starts a
worker, shows a window, sleeps, accesses the network or changes application
style.

Live trading remains permanently disabled. Order paths, consent controls, fail-
closed validation, gates, timeouts, protected sources, desktop_ui public names,
PROJECT_STATE and acceptance scores are unchanged. Existing tests and default-
page snapshots remain unchanged; no baseline fixture refresh is needed. The
user's final visual check remains pending.

## F5 - Read-only backup metadata and restore preview

F5 is a single commit. The collapsed Settings backup section displays the latest
archive modification time in local time and its stat size in human units. The
new quantlab/backup_inspection.py reader bounds state JSON reads to 64 KiB and
uses archive file metadata only for time and size. Missing, moved, absent or
corrupt state/archive metadata produces an unavailable placeholder. Manual
backup completions supply session metadata; automatic completions refresh the
existing durable last_archive state after scheduler completion.

The new desktop_pages/backup_inspection.py panel provides synchronous read-only
ZIP central-directory inspection before restore. Reads are limited to the
22-byte EOCD and at most 4 MiB of central metadata; member payloads, including
the manifest body, are never opened or decompressed. The summary reports member
count, manifest presence, fixed allowlisted product entry names, suppressed name
count and truncation beyond 50 entries. Arbitrary names and member content never
enter widgets, including credential and OOS/holdout-bearing fixtures. ZIP64,
comments, multidisk, excessive member counts, duplicate names, unsafe paths,
links, encrypted members and malformed central metadata fail closed with the
sole B1 validation_failed code. Preview is structural inspection; full manifest,
CRC and content validation remains in the unchanged restore worker.

Preview performs no writes, extraction, jobs or thread creation. Preview is
optional and purely informational; it does not change restore preconditions,
button enablement or the existing call sequence. Restore retains the existing
restore_confirm consent and default-No danger confirmation. Recovery
restrictions still apply. Dispatch remains ui_backup_restore with the unchanged
path payload. Consent resets after dispatch; path changes and job completion
invalidate previews. The existing automatic scheduling, claim_due, watermark,
gate validation and timeouts are unchanged. Live trading remains permanently
disabled and no order path is added. Protected sources and desktop_ui public
names are unchanged.

Privacy toggles mask time, size, entry names and the selected-path editor. Local
time formatting is an injected presentation helper. All new prose uses literal
ui_text keys in a new trailing ZH_TW.update block. The preview button uses the
existing explicit secondary QPushButton theme rules. Widget names are additive
and sorted; no default-page baseline or theme digest changes.

tests/test_backup_inspection_f5.py covers bounded reads, fixed time formatting,
placeholder fallbacks, traversal and corrupt archives, directory hash equality,
payload-read prohibition, truncation, both privacy states, sensitive-data
exclusion, path/file identity invalidation, consent, unchanged job payload and
completion refresh. Import-graph, layout, UI-string and inline-style inventories
include the modules. The user's final visual check remains pending.

## F6 - Instrument and timeframe chart memory

F6 is a single commit. Market preferences include an additive chart_state v1
container keyed by validated instrument identity and timeframe. Existing global
preferences and legacy settings remain supported. The desktop_chart_memory.py
projection stores only visible start/count, latest-bar anchoring and allowlisted
enabled indicator IDs. It retains at most 200 entries in insertion/update order,
evicts the oldest, bounds each entry, and ignores unknown fields, invalid
identities, unsupported versions and malformed containers without discarding
other settings. Invalid, negative, non-integer, non-finite and excessive ranges
use reset_view; valid ranges clamp to the current bar count. A view ending at
the last bar follows the newest bars; a historical view retains its start. An
untouched first view uses the existing reset_view defaults and needs no stored
override.

Instrument and timeframe transitions capture the outgoing view and restore the
incoming view after series loading, without a refresh job. Explicit indicator
enablement edits remain local to each pair. Indicator parameters remain global;
editing parameters invalidates enabled snapshots for untouched default contexts,
preserving the existing global preference behavior. Explicitly edited and loaded
contexts retain their enabled sets. Restore blocks indicator-control signals. No
data, bars, hashes, manifest, drawing, order-line or annotation payload enters
the preference store or changes through the memory projection.

The workspace and pop-out share view changes in memory. Interaction and painting
perform no settings writes. Instrument/timeframe transitions and main-window
close use the existing atomic settings save path; pop-out close merges view and
frame position in one atomic settings save, with the existing B1 failure
handling. No UI text, widgets, object names, styles or default-page baselines
change. Privacy masking remains in the existing renderers, and unrecognized
settings content, including OOS/holdout-bearing fixture fields, is excluded from
the projection.

tests/test_chart_memory_f6.py covers instrument/timeframe and restart round
trips, default view compatibility, hostile zoom values, clamping, future
versions, identity and indicator filtering, bounded eviction, data-hash
equality, privacy states, annotation/order snapshot preservation, latest-bar
growth, pop-out sharing, save counts and write failure. Module inventories
include the memory helper. Live trading remains permanently disabled; no order
path, job dispatch, consent, gate, threshold, budget, timeout, protected source,
acceptance score or desktop_ui public name changes. The user's final visual
check remains pending.
## Round 3 X-U2: compact explanation controls

The strategy question mark is a deliberate QToolButton carrying the unchanged
ui._strategy_page.text_3 explanation, not residue. No widget is removed and all
help_* object names remain in the unchanged widget-name fixture. The item is a
single implementation commit. Existing help.symbol and help.accessible catalog
keys supply the visible question mark and accessible name; no strings are added.

The help-button factory and its relocation insertion both use left alignment
without a stretch factor. The factory sets a fixed size policy; the existing
accessibility pass retains its nonexpanding Minimum policy. Targeted helpButton
theme rules give these existing controls explicit background, border, hover and
focus rendering and a compact content width. Other tool buttons are unaffected.
The appearance stylesheet digest is re-pinned because the stylesheet changed;
its exact equality assertions are retained.

Offscreen evidence on Windows/PySide6 6.12: the actual strategy explanation
control, polished in MainWindow, has an original sizeHint of 50 x 21 and geometry
(9, 81, 982, 21) in a 1000 x 1800 parent layout. With the compact rules and left
alignment its sizeHint is 33 x 23 and geometry is (9, 81, 33, 23). Geometry was
assigned directly to the parent layout without showing a window. These structural
automation checks claim only "not broken"; visual quality remains the user's
final check.

The new test_help_compact_u2 module checks every page for nonexpanding help
policies, preservation of all help_* names, and nonempty accessible names and
tooltips. Strategy assertions cover the <=40 px hint/geometry bound, zero layout
stretch, left alignment, focus-chain membership, and absence of unnamed or
unexplained question-mark controls. They run with privacy disabled and enabled;
the explanation remains exactly the existing catalog text. No account, position,
amount, evaluation-data text, job action, order path or confirmation is added.
Existing paper_confirm and other consent controls are unchanged. No timers,
event filters, deferred deletion or recurring widget discovery are added.

The unchanged accessibility walk and appearance tests pass. Ruff 0.16.10 check
and format checks, Python 3.11 compileall and tools/quality_gate.py pass, as do
the terminal, isolation, history, market and walk-forward smoke modules.

Default help geometry changes affect strategy, backtest, compare, paper and
settings. Snapshot review is isolated to a separate fixture-only commit for
02_full.png, 02_viewport.png, 03_full.png, 03_viewport.png, 04_full.png,
04_viewport.png, 05_full.png, 05_viewport.png, 07_full.png, 07_viewport.png and
metrics.json under tests/fixtures/desktop_pages_before. No public desktop_ui name or module
is added. G3 sources, saved_candidate_pool, PROJECT_STATE, acceptance scores,
gates, thresholds and timeouts have empty diffs; live trading remains disabled.

## Round 3 X-U1: idle background-job explanation

The item is a single implementation commit. DisabledHint displays the new
literal catalog key job.idle_hint for an idle cancel_job control, without the
prerequisite template. The key is appended in a new trailing ZH_TW.update block;
existing catalog entries retain their values. A running job with cancellation
requested retains job.cancel_notice. Other disabled controls retain their
existing prerequisite wording. The command palette retains palette.unavailable,
which already describes the absence of an active job.

The existing header projections remain header.idle, header.running, header.done
and header.failed. JobProgress retains its running stage label, percentage and
single cancellation request behavior. Eligibility and confirmation controls,
including paper_confirm, are unchanged. Cancel accessibility and tooltips remain
nonempty. The new text contains no account, position, amount or evaluation data;
the same idle statement is checked with privacy enabled and disabled.

The cheap test_idle_hint_u1 module checks the actual MainWindow status/header/
cancel-hint labels, catalog wiring, accessibility, palette availability, running
progress, terminal success/failure, cancellation idempotency, other prerequisite
hints and a SimpleNamespace host without job_progress or job_feedback. It uses
no shown windows, style changes, sleeps, network or worker subprocesses. No new
widget, public desktop_ui name, timer, event filter or deferred deletion is
added. Automation evidence claims only "not broken"; visual quality remains the
user's final check.

The existing header, async-status, public-name, catalog-placeholder, UI-text,
import-graph, repository-layout and function-length checks pass. Ruff 0.16.10 check and changed-file
format checks, Python 3.11 compileall and tools/quality_gate.py pass with zero
gate findings.

The shell-level idle hint changes the seven default-window viewport images:
01_viewport.png through 07_viewport.png under
tests/fixtures/desktop_pages_before. Their visual review belongs to the separate
fixture-only commit. Page content, widget names, full-page baselines and metrics
fixtures are unchanged by this implementation. No new module registration or
stylesheet digest is needed. Protected sources, saved_candidate_pool,
PROJECT_STATE, acceptance scores, gates, thresholds and timeouts retain empty
diffs. Live trading remains disabled; no job-start, order or broker path is
added.

## Round 3 X-U4: descriptive backtest result summary

The item is a single implementation commit. ReportSummaryCard is the first
result widget, before the result selector, chart, KPI cards and fills table,
outside collapsed advanced content. It is hidden until a result exists, adding
no default visible text. The existing BacktestSummaryCard and its detailed text
remain unchanged inside advanced content. The new card displays three reported
fields: net_pnl, max_drawdown and closed_lots (the report's closed trade count),
using the same formatter and privacy adapter as existing KPI cards. Existing
detailed report adapters and raw advanced diagnostics retain their source
semantics. The existing page disclaimer remains visible.

A one-line catalog hint describes the metrics without a verdict. New catalog
entries are appended in a trailing ZH_TW.update block. The Qt-free
quantlab.backtest_summary.warning_keys helper emits sample-short warnings below
MIN_SAMPLE_BARS=30 or MIN_SAMPLE_TRADES=5, and a no-closed-trades warning
exactly when closed_lots is zero. The bar count is the reported equity row
count; no external data is loaded. Empty results, failed loads and failed run
validation clear the summary to a placeholder. Amounts follow privacy toggles
immediately. The summary and labels have accessible names, and exactly one
instance of each summary class is created. Widget-name additions are sorted;
baseline files are unchanged.

The cheap test_backtest_summary_policy_u4 and test_backtest_summary_u4 modules
cover boundaries, placement, exact KPI parity, privacy, empty/failure reset,
catalog neutrality and accessibility without showing windows or starting jobs.
The existing presentation tests, KPI assertions and default-page fixtures retain
their original expectations. Import-graph checks pin the new policy module's
lack of dependencies. No new stylesheet, button, public desktop_ui name, timer,
event filter or deferred deletion is introduced.

Automation evidence claims only "not broken". The user's final visual check
remains pending. Live trading stays disabled; order paths, paper_confirm,
existing confirmations, protected engine/provider files, PROJECT_STATE,
acceptance scores, gates and timeouts are unchanged. No evaluation-data field or
label is added.

## TASK X-U6: stop-new-orders exposure confirmation

The stop-new-orders button and host callback open the same patchable three-
choice confirmation before freezing. The pure `stop_exposure_text` helper in
`desktop_pages/paper.py` lists each nonzero signed snapshot position as symbol,
side and absolute quantity, and sums absolute quantities as gross contract
exposure. It performs no broker calls or currency valuation. Snapshot inspection
uses the existing read-only journal reader; an empty account still prompts. If
journal inspection raises, the dialog uses the cached account snapshot when
available, with the same privacy masking. Without a cached snapshot it displays
fixed catalogue text stating that positions and exposure are unknown, together
with the statement that stopping does not close positions. Inspection failures
never prevent confirmation or expose exception text. Confirm still reaches the
original safety-file freeze path; cancel leaves safety state and replay
unchanged. All new UI text is appended to the desktop string catalogue,
including the explicit
statement that existing positions are not closed. Privacy mode masks quantities
and exposure, and dialog buttons have accessible names with cancel as both the
default and escape action. The lazily created dialog adds no default page
widgets or snapshot baseline changes. Existing theme rules explicitly style the
secondary-role push buttons.

Cancel leaves replay and safety state unchanged. Confirm cancels replay and
calls the original freeze path with the original reason and final status
strings. Observe-only cancels replay, applies the existing broker manual order
lock when a policy exists, and locks the paper page against all paper jobs. It
starts no job and neither grants nor requires paper consent. No close/flatten or
new order path is added; live trading remains disabled. Existing consent checks,
protected sources, budgets, timeouts and gates remain unchanged.

`tests/test_paper_stop_u6.py` covers formatting, empty positions, privacy, safe
default/accessibility, cancel, observe-only, original freeze behavior, unchanged
position quantities and real host callback dispatch. Added regressions exercise
a real corrupt SQLite journal and a reader that raises, checking that the dialog
opens, confirm writes the safety file and clears consent, cancel changes
nothing, and cached account quantities retain privacy masking. The existing
desktop kill
button test supplies only a dialog stub and retains its assertions. The item is
a single commit. Automation evidence claims only "not broken". The user's final
visual check remains pending.

## TASK X-U7: inline error next steps

`desktop_pages/error_guidance.py` owns the common B1-code to next-step
catalog-key mapping and the pure `next_step(code)` lookup. Unknown and unmapped
codes add no text. The existing B1 message remains the prefix; ERROR_TABLE and
existing catalog values are unchanged. New catalog values occupy one trailing
ZH_TW.update block and interpolate the existing catalog page names.

Coverage is explicit: missing/empty data uses `history_file_required`,
`market_data_invalid` or the existing generic `validation_failed`; missing
calendar and session input uses `history_sessions_required`,
`history_session_invalid`, `history_date_invalid`, `history_session_limit` or
`validation_failed`. Invalid parameter ranges, insufficient bars and generic
form validation use `validation_failed`. Provider unavailability uses
`network_disabled`, `operation_failed_plan`, `configuration_blocked` and
`http_transport_failed`. An already-running authorization uses
`authorization_busy`; the existing general job guard uses `validation_failed`.
No new error code or exception-text classification is introduced.

The existing WidgetTools button safe/confirmation flow adds a page-local plain
QLabel on failure and re-raises to the original fixed-message handler. The label
registry belongs to explicitly supplied page state; the button's supplied layout
owns the label. JobFeedback receives that same state to clear guidance on a new
run. Pages never discover the shell through widget ancestry. The label has
wordWrap, objectName and accessibleName. It is lazy and does not add default-
page content. Privacy mode neutralizes its message through the existing privacy
adapter, and exception amounts, account identifiers and paths are never
displayed. Successful retry and a new job clear the text, accessible name and
privacy renderer. AsyncStatus reuses its existing label, appending the same
guidance in error state; JobFeedback retains the failing job's code, resets it
at begin, and read_job projects it without starting work. Loading and empty
states replace the error text. The eager AsyncStatus label name is registered
additively in the sorted widget fixture. Snapshot baselines are unchanged.

`tests/test_error_guidance_u7.py` enumerates every mapped code against B1,
exercises every B1 code and a bogus code through next_step, pins the unchanged
ERROR_TABLE source, patches QMessageBox methods to fail during a real typed form
failure, and covers privacy, reset, job projection, accessibility and
catalog/module registration. Import-graph checks pin the display dependencies.
No new button, stylesheet, timer, event filter, deferred deletion or desktop_ui
public name is introduced. Live trading remains disabled; consent controls,
order paths, protected sources, gates, thresholds and timeouts are unchanged. No
evaluation-period data or label is added. The item is a single commit.
Automation evidence claims only "not broken". The user's final visual check
remains pending.


## TASK X-U3: confirmed synthetic quick start

The onboarding area exposes one accessible quick-start button with catalogue
text and an idle/busy tooltip. Its confirmation defaults to cancel. Only an
explicit affirmative answer starts the chain. The small pure QuickStartChain
sequences the existing ui_demo handler, a built-in default strategy payload, the
existing ui_backtest handler, and navigation to the backtest results. Terminal
events come through the existing notification lifecycle; subsequent work waits
for the existing worker to become idle. Existing cancel_job stops the chain
before its original cancellation path. Failure clears sequencing state and
displays the B1 operation_failed_local message inline. Completion, failure and
cancellation reset the chain for a fresh confirmed run.

The operation adapter confines the two flagged operations to the fixed
synthetic-quick-start directory. Real dataset.json, watchlists, candidate
selection and paper state are not inputs or destinations. The results choice is
labelled SYNTHETIC; confirmation, stage notices and the lazily created results
disclaimer explicitly say synthetic data, not real market data. The existing
summary card and KPI privacy renderers continue to mask demo amounts. No new
text contains financial quantities, account identifiers or positions. The
existing onboarding completion rules remain unchanged. The button uses the
existing explicit secondary-button theme rules; no stylesheet changes. Lazy
results labels are excluded from the widget fixture. The eager button and status
names are additive and sorted. Package discovery scans include both new modules,
and the import-graph test pins the sequencer's lack of dependencies.

The cheap test_quick_start_u3 tests cover consent, busy refusal, recorded
operation order, blocked sockets, each stage failing, cancellation, reset,
worker isolation, results labelling and privacy masking without shown windows,
new threads, sleeps or network. MainWindow and desktop_ui public names are
unchanged. No paper/live navigation, paper job, new broker or order path is
introduced. Existing confirmations, paper consent, protected sources, gates,
thresholds and timeouts are unchanged. Live trading remains disabled. New
strings occupy a trailing catalogue update block. The item is a single commit.
Automation evidence claims only "not broken". The user's final visual check
remains pending.

## TASK X-U9: read-only paper journal timeline

The existing Events tab retains events_table and its widget name and behavior.
Opening Events for the first time creates an adjacent Timeline tab with an
accessible type filter and a read-only time/type/summary table. The lazy widgets
are excluded from the eager widget-name fixture. The timeline tab is visible
only while Events or Timeline is selected. The initial four tabs and
default-page snapshot baselines are unchanged. Keyboard tab order includes the
filter and table. There are no new buttons, stylesheet changes, timers, event
filters or deferred deletions.

The existing paper refresh reads the existing bounded journal export once and
updates both projections. quantlab/paper_tab_data.py provides the pure event_type
mapper and timeline_rows projection. Intent, ACK, fill, reject, reconcile and
lock operations have catalog labels; unknown and legacy rows display as other.
Wrapped event payloads supply only a known type and validated timestamp. Missing
times display a catalog placeholder and sort first; recorded times normalize to
UTC and sort ascending, with journal sequence breaking ties stably. Projection
work is bounded to the last TIMELINE_LIMIT records before sorting. A catalog
indicator reports truncation, and an empty journal has a catalog placeholder.

Filtering only hides display rows and preserves the journal. Timeline summaries
contain only journal sequence; financial values, quantities, account/order IDs,
arbitrary messages and evaluation data never enter timeline text or roles,
including with privacy enabled. The table disables editing and interactive
sorting and has no order actions. Live trading remains disabled, and existing
paper_confirm, confirmations, job controls, protected sources, gates and timeouts
are unchanged. No new order or broker path is introduced. New text uses literal
ui_text keys appended in a trailing desktop_strings.py catalog update.

tests/test_paper_timeline_u9.py covers pure classification, timestamp ordering,
sequence ties, the legacy fixture, malformed rows, empty data, bounded 10k-row
projection and rendering, a read-only journal stub that raises on write, filter
round trips, lazy construction, privacy, refresh and accessibility without shown
windows, sleeps or network. Existing C6 table tests preserve their assertions;
the import-graph test pins the projection's lack of application dependencies.
The item is a single commit. Automation evidence claims only "not broken".
The user's final visual check remains pending.


## TASK X-U8: remember display preferences

Before this item, advanced_sections, window x/y/width/height and market
preferences persisted. Last page and per-family parameters did not persist;
the sidebar had only a maximum width and market splitters used layout hints.
The existing settings store now also holds last_page as a module/class page
identity, family_parameters, sidebar_width and bounded splitter_sizes for the
sidebar and market. Unknown or malformed page identities restore page zero;
reordering pages preserves identity. Old settings load with defaults and saves
preserve unknown settings keys. Corrupt settings load as defaults in the UI;
the store still refuses to overwrite corrupt originals.

The sidebar uses a parent-owned splitter with a 120-to-180 pixel navigation
bound. Numeric splitter hints are clamped to screen bounds and Qt child minima.
Family memory follows family switches and explicit settings saves. Only known
indicator parameters are retained; quantities, monetary amounts, accounts,
credentials, provider options, rules and consent values are excluded. Restored
parameters pass through StrategyForm.build_payload and its existing numeric
and strategy validation before being retained. Invalid family values revert to
defaults. No new financial text or evaluation labels are displayed, including
in privacy mode. Existing disclosure, market, geometry and ChatGPT handling
remain intact. Explicit save uses the existing mechanism without timer writes.
Restoring only changes display state and never starts work or activates actions.
Existing consent and paper confirmations remain required; live trading remains
disabled, with no new broker or order path, timeout or gate change.

The pure quantlab/ui_preferences.py projections have Qt-free unit tests.
desktop_pages/preferences.py owns shell serialization and bounded restoration;
desktop_forms.py owns family validation. tests/test_preferences_u8.py covers
identity reorder/fallback, independent families, invalid values, strict bounds,
privacy allowlists, bare hosts, settings None, corrupt reads and existing
market/disclosure/geometry round trips. Registry tests include the new modules.
The Qt-generated sidebar handle name is registered additively in the sorted
widget-name fixture. No buttons, stylesheet rules or default text are added. The
sidebar handle is the only visible change on a first run: the seven viewport
baselines were refreshed in a separate fixture-only commit (metrics.json is
unchanged). MainWindow gains no public name. The item is a single feature commit.
Automation evidence claims only "not broken". The user's final visual check remains pending.

## TASK X-U10: complete offscreen accessibility walk

The prior walk covered seven hard-coded page positions. CompleteOffscreenWalkTests
in tests/test_accessibility_walk.py now compares the actual mounted page classes
and page count with an explicit coverage set. A deliberately mounted extra page
proves that the guard rejects an omitted page. Settings includes its assistant
panel. The original accessibility tests and shortcut tests retain their assertions.
Default unittest discovery includes the new tests; quantlab.yml runs discovery
with verbose test IDs under its unchanged fifteen-minute limit.

One unshown, offscreen window supplies the audit. Network sockets and job starts
raise if called. Timers are stopped, disclosures are expanded, paper tabs include
the lazy timeline, and the chart pop-out is constructed with visible=False.
The assistant creates a synthetic code fold. The walk covers header privacy,
theme and job state, palette, notification center, market dock controls, replay,
quick start, stop/observe/cancel dialog buttons, next-step guidance, and the
timeline filter. It checks disabled and hidden controls as well as visible ones.
The complete new walk has an asserted ten-second budget; each added test uses
bounded widget operations without show(), setStyle(), sleeps, event-pumping
loops, subprocesses or network. The existing legacy fixture remains separate.

Names are checked against catalog literals and templates, including internal Qt
editors and popup views; missing names list the widget type and object name.
NoFocus exceptions have reasons, and repeated logical names have page-specific
upper bounds and documented context. Composite headers, popup views and editors
belong to their named owner. The assistant completion list intentionally keeps
focus in its input, which handles its arrow keys. DisabledHint controls retain
their names and explanatory tooltip. Privacy-enabled tests check header state,
masked assistant text and masked position exposure.

Tab traversal is navigation -> current page in visual row order -> header/status
actions -> notification and cancel actions when enabled and visible. Read-only
status labels do not add tab stops. QTabWidget's QTabBar focus proxy is traversed
once: adding the proxy owner again formerly moved its subchain and stranded
expanded controls. Every page/tab variant now checks membership, uniqueness and
actual nextInFocusChain order. Coalesced layout callbacks only act while visible;
there is no recurring polling scan or child-owned filter on a parent window.

Audit fixes are limited to accessibility and keyboard presentation:

- Market tables and indicator parameters use catalog names instead of raw IDs;
  Qt tab-scroll buttons use catalog names.
- Lazy timeline popup views, headers and corner selection have catalog names;
  paper tab names remain available after lazy creation and count updates.
- The header job label has a catalog accessible name.
- Mounted buttons accept Enter through their existing click/confirmation path;
  lazy assistant fold buttons retain native Enter behavior. QTest checks Enter
  and Space with callbacks blocked, and separately observes disclosure clicks.
- Escape activates the stop dialog's existing cancel button even before show;
  palette and notification Escape handlers are exercised directly.
- The idle cancel tooltip retains its disabled explanation alongside the
  existing shortcut hint.

New catalog keys occupy one trailing ZH_TW.update block. No widgets, object names,
menus, modules or stylesheet rules are added and the widget-name fixture is
unchanged. The navigation list now takes the first Tab stop, so the selected
navigation row renders in the active selection color: the seven viewport
baselines and the R7 focus-chain characterization were refreshed in two separate
fixture-only commits. MainWindow and desktop_ui public names are unchanged. Paper consent and existing confirmations remain required. Live trading
stays disabled; no order/broker path, protected source, threshold, gate, timeout,
evaluation-data text or acceptance score changes. The item is a single feature
commit plus the two fixture-only commits described above.
Automation evidence claims only "not broken". The user's final visual check remains pending.
## T-R9: local workflow artifact ignore policy

`.gitignore` excludes `lt_*.txt` workflow captures and `nohup.out` in a
commented block; the existing `*.log` rule covers `t2-*.log`. The repository
layout policy lists the same new patterns without adding captures to
`ALLOWED_FILES`. An additive offline regression checks both representative
captures, nohup output, legitimate project/agent paths and the absence of
ignored tracked files. Existing layout assertions are unchanged.

This tracked workspace-policy change touches only `.gitignore`,
`tests/test_repo_layout.py` and this contract. It changes no application
behavior, public names, UI fixtures, frozen sources, safety gates or acceptance
scores. Operational artifact inspection/removal and disposable-worktree
cleanup belong to the controller's separate evidence; this policy does not
claim that those operations occurred.

## T-R4: page identity survives visual reordering

`desktop_pages/palette_commands.py` defines the seven unique page ids and the
documented construction/default-order mappings. `install_onboarding` captures
weak references to the actual stack widgets once before its remove/add reorder;
this includes the scroll-area wrappers around ordinary pages. `page_widget`
returns the widget or `None`; `page_index` resolves its current stack position
and returns `-1` for an unknown or unmounted identity. No global registry owns
windows or widgets. Lightweight hosts installed without onboarding register
their existing default visual order once in `install_shortcuts`.

F5 dispatch compares widget identity in constant time: market refreshes market,
settings reads logs, and other pages refresh views. Ctrl+1 through Ctrl+7 retain
their positional rule: key N selects visual position N after any reorder. Named
palette navigation and import/backtest focus resolve identities at execution
time; `command_palette.py` contains the necessary dispatch/hint integration.
Command ids, label keys, aliases, guards, Esc behavior and shortcut sequences
are unchanged. `Command.row` remains import-compatible for existing consumers.
`WORKFLOW_ORDER` remains `(1, 2, 3, 4, 5, 0, 6)`, with a corrected comment
identifying it as a construction-position compatibility mapping. Default page
widgets, labels, onboarding hints, tooltips and visible UI remain unchanged. No
new application module, object name, UI string, feature or fixture is added.
Import-graph registration adds the exercised modules and three dependency pairs
without removing existing checks. All pre-existing test assertions remain
intact.

`tests/test_page_identity_r4.py` constructs one real offscreen MainWindow without
showing it, stops timers once, and reverses stack/navigation with the onboarding
remove/add path. It checks every identity/index, the unknown-id sentinel,
default widgets/order/hints, all positional shortcuts, named palette and focus
commands, execution after population-before-reorder, and F5 dispatch on all
seven pages. It explicitly checks settings after onboarding and the non-settings
data widget at old index 6. Its two tests pass in approximately 1.3 seconds
without network, sleep, style changes or added skips. Window teardown emits no
Qt warnings.

Regression sensitivity was verified by temporarily substituting only
`git show 4c72a30:desktop_pages/shortcuts.py` and running the real-window test:
exit 1, settings `logs.call_count` was 0 instead of 1, and data at index 6 was 1
instead of 0. Restoring the implementation yields exit 0 for both new tests. The
separate AST regression finds no numeric stack/navigation identity comparison in
`desktop_pages/*.py` or `desktop_ui.py`.

Local evidence uses `QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`, and the
specified shared interpreter at `C:/Users/Mark/Desktop/Mark
auto/.venv/Scripts/python.exe` (the installed runtime reports Python 3.13.11).
Each module ran separately as
`python -m unittest discover -s tests -p <module>`:

| Module/check | Result |
| --- | --- |
| `test_page_identity_r4.py` | 2 passed |
| `test_shortcuts.py` | 2 passed, unchanged |
| `test_command_palette_c7.py` | 13 passed, unchanged |
| `test_onboarding_c2.py` | 7 passed, unchanged |
| `test_t9_onboarding.py` | 4 passed, unchanged |
| `test_ui_operations_registry.py` | 6 passed, unchanged public-name assertion |
| `test_import_graph.py` | 9 passed, additive registry/pairs |
| `test_no_hardcoded_ui_text.py` | 13 passed, unchanged |
| `test_repo_layout.py` | 16 passed, unchanged by R4 |
| `test_function_lengths.py` | 2 passed, unchanged source locks/budgets |
| `test_desktop_pages.py -k PageBoundaryTests` | 3 passed, unchanged class limits/layout boundaries |
| Ruff 0.16.10 `check` | Exit 0 repository-wide |
| Ruff `format --check` changed Python files | Exit 0; repository-wide only unchanged ADR 0006 is flagged |
| `py -3.11 -m compileall -q` all six changed Python files | Exit 0 |
| shared `python tools/quality_gate.py` | Exit 0, zero findings, HEAD `b6e6b2a6a1c6e1ce65bbb80d2fae9ecd955c0f83` |

`git diff 4c72a30 --exit-code` returns 0 for all nine protected sources, the
default snapshot directory, widget-name fixture, PROJECT_STATE, optimization
plan, pyproject, quality gate, workflows and product/AI boundary tests. No
fixture refresh is needed. The baseline/current SHA-256 values below are
identical after UTF-8/newline normalization, matching the existing locked-source
convention:

| Source | SHA-256 |
| --- | --- |
| `quantlab/research.py` | `138a0ee2146a2d63773a3397c12e22ecd5d1577260dcf24cc8f06c7440900804` |
| `quantlab/provider.py` | `c15c043156de1d6bf4679034328789b18d171344b56a85432a1d56d42a4fd79a` |
| `quantlab/core.py` | `303b54b0be6d621c340c00f0ed35ea97aab6076147a4cbd93d1be745dd336d93` |
| `quantlab/strategies.py` | `f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def` |
| `quantlab/backtest.py` | `2dcee78c0c7a7d09c54a0d362b6d0a2be957cf910046d3bd6a89525761da5bb6` |
| `quantlab/data.py` | `bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4` |
| `desktop_chatgpt_auth.py` | `4b9320c7552dd8059d6b59d67562706077845bc22037df1f04a54de552f1a1cf` |
| `desktop_chatgpt_provider.py` | `9ceed8ae5c779ebbab725518a7e8bf785e2122de6c95efa915ba69caa5c4f903` |
| `quantlab/saved_candidate_pool.py` | `0a1020d5151fafd3ee4e37e8d5d4822176baf5563aaf9bbb03c156eeb3bedd43` |

The change set contains only page identity/dispatch, its regression, additive
import-graph checks and this contract. Live trading remains permanently
disabled; order guards, fail-closed validation, data boundaries, irreversible
budgets, timeouts, CI caps and acceptance scores are unchanged.

## T-R5: leaf dependencies remove three reciprocal import paths

`runtime_support` owns `RuntimeSafetyError`, `WindowsAppMutex` and
`WINDOWS_APP_MUTEX`. The mutex class and constant are relocated without logic
changes, and `desktop_runtime` re-exports all three names. The dependency
direction is `runtime_support <- desktop_runtime, desktop_errors,
analysis_recovery_windows`; the leaf imports none of these consumers.
`startup_error_code` uses the shared exception type directly from the leaf.
`configuration <- reporting, __main__` is the configuration dependency direction;
report validation no longer imports the CLI. `__main__` retains its existing
`config_from_json`, `execute` and `main` exports.

All pre-existing public names in the five affected consumer modules and
`desktop_ui` retain their original import paths. The leaf adds only the mutex
class and constant to its public names. The mutex's canonical module is
`quantlab.runtime_support`; its old `quantlab.desktop_runtime` alias resolves
the same class, including old pickle lookups. Recovery and worker entry points
retain their paths. Platform and ctypes module objects remain shared, preserving
existing qualified patch targets. Startup classifications and the B1 error
catalogue retain their existing values and identity.

`tests/test_import_graph.py` adds exactly the three R5 pairs while preserving
all nine existing pairs, including R4's three registrations. Its AST traversal
counts function-local imports. All retained local imports in the affected
modules have adjacent reason comments. Additive regressions cover dependency
direction, re-export identity, pickle resolution, qualified patches and startup
and exception codes; all pre-existing assertions remain intact. No new module,
packaging entry, UI text, widget name or snapshot baseline is introduced. Frozen
G3 sources and saved-candidate producer inputs, live-order guards, validation
rules, budgets, timeouts, quality gates and acceptance scores are unchanged. The
implementation contains only import redirection, the mutex relocation and
explanatory import comments.

## T-R6: partial per-file F401/F841 tightening

This item removes the F401/F841 per-file exceptions for 49 files and resolves 89
findings. The number of exception entries containing either code is 59 at
`4c72a30` and 10 after this stage. R6 remains partial; the remaining
exceptions are explicitly listed below. The pyproject change only deletes or
shortens existing per-file entries. Other codes, including E402 and F811,
remain.
`select`, `exclude`, `extend-exclude`, gate configuration and rule versions are
unchanged. No ignore code, noqa, feature, UI control or application module is
added.

Application imports retain their existing bindings through explicit same-name
re-exports (`import X as X` or `from module import X as X`). The validation tool
also declares `__all__` containing its complete original public-name set,
including the `urllib` package; wildcard imports retain the same names. The
eight original application modules had no `__all__`. Their fresh-interpreter
public-name sets are exactly equal before
and after, and `desktop_ui` has exactly the same public names. All application
import targets, symbol lists and their initialization order are unchanged,
including imports from G3 sources and operation registration dependencies.

Per-name `git grep` and module-reference searches precede import removal. The
consumer audit covers from-imports, module aliases, attribute access, constant
getattr names and dotted string/patch references; none consumes a deleted test
import. Existing imported test helpers remain.
Source reads and runtime identity checks establish the preserved bindings.
`tests/test_desktop_runtime.py:626` imports `WindowsAppMutex` and
`WINDOWS_APP_MUTEX` from their retained compatibility path. Whole-repository
tracked-text searches cover each deleted import name and its importing test
module, including docs, tools, packaging, getattr and dotted patch references.
The terminal-smoke consumers use `process_can_run`, the TLS boundary test uses
`report`, and market consumers use `TWSE`, `ROW` and `NOW`; all remain intact.

The substeps run test files first, followed by leaf services and UI modules.
Each row records a separate Ruff check after removing that file's F401/F841
exceptions, followed by cleanup and another check with zero findings. The exact
removed-exception path list is the table's first column. For tests, 'delete'
means dead imports only; for application modules, 'export' preserves the public
compatibility binding. F841 actions are detailed separately.

| File, in substep order | Findings before / after | Import disposition; unused bindings |
| --- | --- | --- |
| `tests/test_analysis_recovery_integration.py` | 1 / 0 | delete `copy` |
| `tests/test_application_icon.py` | 1 / 0 | delete `QIcon` |
| `tests/test_backtest_presentation.py` | 2 / 0 | delete `ast`, `Path` |
| `tests/test_candidate_presentation.py` | 2 / 0 | delete `copy`, `json` |
| `tests/test_chatgpt_auth.py` | 1 / 0 | F841: `url` |
| `tests/test_chatgpt_research.py` | 2 / 0 | delete `util`, `sys` |
| `tests/test_chatgpt_windows.py` | 2 / 0 | delete `json`, `patch` |
| `tests/test_compare_table.py` | 1 / 0 | delete `PATH_ROLE` |
| `tests/test_data.py` | 1 / 0 | delete `csv` |
| `tests/test_desktop_analysis.py` | 3 / 0 | delete `ValidationError`, `validate_analysis_request`; F841: `p` |
| `tests/test_desktop_chatgpt_integration.py` | 3 / 0 | delete `signal`, `time`; F841: `r` |
| `tests/test_desktop_chatgpt_ui.py` | 3 / 0 | F841: `c`, `c`, `c` |
| `tests/test_desktop_market_integration.py` | 2 / 0 | delete `tempfile`, `timezone` |
| `tests/test_desktop_ui_polish_a.py` | 1 / 0 | delete `page_metrics` |
| `tests/test_desktop_ui_polish_b.py` | 4 / 0 | delete `json`, `tempfile`, `backtest_summary_text`; F841: `root` |
| `tests/test_desktop_walk_forward.py` | 2 / 0 | delete `copy`, `run_walk_forward` |
| `tests/test_help_reachability.py` | 1 / 0 | F841: `folder` |
| `tests/test_market_history.py` | 1 / 0 | delete `market_history` |
| `tests/test_market_history_ui.py` | 2 / 0 | delete `tempfile`, `AppPaths` |
| `tests/test_notice_collector.py` | 1 / 0 | delete `io` |
| `tests/test_paper_replay_policy.py` | 1 / 0 | delete `sqlite3` |
| `tests/test_performance_metrics.py` | 1 / 0 | delete `replace` |
| `tests/test_qt_licenses.py` | 1 / 0 | delete `os` |
| `tests/test_recovery_frozen_smoke.py` | 1 / 0 | delete `copy` |
| `tests/test_saved_candidate_pool.py` | 1 / 0 | delete `FAIL_CLOSED_TRANSPORT_PROFILE_V1` |
| `tests/test_settings_sections.py` | 1 / 0 | delete `re` |
| `tests/test_strategy_tabs.py` | 2 / 0 | delete `Path`; F841: `temporary` |
| `tests/test_t9_onboarding.py` | 1 / 0 | delete `ui_text` |
| `tests/test_test_group.py` | 1 / 0 | delete `copy` |
| `tests/test_token_format_producer_profile.py` | 1 / 0 | delete `hashlib` |
| `tests/test_walk_forward.py` | 1 / 0 | delete `WalkForwardPlan` |
| `tests/test_walk_forward_initialization.py` | 1 / 0 | delete `json` |
| `quantlab/desktop_errors.py` | 3 / 0 | export `ErrorCode`, `ErrorText`, `ERROR_LABELS` |
| `quantlab/market_history.py` | 2 / 0 | export `replace`, `io` |
| `quantlab/paper.py` | 1 / 0 | export `Any` |
| `desktop_recovery_smoke.py` | 1 / 0 | export `Path` |
| `desktop_pages/widgets.py` | 1 / 0 | export `QFileDialog` |
| `desktop_pages/paper.py` | 4 / 0 | export `read_json`, `write_json`, `load_dataset`, `QFileDialog` |
| `desktop_pages/views.py` | 4 / 0 | export `read_json`, `load_dataset`, `load_result`, `result_name` |
| `desktop_market.py` | 2 / 0 | export `MarketValidationError`; F841: `exc` |
| `tests/test_baseline_download.py` | 1 / 0 | delete `json` |
| `tests/test_chatgpt_plan.py` | 4 / 0 | F841: four `tmp_path` bindings; keep `self.tmp_path` evaluation |
| `tests/test_desktop_smoke_terminal.py` | 1 / 0 | delete `subprocess`; preserve subprocess imports inside embedded programs |
| `tests/test_desktop_tls_smoke.py` | 1 / 0 | delete `ast` |
| `tests/test_market.py` | 2 / 0 | delete `MarketBar`, `MarketSeries` |
| `tests/test_real_ai_validation.py` | 1 / 0 | delete `content_hash` |
| `quantlab/__main__.py` | 1 / 0 | export `content_hash` |
| `quantlab/desktop_runtime.py` | 3 / 0 | export `WindowsAppMutex`, `WINDOWS_APP_MUTEX`; retain the function-local `content_hash` alias |
| `tools/validate_real_ai.py` | 8 / 0 | export `urllib`, `config_from_json`, `HTTPTransport`, `load_dataset`, `read_json`, `CompatibleProvider`, `FAMILIES`, `demo_campaign_config` |

The per-file commands use Ruff **0.16.10** at
`C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/ruff.exe`:
`ruff check <file> --output-format json` before cleanup, `ruff check <file>`
after cleanup, `ruff format <file>`, and `ruff format --check <file>`. Tests use
the specified shared interpreter with `QT_QPA_PLATFORM=offscreen` and
`PYTHONUTF8=1`, one module per `python -m unittest discover -s tests -p <file>`.

| F841 site, original source line | Preserved action |
| --- | --- |
| `tests/test_chatgpt_auth.py:266` (`url`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_analysis.py:366` (`p`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_chatgpt_integration.py:150` (`r`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_chatgpt_ui.py:789` (`c`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_chatgpt_ui.py:817` (`c`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_chatgpt_ui.py:826` (`c`) | remove unused assignment target; preserve RHS evaluation as expression |
| `tests/test_desktop_ui_polish_b.py:76` (`root`) | remove unused context-manager binding; enter/exit and context body unchanged |
| `tests/test_help_reachability.py:19` (`folder`) | remove unused context-manager binding; enter/exit and context body unchanged |
| `tests/test_strategy_tabs.py:66` (`temporary`) | remove unused context-manager binding; enter/exit and context body unchanged |
| `desktop_market.py:669` (`exc`) | remove unused exception binding; handler unchanged |
| `tests/test_chatgpt_plan.py:216,238,273,287` (`tmp_path`) | remove only assignment targets; retain each `self.tmp_path` attribute evaluation |

No original assertion, test method, fixture or skip decorator is removed or
weakened. Assertion and decorator expressions remain identical. The only
additive regression is
`tests/test_market_history.py::R6ImportCompatibilityTests`, which checks the
identity of existing import-compatible objects without constructing widgets,
starting services, accessing the network or sleeping. It runs in under one
second. No snapshot/widget-name baseline, objectName or UI text changes.

The application substeps exercise these existing test modules before and after;
their case counts are identical for each substep:

| Application module | Test module | Cases before / after |
| --- | --- | --- |
| `quantlab/desktop_errors.py` | `test_error_catalog_b1.py` | 8 / 8 |
| `quantlab/market_history.py` | `test_market_history.py` | 37 / 37 |
| `quantlab/paper.py` | `test_paper.py` | 59 / 59 |
| `desktop_recovery_smoke.py` | `test_recovery_frozen_smoke.py` | 7 / 7 |
| `desktop_pages/widgets.py` | `test_panel_card_c3.py` | 4 / 4 |
| `desktop_pages/paper.py` | `test_paper_tabs_c6.py` | 11 / 11 |
| `desktop_pages/views.py` | `test_desktop_pages.py` | 14 / 14 |
| `desktop_market.py` | `test_desktop_market.py` | 21 / 21 |

The unchanged registry/public-name tests pass (6 tests); import-graph (11), UI-
text (13), layout (16), function-length (2), and Ruff-configuration (7) checks
pass. The existing page classes and MainWindow retain their size limits. The
compatibility regression passes, and all eleven fresh-interpreter module imports
succeed. The CLI, runtime and validation-tool public-name sets are equal before
and after their additional substeps. Every changed Python file passes Ruff
check, format check and `py -3.11
-m compileall -q <changed files>`. Repository-wide Ruff check exits 0;
repository-wide format check identifies only unchanged ADR 0006.

`C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe tools/quality_gate.py`
passes, reporting **0 findings**, with identical gate configuration.

The following raw working-copy SHA-256 values are equal before and after. Each
protected source also has an empty `git diff 4c72a30`; its normalized content
equals the baseline Git blob. No producer literal or loaded G3 import state
changes.

| Protected source | Raw SHA-256, before = after |
| --- | --- |
| `quantlab/research.py` | `4fb7ca86496192d6871477df2fc177a0bd57d755bcaf896f1f5414b97ea1275e` |
| `quantlab/provider.py` | `b26427d0584d83f1e62bf768c458df9b76eb309ca3cdf930e31bba68bde038ee` |
| `quantlab/core.py` | `61a89a7ac7978fe16fadd0f88c528374d3dc05b562ec01059d424c6ff0ca78c4` |
| `quantlab/strategies.py` | `c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132` |
| `quantlab/backtest.py` | `6295ed2e256cb494b43af550e438583b288f494b07fb86db91ef35f82246d91e` |
| `quantlab/data.py` | `7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb` |
| `quantlab/saved_candidate_pool.py` | `20885d4e7680b34eac83ad902cae0819d30f50d178ff217b7093a0a47fda3c3d` |
| `desktop_chatgpt_auth.py` | `316db25c6d10aac93453d4da68784e09ec9a7270c82b438837339365e90fb15f` |
| `desktop_chatgpt_provider.py` | `71e9e54a5f2bac93aab0036c60bae4655ca3e0b45cf38e4f7999e5eb3b9e045e` |

The following 10 F401/F841 exceptions remain; scope is partial. No exception was
added. Seven files have concurrent-lane ownership, two sources form part of
persisted identities, and the research-app entry belongs to R8.

| Retained file | Existing codes | Reason |
| --- | --- | --- |
| `desktop.py` | `F401` | Structure R2 relocates its smoke harness. |
| `desktop_pages/backtest.py` | `F401` | UX U4 changes this page; UX U3 also edits it. |
| `desktop_pages/compare.py` | `F401` | Feature F2 changes this page. |
| `desktop_pages/data.py` | `F401` | Feature F1 changes this page. |
| `desktop_pages/strategy.py` | `F401` | Feature F3 changes this page. |
| `desktop_pages/wf_wizard.py` | `F841` | Feature F3 changes this wizard. |
| `desktop_ui.py` | `E402`, `F401`, `F841` | Feature F1 changes the shell; UX U3 also edits it. Public names and patch targets stay intact. |
| `quantlab/research_analysis.py` | `F401` | `_implementation()` hashes this source into plan packets; reconciliation rejects an existing plan when that hash changes. Even aliases change persisted-plan validity. |
| `quantlab/walk_forward.py` | `F401` | `SOURCE_FILES` includes this source; its content hash is part of the walk-forward binding and identity. Re-export spelling changes that identity. |
| `tools/research_app.py` | `F401` | Development-only Streamlit workspace moved by R8; its exception is kept. |

The additional compatibility assertions cover the validation tool's retained
imports and the identity of its `urllib` package and `urllib.request` module.
They also pin `__all__` to the complete public-name set. CLI and runtime imports
remain at their original locations, including the documented deferred runtime
import. These substeps use `test_cli.py`, `test_desktop_runtime.py` and
`test_real_ai_validation.py` as the existing application tests. No new module,
UI control, objectName, registration, timer or initialization-order change
exists.

Frozen sources, saved-candidate producer inputs, archives, trader paths,
`tests/fixtures/desktop_pages_before`, `desktop_widget_names.json`, PROJECT_STATE,
the optimization plan, CI caps, quality gates and acceptance scores have empty
diffs for this stage. No fixture refresh is required. Live trading remains
permanently disabled; fail-closed validation, money arithmetic, data boundaries,
irreversible budgets, timeouts and retries are unchanged. No object lifetime,
timer, event-filter or widget-ownership logic changes.

## R3 — semantic desktop catalog keys

The desktop catalog uses English lowercase snake_case semantic identifiers in
the form `scope.function.meaning`, matching
`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}$`. Function names omit leading and
trailing underscores and convert camel case to snake_case. The meaning segment
names the control, displayed concept, validation condition or message purpose.
All non-frozen callers use semantic identifiers; no rendered wording changes.

`tests/fixtures/desktop_text_alias_map.json` captures all **1,323** historical
positional keys and their effective rendered strings from the clean pre-change
catalog at `d96fd4cbce3f127e50a9d7ada0a27729630a8769`. It was generated by importing
that catalog before migration, after comparing its normalized source bytes with
the Git blob. The fixture records the source SHA and SHA-256 and also pins the
non-generic catalog entries and existing uppercase registries. It captures final
values after every update block and appended help patch, including
`keyboard.help`; it is independent of the renamed catalog.

`desktop_strings.TEXT_ALIASES` maps those historical keys directly to **1,269**
semantic catalog keys. Aliases contain identifiers only, never rendered text.
`ui_text(key, locale=None)` performs one additional dictionary lookup before its
existing call-time locale selection and default fallback. No alias chains,
cycles, missing targets or collisions with existing non-generic keys exist.
Unknown keys continue to raise `KeyError`. Locale replacement and partial-locale
fallback apply equally to old and semantic identifiers.

Help-button object names retain their historical identities through a private
reverse view of the alias table. The regression test compares those actual
widgets with the unchanged widget-name fixture; semantic lookup identifiers do
not become new object names.

`tests/fixtures/desktop_text_alias_merges.json` records every many-to-one merge;
only keys with identical final strings share a target. Catalog update ordering
and effective registry content are preserved. The two earlier non-generic API
entries superseded by current UI flows remain explicitly registered in
`RETAINED_CATALOG_KEYS` for compatibility.

`tests/test_desktop_text_aliases.py` checks complete alias coverage, exact string
and UTF-8 byte equality for every historical key, documented identical merges,
single-hop lookup, call-time translation, unknown-key errors, preserved catalog
patches and registries, duplicate dictionary keys, and frozen-caller
compatibility. Its AST scans reject historical literals outside the alias table
and alias tests, reject missing literal lookups, and account for every catalog
key through literal references, aliases, registries or finite documented dynamic
prefix/suffix families tied to their existing consumers. Existing caller-test
edits replace literal identifiers while retaining their asserted text and
behavior. The startup AST fingerprint retains its original expected digest;
an additive, message-equality-checked normalization maps the renamed startup
identifier back to its original handler alias before hashing. No fingerprint
constant or existing assertion changes.

The R3 refactor contains no glossary or wording edits. Live trading remains
permanently disabled. No order path, gate, threshold, retry, irreversible budget,
data boundary or timeout changes: Paper 30 seconds, smoke 40 seconds, and the
15-minute job cap retain their limits. Frozen G3 sources and
`quantlab/saved_candidate_pool.py` retain their bytes. Widget names, page metrics,
PNG snapshots, acceptance scores, PROJECT_STATE and the optimization plan are
unchanged; no baseline fixture refresh is required.

## U11 — context-aware canonical glossary checks

`tests/test_glossary_terms.py` parses the twelve bilingual canonical labels in
`docs/GLOSSARY.md`. A data-driven rule table covers exactly those defined
concepts: Backtest, Paper, Replay, Research eligibility, Paper eligibility, OOS,
Holdout, Consumed guard, Irreversible budget, Strategy artifact, Strategy
revision and Live trading. Semantic catalog-key scopes select the relevant
concept; label keys require a canonical English or Traditional Chinese label.
Action and status messages do not have to repeat a concept name. Variant checks
apply within the declared concept scopes, never as a global synonym ban.

Exact `(key, phrase)` exceptions carry individual reasons for synthetic-account
captions, stable operation-log labels and the walk-forward wizard's forward-fold
caption. The latter describes a forward fold rather than independent OOS
eligibility. Tests require every exception to be exercised and demonstrate its
failure when the exception is removed. No entire key or prefix is exempted.

Synthetic fixtures reject Paper, OOS and eligibility variants, swapped research
and paper eligibility labels, and every declared variant for all twelve terms.
They accept separate Backtest/Paper and research/paper eligibility concepts in
one string, unknown vocabulary and unrelated contexts. Diagnostics identify the
semantic key and canonical term. Checks use deterministic string processing,
without Qt, network access, subprocesses or market datasets.

Independent pre-U11 UTF-8 SHA-256 expectations pin all four catalog messages
mentioning disabled live trading, including complete consent and usage text.
The U11 test/documentation change is separate from the R3 key refactor and
contains no wording fixes. Catalog wording, English quick-start safeguards,
historical-key fixtures, UI baselines and existing tests remain unchanged.
The glossary already defines all twelve required canonical terms; no additional
definition is needed. No baseline fixture refresh is required.

Live trading remains permanently disabled. No order path, consent rule,
fail-closed gate, threshold, consumed guard, irreversible budget, OOS/Holdout
warning or data boundary changes. Paper 30 s, smoke 40 s and the 15-minute job
cap retain their limits. Protected engine/provider sources, saved-candidate
profiles, PROJECT_STATE and acceptance scores remain unchanged.

## A3: shared strict JSON input

`quantlab.strict_json.loads(text)` accepts string JSON documents and rejects
duplicate object keys at every depth, including objects inside arrays. Duplicate
diagnostics name the key. NaN, Infinity and -Infinity constants, malformed JSON,
non-string input and excessive parser recursion raise `ValidationError`.
Valid documents retain standard JSON value semantics and canonical JSON
round trips, including Unicode, large integers and Decimal strings.

`strict_json.read(path, max_bytes)` checks file size before opening or decoding,
then reads at most the byte limit plus one to detect growth. Exact-limit files
are accepted; invalid UTF-8 raises `ValidationError`. `reporting.read_json`
delegates with its unchanged 32 MiB limit and preserves the oversize diagnostic.
The four desktop page consumers use the shared loader; journal display retains
its 4 MiB bound and returns None for invalid input. Validation completes before
form values change. The existing B1 validation message and inline guidance
handle rejection without exposing raw exception values; no catalog text changes.
The user manual documents the newly rejected inputs because this rejection is
visible through existing validation feedback.

The private manual-exchange and agent-tool parsers retain their separate
contracts. `quantlab/data.py:447` is intentionally unchanged as a frozen G3
input. No engine, provider, saved-candidate or walk-forward source changes.
Live trading remains permanently disabled; no order path, timeout, eligibility,
OOS/Holdout boundary, consumed guard or irreversible budget changes.
Default page text, widgets and baseline fixtures remain unchanged.

`tests/test_strict_json_a3.py` covers parser failures, file bounds, reporting
delegation, policy round trips, journal rejection and bare-host inline feedback
with preserved form values. The existing tracked-layout test additionally parses
every tracked JSON fixture. Import-graph tests pin the loader to `quantlab.core`
and add `quantlab.strict_json` to reporting's dependencies.

## A4: fixed report source disclosure

`quantlab.reporting.export_report` writes `SOURCE.txt` beside the six existing
data files in the unchanged content-hash directory and returns its string path
as `files['source']`. The source comes exclusively from
`result.manifest['dataset_manifest']['source_type']`. A mismatched top-level
classification does not override it; `load_result` retains its existing binding
validation and rejects inconsistent results.

Each classification has fixed UTF-8 text, terminated by one LF, with no local
paths or timestamps:

- `synthetic`: 資料來源：合成示範（synthetic）。不是實際行情或成交，數字不代表獲利能力。
- `proxy`: 資料來源：代理資料（proxy）。僅供研究參考，不等同官方行情或實際成交，數字不代表獲利能力。
- `official_local`: 資料來源：本機官方資料（official_local）。行情來源為本機匯入的官方資料；回測成交為模擬，數字不代表獲利能力。

Unknown, missing and non-string source types raise `ValidationError` before
any directory creation or write, preserving existing exports. An existing
`SOURCE.txt` symlink is rejected before report writes. Source text uses atomic
replacement and removes temporary files on failure. Repeated export is
idempotent. CSV/JSON bytes, existing return keys, result hashes, dataset/result
loading and validation retain their contracts. No source disclosure enters the
result payload or eligibility decisions.

`tests/test_report_source_a4.py` pins exact source bytes for all three validated
dataset classifications, nested-source precedence, write-free rejection,
symlink refusal, atomic replacement cleanup, round trips and repeated exports.
It pins the six data-file SHA-256 values and digest recorded from main
`1c65154`. Live trading remains permanently disabled; no order path, G3 source,
saved-candidate profile, walk-forward source, timeout, OOS/Holdout boundary,
consumed guard or irreversible budget changes. Default UI and baseline fixtures
remain unchanged.

The UI-operation golden observation includes the normalized `SOURCE.txt` path
in the `ui_backtest` report dictionary. All other observations and existing
registry assertions retain their values and contracts.
## Lane P A1: persistent stop-new-orders and explicit resume-new-orders

Confirm stop freezes the desktop safety state and sets the existing kill switch
once, then journals `manual_order_lock(active=True)` when the policy and readable
journal are available. Observe cancels replay once and journals the same manual
lock without starting a job or changing consent. Neither action closes positions
or cancels existing orders. An absent policy or unreadable journal never constructs
a broker on the confirmation path; the desktop safety file still records the stop.

The account journal is authoritative. Every `_show_account` synchronizes the page
lock from the snapshot, defaulting missing/empty legacy snapshots to unlocked.
Locked pages disable submit, replay and single-cancel controls and chart amend requests,
while reconciliation and the accessible advanced resume button remain reachable.
The idle transition reapplies the lock after generic action enabling. Rejected
requests use `paper.lock.rejected` and the single B1 error catalogue code
`paper_manual_order_lock`; exception values are never rendered as error text.

The locked job gate permits explicit reconcile-with-snapshot/unlock,
kill/lock-on and A2 cancel-all-pending requests. Resume sends `manual_order_lock=False` with the complete
reference snapshot. The existing handler reconciles before unlocking; unknown
orders and unresolved reconciliation still fail closed. The successful account
result clears the page lock in the same process. Consent is never granted by
stopping, observing or resuming and remains necessary for each submit/replay.

The replay handler refuses a manual lock before constructing or starting replay,
so no cursor or fills advance. Normal batch stops retain the kill-switch-only
behavior and create no manual lock events; subsequent batches need no unlock.
Broker risk, cancel, persistence and replay engine code remain unchanged, including
submit's automatic kill-switch reset. The lock survives that reset and restart.
Live trading remains permanently disabled; money math, qualification, timeouts,
research results and hashes, consumed guards and irreversible budgets are unchanged.

Evidence: `tests/test_paper_stop_a1.py` covers real journals and desktop handlers,
same-process resume, restart display, all five operation gates, batch boundaries,
and a counter-test omitting the lock write that reproduces accepted submission.
`tests/test_paper_stop_u6.py` retains privacy, consent, safety-file and quantity
assertions with the persistent-confirm/reachable-observe behavior.
`tests/test_paper_lock_b2.py` retains backend safety assertions and enumerates both
direct stop lock writes plus the explicit kill/unlock job payloads. This item is
a single commit; protected sources, PROJECT_STATE and acceptance scores are unchanged.


## Lane P A2: cancel-all-pending and retained pending orders

The stop confirmation lists nonterminal pending orders and remaining buy/sell
contracts. It retains its three confirm/observe/cancel actions; stopping keeps
existing orders and positions. Empty or terminal-only snapshots preserve the
original text. Privacy masks quantities and counts; order IDs are never shown.
Malformed order rows cannot interrupt the exposure summary.

The advanced Paper control confirms cancel-all-pending separately, with plain
text, accessible buttons, and Cancel as both default and Escape. Empty snapshots
produce a status message without starting a job. The worker derives targets from
the broker snapshot, excludes filled/cancelled/rejected orders, sorts order IDs,
and uses only prepare, existing broker.cancel, and finish. Client ID lists do not
select targets. Broker APIs and journal reducers remain unchanged.

Each order failure is isolated. The normal account result includes
cancel_all_report with cancelled_order_ids, failed_order_ids and errors keyed by
order ID. Codes come from the single B1 catalogue, never exception text.
Repeated requests use existing cancel idempotency and add no duplicate events.
Cancel-all remains available during manual_order_lock and preserves that lock,
cash, positions and fills. Single cancel and amend retain the A1 lock gate.
Submit and replay remain locked until explicit reconcile-and-resume.

All operation, recovery, log, feedback and notification registries include the
new action. Completion feedback gives cancelled and failed counts, and worker
failure clears the pending chart notice. tests/test_paper_cancel_all_a2.py pins
snapshot authority, deterministic attempts, failure isolation, idempotency,
privacy, confirmation defaults and lock preservation with offline evidence.
Live trading remains permanently disabled. This item is a single commit.
### Lane R — B1: descriptive closed-lot trade structure

`quantlab.trade_statistics.describe` consumes a list or tuple of closed FIFO lot
mappings from `BacktestResult.ledger`, accepting Decimal net P&L and numeric
strings from `load_result`. Invalid shapes, missing/nonfinite/nonnumeric P&L or
malformed exit timestamps raise `ValidationError` (existing `validation_failed`
error code). Exits sort chronologically in UTC, stably for equal timestamps;
absent timestamps retain input order before dated rows. ISO strings and datetime
values are supported. Inputs are never mutated. No reference-project formula or
flow was adapted; this implementation follows the supplied B1 formulas independently.

Counts are integers for nonempty samples. Empty samples have every statistic None
with a nonempty semantic catalog reason; defined values have a None reason.
Every non-count numeric output is exactly Decimal, quantized to eight fractional
digits with ROUND_HALF_UP inside an isolated local context. Expectancy is total
net P&L / all lots (including ties); average loss is positive; payoff is average
win / average loss; win rate is wins / all lots. Largest-win share uses the sum
of positive P&L as denominator. Profit factor uses total wins / absolute total
losses. Ties reset the losing streak. Break-even payoff is losses / wins;
break-even win rate is 1 / (1 + payoff), undefined when ties exist. Missing
winning/losing denominators produce None with reasons, never infinity.

The immutable `THRESHOLDS` table is the single threshold source. Its order is the
flag order. These values are asserted against code by the B1 test. Negative
expectancy, dominance, high-win-rate and drawdown comparisons are strict; small
payoff is strictly below 0.40. Thin margin is the open interval
`0 < payoff - breakeven < 0.25 * breakeven`; exactly 25% is excluded. Long streak
and minimum sample counts are inclusive. Profit factor is strictly between 0
and 1.1 and requires at least 20 lots.

| Code | Constants in table order (including severity) |
| --- | --- |
| negative_expectancy | 0, high |
| single_trade_dominance | 0.50, high |
| small_wins_big_losses | 0.70, 0.40, medium |
| thin_edge_margin | 0, 0.25, medium |
| severe_drawdown | 0.50, high |
| long_losing_streak | 8, medium |
| marginal_profit_factor | 20, 0, 1.1, medium |

`ReportSummaryCard.set_values` accepts an optional ledger separately from metrics.
The trade-structure label is created only on result display and hidden/cleared
when no result exists. Its title states backtest samples with selected parameters,
descriptive only. Catalog text names severities explicitly; the label has an
accessible name. Money uses the existing privacy display adapter. The default
card and page presentation stay unchanged. These are derived display data only:
nothing is written back to results, metrics, manifests, content_hash,
reproducibility_hash or any file. Eligibility, selection, ranking, paper permission,
budgets, timeouts and permanently disabled live trading stay unchanged. No order
path is added. B1 is a single commit of the lane. Evidence:
`tests/test_trade_statistics_b1.py` covers formulas, precision, flag boundaries,
threshold-contract parity, invalid input, ordering, privacy and read-only real
synthetic backtest results. The user's final visual check remains pending.

### Lane R B2: read-only OOS daily-return inference

B2 is a single commit of the lane. `quantlab/significance.py` is a pure stdlib
module, independently implemented without adapting reference-project code or
flow. `merge_oos_daily_returns(state)` accepts the state returned by
`read_walk_forward_state(output_dir)`. It checks the excluded holdout status
before inspecting folds, never accesses a holdout record, and concatenates only
folds whose own status and OOS status are both evaluated, in fold-index order.
Other folds are counted and skipped. At most 20 folds are accepted. Duplicate
indices, missing/non-list/empty daily-return lists, invalid dates, or any date
that does not strictly increase reject the entire merge, without a partial
sample. Missing or non-finite returns invalidate all inference; no row is
discarded or imputed. Fewer than two observations produce None with reasons;
zero variance leaves descriptive moments defined but inference undefined.

`mean_positive_test` reports a one-sided Student t tail using the regularized
incomplete beta continued fraction. The bootstrap shifts the sample to zero
mean and counts resampled means at least as large as the observed mean. Its p
value is count / actual resamples, without add-one correction. The confidence
interval uses the original empirical distribution and linearly interpolated
percentiles at alpha/2 and 1-alpha/2. Repeated-value large samples use exact
multinomial counts via beta order-statistic binomial splitting, with the same
empirical resampling distribution. A private `random.Random(seed)` never changes
global random state. All non-count statistics, including t and CI bounds, are
Decimal with exponent -12, ROUND_HALF_EVEN under an isolated precision context;
float is confined to internal statistical computation. Counts are integers.

| Rule | Fixed value |
| --- | --- |
| Default seed | 20261021 |
| Default resamples / alpha | 5000 / Decimal('0.05') |
| Bootstrap work target | n * actual <= 50,000,000 |
| Reduced-resample floor | 1000; this floor takes precedence for n > 50,000, with a note |
| Requests already under target | unchanged, including requests below 1000 |
| Planning alpha / power | 0.05 / 0.8 only |
| Planning z constants | 1.6449 and 0.8416 |
| Required days | max(30, ceil(((1.6449 + 0.8416) * sd / mean)^2)) |
| Required-days cap | 1,000,000,000; larger estimates are None with a reason |
| Invalid planning moments | mean <= 0 or sd == 0 are None with reasons |

`desktop_walk_forward.oos_statistics_text` builds the catalog-based statistics
block during worker compaction. The compact IPC object includes only bounded
derived display text, never raw daily-return arrays. The existing result panel
displays the precomputed text without recomputing on refresh or paint. Its label
is created only after a result arrives, preserving the default page layout.
The explanation is fixed: 假設沒有優勢時，出現至少這麼好結果的機率。
These are derived display data: nothing is written back to results, metrics,
journals, manifests, content_hash, reproducibility_hash, state_hash or any file.
There is no effect on eligibility, candidate selection, ranking or paper
permission. Frozen sources, OOS consumption, budgets and timeouts remain
unchanged. Live trading remains permanently disabled; no order path is added.

`tests/fixtures/significance_goldens.json` contains literal offline SciPy 1.16.3
one-sided t-test oracles for n=2, 5, 30, 60 and 500, including the generating
script text. `tools/generate_significance_goldens.py` is a development-only
regenerator; neither tests nor product imports SciPy. `tests/test_significance_b2.py`
covers numeric goldens, precision, deterministic bootstrap, the independent
small-case resampling reference, caps, zero variance, missing data, strict date
merging, holdout refusal, bounded compaction and unchanged synthetic journal
bytes and hashes. The user's final visual check remains pending.

### R-B4 — fixed-fold Welch decline display

R-B4 is a single item commit. `quantlab.significance.welch_decline_test(early,
recent)` computes Welch's unequal-variance t statistic as early mean minus recent
mean, with Welch–Satterthwaite degrees of freedom. It reuses B2's `_t_tail` and
regularized incomplete-beta implementation. Nothing was adapted from the reference
project. The fixed decline check uses p(early > recent) < 0.05; the mirrored
increase check uses p(recent > early) < 0.05. Otherwise the classification is
`no_significant_difference`. These are descriptive directional checks, without a
claim of familywise error control or a future-performance guarantee.

| Rule | Fixed value |
| --- | --- |
| Directional significance threshold | p < 0.05 |
| Fold split | sort evaluated fold indices; first floor(k/2) early, remainder recent |
| Minimum | 2 evaluated folds and 2 daily observations per half |
| Precision | Decimal exponent -12, ROUND_HALF_EVEN, isolated context; floats internal only |
| Randomness | none |

`split_oos_daily_returns` first applies B2's complete merge validation, including
strictly increasing disjoint dates and the 20-fold bound. It reads only evaluated
OOS results from the `read_walk_forward_state` shape; holdout payloads are never
read. Invalid input, missing returns, insufficient observations and zero variance
in both halves produce None statistics plus reasons, with no partial result.
The cut has no configurable parameter. One constant half is valid when the other
half has positive variance.

`desktop_walk_forward.oos_statistics_text` adds exactly one catalog-based line
for decline, increase (非未來保證), no detectable difference (不等於沒有變化), or
the reason. It creates no widgets or UI operations. These derived display data
are not written back to results, metrics, journals, manifests or any file and
are excluded from content_hash and reproducibility_hash. They have no effect on
eligibility, selection, ranking, B3 verdict or paper permission. Live trading
remains permanently disabled and no order path is added.

`tests/test_significance_b4.py` covers the offline SciPy 1.16.3 golden, its mirrored
tail and degrees of freedom, deterministic effects, split membership for k=2–5,
shuffled-input invariance, invalid inputs, no mutation, Decimal precision and
the display states. `tools/generate_welch_goldens.py` regenerates the synthetic
fixture; SciPy is development-only and is not a product or test dependency.
The user's final visual check remains pending.

### R-B3 — five display-only OOS verdicts

R-B3 is a single item commit. `quantlab/verdict.py` was independently implemented;
no formula, code or flow was adapted from the reference project. `judge(oos_test,
oos_required, oos_returns, flags)` reads B2's statistics and planning dictionaries,
the validated merged OOS daily-return list and B1-shaped code/severity flags. Its
only output fields are `level`, `display_name`, ordered deterministic `reasons`
and integer-or-None `recommended_observations`. Empty samples return no level or
name and the reason `no evaluated OOS fold`; malformed inputs fail closed to
insufficient. Undefined planning includes its reason instead of an invented count.

| Priority | Condition | Level |
| --- | --- | --- |
| 1 | n < 30, undefined/invalid B2 statistics or invalid return sample | insufficient |
| 2 | mean < 0 | negative_expectancy |
| 3 | either p >= 0.05 | luck_suspected |
| 4 | any high flag, including OOS severe_drawdown | fragile_edge |
| 5 | otherwise | statistical_edge |

`compounded_drawdown` starts equity and its peak at Decimal(1), compounds each
merged evaluated OOS return and takes the maximum `(peak - equity) / peak`,
including the initial peak. It uses an isolated precision-400 Decimal context
without intermediate quantization. The threshold is strictly greater than 0.50;
exactly 0.50 does not trigger. Missing/nonfinite returns and returns below -1
are invalid. A total loss yields drawdown 1. Per-fold drawdown metrics and
external severe_drawdown flags are not substituted for this holdout-free source.
Other high flags are sorted by code; duplicate flags are removed. Medium flags
are sorted notes only for statistical_edge. B2 owns the bootstrap seed, cap and
12-place inference precision; B3 adds no randomness or resampling.

`desktop_walk_forward` renders catalog names and explanations at the top of the
existing OOS statistics block, separately from stage codes. Only
completed runs with evaluated folds receive a level. Failed/interrupted runs
and runs without evaluated folds display reasons without a level. The text
explicitly describes an OOS daily-return statistical conclusion, not trading
permission. No widget, objectName, button, UI operation or default-view layout
was added. B4's line-count assertions were updated for the verdict text.

These are derived display data, computed in memory during worker compaction;
inputs are not mutated. Nothing is written back into results, metrics,
manifests, journals or files, or included in content_hash, experiment_id,
reproducibility_hash or state_hash. There is no effect on eligibility, candidate
selection, ranking, paper permission, start/cancel or run/fold status labels.
Frozen sources, holdout exclusion, OOS consumption, budgets and timeouts remain
unchanged. Live trading remains permanently disabled; no order path was added.
`tests/test_verdict_b3.py` exercises priority overlaps, real B2 synthetic samples,
strict compounded drawdown, malformed inputs, purity, stdlib-only imports,
unchanged state hashes and the real walk-forward selection loop with and without
verdict calls. The user's final visual check remains pending.

## B5 — capital warning-threshold scenarios

`quantlab/capital_scenario.py` provides a stdlib-only, in-memory IID bootstrap.
Each draw is uniform with replacement through a private `random.Random(seed)`.
Daily PnL is initial capital times the drawn daily return; capital does not
compound. A path stops on its first equity strictly below the threshold and
retains the crossing equity. Touching the threshold does not stop a path.
The five final-equity percentiles (5, 25, 50, 75, 95) use type-7 inclusive linear
interpolation at `(paths - 1) * p / 100`. Arithmetic uses an isolated Decimal
precision of 50 and ROUND_HALF_EVEN; output Decimals have 12 fractional places.
Initial capital and threshold are positive finite Decimal values or exact
decimal strings, with threshold strictly below initial capital. Missing,
nonfinite or at-most-minus-one returns reject the entire sample.

Positive integer paths and days have a product cap of 1,000,000, validated
before simulation allocation or control callbacks. Seeds are integers (booleans
are rejected); the UI fixes seed 1729. Cancellation is checked on every draw
and before publication, before the absolute monotonic deadline check, so cancel
wins when both trip. The clock is injectable by replacing the module's
`monotonic` function. Cancelled, timed-out and rejected results contain no
statistics or partial counts. The worker uses a 45-second compute deadline
within the existing job deadline; process cancellation and DeadlineExceeded
also clear the scenario display. Window close uses the existing worker stop
flow without a scenario journal or scenario reconciliation operation.

`desktop_capital_scenario.py` accepts exactly reference, start_equity, threshold,
horizon_days, paths and seed. The reference uses the existing `_folder` guard.
Only `read_walk_forward_state` followed by `merge_oos_daily_returns` supplies
inputs inside the worker. Evaluated OOS folds are concatenated in index order;
skipped folds and final holdout values are excluded. Unconfirmed holdout status,
no evaluated folds or any missing return yields no statistics. Raw daily-return
lists never enter the UI payload or IPC result. The operation is SAFE_OPERATIONS
and has no source-writer, analysis-start or workspace-mutation permission.

The result is derived display data: no result files or journal updates, no
content_hash/state_hash changes, and no effect on eligibility, selection or
paper permission. SQLite's existing read-only reader may create WAL sidecars;
authoritative journal bytes remain identical. The lazy WalkForwardResults
controls appear only for saved results with evaluated folds, keep default page
snapshots unchanged, validate before submission and disable during any job.
Loading another result clears the previous scenario. Results contain only the
breach fraction/count, percentiles, actual paths, input echo and fixed status.
No suggested position sizes or real order paths are provided.

The fixed disclaimer is: 假設每日獨立同分布、不複利、不代表市場預測、不是強制平倉模型.
`tests/test_capital_scenario_b5.py` covers reproducibility, validation, cap,
uniform draws, additive capital, threshold crossing, percentiles, cancellation,
deadlines, read-only journal access, operation registration and lazy UI behavior.
The user's final visual check remains pending.

## Strategy idea research (web search, application-verified)

Operations `ui_idea_research` and `ui_idea_adopt` are registered in both
`UI_OPERATIONS` sets. `ui_idea_research` belongs to no recovery family (like
`ui_chatgpt_usage`); `ui_idea_adopt` is in `SOURCE_WRITERS` because it writes a
campaign through the existing manual path. The research job deadline is
150 s plus the existing 10 s worker margin.

Payload allowlists: `{request, registration, model}` or
`{retry_task_id, consent, registration, model}`; consent must equal
`{"network": true, "plan_usage": true}` on every run and the dialog clears
both boxes after each launch. Registration is a 32-hex opaque reference; the
worker requires `read_account_status == ready` before any request. Adoption
accepts exactly `{task_id, candidate_id, config}`.

Stage 1 is one streamed Responses call reusing `PlanHTTPTransport` by import
(`store:false`, `stream:true`, instructions plus one user message, no system
role, no function tools, no `max_tool_calls`/`temperature`/`max_output_tokens`).
The only tool is `{"type":"web_search"}` with `filters.blocked_domains`
(at most 100, from `quantlab/idea_sources.py`), `user_location`
(approximate, TW, Asia/Taipei) and `include:["web_search_call.action.sources"]`.
The input contains only market, timeframe, family hint and direction text.
The application counts `web_search_call` items and closes the stream on the
seventh item or after 90 s, continuing with what it received
(`stop_reason=search_limit|search_timeout`). The search log is written only
from `web_search_call` events.

Only URLs present in returned sources or `url_citation` are fetched
(`not_in_search_results` otherwise); then the URL policy, at most 2 per site and
8 in total. Unsupported capability, HTTP 400 or a tool-refusal code ends as
`search_unavailable`; the dialog offers the fixed source list or pasted URLs,
never a paid API. Usage-limit codes end as `quota_paused` and persist the
existing account pause.

Stage 2 (`quantlab/web_fetch.py`) fetches with no proxy (any detected system
proxy refuses), no cookies or credentials, `https` port 443 only, no automatic
redirects (at most 3 manual hops, each re-checked), every resolved address and
the connected peer public (checked before any byte is sent), blocked exchange,
broker, bank and payment domains, 2 MiB and 15 s per page (`partial` when cut),
3 concurrent pages, 15,000 characters per page and 60,000 in total, and no
automatic retry. 401/403/407/451, password forms and paywall markers are
`blocked`. Text is sanitized (control/format characters and chat-role markers
removed). Source states are pending, loading, read, partial, failed, blocked or
cancelled, emitted only by the worker. Successful pages are cached for 24 h;
page texts and cache entries are deleted after 7 days or by
「清除研究暫存」. Records store titles, URLs, text SHA-256 and quotes only.

Stage 3 is one tool-free call whose user message is a JSON document with each
source as `untrusted_text`. Stage 4 keeps at most 3 candidates and never pads:
`unknown_source`, `quote_not_found`, `data_unavailable`, `needs_custom_rules`,
`invalid_parameters`, `duplicate_candidate` or `invalid_candidate`. Only the 5
built-in families, `rules={}` and integer parameters within
`registry_json_schema` bounds can be backtestable. Model calls per job are at
most 2; there is no extraction retry. A cancelled job never calls the model again.

Adoption builds a manual exchange v1 response for a single-family config
(`families=[family]`, `max_improvements=0`, `max_trials=1`, other settings
unchanged) and calls the existing `ui_campaign` manual handler; the result then
uses the existing `ui_backtest` candidate path. Adopting the same idea twice
reopens the same content-addressed campaign without rewriting it. Cancelling uses
the existing process-tree stop; the dialog then shows unfinished sources as
cancelled. Results open in the system browser (https only); all web text is
plain text. `tools/validate_web_search.py --model <slug> --i-consent` sends one
request and prints only codes, counts, parameter acceptance and elapsed time;
`--list-models --i-consent` reads only the model catalog (display name and
model value), with no search or inference.
Tests: `tests/test_web_fetch.py`, `tests/test_idea_search.py`,
`tests/test_idea_research.py`, `tests/test_idea_research_ui.py` (T1-T19, offline).
Plan/model availability of web search, usage accounting and the real dialog
remain unverified until the owner runs the documented account checks.

## R1-A: explicit reconciliation of an orphaned ChatGPT reservation

Owner approval (2026-10-22) permits changes only to the G3 files
`desktop_chatgpt_provider.py` and `quantlab/research.py` for PR #76's D1=K1,
D2=two-step recovery, D3=300 seconds and D4=`user_confirmed_consumed` design.
No real account call, OAuth interaction or official usage-page read is part of
implementation or automated verification.

The host-only `inspect_unknown_request` is read-only, does not initialize
controls and exposes only kind, sequence, calls and max_age_ok. Other opaque
registrations never disclose their sequence, count, filename or binding.
`resolve_unknown_request` requires literal True confirmation and the current
integer acknowledgement version. It accepts only the selected registration's
sole K1 owner/binding, a consistent ledger whose final reserved_unknown receipt
is sequence=calls, no other unknown receipt or owner anywhere in the installation,
and a ledger mtime at least 300 seconds old. Time alone never performs recovery.

One global BEGIN IMMEDIATE transaction attaches the existing ledger read/write,
keeps delete journals and FULL synchronous durability, inserts an append-only
plan_resolutions audit row, marks the receipt and campaign blocked state
user_confirmed_consumed, and clears only that registration's owner while setting
its known pause. Schema identity remains version 1. Failures roll back all state;
neither inspection nor refused resolution creates or repairs missing controls.
Calls in both ledgers, request/response digests, request bytes, usage, received
bytes and elapsed time remain unchanged. Audit rows contain only local opaque
identifiers, acknowledgement flags/version, UTC time and implementation hash;
UPDATE and DELETE abort. No remote content or credentials are recorded.

The installation barrier accepts a consumed receipt only with its matching
filename/sequence/request_hash audit, and accepts a consumed account pause only
with that registration's audit. Missing or inconsistent evidence remains pending.
Historical K2 and unknown states are unchanged. Resolution itself never produces
ready: the user must separately invoke existing clear_account_pause, whose
global pending and selected-registration restrictions remain. Original campaigns
stay blocked permanently, even after clearing the installation pause. Research
accepts the new receipt spelling but every non-completed receipt still blocks
selection, OOS, holdout and automatic restart. An in-flight stale completion after
resolution still fails invalid_receipt_transition; no budget is refunded.

The controls remain bootstrap-local, outside workspace backup/restore. Signout,
new registrations, workspace changes, restart and elapsed time never reconcile
anything. UI delivery and its fresh three-part acknowledgement are a separate
dependent PR. Automated evidence is recorded with the PR; live-account behavior
remains unverified. Acceptance scores, PROJECT_STATE, other G3 files, trading
paths and all product deadlines remain unchanged.

The owner additionally approved the narrow saved-candidate compatibility
exception on 2026-10-22: append two frozen producer profiles, their
SUPPORTED_PRODUCERS entries and the exact transport selector member, with
necessary tests; preserve all 19 historical profiles and safety checks.
The new profiles record the changed research source and provider LF/CRLF
descriptor hashes. They do not accept manually consumed receipts as completed
research evidence or reopen the interrupted campaign. Existing unsupported or
mixed provenance tuples remain rejected.

## R1-B: explicit local reconciliation UI

The settings connection panel offers unknown-request inspection only for the
selected active registration while all background work is idle. Both controller
and host dispatch enforce the idle condition. The local inspection/resolution
worker never constructs AuthSession or DPAPIVault, refreshes a token, opens a
browser, or reads official usage. A separate bounded ReconciliationEvent carries
only the local inspection or account-status result, preserving ordinary auth
event serialization and login/model state.

After the inspection worker has joined, a fresh dialog requires all three
acknowledgements: official usage checked, no refund/permanent campaign stop
understood, and no other tool currently sending requests. Cancel is the default;
selection changes, cancellation, closing and background activity invalidate the
dialog. The UI's acknowledged-copy version is fixed at 1 and strictly validated
at request and provider boundaries. No checkbox state is persisted.

Resolution and clear-pause remain separate actions. A successful commit is still
reported as recorded if its subsequent status read fails; status remains unknown
and no recovery is automatically enabled. Other installation-wide known pauses
are preserved. The owner-run web-search diagnostic reports fixed App recovery
guidance for the new known pause and still sends no request while paused.
New strings use literal ui_text keys, and new error messages use the shared B1
catalogue. Only the approved existing unknown-outcome action changes; the other
historical catalogue bytes remain locked. Real-account acceptance is untested.

## R2-A: explicit reconciliation of a uniquely mapped finished-unknown ChatGPT receipt

Owner approval (2026-10-23, PR #83, D0-D10 as recommended) permits changes only to
the G3 file `desktop_chatgpt_provider.py`, one appended saved-candidate SIWC
profile and the listed fixture re-pins. `quantlab/research.py` is unchanged. No
real account call, OAuth interaction or official usage-page read is part of
implementation or automated verification.

A K2 receipt finished in-process with an outcome code from the frozen 40-code set
(the research allowlist minus completed, reserved_unknown, user_confirmed_consumed
and the known pause states). The host-only `inspect_finished_unknown_request` is
read-only, never initializes controls, and exposes only kind, sequence, calls,
max_age_ok and the fixed local outcome code for the selected registration's own
resolvable receipt. Other registrations disclose nothing.
`resolve_finished_unknown_request` requires literal True confirmation, the integer
finished acknowledgement version 1, and the expected sequence, calls and outcome
code shown to the user. It accepts only when existing data maps the receipt to
exactly one registration: the installation barrier is pending; no K1 owner or
reserved_unknown row exists; every other receipt is completed, a known pause or
audited consumed; there is exactly one K2 receipt and it is its ledger's last one
with every earlier receipt completed, blocked equal to its code, a NULL response
hash and unknown usage; exactly one unresolved account row exists, ownerless, with
the same code, and it is the selected registration; the ledger mtime is at least
300 seconds old. Every ambiguous shape is refused with all bytes unchanged.

One global BEGIN IMMEDIATE transaction attaches the ledger read/write, keeps
delete journals and FULL synchronous durability, verifies the exact table SQL and
append-only triggers of plan_finished_resolutions (a permissive pre-created table
is never adopted), inserts one audit row with a digest of the original 8-column
receipt, and changes only the receipt status and that account row's state to
user_confirmed_consumed, each requiring exactly one updated row. plan_budget.blocked
keeps the original code; calls, digests, bytes, usage and elapsed time are
unchanged; nothing is refunded. Failures roll back every database, including a
first CREATE TABLE. Schema identity and the R1 acknowledgement version stay 1.

The barrier and the R1 snapshot accept a consumed receipt only with exactly one
valid, schema-qualified R1 or R2 audit row. An R1 row additionally requires
blocked=user_confirmed_consumed; an R2 row requires its previous status to equal
blocked and its receipt digest to match. Unaudited, torn, tampered or forged
evidence stays pending. Builds without R2 see no R1 audit and stay pending.
Resolution never produces ready; the existing clear_account_pause remains a
separate step, and the original campaign stays blocked permanently. Separately
(D7), _finish records any non-completed code outside the allowlisted set as
failed_or_interrupted.

The appended FINISHED_UNKNOWN_RECONCILIATION_SIWC_PROFILE_V1 differs from the R1
SIWC profile only in its protocol and the provider LF/CRLF source pins. All 21
earlier profiles keep their exact identity, and consumed receipts are never
admitted as completed research evidence. Acceptance scores, PROJECT_STATE, other
G3 files, trading paths and all product deadlines remain unchanged.

## R2-B: explicit local reconciliation UI for finished-unknown receipts

The existing settings panel button, dialog widgets, objectNames, focus order and
idle-host rules are reused; no widget is added. The worker first runs the R1
inspection and consults the R2 finished-unknown inspector only when R1 reports
k2_unresolvable; R2 inspector errors are reported, never swallowed. Neither path
constructs AuthSession or DPAPIVault, refreshes a token, opens a browser or
reads official usage.

ReconciliationEvent accepts the kinds k2_resolvable (counts as for K1) and
k2_other_registration (no details), plus an optional inspection_outcome that is
valid only with k2_resolvable and only from a frozen UI copy of the provider's
40 codes, pinned by a drift test. A resolvable, old-enough K2 opens the same
three-acknowledgement dialog with K2 copy: the outcome code is shown as an
internal code for maintainers, the explanation adds that the request is
recorded as consumed even if it may never have reached the server, and the third
acknowledgement states that the official usage page also counts other tools.
Confirming sends resolve_finished_unknown with acknowledgement version 1 and the
sequence, calls and outcome shown; it never falls back to the R1 action.
ConnectionRequest appends three optional target fields after
acknowledgement_version. Every payload carries them; they are null for every
other action, and the UI and the runtime admission both reject them elsewhere.

Recent, other-registration and unmappable K2 results never open the dialog
and show fixed R2 text. Resolution and clear-pause stay separate. Strings live in
a trailing Lane R2 block; the R1 key chatgpt_reconciliation.k2 became unused and
is removed without rewriting other R1 text. The B1 catalogue adds
finished_request_unmappable and shortens the no_resolvable_unknown_request
action; all other entries keep their bytes. Shared infrastructure failures
without a B1 entry still fall back to the generic plan message, as in R1.
Real-account acceptance is untested.

## Headerless official stream: Content-Type exception

Owner approval (2026-10-23) permits one narrow change to the G3 file
`desktop_chatgpt_provider.py`, one appended saved-candidate SIWC profile and the
necessary fixture re-pins. A diagnostic with the owner's sign-in showed that the
official streamed POST /v1/responses reply carries no Content-Type header while
its body is a valid event stream ending in response.completed. The transport now
reads a POST reply whose Content-Type header is entirely absent as a stream. A
present but different or empty type is still refused, and the GET model catalog
still requires application/json. Every consumer keeps strict SSE parsing, byte,
event and deadline limits, and requires response.completed; a headerless garbage
or incomplete body still records a non-completed receipt. No other check,
budget or timeout changes. STREAM_CONTENT_TYPE_SIWC_PROFILE_V1 differs from the
previous SIWC profile only in its protocol and provider LF/CRLF source pins.

## Idea extraction: bounded shape diagnostics

Owner authorization (2026-10-23) permits minimal content-free diagnostics for
the real TMF / 5-minute / unspecified-direction extraction failure. The same
admission conditions now distinguish extraction_output_missing,
extraction_output_multiple and extraction_output_too_large. These fixed codes
contain no account, credential, request, response text or source content. The
single-text requirement, 262144-byte UTF-8 cap, terminal completion, tool/refusal
rejection, JSON and candidate validation remain unchanged. No automatic retry,
budget refund, deadline increase or production acceptance is implied. Real App
verification and the broader functional checklist are recorded separately in
docs/qa/functional-acceptance-2026-10-23.md.

The real App then confirmed extraction_terminal_missing_event_text: text events
precede a completed response that omits its output. Extraction now retains only
response.output_item.done items in memory. An omitted/empty terminal output may
be reconstructed only after response.completed, with one consistent response ID,
unique bounded item IDs, contiguous bounded output indices and completed message
status. Duplicate/invalid items never supply a fallback; deltas never supply
candidate text. A supplied nonempty terminal output remains authoritative. The
existing one-text, UTF-8 byte cap, tool/refusal rejection, JSON and source/candidate
validation still apply. No raw events are logged or persisted by this adapter.
Offline regression fails on f9aa397 and passes with the adapter. This is not a
claim of successful installer or full-product acceptance.

An additional real App check reported that the selected connection requires an
explicit refresh. AuthError has no code attribute, so the generic research
exception mapper previously hid refresh_required as remote_error. The idea-only
transport adapter now maps that exact fixed AuthError argument to
idea_auth_refresh_required and all other AuthError instances to
idea_auth_unavailable without exposing exception text. Refresh remains an
explicit settings action, never an automatic retry. Existing top-level SSE quota
codes remain untouched. Uncoded failed/incomplete/error stream events and common
HTTP error statuses have bounded fixed diagnostics; they do not grant success or
alter pause/cancellation handling. The original 64-entry error text digest stays
unchanged; only the new entries and source-file pin are appended/re-pinned.

The owner-authorized completed-item adapter also applies inside the pinned
ChatGPTPlanProvider execution path, covering campaigns and analysis without
changing SSEParser. A plan-path offline reproduction fails with missing_output
before this change and passes afterward. Identity checks precede item collection;
the original completed payload, DSL, analysis, usage, pause, budget and deadline
checks still run. Only COMPLETED_ITEMS_SIWC_PROFILE_V1 is appended; all 23 earlier
profiles retain exact identities. Compatibility goldens change exactly nine
digest leaves (five unique identities), with every other leaf preserved.

## Adopted candidate form: immutable parameter display

The owner-requested live acceptance found that an adopted candidate's immutable
reference and backtest were correct while the disabled primary strategy form
still displayed builtin defaults. Initial adoption and disk restoration now load
the verified candidate's parameters into those existing fields and clear absent
optional values. The form remains disabled; the existing immutable reference,
rules, qualification checks, budgets, source profiles and execution path stay
unchanged. Rule-backed candidates retain their complete rules without passing
through the editable form decoder, which still rejects rule-backed payloads.
Offline regressions cover every family, optional-value clearing, unchanged rules,
the existing journal-backed backtest/selection path and disk restoration.

## Rejected close: preserve an active application-header timer

Live cancellation acceptance found that the header's host-close watcher stopped
its clock and job-summary timer even when the user declined closing a busy
window. The header still stops immediately on the close event, preserving the
existing accepted-close contract. A context-owned queued check resumes a
previously active timer only while the host remains visible and is not closing.
An already stopped timer stays stopped; destroyed hosts are tolerated. Worker
polling, cancellation, confirmations, reconciliation and the shared close watcher
used by notifications are unchanged. Offline tests cover an ignored generic
close, an actual busy-window No path, preserved polling, accepted closes and
an intentionally stopped timer. Installed acceptance remains a separate gate.

Idea HTTP diagnostics use letter/underscore fixed codes, matching the unchanged
connection-event boundary, and plain localized labels matching the existing
privacy presentation checks. Neither boundary is relaxed.

## UI redesign: task-focused native desktop workspaces

The UI branch starts at committed 567dbb2 in a separate worktree. No G3 source,
saved-candidate profile, engine, acceptance score, budget, timeout, OOS/holdout or
paper eligibility rule changes. Live trading remains permanently disabled.

The compact header projects the existing job/connection state. Theme and privacy
controls are the same instances hosted in Settings; the clock stays hidden for
compatibility. Navigation uses short captions for data, strategy, results and
paper. Comparison keeps its original page identity and Ctrl+4 shortcut and is
reached from results. No page/controller is duplicated. Onboarding can be closed
and reopened; synthetic quick start is in its help dialog.

Data sources are grouped by local, official/history, download and synthetic.
Required contract fields remain visible; optional standardized-data contract
filtering is explicitly enabled rather than silently applying a hidden month.
Summaries derive from the one loaded dataset. Backtest common fields are moved
from the original BacktestForm, not copied. Research/backtest summaries use the
same JSON-priority payload as execution; invalid JSON clears stale summaries.
Loaded results present metrics/equity first, with execution conditions reopenable.
Report-folder navigation validates the loaded result and workspace containment.

Strategy task selection only changes presentation. Model/consent controls mirror
the one connection panel, retaining build_plan_options, candidate_record and all
validation. Candidate restoration does not navigate; explicit adoption navigates
to backtest. Walk-forward retains its five-step wizard. Idea cancellation/retry
remain accessible from either dialog tab while work is running.

Paper readiness is derived from the selected version, account, existing locks,
replay state and stored policy; it never grants qualification. Stop, observe,
reconcile, resume-new-orders, cancel-all, replay pacing and journal semantics
are unchanged. Busy/paused/locked/quarantined/loss-halt messages remain distinct.
The full stop reason is retained when its KPI uses compact body typography.

Disclosures restore defaults and legacy data/backtest/compare/paper settings
without initial writes. Only user toggles persist; unknown/old keys survive.
Malformed preference containers fall back without repairing the source file.
Hidden buttons have no orphaned prerequisite label. Ctrl+K import reveals the
local source before focusing its existing action. All new catalog entries are
in one explicitly marked Lane block in desktop_strings.py; unused draft keys
are removed and old superseded captions remain explicitly retained.

Preview UI.cmd and tools/ui_redesign_preview.py create a disposable synthetic
workspace and isolate profile/temp paths before runtime import. Network/model
jobs are rejected before worker creation. Update checks and release links are
disabled; the update handler also checks the preview flag. This is a developer
review entry point, not an installer or a replacement for desktop.py.

Evidence: tests/test_ui_redesign_*.py, existing desktop/paper/preferences/keyboard
regressions, and docs/qa/ui-redesign/. No numeric golden is re-recorded. Widget
inventory changes and source-line/consumer inventory changes are documented.

## Windows long paths: local I/O spelling and unchanged storage authority

The owner authorized repairing the Windows long-path failures, necessary G3
storage compatibility and append-only producer profiles. Native reproduction
separates Win32 filename limits from unrelated WinError 5/1314 failures. Ordinary
paths fail SQLite writes or directory creation; extended local-drive filenames
complete those same operations. Path length is counted in UTF-16 code units.
No OS registry, security setting, global Python installation, SQLite DLL or VFS
is changed. See the [Windows filename contract](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)
and [SQLite URI filename rules](https://www.sqlite.org/uri.html).

`windows_paths.native_path` reserves suffix space for long local-drive I/O.
Short path spellings remain unchanged. Traversal, trailing-dot/space and reserved
device components are not promoted into extended paths. UNC and device namespaces
are never converted into local drives. `canonical_path` removes only a local
drive's extended prefix for existing path identity/containment comparisons;
workspace pointers, holdout authority and replay bindings retain their ordinary
identities. Existing drive-type, link/reparse, hard-link, size and source checks
remain before access. Backup destinations inside the workspace remain refused.

`sqlite_uri` percent-encodes an extended filename rather than treating its prefix
as a URI authority. All existing ro/rw/rwc modes, timeouts, transactions, locks,
FULL durability, WAL/runtime checks, interrupted-state handling and one-time
range consumption are retained. No immutable/nolock mode or retry is added.
The adapters cover campaign/holdout, Paper/replay, WFO, saved-source readers,
interpretation/recovery and the existing provider ledger connections/ATTACHes.
History import keeps its external source namespace rejection; only validated
source I/O and managed-cache revalidation use the native local spelling.

Two frozen profiles are appended: LONG_PATH_TRANSPORT_PROFILE_V1 and
LONG_PATH_SIWC_PROFILE_V1. Their protocols and necessary research/provider source
pins change; all 24 historical profiles, result-source variants, dependency
targets and exact-tuple/receipt/source admission checks remain. Only their exact
new transport protocol is added to the existing selector. Existing consumed or
interrupted requests never become completed, and no consumption is refunded.

`--smoke-isolated` requires the existing `--smoke-test` report argument. It skips
original known-folder discovery, workspace pointer and settings reads entirely;
normal startup and the default smoke settings-snapshot behavior are unchanged.
Its disposable startup tree uses an extended spelling so recursive cleanup also
handles long descendants. Reports state `user_state_access=none`; the unchanged
worker-stop verification still precedes cleanup. Tests forbid original-state
reads and writes and require every existing smoke phase. Paper 30 seconds,
smoke-worker 40 seconds and research-job 15 minutes remain unchanged. Source,
CI and installed native evidence remain distinct; synthetic cases do not change
formal acceptance, model verification or permanently disabled live trading.

### Frozen recovery smoke: canonical original-data reference

Installed long-TEMP verification found that the disposable extended local-drive
dataset filename reached `validate_analysis_request` as an external reference.
`desktop_recovery_smoke._prepare_plan` now uses `canonical_path` only when
serializing that already verified synthetic dataset reference. Native file I/O
keeps its extended spelling. The request validator, source identity, admission,
launch commit, original-handle containment and strict stop receipt remain
unchanged. Offline regression exercises a 400-plus-character real filesystem
fixture and control journal; raw extended/device and UNC references still reject.
No provider, credentials, network, budget, deadline or producer profile changes.

## Installed desktop: explain persistent Paper order locks

Prepared-host UI review found that replay, submit and individual cancel actions
correctly remained disabled after an explicit stop and after reopening, but their
generic prerequisite falsely asked the user to wait for background work. Their
visible hint and tooltip now project the existing persistent manual-order lock
and direct the user to the existing explicit resume-new-orders action. A lock
keeps priority even when another job is busy. Unlocking clears the disabled hint.
No enabled state, reconciliation requirement, lock, cancellation, journal, budget
or execution deadline changes. Native-widget regressions cover initial locking,
unlocking and a real reopened journal; the installer must be rechecked on-host.

## Windows atomic promotion under transient sharing contention

Synthetic host probes reproduced intermittent WinError 5 with raw file replace,
independent of application logic and long paths. Shared atomic writes (including
durable promotion) and the WFO JSON snapshot now repeat only the exact same native
rename on Windows errors 5/32/33: at most seven attempts, exponential delays from
1 to 32 ms and a 100 ms retry deadline inside the caller's existing time budget.
No bytes are rewritten and no database commit, research evaluation, admission,
range consumption, quota, cancellation or business operation is replayed.
Permanent denial still raises; no delete-then-rename, partial write, ACL change,
readonly-bit removal or success inference from a missing source is allowed.
Durable Windows promotion retains replace-existing and write-through flags;
non-Windows replacement and directory fsync retain their existing semantics.

Regression covers deterministic transient/persistent errors, deadline expiry,
single fsync, unchanged old bytes on failure and real Windows reader handles
with and without release, for ordinary and durable writes. Existing journal,
tamper, crash, one-time range, risk and golden tests remain authoritative.
Native process tests use the venv's actual base Python and existing dependencies:
the investigated Windows venv redirector has a different PID/handle table from
its Python child. This changes test invocation, not retained-handle authority.
Missing symlink privilege remains an explicit host limitation, never a new skip.
The owner explicitly approved the prepared G3 I/O patch and new exact profiles on
2026-10-24. `research.py` adds one import and replaces its two campaign JSON rename
calls; no other G3 file changes. Its genuine new content hash is
`c6d3f1b4b13154c1bf90e6be5a664ac390edc20fb5c544dd909485dfe5fe2ae6`.
All 26 historical frozen producer blocks remain verbatim. Two appended literal
profiles bind only the new protocol/research source tuple; old results keep their
old identity. Exact selection, mixed-source rejection and ambiguous-tuple rejection
remain fail closed, including genuine current campaign-to-saved-pool admission.
No credential, live-trading path, score or timeout change.
The first UI golden update is the exact `ui_walk_forward_preview.result.source_hashes`
entry for `walk_forward.py`, from `2f9c9b4be41c680f28c907925d6002d7841855c1d2c11bfa5b2a928add93337a`
to `00bb1d7c037dd6f18fd75144d24daea79ea14dda865ad686a28b6b031fb5bb48`,
computed by the existing `content_hash(read_text(...))` producer. No result, risk,
metric, exception or historical producer profile is regenerated or relabelled.
The approved campaign source change additionally updates exactly 25 provenance
hash fields: 14 fixture-campaign identities, 8 subscription-campaign identities,
1 subscription reconciliation binding and 2 WFO research/pool source hashes.
Independent checks recompute both old and new campaign IDs from bindings, attempt
IDs from campaign/sequence, selection/holdout hashes, the raw-source subscription
budget identity and current source hashes before replacing only those exact tokens.
All other golden bytes/annotations, metrics, statuses, exceptions and thresholds
remain unchanged; live legacy-vs-registry equality and exact golden assertions stay.
Reporting JSON and source-notice promotion use the same bounded primitive after
their existing symlink checks and encoding. Host stress reproduced the original
reporting failure on write 20. WFO observers and WAL crash-cut injection follow
the new outer promotion callable; their 33 evaluations, 93 commits/writes/exports,
exact event order, actual process-death cuts and restoration assertions remain.
Research-phase and generic-smoke observers also retain promotion timing through
the new outer call while preserving original Path.replace observation controls.
New campaign regression confirms promotion retries repeat neither commit nor
generation; sustained denial leaves the already-reserved trial committed and no
model call occurs. Existing irreversible-budget, reopen and crash tests remain.
The original locked-source and pre-change golden fingerprints are retained.
The source guard first pins the exact new normalized source SHA-256
`b5a45a55550c362ca2d97add56f299cc99f93d49483c845c2635c475fce27d04`,
then reverses only the one import/two promotion edits and requires the complete
historical `25902491cebcdd71359648cc6eaa0eea685b1082240566d74ada29d9139861d7`.
The golden guard pins the complete new semantic corpus
`56133b5b080c8d355816dd02e7b220c9731d7aeb873005c312919df6022aab54`,
checks the 26 exact old/new hashes in `ui_operations_atomic_provenance_delta.json`,
then restores only those fields in memory and still requires the original
`76028f3e7dab0de0bf62f8cea05097d2160374a0e7e7bd754c2bca4b967c2fa2`.
No original baseline digest is retargeted. The exact reporting import set adds
only runtime_support. The Windows-contention simulation explicitly uses spawn
on all platforms; unsupported process methods remain rejected by production.

## Download then import (2026-10-24)

The download tab defaults to automatic research import, with an explicit TMF
contract and versioned SessionCalendar JSON. The per-call network checkbox covers
both download and import, resets after dispatch and on mode changes; opting out
retains the historical download-only ui_refresh payload. Configuration is checked
before network access. No current month, rollover, holiday, night-session ownership
or missing price is inferred.

The ui_refresh composition downloads through the existing bounded TAIFEX client,
checks every extracted member's SHA-256, path, native columns and resource bounds,
and combines only the chosen TMF contract in chronological archive order. It
retains all raw cache files. The unchanged G3 import_taifex, SessionCalendar,
reject_invalid_import and validate_dataset gates remain authoritative. Combined
input retains the existing 64 MiB / one-million-row bounds; there is no unlimited
multi-file admission. Original archive/member hashes are bound into the resulting
dataset manifest hash. Unsupported archive shapes and duplicate sources fail closed.

Only a fully valid result activates dataset.json and dataset_calendar.json.
Previous bytes are backed up to content-addressed download_import_history before
either replacement. A caught publication failure restores both prior byte streams;
this is not a claim of a process-crash-atomic two-file transaction. Failed downloads,
validation or imports leave prior active research data intact. Successful jobs
refresh the existing dataset summary and strategy navigation and show a human
download/import count. No budgets, OOS gates, risk, timeout, credential, live trading,
G3 sources or historical saved-candidate profiles change. Sitecore is outside scope.

Offline regressions exercise real native-schema ZIP download parsing, two-file
TMF-only import, original quality validation, missing consent/configuration before
HTTP, missing-minute rejection, tamper/duplicate rejection and byte-exact rollback
with retained backup. Desktop checks cover default choice, consent reset, legacy
payload, active-summary refresh and light/dark layouts at 1366x768 and 1920x1080.
The widget guard admits only the six named new controls while preserving its
historical inventory. B1 adds exactly three typed errors; exact new text and the
complete old source/message digests remain asserted.

The associated full desktop regression reproduced Windows access denial at the
backtest report-directory promotion. That single rename now uses the existing
bounded replace_file primitive (unchanged 0.1 s envelope / at most seven attempts).
Only directory publication is retried; computation, serialization, result identity,
existing-target verification and active_result activation retain their order.
Deterministic transient/permanent denial checks require exactly one backtest and
preserve the previous active reference on permanent failure. Native Windows tests
hold a real directory handle without delete sharing, verify rejection while held,
and verify complete publication after release. No timeout, ACL or privilege change.

The complete CI walk additionally distinguishes the two calendar file pickers with
an explicit automatic-import label. The new configuration error uses a descriptive
Chinese contract label, retaining the original fixed-code presentation sanitizer.
Tooltip traversal exercises both automatic import and the historical download-only
consent route. The shared widget list adds exactly six names; a new historical
digest guard removes only those six and still requires the complete old list.
The R7 base, original redesign delta and page-services inventory remain unchanged
and are digest-pinned. A separate reviewed download delta replaces only the one
download caption and adds the six new focus controls / four new refresh controls.
All four loaded-data/report/frozen refresh states require that same exact delta;
chart pixels, eight result snapshots, refresh order and error boundaries retain
their historical assertions. The AST service inventory admits only two test-observer
patch_sensitive flags (contract and run_backtest), existing observer line shifts
and exactly five new observer references. The 80 services, 130 aliases and 84 state
copies retain their identities and order. No full golden regeneration or new
accessibility exception is used.

The full Linux UI job reached its unchanged 15-minute cap after all 3,122 cases
had reported OK; that cancelled job is not accepted as passed. UI execution now
uses the existing whole-module core/research partition on two independent Linux
3.12 runners, each retaining 15 minutes and identical UI/Qt/auth/SQLite locks.
No case is removed and no per-case or production deadline changes. The stable
mandatory `ui` name belongs to an independent genuine-discovery aggregate.
It requires exactly two complete reports, matching source bytes (including both
UI packages, fixtures, locks and workflow), run, attempt, Python and pinned SQLite,
unchanged local identity, original discovery/order/partition and exact started /
stopped case IDs. Missing, duplicate, incomplete, failed or stale work cannot pass.
The five original Streamlit tests must be discovered and executed; their skips
are forbidden. Only the 34 original Linux-inapplicable native Windows skips from
the full run are admitted with exact IDs/reasons. Reports/artifacts are attempt
bound, and the final gate requires both producers and the independent aggregate.
The original Windows core coverage and research worker validators are unchanged.

The following full run's Linux offline 3.12 job also reached 15 minutes near its
last cases, with no completed successful report. This is a failure, not a pass.
Both original Linux offline profiles (3.11/3.12) now use the same whole-module
core/research partition and independent exact coverage under the original
non-Streamlit dependencies. The original mandatory Linux check names belong only
to their complete independent aggregates. The shared validator binds the Python
profile, pinned SQLite and unchanged source/runtime/run/attempt, exact original
discovery/start/stop/order, all original native applicability skips plus the five
original offline Streamlit skips. UI still requires pinned Streamlit and forbids
those five skips; offline evidence cannot substitute for UI. Historical skip
content is hash-pinned. Both producers and both profile aggregates are required
by the final gate; no retries, changed test limits, removed cases or new skips.

Installed-main public-data testing found an observed 2026-10-27 provisional archive
above the intended 2026-10-22 archive. Automatic import now supplies the validated
calendar's explicit trade dates to the downloader before archive selection and
fetching. It rechecks every returned archive date before parsing or activation.
Only observed official URLs matching that supplied scope may be requested; no
weekday, holiday, current-date completion, night-session ownership or rollover is
inferred. All downloads retain their original provisional/unverified classification
until the unchanged full calendar and data-quality validation succeeds. Normal
download-only discovery remains unchanged. The optional internal date set must be
a nonempty frozenset of at most 256 ISO dates, matching the calendar input bound.
No matching archive preserves the previous cache manifest and active research data.
Original file, row, timeout, publication backup and rollback limits are unchanged.

## Unified AI research and multi-market desktop (owner request 2026-10-26)

Normal desktop startup and --platform-v2 compose the same six-workspace window.
The original smoke, TLS and frozen worker dispatch paths retain their behavior.
One ResearchSession owns the original WorkspaceLocator/bootstrap, writer lock,
prepare_workspace recovery, RuntimeGuard, JobManager, settings and MainWindow.
Its original presenter is an embedded Qt widget, not another desktop subprocess.
The v2 engine remains independent and owns its existing typed command boundary.
The embedded settings port preserves the original standalone window geometry
(including absence), rather than publishing child-widget dimensions. All other
explicit business preference changes use the original SettingsStore unchanged.

Research data, AI search/candidates, backtests/comparisons, original paper tools,
assistant and ChatGPT connection settings route inside that same window. The
original controller alone restores the saved login and supplies connection/model
state. Credentials are not copied to the v2 book or handled by a second resolver.
The explicit isolated --research-bootstrap test option never restores a user's
remembered login. Busy original sessions are not stolen, killed or migrated;
failure is visible and the multi-market workspace remains usable for inspection.

Global research cancellation delegates to the original pending/cancel/recovery
gate, never a v2 order action. Closing the outer window first retains its existing
scope confirmation and busy-operation checks, then asks the original research
window to close. A refused or asynchronous research reconciliation retains the
outer window and writer lock. Only original accepted close releases that session.
The original assistant reply process must also stop and join before that lock is
released; an unconfirmed assistant stop refuses close without unlocking.
No timeouts, OOS access, irreversible budgets, AI tool permissions, risk gates,
research evidence or historical producer profiles change. Research candidates do
not auto-deploy or become evidence for another market or holding policy.
Original v1 live prohibition and separate v2 execution-disabled defaults remain.
Sitecore and real financial operations are outside this work.

The executable/source __main__ entry uses desktop.launch: no arguments open the
unified composition, while explicit diagnostic/engine arguments retain dispatch.
The callable desktop.main legacy recovery API remains compatible for existing
integrations; no frozen/test-environment conditional changes behavior. An original
workspace presenter closing itself disables its released research view immediately
and requests outer-shell close through the same guarded lifecycle.

The embedded disabled-action explanations bind explicitly to the original
research host. Missing assistant models have an actionable prerequisite without
changing eligibility. Completed connection jobs clear only stale generic running
captions after confirmed idle/done; failures and pending reconciliation remain.
The developer-only web UI runs its unchanged fixture campaign through the existing
CLI in an admitted, owned process tree. It preserves all trials, budgets and
results, joins failures/timeout descendants, retains unverified stops and refuses
new work. It never becomes a production broker or arbitrary-code interface.
Diagnostic report publication reuses the bounded Windows same-rename helper;
no research, transaction, serialization or budget operation is replayed.

The public launch wrapper lives in the passive root trading_entry module; importing
desktop alone does not initialize IPC or Qt. Keeping this composition entry outside
quantlab/trading preserves existing engine research producer identities. Explicit
embedded hint hosts and missing-model prerequisites apply only to UnifiedResearch;
the standalone v1 characterization remains unchanged. The developer web campaign
adapter loads only inside the user-invoked callback, preserving passive imports.

PyInstaller native dependency analysis temporarily restricts only its process PATH
to the pinned private Python and Windows directories, restoring the original PATH
in finally. This prevents unrelated developer-tool ICU DLLs from shadowing the
Windows ICU API required by Qt. No installed software or user files are removed;
the complete original regression gate and Qt license audit remain mandatory.
The build input manifest explicitly hashes the passive trading_entry source.

### Unified installer lifecycle compatibility

The historical v1 installer lifecycle and supervisor scripts retain their original
byte-pinned guards. The separate unified lifecycle preserves those install, smoke,
active-app refusal, uninstall and sentinel assertions, adding only the new explicit
empty-LOCAL engine shutdown and interface-close interaction. Its complete close
flow, including owned descendants exiting, shares the original 15-second budget.
Unknown contexts, nonzero positions/orders, unverified stopped state, ambiguous
controls, changed creation identity or failed cleanup still fail acceptance.
Dialog discovery enumerates only the retained process's GUI thread and native
owner chain. The test never searches the desktop, adopts PIDs or bypasses modals.
The existing v1 entry remains available; unified clean-kit assembly requires exact
candidate hashes for the variant and its extension and records the entry alias.
Native UI fixtures compile/run only on ephemeral CI; actual user-host UI inspection
continues through the approved computer-use interface. No personal-host uninstall
or acceptance-helper compilation is introduced.

Native close observation uses one bounded UI Automation property-cache snapshot
instead of per-property cross-process enumeration. All descendant PIDs are checked,
creation ownership and the original deadline remain checked throughout, and the
selected live control is revalidated before mutation. Snapshot caching does not
relax the 512-element cap, exact dialog scope or 15-second total close-and-drain
budget. The ephemeral CI owned-window fixture exercises the production collector
against at least 128 real native controls; it is not a personal-host UI action.

Accessible list selection is a presentation navigation event: exactly one selected
workspace synchronizes its current row and visible page, including a return from
an embedded research view. It never emits a financial command or replaces the
research session. Native source-Qt qualification runs early only in ephemeral CI,
with explicit private trading/research roots and login restoration disabled by
that bootstrap. It uses the same owned-process close fixture and original
15-second close-and-drain limit. This source-only result cannot replace frozen
installer, upgrade, uninstall, recovery or clean-client acceptance. Personal-host
invocations refuse before runtime/GUI loading; no host UIA action is introduced.

An owned confirmation must be visible; a hidden retired window with the same title
cannot qualify. After a single asynchronous confirmation press, the fixture waits
for that exact visible dialog to disappear before the next action. An unexpected
replacement fails; interface-process exit still requires the final original zero
exit-code and owned-descendant-drain assertions. The cached scope snapshot is
validated only while its exact native visible dialog identity remains current.
No action is blindly repeated, and all waits share the original 15-second limit.

View-only context selection has an immutable ContextNavigationRequest and its own
ContextNavigationPort. Its source context and generation, configured target mode
and account, pending-mutation exclusion, atomic selection and persisted registry
remain authoritative. It cannot change book contents, connect a broker, grant
qualification, move funds or replay commands. The legacy version-bound switch
command and every financial command retain their original admission. A priority
stop during opening cancels selection through the same epoch fence. Unknown
selection outcomes are not automatically repeated. V2 producer identity continues
to cover the changed Application files; no historical identity is relabeled.
After the final validated interface confirmation, process zero exit and owned
subtree quiescence are authoritative; no live-window query races that expected
window destruction. Intermediate modal closure is still explicitly observed.


### Unified integration: owned synthetic-context cleanup

Only the real-IPC test fixture may re-observe and make a fresh shutdown request after an explicit rejected state_conflict receipt, with at most three attempts. Other refusals and unknown outcomes are not replayed. Production command CAS checks, all test assertions, forced-cleanup failure and existing join deadlines remain unchanged. DomainError cleanup refusals are recorded. A real IPC case injects a version change and asserts the stale request rejects before a fresh shutdown succeeds; bounded-rejection and unknown-outcome cases remain mandatory.


The same bounded explicit-refusal helper is shared by both owned synthetic IPC fixtures. A broker-tag fault-port case additionally injects a real version advance before shutdown and retains stale-command rejection plus normal zero-exit assertions. Strict stalled-connect/query timing tests and all production code remain unchanged.

### LM1 slice 1: pure live market domain

Immutable Tick input validates prices, timestamps and resolver-supplied session
and trade date. Pure minute composition uses exchange source time, suppresses
known sequence duplicates, orders forming-minute OHLC by source time, and never
reopens finalized minutes. Rejected late ticks and caller-reported loss mark
data incomplete. Period bars derive only from minute bars; daily bars combine
sessions by supplied trade date and require caller-confirmed trade-date closure.
History yields its suffix to live bars and records an explicit gap without
interpolation. Freshness uses explicit time, connection and calendar-session
facts with validated shared settings. Quote statistics select the supplied
previous trade-date close; unknown references and non-live P&L remain None.
InstrumentSpec supplies the multiplier for the single domain P&L formula.
Application liquidation delegates arithmetic while retaining executable-side
pricing, fees, slippage and its existing 30-second stale-quote refusal. This
slice adds no subscriptions, adapter/runtime wiring, UI or execution path.

### LM1 slice 2: live market ports and application coordination

MarketDataPort adds bounded, consuming tick drains in delivery order. The local
connector can use a seeded pull feed with an injected clock and explicit session
resolver; an unconfigured feed and the temporary Shioaji stub return no ticks.
LiveMarketService allocates strategy subscriptions before watch entries, reports
refused watch entries with capability_missing and raises that code on explicit
over-capacity additions. Per-instrument minute buffers retain the configured
trade-date count with a hard minute capacity. Domain functions remain the sole
authority for bar composition, aggregation, merge, freshness and quote statistics.
History requests use at most 30-calendar-day windows; normalized failures retain
live bars and expose the error code until a successful backfill. Quiet polling,
duplicate ticks and repeated identical allocations do not advance market_revision;
changed bars, quote facts, freshness, history health or allocations do. Frozen
watch, health and overview DTOs are additive presentation contracts. Scheduling,
runtime/IPC/engine wiring and UI integration remain outside this slice.

### LM1 slice 3: shared snapshots and host scheduling

TradingEngine accepts an optional LiveMarketService; existing quote handling and
quote_revision remain independent. UiState adds market_revision (default 0),
market_watch (default empty tuple) and market_health (default empty overview).
The tagged codec registers LiveBar/DataGap and market DTOs; old snapshots decode
using defaults, and Response/IpcFacade carry the same frozen snapshot unchanged.
The local composition injects seeded simulated feeds. Connected broker contexts
inject their normalized market connector before account cache wrapping. The
existing owned host coordinator schedules bounded drains every 0.5 seconds,
under the engine lock, and stops with the host. Application owns allocation,
session facts and Domain delegation; runtime adds no market calculation rules.
Views reuse Domain P&L arithmetic while retaining the existing 30-second checks.
No UI, order action or live execution permission is added.

Periodic market snapshots carry quote/reference/change and health/freshness facts
with only `LiveMarketSettings.snapshot_bar_tail` bars per instrument (default 2,
maximum 32). Full retention is read separately through additive `MARKET_SERIES`
IPC requests, never a UiAction. Application builds each chosen-period page from
LiveMarketService; offsets/next_offset traverse ascending bars with gaps and
forming/incomplete flags intact. `series_page_limit` caps pages at 1,000 bars
(configurable downward), with a half-wire byte budget reserving envelope space.
Clients pass the returned market_revision to subsequent pages; a changed revision
returns state_conflict and requires restarting. Reads do not mutate trading state.
Older snapshot and envelope fields retain their defaults. Presentation wiring
remains deferred to T2.

The LM1 performance requirement (specified before measurement): for 20
instruments at 10 ticks/second each for 10 minutes (120,000 ticks), the offline
target is p95 <= 50 ms and maximum <= 250 ms per drain/update batch of at most
100 ticks at a 0.5-second cadence, with <= 256 MiB incremental process RSS for
the live market service, buffers and snapshot construction. Samples must include
all 1,200 updates, drained tick counts and memory baseline/peak; any benchmark
must state hardware, Python version and history preload. Retention remains
bounded independently of this ten-minute workload. These are requirements,
not measurements: no performance benchmark has been run for T1. Real-broker
delivery, latency, memory and recovery behavior: PENDING USER CONFIRMATION.

### LM1 T2 slice 1: session health, polling and chart boundaries

Market polling asks the existing SessionResolver for each instrument's current
session. Only session_closed becomes CLOSED; other resolver failures propagate
through the existing application issue path. Explicit poll session overrides
remain available for deterministic fixtures. No instrument-type branch is added.
Published default views are cached per allocated instrument and invalidated by
tick/minute/freshness changes or backfill, and evicted on unsubscribe. Retention
is trimmed on backfill and live trade-date changes; deque bounds still apply on
every append. Replayed ticks and unchanged polls preserve market_revision.

Before changing desktop_charts.py, characterization tests passed for atomic
validation (numeric/OHLC/volume, contract, interval and trace identity), empty
series, and the inclusive 100,000-bar limit. append_bar and replace_last_bar use
the same per-bar validator. They accept host-supplied display data only, clear
index-based layers as set_series does, retain labels/drawings and viewport zoom,
and follow an appended bar only if the viewport was already at the end. Replacing
an empty series is rejected. A subTest table checks bar/detail equivalence to
full set_series and atomic rejection of invalid bars. set_series validation and
its existing reset behavior remain unchanged.

Host-offscreen measurement on 2026-10-28, before chart implementation changes:
`$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe tools/lm1_slice1_probe.py chart`
(exit 0). Host DESKTOP-7O0GSTN, Windows-10-10.0.19045-SP0, AMD64 Family 25
Model 33 Stepping 0 / AuthenticAMD, CPython 3.13.11 MSC v.1944 64-bit AMD64.
Ten calls with 34,000 synthetic 1m MarketBars, excluding fixture creation and
painting (including validation and Qt update scheduling), took in milliseconds:
80.229, 83.446, 89.434, 86.271, 98.852, 86.598, 86.209, 97.982, 83.967,
81.610. Median 86.240 ms, maximum 98.852 ms: **the <50 ms/call threshold was
not met**. The widget was offscreen and not shown; this is no visual acceptance.

Offline full-buffer measurement, same host/interpreter/environment:
`.venv\Scripts\python.exe tools/lm1_slice1_probe.py poll` (exit 0). Each of 20
instruments is preloaded with 34,200 continuous synthetic 1m history bars; no
calendar/reference-price calculation is configured. Each update advances fake
time 0.5 s and drains 100 distinct accepted ticks (five per instrument), followed
by bounded views and overview construction. No broker, sleep or painting occurs.
Before the polling changes, ten update samples had median 639.822 ms, range
612.386–688.052 ms; ten quiet samples had median 623.719 ms, range
604.159–690.638 ms. After the changes, update samples in milliseconds were:
389.146, 156.664, 165.575, 159.202, 151.811, 155.377, 160.595, 158.809,
167.667, 194.190 (median 159.899). The first sample includes initial cache
construction; the remaining nine range from 151.811 to 194.190 ms. Quiet
samples had median 0.186 ms, range 0.111–0.256 ms. **The cold maximum still
exceeds 250 ms and these samples do not establish the LM1 performance
requirement**: this is a ten-batch diagnostic, not the required 1,200-batch/RSS
acceptance run. The probe prints every timing for reproducibility.

Follow-up (2026-10-29): re-sorting and scanning full retention for every
changed instrument dominated each update. `merge_history_live` is now composed
of `history_before` and `join_history_live` with unchanged results. The
Application caches per instrument the ordered history prefix and its
any-incomplete flag, keyed by a history revision (bumped whenever history or
live bars are replaced by different objects, so a re-backfilled batch still wins
even when numerically equal) and the live suffix start. An earlier cut of
the same history slices the cached prefix by bisection. Previous-trade-date
closes are built lazily per date. Recovery keeps the uncached full merge. A
subTest table checks cached and uncached `watch` equality across backfill,
first ticks, a new minute and a later backfill, for 1m and 5m. Same host and
interpreter, `tools/lm1_slice1_probe.py poll --calls 1200` (20 instruments,
34,200 preloaded bars each, 100 ticks per 0.5 s batch, 1,200 batches = ten
fake minutes): p50 10.61 ms, p95 13.24 ms, maximum 204.44 ms (the first,
cold batch); one batch exceeded 50 ms. This meets the p95 <= 50 ms and maximum
<= 250 ms timing targets offline. Incremental RSS was not measured, so the full
LM1 performance acceptance is still not claimed. Real-broker delivery: PENDING
USER CONFIRMATION.

### LM1 T2 slice 2: market watch panels and watchlist settings

`MarketWatchWidget(facade, chart, state)` is a standalone three-panel widget;
the composition root injects an existing CandlestickChart. It is deliberately
not wired into window.py/workspaces.py until slice 3. Pure market_watch_rows
functions format typed views, preserve supplied change/change-percent and trade
dates, and render missing facts as Unknown. Optional bid/ask, session OHLC and
total-volume fields remain Unknown when unavailable; receive latency is supplied
by the Application mapper. Freshness uses text plus palette roles, including
update times for delayed/stopped/closed data. The header uses an explicit
market_connection view field, independent of engine trading stop state.

Period buttons request Application-aggregated MARKET_SERIES pages through the
facade, pinning subsequent pages to the first revision. No presentation price
arithmetic or aggregation is introduced. One series request runs at a time;
new selections supersede old results. Workers complete on the GUI thread and
are detached safely when the widget is destroyed. Matching retained prefixes
permit append_bar/replace_last_bar; other series changes use set_series. Gap
and history-error indicators use view flags, and retry uses the same series
request with a bounded Application history retry. All new visible labels use
literal ui_text keys; controls have object/accessibility names and tab order.

Watchlist changes use existing SAVE_SETTINGS commands with an optional watchlist
payload, without a UiAction addition or an order path. Application validates
identities/capacity before allocation and retains strategy subscription priority.
Runtime reuses SettingsStore's atomic settings path at launch.root/settings.json,
under market_watch_v2, retaining unrelated preferences. Explicit empty lists
survive restart. Settings are restored when the runtime opens and when a newly
connected engine is adopted. Successful saves advance the public version, and
closed/transitioning/stale contexts refuse changes. Persisted instruments with
no current view remain visible as Unknown rows.

T2 restore regression contract: absent/null market_watch_v2 preserves the unset
watchlist and existing market allocation. Restore does not enumerate or resolve
the catalog or read a subscription limit to invent saved preferences. The
existing market cycle retains ownership of default subscriptions; until a list
is explicitly saved, runtime snapshots project the available market view IDs.
An explicit empty list clears watch subscriptions and stays empty on restart.
Engines without a live market service retain saved intent for reconnect without
resolving contracts. Settings shape/identity validation remains at settings load;
restore does not repeat it. The P1 transport/wiring fixtures and assertions are
unchanged. Regression coverage: tests/test_watchlist_settings.py.

Slice-2 files added: desktop_trading/market_watch.py, market_watch_rows.py;
quantlab/trading/application/watchlist.py;
quantlab/trading/runtime/watchlist_settings.py; tests/test_market_watch_ui.py.
Existing files extended: desktop_strings.py; application/contracts.py, facade.py,
contextnavigation.py, market_views.py, live_market.py, market_cycle.py;
runtime/bootstrap.py; this contract. Slice-1 edits remain intact. No locked
file, gate implementation, window.py or workspaces.py was edited for this slice.
GitNexus status reported stale; per the task controller's explicit instruction,
no analyze, commit, branch, reset, checkout or push was run. Impact reported HIGH
for shared DTOs, CRITICAL for the additive string catalog, LOW for the mapper,
polling and runtime class; series callers unresolved by graph were confirmed
in source (facade/server/service tests).

Host-offscreen verification (2026-10-28; not native visual acceptance):
Set `$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'` first. Commands:

- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_market_watch_ui.py -k RowTests -k WidgetTests`: exit 0, 6 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_trading_ui.py`: exit 0, 30 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_desktop_charts.py`: exit 0, 12 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_page_services_r1.py`: exit 0, 15 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_live_market_service.py`: exit 0, 5 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_live_market_repairs.py`: exit 0, 4 tests.
- `.venv/Scripts/python.exe -m unittest discover -s tests -p test_trading_market_refresh.py`: exit 0, 4 tests.
- `.venv/Scripts/python.exe tools/check_trading_architecture.py`: exit 0, zero violations.
- `.venv/Scripts/python.exe -m unittest tests.test_trading_architecture tests.test_docs_layering`: exit 0, 16 tests.
- `.venv/Scripts/python.exe tools/quality_gate.py`: exit 0, zero findings.
- `.venv/Scripts/ruff.exe check .`: exit 0 (access-denied warnings for sandbox-created temporary directories).
- `.venv/Scripts/ruff.exe format --check <13 slice-2 changed Python files>`: exit 0.
- `py -3.11 -m compileall -q <13 slice-2 changed Python files>`: exit 0.
- `git diff --check`: exit 0.

The full `.venv/Scripts/python.exe -m unittest discover -s tests -p test_market_watch_ui.py`
was interrupted (exit 1) after stalling in the persistence test. A diagnostic
faulthandler traceback localized the stall to SettingsStore.save -> atomic_write
-> tempfile.mkstemp/_mkstemp_inner. No assertion failure was reached. This is the
sandbox tempfile non-blocker explicitly documented in t2-base.md; the controller
must rerun the unmodified full module outside the sandbox. The persistence test
uses a real temporary settings file, Runtime SAVE_SETTINGS dispatch, nonempty
restart restoration, unrelated-key retention, and explicit-empty restoration.
It is present, not skipped, and persistence is not claimed as locally verified.

Physical Windows display checks, 150%/200% scaling and real market viewing remain
PENDING USER CONFIRMATION. Offscreen tests do not establish visual or broker PASS.

### LM1 T2 slice 3: market workspace and snapshot polling

The v2 runtime composition root now injects MarketWatchWidget and the shared
CandlestickChart into TradingWindow. This is the only trading_runtime.py change:
construction/wiring, with no market rules or legacy research changes. The market
workspace embeds watchlist | chart | quote detail in the existing three-panel
splitter concept. The original instrument table and research/data routes remain
under the initially collapsed market_archive button at the bottom.

The existing one-second snapshot poll renders market watch when market_revision
changes. With unchanged context/version/quote_revision, it retains every table
selection and skips the other tables. Existing quote_revision rendering and
financial-fact/freshness invalidation still run when those facts change together
with market_revision. No market arithmetic is added to window.py/workspaces.py.

Before completing the partial edits, two characterization tests in
test_trading_ui.py passed against both the partial working tree and the original
22d5dc7 window.py/workspaces.py, loaded in memory using git show (no source
restoration or checkout). They preserve the market workspace routes/table shape
and identify the quote-only poll's position/market updates and retained selections.
The new test_trading_ui_market_watch.py extension exercises the real widget,
snapshot poll, chart request/result, header/detail updates, non-first watch
selection, strategy/position/order selections and absence of table model resets
or data changes outside market watch.

Host-offscreen layout tests first exposed squeezed period buttons, collapsible
panels and Tab moving among watchlist cells. Minimum layout constraints now let
the existing workspace scroll area expose the full content, splitters retain
all three panels, and Tab leaves the row-selection table. Tests exercise 20pt
Arial at the 600x300 minimum window, reach each required input/period/retry/archive
control by scrolling, check minimum control widths and non-overlap, and exercise
Tab order plus Space activation. These are geometry/wiring assertions, not native
visual acceptance. The existing broker-cycle test double now supplies typed
LiveMarketSettings required by watchlist initialization; no assertion was removed.

Criteria-T2.json review against 22d5dc7 plus the seven new T2 Python files:

| Criterion | Evidence / disposition |
|---|---|
| 1 | Both market_watch modules exist; row formatting has no Qt; AST architecture scan: 0 violations. |
| 2 | Source review: no market/reference/P&L/freshness arithmetic; period requests use Application MarketSeriesQuery pages. Length/prefix comparisons only choose display updates. |
| 3 | Slice-1 pre-edit characterization and exact 34,000-bar command/host/timings remain recorded above; median 86.240ms exceeded 50ms. |
| 4 | Append/replace remain display methods; chart subTest tests verify full-series equivalence, invalid input and inclusive 100,000 limit. |
| 5 | AST/source check: zero CJK characters and all ui_text calls have literal keys in market_watch*.py; unknown formatting tests pass. |
| 6 | Existing UI refusal test verifies 20-slot header, SAVE_SETTINGS payload, ERROR_TABLE feedback and retained strategy subscriptions. |
| 7 | Existing temporary-settings test covers persisted watches, restart allocation, unrelated preferences and explicit-empty restoration. Reconnected candidates call the same restore adapter. Local persistence execution is filesystem-blocked below; controller rerun required. |
| 8 | Poll characterization and five workspace extension tests pass host-offscreen; market-only poll updates all three panels, retaining table objects/selections without reset/data changes elsewhere. |
| 9 | Existing row/widget tests cover freshness text/time/palette, unknown facts, gap/history error/retry and instrument-independent components. |
| 10 | Object/accessibility names, actual Tab/Space navigation and minimum-window/large-font geometry tests pass host-offscreen. Required controls remain scroll-reachable. |
| 11 | desktop_market.py unchanged; C5 and test_desktop_market.py pass. Archive opens by keyboard and retains legacy routes. Broader legacy filesystem-dependent tests require controller rerun. |
| 12 | No UiAction additions or order controls; seven new modules have responsibility docstrings and <=400 lines: widget 294, rows 128, application watchlist 55, runtime settings 39, widget tests 331, workspace tests 161, probe 125. |
| 13 | Review: typed data is trusted; optional missing facts remain Unknown. Worker exceptions surface a request-error label; boundary/settings errors use existing codes. UI tests assert display/wiring, with subTest tables; no old test is weakened/skipped/deleted. |
| 14 | Full tracked diff from 22d5dc7 has no G3, saved_candidate_pool.py, PROJECT_STATE.md, ACCEPTANCE.json, desktop_market.py, aggregate_bars or gate changes. Live execution stays disabled. |
| 15 | Exact gate commands/results follow. Filesystem-blocked runs are the explicit t2-base.md exceptions, not passing tests. No PR-head SHA was created: commit/push/branch/reset/checkout are prohibited for this slice. |
| 16 | Physical Windows screen, native 150% scaling, native 200% scaling and user's real market viewing: **PENDING USER CONFIRMATION**. All local UI evidence is labelled host-offscreen. |

Slice-3 files: desktop_trading/window.py, workspaces.py, market_watch.py;
trading_runtime.py; tests/test_trading_ui.py, test_trading_ui_market_watch.py,
test_live_market_repairs.py; this contract. Slices 1–2 are retained.

Host-offscreen verification on 2026-10-28, PowerShell from the repository root:
`$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'`.
Each row below runs
`.venv/Scripts/python.exe -m unittest discover -s tests -p <pattern>`
with any listed extra arguments (each module is a separate invocation).

| Pattern / extra arguments | Result |
|---|---|
| test_market_watch_ui.py | 50-second diagnostic wrapper timeout; blocked in initial SettingsStore.save. No assertion failure reached. |
| test_market_watch_ui.py -k RowTests -k WidgetTests | exit 0; 6 tests. |
| test_trading_ui.py | exit 0; 32 tests, including both characterizations. |
| test_trading_ui_market_watch.py | exit 0; 5 tests. |
| test_trading_ui_integration.py | exit 1; 12 setup errors opening sandbox temporary SQLite files. |
| test_desktop_charts.py | exit 0; 12 tests. |
| test_chart_data.py | exit 0; 15 tests. |
| test_chart_memory_f6.py | exit 0; 11 tests. |
| test_market_workspace_c5.py | exit 0; 11 tests. |
| test_trading_market_refresh.py | exit 0; 4 tests. |
| test_desktop_market*.py | exit 1; 46 tests, 33 filesystem errors, 2 existing skips. WinError 5 in temporary workspace creation/cleanup and manual export. No test was changed to skip. |
| test_desktop_market.py | exit 0; 21 tests. |
| test_page_services_r1.py | exit 0; 15 tests. |
| test_live_market_service.py | exit 0; 5 tests. |
| test_live_market_repairs.py | exit 0; 4 tests after correcting typed mock settings (initial run: exit 1, four subTest setup errors). |

Persistence diagnosis used the following command with a 15-second outer timeout:
`.venv/Scripts/python.exe -X faulthandler -c "import faulthandler, unittest; faulthandler.dump_traceback_later(5); unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests', '-p', 'test_market_watch_ui.py', '-k', 'PersistenceTests'])"`.
The five-second traceback identifies tempfile._mkstemp_inner -> mkstemp ->
runtime_support.atomic_write -> SettingsStore.save at the test's initial save.
The outer timeout then terminated it; persistence is not claimed as passed.
These filesystem denials/stalls are the base instruction's explicit non-blockers;
the controller must rerun the full persistence/integration/legacy modules outside
the sandbox. No production or test fallback was added to bypass them.

The 23 changed/new Python paths used for formatting and compilation are:

```powershell
$T2Python = @(
  'desktop_charts.py', 'desktop_strings.py',
  'desktop_trading/window.py', 'desktop_trading/workspaces.py',
  'quantlab/trading/application/contextnavigation.py',
  'quantlab/trading/application/contracts.py',
  'quantlab/trading/application/facade.py',
  'quantlab/trading/application/live_market.py',
  'quantlab/trading/application/market_cycle.py',
  'quantlab/trading/application/market_views.py',
  'quantlab/trading/runtime/bootstrap.py',
  'tests/test_desktop_charts.py', 'tests/test_live_market_repairs.py',
  'tests/test_live_market_service.py', 'tests/test_trading_ui.py',
  'trading_runtime.py', 'desktop_trading/market_watch.py',
  'desktop_trading/market_watch_rows.py',
  'quantlab/trading/application/watchlist.py',
  'quantlab/trading/runtime/watchlist_settings.py',
  'tests/test_market_watch_ui.py', 'tests/test_trading_ui_market_watch.py',
  'tools/lm1_slice1_probe.py'
)
.venv/Scripts/ruff.exe format $T2Python
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check $T2Python
py -3.11 -m compileall -q $T2Python
.venv/Scripts/python.exe tools/quality_gate.py
.venv/Scripts/python.exe tools/check_trading_architecture.py
.venv/Scripts/python.exe -m unittest tests.test_trading_architecture tests.test_docs_layering
git diff --check
```

All commands above exit 0; quality gate has 0 findings, architecture has 0
violations, architecture/docs unit gates run 16 tests. Ruff reports access-denied
warnings for sandbox-created temporary directories, with no lint findings.
An initial Python subprocess wrapper used a relative slash-form executable path
and failed with WinError 2 before running Ruff; absolute executable paths fixed
that invocation. It did not indicate a source failure.

GitNexus impact: apply_state LOW (three direct callers: initialization, snapshot
result and context switching; no resolved processes), _market_page LOW (build
process and TradingWindow initialization), runtime _run_window LOW (run_window,
desktop main and trading entry). The new widget is absent from the baseline
index (UNKNOWN); direct source searches confirmed runtime injection and UI test
callers before its layout edits. The test method's UNKNOWN impact was likewise
confirmed through unittest discovery. No re-index was run per the base command.
`node .gitnexus/run.cjs detect-changes --scope all --repo .` exited 1:
`Git diff failed: spawnSync git EPERM`. This is unresolved graph evidence, not a
clean impact verdict. No commit was attempted; the controller should rerun this
check before committing. Ordinary git diff and protected-path checks completed.

### LM1 T3 final: overview dashboard (2026-10-29)

Evidence is **host-offscreen** only, adjacent to the P2 market workspace entry.
Physical Windows screen, native 150% scaling, native 200% scaling and real
automated-trading monitoring: **PENDING USER CONFIRMATION**. Offscreen geometry,
keyboard and wiring checks do not establish these user acceptance results.

Reviewed all criteria-T3.json items against base main `07b66e4`, including the
retained slice-1 diff and all five new Python modules. No commit or PR-head SHA
was created: the controller explicitly prohibits git commit/push/branch/reset/
checkout and GitNexus analyze in this working tree.

| Criterion | Evidence / disposition |
|---|---|
| 1 | dashboard.py renders dashboard_rows output; rows have no Qt import. Architecture scan covers both modules; result recorded below. |
| 2 | Broker, market, engine and reconciliation lights include text and colour. Visible one-line red summary is asserted in test_dashboard_ui. |
| 3 | One shared STOPPED MarketHealthView drives watch and dashboard in an offscreen test; DELAYED remains warning. Dashboard rows reuse market_watch_rows.freshness_text. |
| 4 | Five today facts are Application fields; dashboard modules only format them. Snapshot computes daily_loss_room once and derives remaining risk and remaining daily loss from it; sessions.py and workflows.py formulas were not changed in slice 2. |
| 5 | Strategy table displays name, version, activity, today orders and P&L from slice-1 Application fields. |
| 6 | Position table displays instrument, strategy/version, direction, quantity, holding days, exit window, P&L and quote time. One UI assertion covers Unknown for a non-LIVE quote; valuation remains in Domain/Application. |
| 7 | The prominent pending_issue_details list is at the top. recent_events reuses events, preserves the latest-100 chronological display and expands with Space. Disconnect test retains last prices and table objects, with STOPPED and a red light. |
| 8 | Exactly STOP_NEW, CANCEL_ENTRIES and RECONCILE operation buttons use window.command; keyboard tests assert existing UiActions. No new action or engine/runtime handler. New strategy and local step remain outside the dashboard. |
| 9 | Literal ui_text keys; zero CJK characters in dashboard*.py. Controls have objectName/accessibility names; Tab and Space tests pass. |
| 10 | Two characterization tests passed before editing _overview_page/apply_state and pass afterward. Those modules only host/alias/render the widget. market_revision updates status, summary and quote cells in place, preserving selection and table models. |
| 11 | AST comparison confirms old StrategyView/PositionView/UiState fields unchanged in order/type/default, and additions defaulted at the end. Old-snapshot decoding remains covered by test_market_series_transport. |
| 12 | New module line counts: dashboard 164, rows 135, UI tests 197, row tests 114, characterization 58. Each has a responsibility docstring. New StatusLight is frozen; money stays Decimal. Typed facts are trusted; no swallowed exceptions or new redundant validation. UI tests assert display/wiring with subTest tables. No existing test weakened. |
| 13 | Full diff leaves G3, saved_candidate_pool.py, PROJECT_STATE.md, ACCEPTANCE.json, desktop_market.py, chart_data.py and both gates untouched. UiAction is AST-identical to base; live execution remains disabled. |
| 14 | Individual commands and exact exits follow. Filesystem-denied suites are controller-authorized sandbox exceptions, not passes; rerun outside sandbox. |
| 15 | Physical Windows screen, 150%/200% scaling and real automated-trading monitoring remain **PENDING USER CONFIRMATION**; all UI evidence is host-offscreen. |

GitNexus pre-edit: _overview_page LOW (build process and window initialization),
apply_state LOW (initialization, result, context switch; caller set lower-bound).
Snapshot UNKNOWN was resolved for navigation by reading LocalFacade.snapshot,
which calls views.snapshot under the engine lock. The stale baseline graph does
not contain the new dashboard modules; direct source/reference review covers
them. No re-index was run per controller instruction. Final MCP
`detect_changes(scope=all, repo=mark-auto)` reports 19 changed symbols, five
processes, MEDIUM risk, with no partial/truncated flags. This is navigation
evidence, not a substitute for tests or review of untracked new files.

Slice-2 changed files: desktop_strings.py; desktop_trading/dashboard.py,
dashboard_rows.py, workspaces.py, window.py; quantlab/trading/application/views.py;
tests/test_dashboard_characterization.py, test_dashboard_ui.py; this contract.
All slice-1 files and tests are retained.

Host-offscreen commands on 2026-10-29 from the repository root, with
`$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'`:

| Exact command | Exit / result |
|---|---|
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_dashboard_ui.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_dashboard_characterization.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_trading_ui.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_trading_ui_integration.py` | 1 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_trading_application.py` | TIMEOUT (45s) |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_trading_performance.py` | TIMEOUT (45s) |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_dashboard_rows.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_market_watch_ui.py` | TIMEOUT (45s) |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_trading_ui_market_watch.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_r7_characterization.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_desktop_text_aliases.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_page_services_r1.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -X faulthandler -m unittest discover -s tests -p test_market_series_transport.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe" check .` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe" format --check desktop_strings.py desktop_trading/dashboard.py desktop_trading/dashboard_rows.py desktop_trading/window.py desktop_trading/workspaces.py quantlab/trading/application/contracts.py quantlab/trading/application/events.py quantlab/trading/application/performance.py quantlab/trading/application/state.py quantlab/trading/application/views.py quantlab/trading/application/workflows.py tests/test_dashboard_characterization.py tests/test_dashboard_rows.py tests/test_dashboard_ui.py tests/test_market_series_transport.py tests/test_trading_application.py` | 0 |
| `py -3.11 -m compileall -q desktop_strings.py desktop_trading/dashboard.py desktop_trading/dashboard_rows.py desktop_trading/window.py desktop_trading/workspaces.py quantlab/trading/application/contracts.py quantlab/trading/application/events.py quantlab/trading/application/performance.py quantlab/trading/application/state.py quantlab/trading/application/views.py quantlab/trading/application/workflows.py tests/test_dashboard_characterization.py tests/test_dashboard_rows.py tests/test_dashboard_ui.py tests/test_market_series_transport.py tests/test_trading_application.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" tools/quality_gate.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest tests.test_trading_architecture tests.test_docs_layering` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" tools/check_trading_architecture.py` | 0 |
| `git diff --check` | 0 |

The pre-edit characterization command was also run separately before changing
workspaces.py/window.py: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_dashboard_characterization.py`, exit 0 (two tests).
After the final market-cell update, test_dashboard_ui and
test_trading_ui_market_watch were separately rerun, exit 0 each (five tests each).
With `PYTHONPATH=tests`, `.venv\Scripts\python.exe -m unittest test_trading_application.DashboardApplicationTests test_market_watch_ui.RowTests test_market_watch_ui.WidgetTests`
exits 0 (eight tests), verifying the new Application facts and non-persistence
market UI independently of the sandbox filesystem failures.

The integration suite exits 1 during fixture setup: SQLite cannot open the temp
database; cleanup reports WinError 5. Full application/performance/market-watch
runs exceeded the 45-second harness limit and were terminated, not passed.
Separate diagnostic commands, each exit 1, were:

```powershell
.venv\Scripts\python.exe -c "import faulthandler,unittest; faulthandler.dump_traceback_later(5,exit=True); unittest.main(module=None)" discover -s tests -p test_trading_application.py
.venv\Scripts\python.exe -c "import faulthandler,unittest; faulthandler.dump_traceback_later(5,exit=True); unittest.main(module=None)" discover -s tests -p test_trading_performance.py
.venv\Scripts\python.exe -c "import faulthandler,unittest; faulthandler.dump_traceback_later(5,exit=True); unittest.main(module=None)" discover -s tests -p test_market_watch_ui.py
```

Stacks locate application/performance in tempfile.mkdtemp during setUp and
market-watch persistence in tempfile.mkstemp during atomic_write. These are
explicit non-blockers in t3-base.md; controller reruns outside the sandbox remain
required. No test assertion was weakened, skipped or removed. Local command
logs/results are in .tmp-t3-slice2/; AST/protected-file review is review.json.
An initial relative forward-slash subprocess executable failed with WinError 2
before running the formatter; absolute executable paths corrected it.
Ruff reports directory-access warnings and no lint findings. Architecture reports
0 violations and quality gate reports 0 findings. This is working-tree evidence,
not a claim that gates ran against a committed PR head SHA.

### LM1 T3 slice 1: application facts and pure dashboard rows (2026-10-29)

This slice supplies read models and pure display functions only. The dashboard
widget and overview wiring belong to a subsequent slice. No trading action or
execution capability is added. Physical Windows appearance, 150%/200% scaling,
and actual automated-trading monitoring remain PENDING USER CONFIRMATION;
Qt evidence here is host-offscreen only.

New fields are appended with defaults; existing fields retain their positions,
types and meaning. Money remains Decimal and unknown facts remain None.

| Field | Why it is needed |
|---|---|
| StrategyView.today_order_count | Orders lack a presentation-level strategy/version daily count; decision timestamps are matched to calendar trade dates, including night sessions. Unresolvable dates remain unknown. |
| StrategyView.today_pnl | Existing PerformanceView.attributed_pnl is cumulative version equity, not today's change. Reuse that recorded equity basis minus a known daily baseline; non-LIVE open holdings suppress the result. |
| StrategyView.activity_state | The existing state is deployment lifecycle (e.g. ACTIVE), which cannot distinguish running, paused and a latched daily risk stop. Application supplies that distinction without changing the existing lifecycle field. |
| PositionView.unrealized_pnl | Existing performance aggregates versions, not lots. Call Domain quote_stats.unrealized_pnl with signed quantity and entry cost; non-LIVE or unverified facts remain unknown. |
| PositionView.quote_freshness | Existing quote_time has no freshness classification. Reuse live-market health; without that service use the shared Domain classifier. |
| UiState.unrealized_pnl | Application aggregates lot values once; Presentation must not total money. Any unknown lot makes the portfolio total unknown. |
| UiState.remaining_daily_loss | remaining_risk also subtracts reservations, so it cannot represent the remaining daily loss allowance. Use the existing daily-loss basis without that reservation deduction. |
| UiState.today_fill_count | Existing OrderView.filled is cumulative quantity, not dated execution count. Unknown execution history remains unknown. |
| VersionEquityTrack.daily_baseline | A cumulative version observation cannot reconstruct a daily baseline. Newly seeded versions start at zero; local day advancement captures the current version marks before advancing the clock. Missing legacy or externally unattested daily baselines remain unknown. |
| LocalOrder.fill_count_day, daily_fill_count | Preserve the date and count of observed fill events across snapshots/restarts. Calendar trade dates own the counts; reconciled cumulative deltas cannot establish execution counts. |

No additional held-days, quote-time, exit-date, portfolio daily-P&L, risk, or
performance fields are introduced. Dashboard positions display the existing
exit_window as the planned exit range. The existing registered dataclass codec
already decodes absent fields through defaults; no protocol/codec edits are
needed. One old-snapshot Response test covers missing StrategyView, PositionView
and UiState additions.

Each lot's gross mark is calculated once and reused by PerformanceView. Its
existing 30-second coverage contract is preserved; dashboard display additionally
requires the shared LIVE classification. This keeps the existing performance
read model compatible while preventing delayed dashboard valuations.

desktop_trading/dashboard_rows.py formats status lights, textual red summaries,
today items, strategies, positions, issues and recent events. It imports no Qt
and computes no money or freshness. Market labels and levels reuse
market_watch_rows.freshness_text, with only STOPPED promoted to red. DELAYED is
warning, CLOSED/UNKNOWN muted. Pending issues preserve their supplied order;
events use existing event labels, most recent first. Literal strings live in
the trailing Lane LM1 dashboard catalog block.

Changed files: desktop_strings.py; desktop_trading/dashboard_rows.py;
quantlab/trading/application/{contracts,views,state,events,performance,workflows}.py;
tests/{test_dashboard_rows,test_trading_application,test_market_series_transport}.py;
this implementation contract.

Verification commands use PYTHONUTF8=1 and QT_QPA_PLATFORM=offscreen. Each command
below was run from the repository root; exit codes are recorded explicitly.

| Command | Exit |
|---|---:|
| `.venv\Scripts\ruff.exe check .` | 0 |
| `.venv\Scripts\ruff.exe format --check desktop_strings.py quantlab/trading/application/contracts.py quantlab/trading/application/events.py quantlab/trading/application/performance.py quantlab/trading/application/state.py quantlab/trading/application/views.py quantlab/trading/application/workflows.py tests/test_market_series_transport.py tests/test_trading_application.py desktop_trading/dashboard_rows.py tests/test_dashboard_rows.py` | 0 |
| `py -3.11 -m compileall -q desktop_strings.py quantlab/trading/application/contracts.py quantlab/trading/application/events.py quantlab/trading/application/performance.py quantlab/trading/application/state.py quantlab/trading/application/views.py quantlab/trading/application/workflows.py tests/test_market_series_transport.py tests/test_trading_application.py desktop_trading/dashboard_rows.py tests/test_dashboard_rows.py` | 0 |
| `.venv\Scripts\python.exe tools/quality_gate.py` | 0 |
| `.venv\Scripts\python.exe -m unittest tests.test_trading_architecture tests.test_docs_layering` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_dashboard_rows.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_application.py -v` | 124 (45-second timeout) |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_performance.py -v` | 124 (45-second timeout) |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_ui.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_market_watch_ui.py -v` | 124 (45-second timeout) |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_market_service.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_market_series_transport.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_desktop_text_aliases.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_page_services_r1.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_market_wiring.py -v` | 0 |
| `.venv\Scripts\python.exe -m unittest test_market_watch_ui.RowTests test_market_watch_ui.WidgetTests test_trading_application.DashboardApplicationTests` (PYTHONPATH=tests) | 0 |
| `git diff --check` | 0 |

The targeted final command passes eight tests, including both new application
tests. The three full-suite timeouts are sandbox filesystem limitations allowed
by the T3 base instructions: faulthandler confirms tempfile.mkdtemp in application
setUp (also used by performance), and tempfile.mkstemp in atomic_write during
market-watch persistence. No assertion failure was hidden or test disabled.
The controller must rerun these three complete suites outside this sandbox.
Ruff reports directory-access warnings but no lint findings. Logs and exact
commands are retained locally in .tmp-t3-slice1/.

The final combined regression command also exits 0 (90 tests), with
PYTHONPATH=tests: `.venv\Scripts\python.exe -m unittest test_dashboard_rows test_market_watch_ui.RowTests test_market_watch_ui.WidgetTests test_trading_application.DashboardApplicationTests test_live_market_wiring test_market_series_transport test_live_market_service test_trading_ui test_desktop_text_aliases test_page_services_r1`.
An intermediate inventory failure caused by a fake's `summary` attribute was
fixed by removing that page-alias collision; the fixture and existing tests were
not changed. All static gates were rerun after the final Python changes.

GitNexus StrategyView, PositionView and UiState impact is HIGH (27 direct
dependents each); only defaulted additions were made. Other touched application
symbols have LOW/MEDIUM impact. snapshot is UNKNOWN with unresolved dynamic
callers; direct source inspection confirms LocalFacade.snapshot consumes it.
Status identifies the existing base index as stale; no analyze was run, as
required by the controller's T3 instructions. CLI detect-changes exits 1 with
spawnSync git EPERM. The MCP fallback detect_changes(scope=all, repo=mark-auto)
succeeds without partial/truncated flags: sixteen changed symbols, four affected
flows, MEDIUM risk. New untracked modules require direct review because they
are absent from that baseline graph. No commit, push or branch operation ran.

## LM1 T4 slice 1: fake-SDK tick delivery (2026-10-29)

The Shioaji gateway uses the pinned SDK facade's stock/futures tick callback
setters on its first subscription. Construction remains inert and disconnected;
legacy injected account-only SDK doubles retain their original market surface.
Tick delivery requires the pinned facade. No order path or UI action is added.

`adapters/shioaji/tick_stream.py` translates SDK ticks to immutable Domain Tick
values. Prices are Decimal; trade date/session come exclusively from the injected
TradeDateResolver. Missing resolver/calendar, naive source time, non-positive
price, invalid volume, unknown session and receive-before-source time fail closed.
One adapter callback guard logs a sanitized rejection and lets later ticks flow.
The callback performs only translation and bounded enqueueing under a short lock.
The existing LiveMarketSettings.queue_limit controls the queue; no new setting
or timeout is introduced. SDK sequence identity is not fabricated.

Queue overflow coalesces into a typed TickLoss envelope per instrument between
drains, retaining exact lost-tick count and earliest/latest source times. This
keeps overflow metadata bounded by the active subscription count. The optional
TickLossSource port and RoutedMarketData forward these envelopes independently
of the tick budget. LiveMarketService records one issue per envelope, marks
retained affected minutes incomplete, and remembers loss for later-arriving
minutes. Coalesced intervals conservatively include intervening minutes; no
missing bar is synthesized. Bar composition/freshness remain Domain/Application.
The issue and loss retention collections are bounded.

Characterization ran before changing production behavior: the extended
`test_trading_sdk_facade` (11 tests) and `test_trading_adapters` (31 tests) both
exited 0. The new tick-boundary suite first failed on absent callback wiring,
normalization module and settings injection; the overflow suite first failed
on missing incomplete flags. Both then passed with the implementation.
Mock evidence only: no network, account, credential/keyring access or real SDK
import was used. Real broker-simulation subscription and callback delivery:
PENDING USER CONFIRMATION via the existing CONNECT_READ_ONLY action. Reconnect,
backfill and the shared two-connector contract suite are outside this slice.

Changed files:

- quantlab/trading/adapters/shioaji/tick_stream.py (new)
- quantlab/trading/adapters/shioaji/gateway.py
- quantlab/trading/adapters/shioaji/market_data.py
- quantlab/trading/application/live_market.py
- quantlab/trading/runtime/live_market.py
- quantlab/trading/ports/tick_stream.py (new)
- tests/shioaji_tick_fakes.py (new)
- tests/test_shioaji_tick_stream.py (new)
- tests/test_shioaji_tick_overflow.py (new)
- tests/test_trading_adapters.py
- tests/test_trading_sdk_facade.py
- docs/agent/IMPLEMENTATION_CONTRACTS.md

GitNexus pre-edit impact: ShioajiAdapter MEDIUM (34 dependents),
market_data.subscribe LOW (connect_profile_engine), LiveMarketService LOW,
RoutedMarketData LOW. Gateway drain_ticks is UNKNOWN; direct text/source review
confirms consumption through MarketDataPort by LiveMarketService and the router.
Status reports the controller's existing index as stale; no analyze ran, as
required by t4-base.md. detect_changes(scope=all, repo=mark-auto) returned 24
changed symbols, nine affected processes, HIGH risk, without partial/truncated
flags. Polling, allocation and broker-connect flows were reviewed against the
actual diff; the stale index also maps adjacent unchanged methods into touched
ranges. New untracked modules were reviewed directly. No commit, push or branch
operation ran. Protected files and gates remain untouched.

Final slice verification (working tree, no commit created):
`$env:PYTHONUTF8='1'`; `$env:QT_QPA_PLATFORM='offscreen'`.

| Exact process command | Exit code |
|---|---:|
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_tick_adapters_contract.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_sdk_facade.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_sdk_loader.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_adapters.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_broker_runtime.py` | 124 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_broker_sessions.py` | 124 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_trading_readonly_coordination.py` | 124 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_live_market_service.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_live_bars.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_live_market_wiring.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_shioaji_tick_stream.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_shioaji_tick_overflow.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_page_services_r1.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe" check .` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\ruff.exe" format --check quantlab/trading/adapters/shioaji/tick_stream.py quantlab/trading/adapters/shioaji/gateway.py quantlab/trading/adapters/shioaji/market_data.py quantlab/trading/application/live_market.py quantlab/trading/runtime/live_market.py quantlab/trading/ports/tick_stream.py tests/test_shioaji_tick_stream.py tests/test_shioaji_tick_overflow.py tests/shioaji_tick_fakes.py tests/test_trading_adapters.py tests/test_trading_sdk_facade.py` | 0 |
| `py -3.11 -m compileall -q quantlab/trading/adapters/shioaji/tick_stream.py quantlab/trading/adapters/shioaji/gateway.py quantlab/trading/adapters/shioaji/market_data.py quantlab/trading/application/live_market.py quantlab/trading/runtime/live_market.py quantlab/trading/ports/tick_stream.py tests/test_shioaji_tick_stream.py tests/test_shioaji_tick_overflow.py tests/shioaji_tick_fakes.py tests/test_trading_adapters.py tests/test_trading_sdk_facade.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" tools/quality_gate.py` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" -m unittest tests.test_trading_architecture tests.test_docs_layering` | 0 |
| `"C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe" tools/check_trading_architecture.py` | 0 |
| `git diff --check` | 0 |

112 tests passed across the completed suites, including all eight new tick
stream/overflow tests. Ruff reports pre-existing inaccessible-directory warnings
but exits 0; the architecture scanner reports zero violations and the quality
gate reports zero findings. After bounding the producer-thread join to one second
(with a daemon thread and explicit liveness assertion), the five-test tick-stream
suite, repo Ruff check, its format check and Python 3.11 compileall were rerun:
all exit 0. No existing test or application timeout was increased.

Exit 124 is the outer runner's 60-second termination, not a test assertion
failure. Faulthandler diagnostics terminate after three seconds (exit 1) and show
all three affected suites stalled in tempfile.mkdtemp, before product code:

- test_trading_broker_runtime.py:45, BrokerRuntimeTests.setUp
- test_trading_broker_sessions.py:145, BrokerSessionLifecycleTests.setUp
- test_trading_coordinator.py:38, laboratory used by read-only coordination

These tests explicitly target a temp directory under the workspace's parent,
which is outside this sandbox's writable root. This is the non-blocking sandbox
exception in t4-base.md; the controller must rerun the three original discovery
commands outside the sandbox. No suite was weakened or skipped. Exact commands,
per-suite logs, diagnostic stacks and machine-readable exit codes are retained
locally under .tmp-t4-slice1/. Slice status: DONE under that documented exception;
real-broker evidence remains PENDING USER CONFIRMATION.


## LM1 T4 final slice: reconnect and shared tick contract (2026-10-29)

Scope: Slice 1 is retained. Verification below is **mock evidence** from fake SDK
objects and injected clocks, not a real broker session. The controller owns
index refresh, commits and head-SHA verification; these commands ran against the
complete working tree and reviewed diff versus local `main`, without committing.

The SDK session-down callback records typed connection facts. After the existing
explicit session connection/adoption succeeds, the next Application poll replaces
receipt ownership, restores active subscriptions in strategy-first allocation
order, and backfills the disconnected interval through the existing `history()`
port in windows of at most 30 days. The settings subscription limit is enforced
by both allocation and the Shioaji boundary (never more than 20). Last known
prices and buffers survive disconnection and failed restore. No login retry,
credential discovery, new UI action or execution path is added.

P1 Domain merge now accepts explicit recovery inside a live suffix, with live
bars winning overlaps. Failed or empty history windows remain P1 `DataGap`
intervals; later windows are still attempted. A successful retry subtracts only
the recovered portion of a gap. These pure merge/gap rules stay in Domain;
Application schedules recovery and publishes the existing health/error views.
The shared factory table in `test_tick_adapters_contract.py` executes the same
assertions against simulated tick_feed and fake-SDK Shioaji. The Slice-1
Shioaji-only drain test was moved into that suite with its exact FIFO prices
retained as factory expectations; existing simulator sequence assertions remain.

### Locked criteria review (all 14, full diff versus main)

| Criterion | Evidence / disposition |
|---|---|
| 1 | `tick_stream.py` registers stock/futures callbacks through sdk_facade only. The import grep below finds only sdk_loader line 16; architecture reports 0 violations. |
| 2 | Fake-SDK normalization table covers Decimal price, resolver trade date/session, missing calendar/resolver, nonpositive price, invalid session, negative volume and received-before-source. |
| 3 | Callback translates/enqueues under the queue lock; capacity uses LiveMarketSettings.queue_limit. No adapter bar, aggregation or freshness computation. |
| 4 | The recorded callback guard logs a sanitized error; the next valid callback still drains. No vendor exception text is published. |
| 5 | Small-queue overflow tests assert exact loss accounting, issue delivery and affected Application bars marked incomplete. |
| 6 | Fake SDK/clock reconnect tests cover configured limits 2 and 20, promoted strategy priority, loss between polls, 65-day recovery in 30/30/5-day windows, no repeated recovery, continued callbacks, failed/empty windows, retry and failed subscription restore. |
| 7 | Port drains expose Domain Tick only. Slice-1 facade/market characterization retained; new disconnect/receipt characterization passed before session/market edits (32 adapter tests). |
| 8 | One parametrised connector factory table runs shared drain, receipt, ordering, budget, once-only/FIFO and unsubscribe assertions for both connectors; duplicated connector-only drain test moved, not weakened. |
| 9 | Deterministic separate producer thread covers queue limits 3 and 100, bounded join, exact drained-plus-lost accounting and no exception. |
| 10 | All T4 tick tests use fake SDKs; no actual login, credential/keyring read, SDK import or network. SDK loader tests inject fake modules. Existing disconnected/read-only/execution-disabled defaults remain. No new order call. Real initial connection remains the existing CONNECT_READ_ONLY path. |
| 11 | AST/line audit of all 37 new Python modules versus main (including untracked T4 modules): responsibility docstrings present, each <=400 lines. Rule 12: optional capabilities discovered once at composition; SDK/config validation only, callback guard records errors, history failures publish typed errors/gaps, subscription errors propagate. Rule 13: shared/subTest cases, Domain arithmetic tested in Domain, no UI changes in T4. |
| 12 | Full diff excludes all eight G3 files, saved_candidate_pool.py, PROJECT_STATE.md, ACCEPTANCE.json and both gate implementations. No live/order/ExecutionPort/UiAction expansion. |
| 13 | Commands and exit codes below. All completed gates pass; three original broker suites hit the documented sandbox tempfile exception and require the controller's outside-sandbox rerun. No tests skipped or timeouts increased. |
| 14 | **Real Shioaji broker-simulation subscription, callback delivery and reconnect = PENDING USER CONFIRMATION (via CONNECT_READ_ONLY).** Fake-SDK results are **mock evidence**, never real-broker PASS. |

### T4 files (both slices)

- `docs/agent/IMPLEMENTATION_CONTRACTS.md`
- `quantlab/trading/adapters/shioaji/gateway.py`
- `quantlab/trading/adapters/shioaji/market_data.py`
- `quantlab/trading/adapters/shioaji/tick_stream.py`
- `quantlab/trading/ports/tick_stream.py`
- `quantlab/trading/application/live_market.py`
- `quantlab/trading/domain/live_bars.py`
- `quantlab/trading/runtime/live_market.py`
- `tests/shioaji_tick_fakes.py`
- `tests/test_shioaji_tick_stream.py`
- `tests/test_shioaji_tick_overflow.py`
- `tests/test_shioaji_tick_reconnect.py`
- `tests/test_tick_adapters_contract.py`
- `tests/test_live_bars.py`
- `tests/test_trading_adapters.py`
- `tests/test_trading_sdk_facade.py`

### Verification commands and exit codes

PowerShell environment: `$env:PYTHONUTF8='1'`; `$env:QT_QPA_PLATFORM='offscreen'`.
The provisioned `.venv\Scripts\python.exe` is Python 3.13.11. Compilation and
additional quality/architecture/docs checks also ran using `py -3.11`.
`$changedPython` below is the exact sorted set from:

```powershell
$changedPython = @((git diff --name-only --diff-filter=ACM main -- '*.py') + @(
  'quantlab/trading/adapters/shioaji/tick_stream.py',
  'quantlab/trading/ports/tick_stream.py',
  'tests/shioaji_tick_fakes.py',
  'tests/test_shioaji_tick_stream.py',
  'tests/test_shioaji_tick_overflow.py',
  'tests/test_shioaji_tick_reconnect.py'
) | Sort-Object -Unique)
```

Each test row was executed as its own process, not a combined test discovery.

| Command | Exit |
|---|---:|
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_tick_adapters_contract.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_sdk_facade.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_sdk_loader.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_adapters.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_broker_runtime.py` | 124 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_broker_sessions.py` | 124 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_trading_readonly_coordination.py` | 124 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_market_service.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_market_wiring.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_bars.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_market_series_transport.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_page_services_r1.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_shioaji_tick_stream.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_shioaji_tick_overflow.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_shioaji_tick_reconnect.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_market_repairs.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_freshness.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_quote_stats.py` | 0 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_watchlist_settings.py` | 0 |
| `.venv\Scripts\ruff.exe check .` | 0 |
| `.venv\Scripts\ruff.exe format --check $changedPython` | 0 |
| `py -3.11 -m compileall -q $changedPython` | 0 |
| `.venv\Scripts\python.exe tools/quality_gate.py` | 0 |
| `.venv\Scripts\python.exe -m unittest tests.test_trading_architecture tests.test_docs_layering` | 0 |
| `.venv\Scripts\python.exe tools/check_trading_architecture.py` | 0 |
| `git diff --check` | 0 |
| `py -3.11 tools/quality_gate.py` | 0 |
| `py -3.11 -m unittest tests.test_trading_architecture tests.test_docs_layering` | 0 |
| `rg -n '^\s*(import shioaji\b|from shioaji\b)' quantlab tests desktop_trading` | 0 (only sdk_loader.py:16) |

Ruff emits pre-existing inaccessible-directory warnings and exits 0. Architecture
reports `0 violation(s)`; quality gate reports `0 finding(s)`. Detailed command
arguments, per-suite logs, new-module audit and exit codes are retained locally
under `.tmp-t4-slice2/`.

The three exit-124 rows are the outer verification runner's 45-second limit.
Separate faulthandler probes terminated after three seconds (Python exit 1) and
confirmed all three are blocked in `tempfile.mkdtemp`, before the affected
product code: broker runtime setUp line 45; broker sessions setUp line 145;
readonly coordination's `test_trading_coordinator.laboratory` line 38. Their
fixtures request temp directories outside the writable workspace. This is the
explicit non-blocking sandbox exception in t4-base.md; the controller must rerun
the original discovery commands outside the sandbox. No replacement tests,
skips, fixture rewrites or timeout extensions were used.
