# M2 autonomous decisions

## M2-0 / prerequisite evidence — 2026-11-01 12:04–12:12 Asia/Taipei

- Evidence supplied by the coordinating agent: after `git fetch origin`, main
  was `0453136`; specification PR #124 was OPEN at `07d3cc9` on
  `origin/claude/m2-spec`. Both `gh pr list --state all --head
  codex/fix-market-settings` and `git ls-remote --heads origin
  '*market-settings*'` returned no matching prerequisite.
- Decision: start only independent M2-0 and M2-6. M2-1/M2-2 remain unstarted
  until explicit merge evidence for the market-settings prerequisite is
  available. Do not infer completion from a missing branch or merge main.
- Scope: this worktree owns only M2-0. The specification remains implementation
  guidance, not evidence that M2 execution features have been delivered.

## M2-0 / D1 policy and historical boundaries — 2026-11-01 Asia/Taipei

- Authority: owner decision D1 dated 2026-11-01 in
  `origin/claude/m2-spec:docs/design/m2-sinopac-sim-auto-trading-spec.md`.
- Alternatives: retain the old product-wide permanent prohibition; suggest an
  immediate LIVE toggle; or distinguish the v1 research/Paper contract from
  the authorized v2 roadmap. Choose the last: production orders are disabled
  by default, future enablement needs a separate explicit owner decision,
  and M2 continues to hard-disable production orders. The v1 real-order ban
  remains permanent. SinoPac simulation orders are authorized for subsequent
  M2-2 implementation and verification, not enabled by this policy-only PR.
- Update README, contributor safety/mission guidance, the upgrade contract,
  all six ADR policy statements, the glossary and PR risk checklist. Preserve
  historical dates, evidence, budgets, scopes and immutable records. Append
  the current policy to IMPLEMENTATION_CONTRACTS without rewriting its frozen
  historical contracts.
- The passive banner has two existing, deliberately equivalent records:
  `ui.init.research_mode_banner` and `header.live_disabled`. Apply the single
  authorized wording delta, `研究模式・實盤停用` → `研究模式・正式下單停用`, to both;
  do not add or renumber catalog/alias records. Existing HeaderTests require
  equality. Retain the original `ui.__init__.text_3` alias and all provenance.
- Baseline updates belong to a separate commit with this D1 reason. Preserve
  historical source identities and exact unchanged values; admit only this
  banner delta and the ADR safety-policy phrase. Do not regenerate fixtures,
  accept arbitrary current inventories, remove tests or relax safety checks.
- Verification status: focused checks pending during implementation. The
  coordinating agent owns serial full discovery, isolated LOCAL/fake
  BROKER_SIMULATION launch checks, push/PR creation and remote CI. No passing
  full suite, actual broker verification or CI result is inferred here.

## M2-0 / graph and focused verification — 2026-11-01 Asia/Taipei

- Worktree/base: `.worktrees/m2-policy`, `codex/m2-0-policy`, main `0453136`.
  Installed GitNexus 1.6.12 `status` initially reported no index. Offline
  `analyze --index-only` completed in 100.8 seconds with 19,448 nodes,
  51,674 edges and 629 reported flows. Its process-extraction cap warnings are
  not interpreted as proof of absent flows. No extensions were downloaded.
- Upstream impact ran before editing both string ENTRIES records and the
  affected ADR/glossary/alias/R7 test methods. Each reported UNKNOWN/zero
  resolved callers. Direct source and text searches confirmed the static
  translation_parts → catalog_data → catalog assembly, AppHeader badge and
  disclosure consumers, exact header-equality assertion, and unittest
  discovery methods. UNKNOWN was resolved with that evidence, not read as low.
- Source graph change analysis completed: 24 symbols in 14 tracked files,
  zero reported affected processes, low risk, no partial/truncation flag.
  This bounded graph result supplements direct diff and tests.
- Pinned Ruff check/format passed for both changed Python source files.
  `python -m unittest discover -s tests -p test_header_c1.py -v` passed all
  six tests in 2.041 seconds. Exact baseline assertions are intentionally
  updated only in the following, separate D1 baseline commit.


## M2-0 / completed verification and owner follow-up — 2026-11-01T14:57+08:00

- The owner's follow-up assigns the absent market-settings prerequisite to
  this run and permits dependent implementation after its own green CI,
  without a main merge. PR #129 reached all35 SUCCESS on run41279585267,
  attempt2, exact2d8319b. M2-1/M2-2 now proceed in separate worktrees.
  This supersedes the initial wait-for-merge decision; it does not enable
  LIVE or authorize second-round automatic trading.
- Final complete M2-0 discovery on unchanged97e2a8b: 3,888 tests in 2,380.898 s; FAILED (failures=10, errors=27, skipped=42).
  No new failure identities; all actual traceback differences were reviewed.
  Preserve the nonzero main-host result honestly. The initial new smoke-marker
  failure passed on this complete unchanged retry; the separate incomplete
  permission-loop attempt is excluded rather than called a pass.
- Use normal user execution for later full suites after diagnosing the
  restricted-run tempfile retry. Do not change test limits, Windows policy,
  ACLs, application code or dependencies to hide that harness mistake.
- Actual LOCAL and fake BROKER_SIMULATION windows returned0 and released their
  owned resources. Source PR128 had35/35 CI success; final documentation-head
  CI is verified separately before delivery. Evidence and limitations are in
  docs/analysis/m2-policy/verification.md and its companion files.
- This commit adds verification documentation only. No product/test/fixture
  behavior, G3 source, SDK pin, PROJECT_STATE or acceptance score changes.

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

## Market-settings fix / final frozen-source evidence — 2026-11-01

The coordinator verified source head
`34673c269e80ecdc2f9a707e77b22df2fe28e0f2` with complete serial discovery:
3,893 tests in 2,094.353s, 10 failures, 27 errors, 42 existing skips. Main 0453136
has 3,888 tests in 1,968.015s with 10 failures, 27 errors, 42 skips. All 36 failing
IDs are preexisting and there are no new IDs; this local suite is nonzero,
not a pass. Of 37 occurrences, 36 match ordered traceback frames/types. One
unchanged standalone native retained-handle case reaches a different native
assertion (already signaled 0 rather than WAIT_TIMEOUT 258); its exact cause
remains unresolved. E06's same primary PID mismatch has secondary cleanup
WinError 5 on .sqlite-shm instead of main's WinError 32 on .sqlite. Preserve
these limits; do not call every failure's underlying cause identical. An
incomplete extra main replay is excluded from passing/count/cause evidence.

Actual run_window returning 0 checks at this source passed: LOCAL 12.183s and fake
BROKER_SIMULATION 6.173s, each with 7 embedded research pages/2,726 widgets,
clean engine/research release and no real SDK import. Fake broker counts
were 1 login/1 logout/2 subscriptions/0 order constructors/0 orders; broker
financial facts remained unknown. The full-suite-owned wrapper 153036 and
native child 230124 were normally authenticatedly shut down and both exited.
No user application or data was altered.

The new origin/main UI guidelines section 10 was read without merging main
or changing verified source. Real-window fake-facade captures at 1366×768
and 1920×1080 plus 90px empty-chart details were visually inspected. The changed
group has readable controls, no horizontal scrollbar, labeled/named inputs
and buttons, and actual Tab order environment→reference→save→connect→disconnect.
Disabled settings still show 未連線 when supplied a stale CONNECTED value/error.
The isolated capture records 0 commands/0 child processes/no SDK import.

Final screenshots, focused/static limitations, exact startup JSON and bounded
failure comparison are in
[market settings verification](../analysis/market-settings-fix/verification.md).
This evidence commit changes only documents/captures, retaining all product,
test, theme and tool bytes at the frozen source. Existing page architecture,
strings and general UI redesign are outside this three-defect fix. Remote
CI is still pending and required independently before M2-1/M2-2 begin.
Final document/layout checks passed: 37 tests in 4.645s. The offline index
refresh completed; complete change analysis reported 10 document symbols,
12 evidence files and LOW risk with no partial/truncation flag. No graph
absence is used to waive tests or the full-run native-cause limits above.
