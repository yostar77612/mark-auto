# M1-2 implementation handoff

2026-11-01 02:10 Asia/Taipei. This is the M1-2 worktree record for consolidation
into `m1-decisions.md`, `IMPLEMENTATION_CONTRACTS.md` and the final run report.

## Autonomous decisions

- Retain the interrupted terminal/search/layout implementation and complete it.
  The legacy `MarketWatchWidget` remains available with its objectNames and tests;
  its visible periods are now 1m/5m/15m/1d and the query API remains unchanged.
- Supply the existing C5 `WorkspacePanel` and appearance colors from
  `trading_runtime.py`. Presentation does not import an adapter or the research
  workspace's infrastructure dependencies. `LayoutStore` adds panel/area/file/
  default parameters while preserving all original defaults and file name.
- Terminal layouts use `market-terminal-layout-v1.json`; named presets, keyboard
  movement/collapse and drag handles retain C5 behavior. Unsupported terminal
  areas are rejected at the JSON boundary through the store's `areas` argument.
- Serialize chart-selection requests and coalesce pending selections so the last
  user action owns the temporary subscription. An initial asynchronous preference
  read cannot override a newer selection. Stale series results never repaint the
  newly selected instrument, and pending history retries preserve their intent.
- Read the final index page before selecting the newest trading date. Fetching
  only the first year-history page would otherwise show an old day. Identical
  chart data preserves the user's viewport; alert selections focus their UTC time.
- Add `CandlestickChart(show_volume=False)` only for the index mini chart; its
  default remains True. Existing chart and C5 tests pass unchanged.
- Display prices using `MarketWatchView.price_tick` when provided by M1-1. Until
  tick metadata is known, use the ordinary Taiwan stock bands and index decimals.
  Missing index turnover remains unknown. All arithmetic remains Decimal.
- Draw the search magnifier with Qt primitives; the emoji glyph was missing in
  the Windows offscreen renderer. Load Windows CJK fonts explicitly for snapshots,
  matching `tools/ui_snapshot.py`. No raster image generator is needed.
- The Windows restricted file runner hangs in `NamedTemporaryFile` while writing
  layout metadata. A faulthandler trace identified that exact boundary; running the
  same offline tests with normal file access passes. No test was skipped or weakened.

## Behavior contract for M1-2

The market workspace is a terminal without an outer scroll area. The fixed search
and status rows surround four movable panels: quotes, alerts, chart and index.
Directory search normalizes fullwidth text and case, ranks exact code / code
prefix / name prefix / contains, debounces 150 ms, caps results at twenty, and
supports mouse, arrows, Enter and Escape. Choosing a result only changes the chart.

The chart remembers each instrument's period for the current run. Watch toggles
use the existing settings command, retain subscriptions during promotion and give
a five-second full-list message. The six quote columns support numeric sorting,
default watch order, localized unknown values, sign/percent formatting, volume
separators, color preferences, tooltips and no horizontal scrollbar. Diagnostics
show Taipei time and the separate market-data environment's Chinese source name.
Status text bounds non-live instrument summaries to three and shows usage or
unknown, subscription counts and available watch capacity.

## Verification performed

All commands run from `.worktrees/m1-terminal` with `QT_QPA_PLATFORM=offscreen`.
Interpreter/tool path is the provisioned root `.venv/Scripts/`.

| Command | Result |
| --- | --- |
| `python -m unittest tests.test_symbol_search` | 2 passed, exit 0 |
| `python -m unittest tests.test_market_terminal_ui` | 9 passed, exit 0 |
| `python -m unittest tests.test_market_workspace_c5` | 11 passed, exit 0 |
| `python -m unittest tests.test_market_watch_ui` | 7 passed, exit 0 |
| `python -m unittest tests.test_trading_ui_market_watch` | 5 passed, exit 0 |
| `python -m unittest tests.test_desktop_charts` | 12 passed, exit 0 |
| Ruff check/format on changed Python files | exit 0 |
| `python tools/check_layers.py` | 0 findings, exit 0 |
| `python -m tools.m1_terminal_snapshot --out docs/analysis/m1-terminal` | exit 0; both sizes, no unlabeled inputs |

Root performs the one full prepush pass, strict v2 gate, final integrated tests,
contract append, design status update and stacked PR publication. This worktree
does not claim those final integration checks passed.

GitNexus impact was run for retained/modified classes, helpers and methods before
editing. Resolved class risks: CandlestickChart MEDIUM (17 dependents),
LayoutStore LOW (5), validate_layout LOW (11), WorkspacePanel LOW (7),
MarketWatchWidget LOW (8), `_market_page` LOW (2, build flow), `_run_window`
LOW (3), `_paint_chart_bars` LOW (1, paintEvent). New/partially indexed methods
return UNKNOWN/not-found; direct source/reference searches confirm their local
terminal callers, Qt callbacks and injected composition, without calling them
unused. No HIGH/CRITICAL symbol edit was identified. `detect_changes(scope=all,
worktree=...)` ran without partial/truncated; repeat after staging precedes commit.
The post-staging result maps 39 symbols and seven presentation processes with
aggregate HIGH risk (completion callbacks, colors/formatting, view/submit and
diagnostic strings). Source review and the listed real-widget tests cover these
flows; the index still maps some retained callback lines from the interrupted
version. Copied, unstaged M1-1 contracts are included in the all-scope report but
excluded from the actual M1-2 commit.

## Integration notes and limitations

- Dependencies copied for tests only, excluded from this commit:
  `domain/watch.py`, `application/market_settings.py`, `application/contracts.py`.
  They belong to M1-1's connection commit. M1-2 is stacked on M1-1.
- Root's facade supplies `symbol_directory()`, `market_preferences()`,
  `select_market_instrument(id, period)`, `market_status()`, `market_series()`.
- Root wires BrokerPanel market signals after stacking connection changes; this
  worktree cannot add them before the required BrokerPanel dependency exists.
- M1-3 replaces the alerts placeholder and registers its strings after stacking.
  Register phase 57/58 only with their corresponding string modules present.
- Existing chart legend missing-glyph correction belongs to M1-U. Regenerate the
  screenshots on the final integrated head after that correction if appropriate.
- Real App visual inspection, broker login, market permissions, actual quota and
  subscriptions remain pending owner verification. No SDK login or credential
  resolver was called by any test or screenshot.
