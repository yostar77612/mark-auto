# C5: Market overview dock workspace

Status: IMPLEMENTED; focused automated verification passed.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
Requirement: Shioaji borrowing list, second part, section 1.3 row C5;
sections 0 and 0.1 and the first-part global limits apply.

## Implementation

[MarketWorkspace](../../desktop_market_workspace.py) supplies equivalent dock
panels around the existing instrument cards, watchlist controls and chart
controls. Stable panel IDs are `cards`, `watchlist`, `chart`; objectNames are
`market_dock_<id>`. Public dashboard references and original content objectNames
remain intact. There is one chart, one watchlist and one set of cards.

Drag a panel title onto another panel to dock at that panel's area/position.
Tab reaches each title menu: Enter/Space opens its actions, C collapses/reopens
its content, and menu actions dock above/left/center/right/below or reorder.
Collapsed titles show [+]; retained content is hidden rather than destroyed.
No child event filters, recurring timers or per-event child searches are added.

The visible layout menu offers apply preset, save as, named restore/delete and
reset. Exactly three stable preset IDs exist: `overview`, `chart_focus`,
`watchlist_focus`. Overview preserves the old cards-above/watchlist-left/chart-
center structure and approximate 190:740:230 proportions including side controls.
Chart focus collapses cards and uses 120:810:230; watchlist focus uses
460:470:230. Reset always applies overview. Titles use shared theme properties;
keyboard controls inherit theme foreground/background and a token-based focus
border. Strings use literal catalog keys. Safety, source/stale status and the
live-disabled notice remain outside the collapsible panels.

## Persistence and validation

[LayoutStore](../../desktop_market_layout.py) uses only
`<settings parent>/display_profile/market-layout-v1.json`, beside DrawingStore.
The mount reads persisted state once; a bare dashboard or missing settings path
uses memory only. Only explicit named saves/deletes write the file. Preset,
restore and reset actions never rewrite it. No layout name is a filesystem path.

The version-1 document has exactly `version`, `current`, `layouts` keys.
`current` and each named layout have exactly `version`, `panels`. All three
panel IDs are required, each with exactly `area`, `position`, `size`, `collapsed`.
Areas are top/left/center/right/bottom; position is an integer 0..2; size is a
strict integer clamped to 80..2000; collapsed is a boolean. Booleans/floats/strings
are rejected for integer fields. Names are 1..64 trimmed characters, reject path
separators/control characters and reserved simple names; at most 20 layouts and
128000 input bytes are accepted. Unknown fields/IDs, incomplete panels, unsupported
versions, invalid JSON/UTF-8 and missing files fall back to overview without a
modal dialog or rewriting/deleting the source. A bad named entry is isolated;
valid siblings remain loadable, and selecting a missing/invalid name resets to
overview. No observations, market inputs, credentials, research or data hashes
are serialized. Content is never executed.

Saves flush/fsync a temporary file in the same directory, then `os.replace` it.
On failure, the old file and in-memory names survive, temporary files are removed,
and an inline B1 `operation_failed_local` message appears, with no exception
text/path. No second error table is introduced.

## Data and safety boundary

Layout operations only reparent retained panels, set content visibility and
splitter sizes. They never emit refresh/sample/preferences/render intent, fetch,
start jobs, ask for consent, load caches, set series or rebind chart layers.
Instrument/timeframe selection, watchlist order/selection, indicator preferences,
chart bars and overlays survive unchanged. Existing refresh consent (default No)
and `ui_market_refresh` opt-in payload remain unchanged.

Live trading remains permanently disabled. No order, engine, G3, frozen profile,
Decimal, OOS/final-holdout, budget, gate or timeout changes are made. No credentials
or protected data were read or delegated. PROJECT_STATE and acceptance scores
remain untouched.

## Verification and remaining checks

The focused C5 suite covers identity, presets/idempotence, keyboard actions,
collapse/reopen, save/restore/overwrite/delete, bounds/type validation, corruption,
atomic failures, startup, in-memory hosts, artifact byte/hash isolation, no-data-
flow sentinels and 50 preset applications followed by widget destruction.
The extended accessibility walk and unchanged scaled-layout checks pass.
Offscreen tests are evidence for behavior, not a visual-quality claim.

The implementation sandbox could not run the real desktop startup smokes; the
controller ran them outside the sandbox and they pass. The two new root modules
are tracked, so the repository-layout inventory passes. GitNexus analyze failed
in the sandbox (spawn EPERM); the main-repository graph was used only as limited
navigation evidence followed by direct source reads.

The intentional new title/menu controls required a separate fixture
refresh under `tests/fixtures/desktop_pages_before`: `metrics.json`,
`06_full.png`, `06_viewport.png`. The refresh landed as a separate fixture-only commit after the implementation commit.
The stylesheet digest assertion is re-pinned for the new QToolButton focus rule;
all assertions remain. Widget-name additions are additive.

Real-App drag, keyboard menus, both themes/enlarged fonts, shrink reachability,
named restore and chart continuity remain PENDING USER FINAL CONFIRMATION.
Rollback removes workspace composition and ignores the display-only file.
The implementation is one commit; the baseline refresh is a second, fixture-only commit.

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
B4's exact baseline assertion passes after that separate fixture-only refresh,
which changes only the two market PNGs and the market metrics. Real-App visual
check remains PENDING USER FINAL CONFIRMATION.
