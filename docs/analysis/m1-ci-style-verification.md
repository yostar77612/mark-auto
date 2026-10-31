# M1-2 CI style correction (2026-11-01 03:42 Asia/Taipei)

This correction is isolated in `codex/m1-ci-style-work`, based on the published
M1-2 branch. It does not modify fixtures, test limits, G3 files or existing
assertions. No full suite was started while the controller's main suite ran.

## Cause and decision

The existing no-inline stylesheet guard found four new calls: three in the
terminal renderer and one on its period buttons. B11's public/class test invokes
that guard before checking the research MainWindow, so the failure did not imply
a broken public API or class limit. MainWindow remains 144 lines and the terminal
class remains 294 lines with its original twenty methods.

The terminal now sets semantic properties for period, freshness and direction.
Private helpers in `desktop_app/shell/theme.py` own its scoped selector rules.
The composition root injects the style callback, preserving the trading UI's
dependency boundary. Existing callers may omit the callback. The ordinary theme
refresh traversal updates terminal labels and table colors immediately when
appearance or rise/fall convention changes, without waiting for another tick.
Unknown numeric values retain their existing gray treatment.

Legacy app and research-market stylesheet builders remain byte-identical. Their
default SHA256 values are:

- App: `f4bc1159f8d0113902449efb3a34e7340ba40a422037bbd379d82109cd053b2e`
- Market: `7ce3a6cb5bc9c2c0eab3fdffc4fc4139327db3a3e9c546661f1b0ef5cde205cf`

No baseline update is needed for this correction.

## Verification

Using the provisioned root `.venv/Scripts/python.exe`, with
`QT_QPA_PLATFORM=offscreen`, each listed command exited 0:

- `python -m unittest tests.test_no_inline_stylesheet.NoInlineStylesheetTests.test_desktop_and_tools_have_no_inline_stylesheet`
  (first run failed on the four calls; the corrected run passed).
- `python -m unittest tests.test_market_terminal_theme` (3 tests).
- `python -m unittest tests.test_market_terminal_ui` (12 unchanged tests).
- Selected cases, 6 tests total:
  `tests.test_b4_appearance.AppearanceTests.test_live_convention_candles_cells_pnl_market_and_legend`,
  `tests.test_b4_appearance.AppearanceTests.test_chart_offscreen_background_and_palette`,
  `tests.test_b4_appearance.AppearanceTests.test_theme_change_keeps_styles_and_ui_text_centralized`,
  `tests.test_desktop_theme.DesktopThemeTests.test_tokens_and_complete_selectors`,
  `tests.test_desktop_theme.DesktopThemeTests.test_apply_and_status_refresh_offscreen`,
  `tests.test_ui_operations_registry.RegistryTests.test_public_names_unchanged`.
- Ruff check/format on changed Python files, `tools/check_layers.py` (0 findings),
  `tools/check_trading_architecture.py` (0 violations), `git diff --check`.

## GitNexus evidence

The new worktree's git root was confirmed. `status` reported no index, then
`analyze --index-only` completed in 72.9 seconds with 18,998 nodes and 50,770
edges. It did not download FTS extensions or rewrite AGENTS/CLAUDE. Analyzer
warnings about unresolved Python receiver types and bounded process discovery
remain limitations; missing paths are not treated as unused.

Every query and impact used this explicit worktree as `repo`. Before editing,
the exact render method UID reported **HIGH**, 9 dependents/3 processes
(`capture_terminal`, `capture_window`, asynchronous completion), with thirteen
unresolved receiver calls. `apply_theme` reported **HIGH**, 16 dependents and
the readability-audit process. These warnings were communicated before edits;
the new selectors are scoped to the terminal and unchanged legacy theme paths
were checked with focused tests. Constructor/snapshot entry points and new
private helpers were UNKNOWN; direct source references confirmed composition,
CLI dispatch, Qt callbacks and tests. Class/chart-panel/runtime entry impacts
were LOW (7/2/3 dependents respectively).

Pre-commit `detect_changes(scope=all)` is run against the explicit worktree after
staging; a result with partial/truncated is not accepted. The controller retains
the serial U → M1-1 → M1-2 → M1-3 merge and final CI responsibilities.

The completed staged result mapped 9 symbols and 16 presentation/theme processes,
with aggregate **CRITICAL** risk and no partial/truncated flags. Those processes
are the two snapshot entry points, terminal completion/rendering and appearance
application/readability auditing. The scoped-selector and unchanged-legacy tests
above are the targeted mitigation; this does not waive the aggregate warning.
