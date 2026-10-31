# M1-U delivery record

Status: IMPLEMENTED (offline verification). Real-App owner visual confirmation
remains pending. Date: 2026-11-01 Asia/Taipei.

## Autonomous decisions

- Keep the existing five persisted workflow completion facts and derive its
  order/captions from the same page identity definitions as the sidebar. The
  comparison page is visible again. Partial completion now leaves the strip
  visible, so completed/current/pending states can be read; explicit dismissal
  and all-completed hiding still reclaim the strip's height.
- Preserve `research_mode_status` as a hidden, owned compatibility control;
  the visible help entry is `onboarding_help`. The old accessibility identity
  and explanation-expansion behavior remain, and existing tests still verify
  them. No visible duplicate help checkbox remains.
- U9 uses Qt native arrows through a small shared disclosure constructor;
  saved section keys, checked state, focus and widget ownership stay intact.
- U11's actual four-entry task selector is in redesign_strategy_layout.py.
  Retain existing QPushButton identities/keyboard commands and render all four
  as tabs with an underline and muted selected background. No action logic or
  strategy eligibility changed.
- U13 moves the original detailed labels into a click-open dialog and exposes
  a single-line summary. The original labels/objectNames and text remain.
  `test_trading_ui` now opens that dialog before the original visibility/content
  assertions, adding compact-header visibility and <=48px checks. This updates
  the intentional presentation contract without removing coverage.
- U3's earlier tests required hiding after any single completed step. That
  conflicts with the new requirement to show finished/ongoing/pending states.
  Those assertions now require partial progress to remain visible and retain
  the original dismissal/height-reclamation checks. No safety assertion changed.
- U6 places the prerequisite on its own full-width card row. Shared accessibility
  may enable label wrapping; it no longer gets confined beside the button.
- All modifications are presentation only. There is no SDK login, account/CA
  access, execution operation, user-data deletion, G3/PROJECT_STATE/SDK version
  change, budget/timeout relaxation or acceptance-score change.

## U1-U13 screenshot evidence

All seven research pages were captured before/after using
`tools/ui_snapshot.py --size 1366x768`. Each directory includes full-page and
viewport PNGs plus metrics.json. Snapshot inputs are disposable offline data.

| Item | Result | Before / after image under docs/analysis |
|---|---|---|
| U1 | Known missing glyphs removed; numeric cells use CJK-capable font; catalogue scan test | m1-u-before/06_viewport.png / m1-u-after/06_viewport.png |
| U2 | Native inner focus outline removed; focus border on navigation container | m1-u-before/01_viewport.png / m1-u-after/01_viewport.png |
| U3 | Sidebar order/captions, page-id navigation, three states/current marker | m1-u-before/03_viewport.png / m1-u-after/03_viewport.png |
| U4 | One visible help entry, passive research badge, redundant ready line hidden | m1-u-before/01_viewport.png / m1-u-after/01_viewport.png |
| U5 | Full short headers with original tooltips and visible empty explanation | m1-u-before/04_viewport.png / m1-u-after/04_viewport.png |
| U6 | Backtest prerequisite below the action on a full-width card row | m1-u-before/03_viewport.png / m1-u-after/03_viewport.png |
| U7 | Backtest strategy name uses the strategy form's Chinese family labels | m1-u-before/03_viewport.png / m1-u-after/03_viewport.png |
| U8 | One replay-length caption and unchanged spinbox/accessibility | m1-u-before/05_viewport.png / m1-u-after/05_viewport.png |
| U9 | Advanced controls share native arrow/checkable style | m1-u-before/05_full.png / m1-u-after/05_full.png |
| U10 | Help icons placed at page-title right | m1-u-before/03_viewport.png / m1-u-after/03_viewport.png |
| U11 | Four strategy entries render as tabs | m1-u-before/02_viewport.png / m1-u-after/02_viewport.png |
| U12 | Prepare is sole primary until prerequisites; run becomes primary when ready | m1-u-before/03_viewport.png / m1-u-after/03_viewport.png; test_m1_ui_defects |
| U13 | Single-line <=48px trading context; click-open original details | m1-u-before/08_trading_header.png / m1-u-after/08_trading_header.png / m1-u-after/09_trading_details.png |

The seven viewport images were inspected; the backtest, comparison, strategy,
paper and trading header/details show the changed presentation. Real-App visual
confirmation is pending the owner, as specified.

## Verification

Environment: root `.venv/Scripts/python.exe`, PYTHONUTF8=1,
QT_QPA_PLATFORM=offscreen, PYTHONPATH=tests. Each suite runs independently.

- test_m1_ui_defects: 6 passed.
- test_onboarding_c2: 7 passed.
- test_t9_onboarding: 5 passed.
- test_desktop_ui_polish_a: 5 passed.
- test_desktop_ui_polish_b: 5 passed.
- test_ui_redesign_strategy: 12 passed.
- test_trading_ui: 32 passed.
- test_desktop_theme: 4 passed.
- test_compare_table: 6 passed (including original Taipei/descriptive-Sharpe assertions).
- test_help_compact_u2: 2 passed (including original fixed size/stretch/privacy checks).
- test_market_series_transport: 8 passed after setting PYTHONPATH=tests.
- test_windows_long_paths: 9 passed after setting PYTHONPATH=tests.

Initial `powershell -File tools/prepush.ps1 -Tests` ran 275 tests: exit 1.
Ruff check/format, Python 3.11 syntax scan and quality_gate passed. Three
presentation failures were corrected with all original assertions retained.
Two imports needed the existing tests directory on PYTHONPATH and then passed.
Three symlink cases require the host privilege absent here (WinError 1314),
and three retained-process-handle cases fail with the venv Python redirector.
The same symlink and handle failures were reproduced on detached origin/main
`ba597b5`, without changing that checkout's source. Per windows-native-testing.md,
the actual base interpreter was also tried: its installed third-party `tests`
package shadows the repository's namespace. Explicit paths/discovery failed
import; `-S` with explicit existing dependencies ran 26 original tests, but the
three child-process cases re-enter that base environment and still fail before
their readiness barrier. These remain host-environment failures, not passes;
no skips, deadlines, permissions or assertions were changed to manufacture success.

Final rerun with PYTHONPATH=tests: 290 tests executed in 71.488s, 284 passed;
only those 3 symlink errors and 3 retained-handle failures remain. Exit 1 is
reported honestly. Ruff check, Ruff format (1033 Python files), py -3.11 syntax
scan (980 tracked Python files), quality_gate (0 findings), check_layers
(0 findings) and git diff --check all passed. Exact stage command:
`powershell -File tools/prepush.ps1 -Tests`; interpreter selected by the existing
script is `C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe`.

Shared UI entrypoint pre-edit impact is CRITICAL: install_onboarding,
_build_window_chrome, apply_theme, help_button, choose_mode and build_strategy
reach 49-126 processes/20 modules. Changes remain in presentation; existing
UI content, keyboard and safety behavior tests above cover the affected paths.
Methods unresolved by the graph were confirmed through direct source/rg reads;
UNKNOWN was not treated as an all-clear. Full prepush/layer/detect result follows
in this PR's validation record.

GitNexus detect_changes(scope=all, worktree=this checkout) returned 57 changed
symbols, 13 affected flows across 58 files, HIGH risk, with neither partial nor
truncated flags. All connect/strategy/help/formatting flows in that report were
reviewed against the source and tests above. The analyser's broader unresolved
dispatch/process coverage warnings remain limitations; graph results do not
replace runtime verification.
