# M2 autonomous decisions

## Market-settings prerequisite fix / owner steering — 2026-11-01 Asia/Taipei

The owner explicitly assigned the three installed 0.3.0 market regressions in
`build/codex-market-fix-prompt.md` to this work. The previously missing
`codex/fix-market-settings` prerequisite is now an implementation assignment,
not a reason to wait. This worktree starts from `origin/main` `afc45ea` and
owns that fix branch only. The coordinating agent owns complete serial
discovery, actual LOCAL/fake BROKER_SIMULATION startup, push/PR and all-green
CI. M2-1/M2-2 may continue after the fix PR and green CI under this new owner
instruction, without waiting for a main merge. No main merge or round-two
implementation is authorized here.

## Market-settings fix / boundaries and minimal changes — 2026-11-01

- Save: test the actual Qt combo and save button first. Both broker-simulation
  and LIVE selections reproduced zero save signals plus the installed error.
  Qt returns the str-enum payload as a plain string. Reconstruct Environment
  once at the UI boundary, matching the existing BrokerPanel convention;
  retain MarketDataSettings validation, secret-reference-only input and the
  existing explicit save/connect workflow. No real credential is resolved.
- Status: a disabled market panel must display the existing disconnected
  string regardless of the supplied engine-derived status or stale error.
  Add that presentation branch after loading the form fields. Enabled market
  statuses/errors keep their original behavior. Do not change bootstrap's
  market_connection projection or its other consumers.
- Empty chart: actual QPainter text-region observation reproduced legend
  overlap at the terminal's existing 90px minimum for three font sizes.
  Move the centered empty/error message below the legend only when its
  centered bounds would overlap. Preserve normal-size empty positions and
  the entire nonempty rendering path. No string/style/theme change or new
  layout abstraction is needed.
- Tests are at the owner-specified seams: real combo/button signal transport,
  panel apply/display, and actual Qt painter text bounds. No constructor-only
  substitute, safety skip, budget/timeout change or weakened old assertion.

## Market-settings fix / trading currentData audit — 2026-11-01

The audit covers every currentData call in desktop_app/features/trading:

| Consumer | Existing enum handling / conclusion |
|---|---|
| MarketDataPanel save | Missing Environment reconstruction was the reproduced defect; now fixed. |
| BrokerPanel.settings | Already reconstructs Environment. |
| TradingWindow environment navigation | Already reconstructs Environment before use. Account/context/strategy selections are string/tuple identities; settings risk is Decimal, not an enum. |
| StrategyWizard.form | Already reconstructs Market, HoldingKind and Side. Candidate/default/JSON-preview comparisons use the str-enums' value equality; no typed domain value escapes unconverted. |
| AlertRuleDialog.create_rule | Already reconstructs AlertKind. Kind/default/scanner lookup uses value equality; parameter, scope and period values are intentional strings. All twelve actual Qt kind selections create typed rules in the added regression. |
| ResearchPanel navigation | Stores ordinary page-identity strings. |

No other matching typed-boundary bug was found; do not insert redundant
internal validation or change the existing alert/wizard semantics.

## Market-settings fix / graph and verification ownership — 2026-11-01

GitNexus status initially reported no worktree index; installed offline
`analyze --index-only` completed in 166.0s with 19,473 nodes and 51,718 edges.
Worker self-healing and flow-cap warnings were retained, not treated as proof
of absent flows. Before source edits, impacts used the already indexed policy
worktree's byte-identical panel/chart sources while this index was building:
save/paintEvent UNKNOWN were resolved through direct Qt bindings and source;
apply LOW had one direct caller and three unresolved dynamic call sites.
The completed local index repeated paintEvent UNKNOWN and reported the shared
CandlestickChart class MEDIUM, 19 affected symbols / nine direct. Tests remain
required despite those graph results.

All three original feedback loops went red before their corresponding fix,
then green. Five new offline Qt regressions passed, including two saved enum
identities, disabled/error status combinations, enabled states, all twelve
alert kinds, and 18 empty/error paint scenarios. Broader focused/prepush and
pre-commit complete graph evidence will be recorded by this phase; full
discovery, real composition startup and remote CI remain coordinating-agent
checks until their actual results exist. No completion of unrun checks is
claimed.

## Market-settings fix / focused results and prepush limitation — 2026-11-01

- All five new Qt tests pass. Twelve relevant existing modules also pass:
  test_desktop_charts (12), test_market_terminal_ui (12), test_market_watch_ui
  (7), test_chart_data (15), test_chart_footer (3), test_market_empty_ui (5),
  test_alert_ui (4), test_trading_ui (32), test_market_connection (4),
  test_market_session (5), test_r7_characterization (15) and
  test_r7_function_lengths (3): 117 existing + 5 new = 122 tests. The original
  four R7 chart captures, painter-stack counts and eight result snapshots
  pass unchanged. No historical fixture re-pin is needed.
- Exact attempted command: `pwsh -NoProfile -File tools/prepush.ps1 -Tests
  -Base origin/main` from this worktree, with the provisioned root venv,
  QT_QPA_PLATFORM=offscreen, PYTHONUTF8=1 and tests/checkout PYTHONPATH.
  Ruff check/format (1,102 files), Python 3.11 syntax (1,038 tracked sources)
  and the credential/static gate (zero findings) passed. The complete
  prepush command exits 1 and is not reported as passing.
- Cause: its unchanged test selector finds only test_market_settings_fix;
  PowerShell stores the single pipeline result in a scalar string and
  `@modules` splats its characters. A harmless argv probe directly showed
  `t`, `e`, ... `.` as separate arguments; unittest raises Empty module name
  before executing tests. This is the same tools/prepush.ps1 code as main.
  Preserve the three-bug scope and do not alter the gate or conceal its
  failure. The explicitly selected module independently ran all five tests
  successfully; the coordinating agent also requires complete discovery.
- The only separate baseline/inventory change is registering the new
  127-line test module in inventory section 2. Existing module rows, catalog
  count/order, aliases, fixtures, protected files and limits remain unchanged.
- Final offline index refresh completed in 46.8s (19,487 nodes / 51,748 edges).
  Complete pre-commit graph analysis reported 18 symbols / six files / LOW,
  with no partial or truncation flag. Required repo-layout (29) and document
  layering (8) tests also passed, bringing focused verification to 159 tests
  in 15 actual modules; the dependency-layer gate reported zero findings.
  Final commits and the coordinating agent's full/startup/remote checks retain
  their actual evidence separately.
