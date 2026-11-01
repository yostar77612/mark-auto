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

## 2026-11-01 12:20 Asia/Taipei — M2-6 first-round trading page

- **Environment authority:** reuse the existing settings `environment` selector,
  `_environment_selected` and `UiAction.SWITCH_CONTEXT`. The new
  `trading_environment` mirrors accepted `UiState.environment`. Both selectors
  revert immediately while a switch is pending; rejection/unavailable accounts
  retain the old book and environment. No new DTO, session or backend settings.
- **LIVE UI safety:** reject the current order-capable UI intents DEPLOY, STEP,
  RESUME, CANCEL_ENTRIES and FLATTEN at `TradingWindow.command`, and disable their
  controls. STOP_NEW and RECONCILE remain usable. This is UI protection only;
  M2-2 must implement the engine/gateway LIVE invariant and extend the independent
  intent inventory when it adds manual order actions. No SDK/login/order test ran.
- **Layout:** preserve all twelve position columns and their original values.
  Keep the first column sized to actual contents; stretch the other columns,
  shorten headings with original-heading tooltips and preserve full cell text in
  tooltips. Full-data geometry tests require a zero horizontal scroll range,
  complete first-column text width and all columns inside the viewport at 1366.
- **Styles:** put scoped LOCAL grey-blue, SIM green and LIVE red rules only in
  `desktop_app/shell/theme.py`; apply them at `_run_window` composition. Feature
  widgets set semantic properties without importing the shell or adding inline
  QSS. Historical stylesheet builders and import gates remain unchanged.
- **Delivery:** performance comparison is explicitly deferred to round two,
  as permitted by M2 specification section 7. No M2-3/4/5/7 work is included.
  Full-suite runs, actual LOCAL/SIM fake-SDK startup, push/PR and CI are owned by
  the root coordinator and remain pending this focused delivery.
- **Catalogue:** phase 61 orders 2753–2775 add exactly 23 keys. Pin current
  catalogue output and the exact count in a separate baseline-only commit;
  retain all historical values, aliases, identity checks and assertions.
- **Graph:** explicit-worktree command impact is CRITICAL (13 known upstream,
  eight flows, 22 unresolved receivers); catalogue/theme File risks are CRITICAL,
  translation-parts HIGH. Page/render/startup changes are LOW; signal dispatch
  and new helpers are UNKNOWN and were checked by text and direct source.
  Index flow/callable candidate caps remain a limitation; tests supplement them.

Affected sources: trading `trading_page`, `workspaces`, `window`, `rendering`;
shell `theme`; strings `m2_trading`, `catalog`, `translation_parts`;
`trading_runtime.py`. Offline evidence is in `docs/analysis/m2-trading/`.

### Follow-up boundary verification — same delivery

- Reproduced a nested-confirmation poll emitting the inconsistent tuple
  `(LOCAL, sim-futures, sim)`. Capture the requested environment together with
  account/context before either confirmation, so an accepted-state poll cannot
  change only one field. The exact failing scenario now passes.
- Accepted-state selectors initially blocked first broker-profile import in a
  LOCAL-only registry. `add_context` now explicitly asks SIM or LIVE when current
  state is LOCAL, then uses the unchanged file chooser and ADD_CONTEXT boundary.
  It never uses a hidden pending target. Cancelling either choice emits nothing.
- STOP_NEW is not universally state-only: normal executable contexts also cancel
  entry orders. Preserve that original LOCAL/SIM caption and scope; in the current
  read-only LIVE context show only “停止新倉” and explain the local stop flag.
  M2-2 must still verify STOP_NEW in its complete engine/gateway LIVE inventory.
- `_switch_context` pre-edit impact LOW; `add_context` UNKNOWN, confirmed by its
  workspace button reference and source. Added independent regression coverage.

## 2026-11-01T12:30+08:00 — first-round PR stack and merge

- Merge M2-0 into M2-6 with a normal merge, preserving both source and separate
  baseline commits. M2-6 will target `codex/m2-0-policy`. This removes the
  competing new decision files and retains one exact text/catalog baseline.
- Preserve the common frozen implementation contracts byte-for-byte, then append
  both M2-0 and M2-6 contracts. Preserve both phases' decision history below one
  document heading. No new product behavior is introduced by conflict resolution.
- The catalog combines D1's two approved existing badge changes with M2-6's
  23 additive records (orders 2753–2775). All other existing records, aliases,
  historical identities and exact test assertions stay intact.
- Run full discovery and both actual LOCAL/fake BROKER_SIMULATION startup checks
  on the combined source before pushing M2-6. M2-1/M2-2 remain unstarted because
  the expressly required market-settings merge is still absent; no main merge,
  history rewrite or second-round work is authorized here.

## 2026-11-01 13:17 Asia/Taipei — owner-added M2-6 items 6–8

- The owner expanded this same first-round branch with real Taipei dates,
  first-start overview presentation and plain-language explanations. Normally
  merged documentation-only main `afc45ea` as `12e484e`; no history rewrite.
- Today comes from aware UTC converted through `Asia/Taipei`, independently of
  `UiState.trading_day`. LOCAL labels both dates explicitly; broker environments
  show only today in the compact header/tooltip. Same-version market-only updates
  refresh the date so midnight cannot leave yesterday's label behind. Existing
  detailed book metadata remains available through the context dialog.
- A real fresh `build_runtime(RuntimeLaunch(...))` snapshot has version1 and the
  sole `startup_reconciliation_required` event. Only this empty LOCAL state,
  without strategies/exposure/issues/reconciliation differences, is neutral.
  The real reopened book has version2/two startup events and still warns. UI
  tests also retain warnings for populated/stopped/failed cases. Rendering never
  marks the engine reconciled, resumes it or clears any issue.
- The empty strategy label is hidden in favor of an explicit first-strategy
  button, routed to the strategy workspace and the existing wizard. The new CTA
  changes Dashboard's exact QPushButton inventory from four to five; the separate
  baseline binds all five names/count, not a relaxed button budget.
- Complete former explanations remain in plain-text, keyboard-accessible owned
  QDialogs; short summaries stay visible. This avoids transient popup ownership
  and retains original safety/valuation text. Performance comparison stays in
  round two; only its two technical column captions become plain language.
- Move dashboard's existing inline red/light styling into scoped shell QSS so
  neutral first-start colors and actual warnings can coexist. Theme File impact
  remains CRITICAL; other named flows are LOW, constructor/dynamic dispatch
  UNKNOWN verified against source/call sites. Graph parser/trace caps remain
  acknowledged; no shared-axis risk waiver or import-gate change.
- The overview's existing cancel-entry control now follows the same LIVE UI
  disable rule as its trading-page counterpart; both stop buttons use the precise
  LIVE read-only caption/help. No backend execution capability changes.
- Add 20 literal catalogue keys at orders2776–2795 (total2796); all43
  M2-6 keys across the two slices are additive, with original aliases unchanged.
- The owner assigned the market-settings prerequisite to the root team. M2-1/2
  can stack after that fix's CI is green; they are no longer waiting on another
  person. They remain outside this UI work. The later M2-9 doc addition is
  explicitly second-round and is not implemented here. M2-8 is another owner.
- The old queued M2-6 full run was cancelled before starting. Root will rerun
  complete discovery and both actual LOCAL/fake-SIM starts on the final head.
  The prior79fc99c startup/full-check evidence does not validate this new source.

### 2026-11-01 — M2-6 scoped adoption of merged UI guidelines (PR127)

- Owner explicitly authorized this follow-up before the first M2-6 full run.
  Normally merge documentation-only main; keep full UX-1, header badges and
  complete overview redesign deferred. Preserve this round's date/first-start
  behavior and all prior financial/safety evidence.
- Put the changed explanations' existing help controls at each page title's
  right. Preserve separate complete PlainText content and owned dialog lifetime.
- Reuse theme's role convention: secondary by default, one trade reconcile
  primary, overview empty-strategy primary; stop/cancel/flatten danger. Require
  native Cancel-default confirmation. Reject context/account/environment/book
  changes during the dialog; do not silently retarget the confirmed operation.
- Six default position columns retain product, quantity, sellable, strategy,
  exit and protection. Optional columns remain selectable and fully populated.
  Composition injects a dedicated atomic presentation preference file; UI owns
  no file IO. Failed writes preserve previous choices and explain failure.
- Empty trade tables get explanation and a strategy navigation action, without
  manufacturing rows; retain the overview wizard action and add its reason.
  Display stock lots and Taipei timestamps only; no model/financial conversion.
- Add10 catalogue records2796–2805 (total2806). Source and the exact changed
  presentation/confirmation-aware test baseline remain separate commits.
  Full discovery, actual LOCAL/fake-SIM starts and remote CI remain root-owned.

### 2026-11-01 — Empty projections do not establish zero broker exposure

- Root review identified that empty position/order views can mean missing or
  unverified broker data. Replace only the two existing empty-table messages
  with "尚無可顯示的…資料" wording and direct next-step context. Do not introduce a
  false zero, an automatic-strategy prerequisite or a new framework/state flag.
- Retain both current strategy-navigation CTAs for this slice; M2-2 owns later
  manual-order navigation. Test accepted disconnected SIM/LIVE snapshots with
  unknown financial facts, and refresh both empty screenshot sizes.
- Catalogue maximum stays2805; exactly two existing values change in a separate
  baseline commit. Root repeats actual startup/full checks after this head.

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


## M2-6 / final policy evidence merge — 2026-11-01 Asia/Taipei

- Normally merge the completed M2-0 verification documentation, preserving
  both decision histories. No product, test, tool, catalogue or fixture content
  changes from tested M2-6 source5285742. No history rewrite or main merge.
- M2-6 actual LOCAL/fake-SIM startup checks already passed on5285742 with
  clean normal release. Final branch full discovery is still scheduled after
  the active M2-8 full suite; no focused/startup pass substitutes for it.

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

## M2-6 / first complete-run corrections and cleanup prerequisite

Retain the first complete run's 3914/1638.307s, 14 failures, 27 errors and 42
existing skips as FAILED, including all four new identities. Replace the real
page-boundary violation with an explicit owned trading-page argument; do not
relax the original no-parent/shell-discovery test or move that lookup elsewhere.
The established page-3 contract is checked in a real widget regression that
separately supplies a page different from the layout owner.

Commit that source correction with the normal pinned-main `67249dc` merge as
`f98d98c`, then independently update the three feature-caused visible-label test
references. Preserve all identity/finance/repaint assertions and add exact original
full-warning help/accessibility checks. No catalogue value, historical fixture,
skip, cap or timeout is changed to hide a failure. Source and exact text-baseline
changes remain separate commits.

Normally integrate final M2-8 `fdfde06` as the next test-cleanup prerequisite,
retaining its seven source/test/tool blobs exactly. Delivery dependency becomes
M2-8 → M2-6 → M2-1 → M2-2; root runs one new final-composite M2-6 full suite and
actual startup serially after M2-8. Prior runs keep their original source IDs.
No real key, CA, broker operation, installed-app control or git-history rewrite
is performed. Detailed focused evidence and the retained first-run comparison
are in [M2-6 verification](../analysis/m2-trading/verification.md).

## M2-8 — 2026-11-01 13:09 Asia/Taipei

Problem: on this Windows host the venv executable is a redirector. The retained
Popen PID is the redirector, while the authenticated engine session correctly
publishes the native Python child's PID. `ensure_engine` rejects that mismatch
and times out; a failed unittest `setUpClass` never calls `tearDownClass`.
The completed main and M2-6 runs demonstrated healthy LOCAL engines left alive
with locked SQLite files. Both were separately shut down through authenticated
IPC after verifying their exact fixture path and session/child identity.

Options: weaken the production PID comparison, change production ownership
semantics, or correct test/developer launching and register cleanup before setup.
Choose the last option. `tools/owned_trading_engine.py` scopes only the source
launcher reference in `context_client`: it uses `sys._base_executable` with the
already installed import paths. It does not mutate global `sys.executable` or
the subprocess module, replace a runtime facade, or bypass any PID, account,
environment, authenticated-IPC, engine-owner, handle or installer guard.
Product runtime files remain unchanged.

Each scope records the actual native Popen before startup can fail. It closes
only those handles, validates the session PID before any control command, sends
normal SHUTDOWN_ENGINE, waits for exit, and removes only matching `_STARTED`
entries. A reused host is not registered and is not closed. A failed shutdown
does not prevent attempting the remaining owned children. An unresponsive own
native child may require the retained handle's terminate as failure containment;
that always raises and cannot produce passing acceptance. No process discovery,
broad kill, user-data deletion, timeout extension, skip or applicability change
is used to manufacture a pass.

Class cleanup uses `addClassCleanup`/`enterClassContext`; per-case engines use
`enterContext`. Temp cleanup is registered first, so engine cleanup runs before
fixture data cleanup. Synthetic multiprocessing hosts register their individual
authenticated cleanup hook before `start` and readiness assertions, independently
of UI `tearDown` or other host cleanup failures. The load probe establishes its
owner scope before `ensure_engine`, including partial initialization and report
writing failures; its source identity also includes the new launcher helper.

Tracked launcher coverage:

| Owner | Coverage |
|---|---|
| `tests/test_trading_runtime.py` | Shared class host; per-case shutdown/deep roots; second-owner rejection and standalone UI client use native Python with the same packages. All prior protocol/identity/transport assertions remain. |
| `tests/test_runtime_context_client_v2.py` | Context-manager-created LOCAL/pending hosts use a scope registered in setUp. Synthetic hosts each register separate cleanup before start. Cleanup still runs if UI drain/teardown fails. |
| `tests/test_trading_runtime_context.py` | Every retained synthetic multiprocessing host has a cleanup hook before start; one failure cannot abort cleanup of another hook. |
| `tests/test_trading_installer_guard.py` | Engine scope encloses each guard-lifetime case before temporary-directory cleanup; controlled UI entry uses native Python and cooperative stop before exact-handle failure containment. |
| `tools/trading_load_probe.py` | Scope starts before initialization, normal IPC cleanup in finally even without a returned facade; cleanup failure marks report FAIL. |
| `tests/test_runtime_context_cli_v2.py` | Routing-only calls mock `serve`/`run_window`; no child or engine is launched. |

`git grep -- '--trading-engine'` and all `ensure_engine`/`open_context`/`_run_window`
test/tool references were reviewed after graph discovery. The second-owner
subprocess deliberately cannot acquire an existing root; its direct native
Popen in `subprocess.run` cannot strand a venv grandchild on timeout.

Graph: the new worktree was indexed locally (19,469 nodes, 51,711 edges). Existing
symbols were impacted before edits; test lifecycle dispatch is UNKNOWN in the
graph, so direct source and text references confirmed unittest entry points and
fixture consumers. `start_ui_entry` and load-probe helpers are LOW; synthetic
`start` is MEDIUM with unresolved dynamic receiver sites, cross-checked by text.
No HIGH/CRITICAL pre-edit change was reported. New untracked symbols initially return
UNKNOWN/not-found; they require final indexed change analysis, not an unaffected
claim. Initial discovery used the already indexed source-identical main probe
while the worktree index built; relevant source diff against main was empty.

Final graph analysis is HIGH: 64 changed symbols, 12 files and nine affected
execution flows, all belonging to the existing developer load-probe main entry.
The new scope has five test/tool importers (MEDIUM); its cleanup and load-probe
main are LOW. Callable cleanup/launcher hooks remain UNKNOWN to static dispatch
and were confirmed in the source and real-process tests. The complete result
has no partial/truncated flag or empty IDs. Review covers the launcher binding,
all registered cleanup hooks and truthful load-report failure paths; production
files have no diff. The initial incremental rebuild lost method IDs and falsely
reported CRITICAL/603 unrelated flows. A local-only forced rebuild restored all
IDs and the complete result above; no source/test semantics were changed to
work around the index defect, and no FTS extension was downloaded.

Evidence boundary: offline LOCAL and injected synthetic ports only, no real SDK
login, credentials, CA or order operation. Focused checks are recorded in
[m2-8-verification.md](m2-8-verification.md). Controller schedules the branch full
suite, final real-window startup and CI independently; they are not inferred
from focused tests or a tooling-only launch check.

## M2-8 — 2026-11-01 native installer precondition

The controller granted an exclusive native test window after policy full-suite
completion and normal cleanup of its exact test-owned source engine. The seven
installer-guard cases ran: five boundary cases pass, and both native cases fail
their unchanged preexisting-app assertion before any child or fixture creation.
The controller confirms those same failures in main's complete baseline.
Read-only inspection found the owner's installed 0.3.0 GUI and LOCAL engine,
both older than this task, which the source-Python engine scan does not include.
Choose to preserve the assertions and record the host limitation; never stop
those non-fixture processes, use a different mutex, add a skip, or claim native
acceptance passed. No further engine tests run while the controller resumes
the next full suite. Details and pending full/startup/CI evidence are in
[m2-8-verification.md](m2-8-verification.md).

## M2-1 / authorized foundation — 2026-11-01

The coordinator confirmed prerequisite PR129 all35 checks green on attempt2,
run41279585267, source2d8319b, at14:35 Asia/Taipei. The owner's later steering
authorizes M2-1/M2-2 from dependent branches without merging main. Start this
backend branch at final M2-6 source5285742, then normally merge the market fix
and M2-8 cleanup. Preserve each implementation's source bytes; resolve only
append-only decision/behavior/inventory conflicts by retaining both intents.
No rebase, main merge, user-data deletion or production financial operation.

Initial GitNexus status was unindexed; offline single-worker analysis completed
in143.5s with19,608 nodes and52,009 edges. Index flow/receiver caps remain known
navigation limits, not evidence an omitted path is unused. Before merging,
the existing indexed prerequisite supplied impacts on source-confirmed matching
premerge blobs: shared charts, installer-test and load-probe file targets were
CRITICAL; market panel LOW; unresolved unittest callers were confirmed through
discovery/import references. That warning is retained despite complete low-risk
change detection for the market merge. New own-worktree graph change detection
is required before this merge commit and every subsequent implementation commit.

Only lint and source-byte comparisons run while the coordinator's serial policy
suite is at process-sensitive cases; do not start another full suite or heavy
process-focused tests. Full discovery/startup/push/CI belong to the coordinator.
Next freeze typed Sinopac connection DTO/actions for parallel UI and manual SIM
implementation. No connection or execution behavior is claimed delivered by
this foundation commit.

## M2-1 / shared wire contract first — 2026-11-01

Freeze reference-only SinopacConnectionSettings, masked SinopacAccountView,
four SinopacReadiness facts and SinopacConnectionView in a separate application
module, reexported by contracts.py and explicitly registered in the trusted
codec. New command fields and UiState.sinopac_connection have defaults, so
old wire documents decode without introducing a connection or changing books.
Connection revision/generation are independent of the engine book version;
subsequent runtime acceptance checks them. The only settings are environment,
key reference, optional certificate file/secret reference and fee discount.
No person_id, raw account identity or secret value belongs in these DTOs.

The four actions are save-and-connect, account selection, optional CA activation
and disconnect. A draft SIM environment does not imply changing an accepted
LOCAL trading book. Initial account signed state can be unknown; execution
readiness remains blocked pending dependent M2-2. Reason codes are presentation
keys, never native exception text. The UI agent owns all new catalog strings
from order2806, and the manual agent owns separate manual_contracts.py DTOs.

Pre-edit impact is CRITICAL for UiAction/UiCommand/UiState (37 direct,73 total)
and HIGH for registry initialize (6 direct,19 total). New names were absent in
graph and text. Four pure boundary/codec tests went RED on the missing module,
then passed in0.003s, including old-field omission and malformed settings. This
slice starts no engine, SDK or child process. Inventory/baseline registration
is a separate precise commit; broader runtime implementation is still pending.

## M2-1 / immutable facade environment — 2026-11-01

Require ShioajiSDKFacade(client,module,environment=Environment...) explicitly;
neither native simulation flags nor a LOCAL default establish execution scope.
Expose a getter-only environment property; factory and retained legacy market
construction pass their immutable configured environment. The manual-execution
agent owns guards in the three existing mutation bodies and a central predicate,
so this slice does not replace those bodies or add a second order path.

Two pure tests went RED before implementation and now pass. With existing fake
facade, tick-stream and price-band cases,33 tests passed in4.573s. Existing fake
constructor sites receive only explicit BROKER_SIMULATION arguments; original
assertions and expected requests remain intact. Those fixture edits and new
module inventory rows are a separate commit. Source impacts: facade MEDIUM
(10 direct), factory LOW(4), MarketSession LOW(2). UNKNOWN test/helper file
impacts were confirmed via direct imports and unittest discovery references.

## M2-1 / precise constructor fixtures and inventory — 2026-11-01

This independent fixture commit adds only explicit BROKER_SIMULATION arguments
at the six existing fake facade construction sites across the shared tick fake,
SDK facade and price-band fixtures, plus the required Environment import. All
old assertions, timeout cases, request expectations and failure paths remain.
Register only the three reviewed new DTO/environment-test modules in inventory;
no historical producer hash, appearance baseline, string or SDK pin is repinned.

Complete source/fixture change detection reports16 symbols across9 files and
CRITICAL graph risk with613 listed affected processes, dominated by the shared
tick_gateway test-helper node. Source search confirms its direct consumers are
the tick fixture modules; this does not waive the CRITICAL warning or replace
tests. All33 relevant fake tests passed. Future source PR notes retain this
warning and the index's dynamic receiver/process-cap limitations explicitly.

## M2-1 / shared native owner — 2026-11-01

One SharedSDKSession authenticates with trade reports enabled. Typed facade
consumers retain the same immutable environment and execution guards. Native
callback registration occurs once per event; callback failures are counted,
sanitized and isolated from other consumers. Quote/scanner leases are shared;
consumer logout detaches only its callbacks/subscriptions. Native logout is
the owner's responsibility. Existing MarketSession can adopt a consumer, so
directory, history, tick and scanner services use the authenticated session.

Four new fake-only tests were RED before implementation. With the existing
market session and controller regressions, all13 focused tests pass in0.050s.
No SDK import, real credentials, CA, broker orders or engine process occurred.
MarketSession.connect impact was UNKNOWN (dynamic receivers), confirmed by
runtime and test source references. Disconnect impact was CRITICAL (2direct,
167flows); its existing body remains unchanged. Adoption reuses that body via
the consumer's detach-only logout, preserving legacy independent sessions.

## M2-1 / unified backend acceptance and routing — 2026-11-01

The explicit profile-free RuntimeLaunch.sinopac mode owns a single SDK session
in one stable environment host (SINOPAC:environment). Its process seed stays
sinopac-pending; navigating discovered account aliases changes only the client
view. LOCAL first-connect routes connection/market intents to that host while
preserving LOCAL cash, positions, book version and selected context. Switching
to SIM remains a separate navigation intent. Environment replacement confirms
the previous native logout before constructing/logging in the next client.
Unknown logout remains blocked on retries; no process termination is used.
An existing connected legacy market/profile session is retired through the same
bounded explicit transition before unified login; legacy profile files and
hash-pinned resource loading remain supported for their existing callers.

Connection generation is an opaque UUID. Material accepted state changes use a
persisted monotonic revision, independent of ticks/book version. Composite
projection offsets revisions across environment hosts and maps CAS back without
refreshing a stale intent to a newer native revision. Owned workers have the
existing eight-second acceptance deadline. Disconnect waits on an Event for at
most7.5seconds outside book locks. Expired login/account/CA completions cannot
promote; candidates clean up normally. Close is bounded and reports uncertainty.
Trusted factory/SecretResolver/resource-factory injection passes through
serve/build_runtime for offline integration; startup never resolves secrets.

Discovered aliases derive from the complete environment/account-type/broker/id
identity. Only masked labels, signed tri-state and reason codes cross the wire.
Preferences preserve references, selected aliases and generated masked metadata
with identity hashes; raw account IDs/person_id/passwords are never saved.
Historical/unselected/disappeared aliases remain available for book navigation,
with unknown or unavailable evidence, independently of current selection. This
never removes trading obligations; M2-2 owns canonical ledger reconciliation.
Query readiness requires successful selected-account position queries. Callback
delivery failures explicitly degrade readiness; simulation execution remains
implementation_pending in this M2-1 slice and production is always blocked.

The generated catalogue initially supports ordinary cash security2330 and the
nearest actual, unexpired TMF month. Native ContractV2 supplies lot, multiplier,
month/expiry, ticks and optional daily price limits. Missing limits remain
missing. Stock classification comes from bounded automatic public ISIN data,
not SDK industry codes or symbol guesses. Publication date and full response
SHA are retained. The official page observed2026-11-01 was10,186,180bytes,
SHA256 de68b53f834f4b17dab7a9125f932c4a270c202ec9deed7e672d564ddf170e54;
its2330 row parsed TW0002330008/ESVUFR with publication2026-11-01. Read budget
is2.5seconds and32MiB; unavailable/stale classification blocks that stock's
resource generation while market/account services remain usable.

Calendar coverage is explicitly2026 only:242 positive scheduled common dates,
after excluding the independently recorded July10 TAIFEX closure. Its window
09:00<=t<13:30 is a conservative shared manual window, not full TMF hours or an
actual-open/emergency-completeness guarantee. 2027 is unavailable, never guessed.
M1 quote/history sessions retain their independent received-timestamp behavior.
Fees are versioned application estimates (adjustable stock-fee discount), not
broker billing. TMF35050TWD initial margin is the dated TAIFEX exchange reference
2026-08-12 observed2026-11-01, never fabricated broker funds. No positive broker
cash/equity or global atomic order observation is inferred from simulation zeros.

New CA enrollment stores only ca_password under the certificate reference. The
legacy triple credential schema remains intact for its existing path. Explicit
optional activation derives person_id from selected native accounts and uses a
user-selected PFX path; references alone cross UI/IPC. SIM defaults NOT_REQUIRED
based on official documentation, not owner real-SIM verification. Tests use an
invalid fake certificate file and fake SDK callable only; no real CA was used.

Pre-edit routing impacts are CRITICAL for RuntimeLaunch, RuntimeBundle,
RuntimeContextManager/_Entry, ContextIpcFacade, CompositeFacade, desktop entry
points and server dispatch/serve (broad160+flow attribution). Resolver impact is
CRITICAL as previously recorded. UNKNOWN targets were checked against source.
The new calendar builder's first symbol lookup occurred after initial creation;
this local workflow miss is retained rather than represented as a pre-edit
check. Subsequent source review, fake boundary tests and full change detection
cover the resulting definition. No FTS/vector extension was installed.

## M2-1 / exact inventory baseline — 2026-11-01

The source commit e640eb0 is followed by an independent inventory-only change
for the seventeen new backend/test/tool modules since af262ab. Each row retains
its actual path, line count and reviewed layer. The three DTO/environment rows
already added by af262ab remain unchanged. Historical rows/producer hashes and
all existing assertions remain intact; no appearance/catalog baseline is reset.
The existing bootstrap module remains an explicit composition boundary rather
than moving its public lifecycle during this feature; new owner/resource modules
are bounded and their functions meet the50-line readability target.

Complete source detect reported130symbols/29files/608flows at CRITICAL risk,
with no partial/truncated flags. One existing desktop.py parse_args record has
an empty graph UID (its pre-edit impact still reported187direct callers). This
is retained as an index limitation, not an unused/unaffected claim. Actual parser
source and existing CLI tests were independently verified. Raw CLI report and
structured flag/UID summary are in ignored .tmp/m2-backend-detect files.

## M2-1 / single three-step connection presentation — 2026-11-01

Use one visible BrokerPanel for environment/key save-and-connect, discovered
masked accounts and optional certificate references. Remove the independent
MarketDataPanel and twelve-reference primary form rather than keeping hidden
obsolete controls. Retain the existing legacy profile import in the collapsed
advanced section, and preserve offline legacy metadata persistence/readiness
coverage through its typed commands. Account identities, SDK objects, secrets,
person_id and certificate contents never enter the widget implementation.

The connection draft defaults to broker simulation and the documented OS key
reference. It is separate from the accepted Trade/Settings book selectors;
connecting, a failed request or an unacknowledged request cannot switch a LOCAL
book. Connection generation/revision are submitted independently of engine
version. Render the connection view before same-book, stale-book and market-only
shortcuts; reject older connection revisions. User-edited references and Decimal
fee discount survive polling and book navigation, and only a matching accepted
receipt clears those drafts. Checkbox clicks submit aliases then immediately
restore accepted selection until the acknowledgement. An IPC failure shows
unknown liveness rather than retaining a successful connection status.

Certificate selection is reference-only and optional. Simulation's NOT_REQUIRED
status follows the official contract, not a real-credential experiment. The
shared runtime owns credential resolution, connection reuse, signed/permission
validation and CA activation. Production readiness is always rendered blocked,
including an inconsistent READY DTO; signed/account discovery alone never grants
execution. Simulation execution remains pending dependent M2-2. Fee discount is
editable as Decimal (0 < d <= 1, default1), with built-in estimate assumptions
explained in help; M2-9 tax/calendar/expiry UX remains second-round scope.

The four intents run through the existing asynchronous worker. Duplicate requests
are disabled, pending status is neutral, account/CA controls open progressively,
and disconnect requires native confirmation with Cancel as default. Capture its
revision/generation before the dialog and reject a connection replaced while the
dialog is open. Reasons are mapped to literal Chinese catalogue keys, never
vendor text. Account-data absence does not assert that the broker has zero
accounts. Help remains title-right; style rules are scoped in theme.py.

Work is exclusive to codex/m2-1-connection-ui, normally merged with frozen DTO
986f7cf. Catalogue phase62 owns orders2806–2877; M2-2 starts phase63/order2878.
Pre-edit graph risks are retained: Window.command/_run and theme/catalog are
CRITICAL; translation_parts HIGH. Dynamic/unittest UNKNOWN callers were checked
against source/discovery. The current UI source has no real SDK import or
financial operation. Full discovery, real startup and remote CI are coordinator
steps after normal integration with the shared backend; fake-Qt proofs here do
not establish the M2-2 engine LIVE invariant.

M2-1 integration followup: account/context discovery may change selector choices
without incrementing the accepted engine book version. A RED/GREEN real-widget
case required invalidating only presentation before the same-version/market-only
shortcut; the accepted LOCAL account, positions and dirty connection reference
remain unchanged. Its named helper impact is CRITICAL (45 upstream sites,
3 processes,5 modules), retained as a warning alongside source checks rather than
waived by the graph's shared-name/dynamic gaps. Final backend accounts_unavailable
and callback_failed reasons map to existing Chinese next-step copy, with explicit
unknown-readiness tests; no new catalogue records were needed.
## M2-1 / explicit unified broker startup identity — 2026-11-01

Static review of the prepared actual-startup probe found a genuine entry-path
gap: configure_launch handled explicit LOCAL/profile requests, then hashed every
profile-free broker alias into an UNCONFIGURED host. An already registered
unified alias therefore lost its stable SINOPAC environment host when launched
directly through _run_window(environment=BROKER_SIMULATION, account_ref=alias).

Before the existing generic fallback, reuse a registered explicit unified entry
with the same environment and known alias. Keep LOCAL, selected-profile and
unregistered legacy-alias behavior unchanged. This is metadata routing only;
it performs no SDK login, host startup, automatic selection or snapshot synthesis.
The real direct-SIM window probe must use this path, with natural prior owner
discovery/selection, rather than patching configuration or read models.

The new metadata regression was RED for both SIM and LIVE (hashed contexts
instead of the registered unified context). After the four-line correction,
all three UnifiedRegistryTests pass in 0.072s; ensure_engine is mocked and its
single registration call is checked. No Qt app, host, SDK or process test ran.
Ruff check/format pass. configure_launch impact is LOW (one direct caller,
two modules); cached graph/source were read during the coordinator's isolated
full-suite window. Full index refresh/change analysis and separate commits wait
for the coordinator to release that exclusive window.

Initial integrated source 90bdda8's prior 96 focused results remain attributed
to that source only. They are not relabeled as verification of this correction;
actual direct-SIM startup, updated focused/full and CI remain separate gates.

## M2-1 / LIVE CA remains outside query-only scope — 2026-11-01

The specification limits LIVE to login, market and account queries. The unified
CA flow is therefore accepted only for BROKER_SIMULATION when explicitly used;
this does not change the legacy connector CA path. Reject a LIVE CA intent at
the owner boundary before creating a worker and independently at the executor
before file/password/native SDK access. Return the existing
production_orders_disabled reason, which already renders the formal query-only
Chinese guidance; do not add/reorder catalogue strings or imply LIVE opt-in.

The LIVE certificate path, picker, password-reference and activation controls
are disabled, with existing formal-readonly guidance in status/tooltips. The
panel helper stays in the same module and BrokerPanel remains292 lines, below
its300-line cap. Valid optional SIM activation remains tested with an invalid
fake PFX file, fake password and fake SDK only.

Both new backend/UI cases were RED first (LIVE request accepted/controls enabled).
After correction,23 fake, metadata and small-widget tests pass in0.558s. The
backend test also calls the executor independently and proves zero password
reads/native CA calls and unchanged accepted view on refusal. Existing SIM
activation assertions are intact. Impact is LOW for the executor, MEDIUM for
panel enablement (nine direct,two flows); UNKNOWN dynamic command/test targets
were confirmed by actual RuntimeBundle callers and unittest references.

After the isolated full8 smoke-sensitive prefix completed, the coordinator
released a single-worker offline index and these small tests. This does not
claim the entire full retry ran without later index/Qt activity. Actual startup
and process-heavy verification remain coordinator-only until that full ends.

## M2-1 / merge graph evidence chronology — 2026-11-01

Documentation merge3623c4447f2e45e55fe6fa8970d37c2589834eaf was committed after
staged analysis showed59symbols/eight docs/zero flows, LOW, with no missing IDs
or truncation. At that time scope-all still had an empty UID for the new
_certificate_controls helper. Using the clean staged subset while that all-scope
issue remained was a workflow gap; it is not represented as clean precommit
all-scope validation, and history is not rewritten to obscure the sequence.

An offline forced single-worker rebuild then restored symbol identities
(20,092nodes/641flows,28.0s). Retrospective exact committed comparison
90bdda8..3623c44 reports59symbols/eight documentation files/zero flows, LOW,
zero empty IDs and no partial/truncated flags. Source-all subsequently reports
21symbols/nine files/eight flows, HIGH, all21returned with zero empty IDs and no
partial/truncated flags. The HIGH warning is retained alongside actual focused
tests; it is not lowered through riskSharedAxes or graph absence. These checks
precede the separate source-fix commit, not the documentation merge.

## M2-1 / scoped LIVE evidence recapture — 2026-11-01

Source36fc1e8 passed23 updated fake/small-widget/metadata tests, Python3.11
compilation, Ruff and complete all/staged graph checks (23symbols/10files/eight
flows, HIGH, zero missing IDs/truncation). Under the coordinator's explicit
lightweight Qt allowance, replace only1366×768/1920×1080 LIVE visual fixtures.
The audited helper uses public fake DTOs/RecordingFacade and the real window/
theme, with SDK imports forbidden, no engine/runtime/login/commands. It checks
CA controls while expanded before restoring the original collapsed capture state.
Both images retain the LOCAL book, formal connection label and readable readonly
CA guidance; visual inspection passes and horizontal scrollbar maxima are zero.
Other scenes and unrelated historical baselines are not regenerated. The capture
record pins36fc1e8 and each image hash. Actual startup/full/CI stay separate.

## M2-8 — 2026-11-01 complete-run evidence boundary

Retain the first complete run's NEW positive-smoke timeout as a real failure,
even though the exact unchanged case subsequently passes sequentially on main
(15.027s) and M2-8 (13.915s). The unchanged full retry completes 3909 tests in
1487.114s with 10 failures, 22 errors, 42 existing skips and no new failed IDs
versus main. Only its smoke-sensitive prefix was quiescent; other-worktree index
and small Qt/metadata checks resumed later. Do not claim full-run isolation,
prove a latency cause from correlation, raise deadlines or label the first
failure a waived flake. Raw review retains the E06 cleanup WinError/path
difference even though exception types and failed IDs match. Normal actual
LOCAL/fake-SIM startup passes at the same source head are independent evidence;
they do not turn failed native-host suites into acceptance. Commit only reviewed,
sanitized evidence and documentation; leave executable/test/tool bytes unchanged
from `8f03a9905c337680f2f963ba284bed5bf3638bcb`. Controller owns push and CI.

## M2-8 — latest-main normal integration

Merge main `67249dc126423212bbcced2048992c4c50a1be48` normally into the M2-8
branch, preserving all market, policy and cleanup decision/contract blocks.
Keep every inherited source/test/baseline blob exact; resolve only appended
documentation, with no rebase, source rewrite or new baseline change. The
result combines separately tested sources and needs new full discovery and
actual startup at the final head. Preserve earlier failed-run evidence under
its original `8f03a99` scope; do not present it as final composite acceptance.
Controller serializes native/engine/full validation after M2-6 completes.

## M2-1 / source-identical M2-8 documentation integration and startup

Normally merge final M2-8 `fdfde06` into M2-1 `8d98564`, retaining every M2-1,
M2-6, policy, market and cleanup decision/contract section. Resolve only the two
documentation conflicts. All 1202 non-documentation checkout byte hashes and
all non-documentation Git blobs remain identical to `8d98564`; no fixture or
source change is introduced. Review and sanitize the three actual startup result
JSONs, retaining their original source identity, guard/cleanup facts and explicit
resource_calls=0 limitation. Their source-equivalent applicability is stated;
they are not falsely described as rerun on the new documentation commit. Full
discovery and current-head CI remain separate coordinator gates. No engine,
native lifetime, Qt or startup test is executed for this documentation merge.

## M2-6 / exact cleanup inheritance and two runtime copy oracles

Normal merge `dc58096` preserves all seven M2-8 source/test/tool files exactly.
Only afterward apply a separately authorized presentation-baseline delta to
two RuntimeContextClientTests cases: expect the existing short facts-pending
label, while retaining the complete original warning and its no-empty-exposure
meaning in actual help/accessibility assertions. Their prior startup-PID errors
had hidden these body assertions. Real SIM/LIVE widget surrogates reproduce the
old expectation failure and verify the corrected text plus unknown financial
facts and zero commands. Do not claim the native IPC bodies were rerun alongside
the active M2-8 full suite. Preserve every other context/finance/ownership and
no-engine-creation assertion and all cleanup behavior; no cap, skip, timeout or
catalogue change. Stop the audit after all actual changed-copy references are
accounted for. Final full discovery/startup/CI remain root's serialized gates.

## M2-1 / inherit the final M2-6 full-suite corrections

Normally merge M2-6 `4fd1f6e` into M2-1. Only six non-documentation paths
change: the explicit trading page owner, its real Qt regression and five
feature-specific visible-label oracles (four test files). Preserve full help,
unknown financial facts, ownership and no-implicit-connection assertions. All
other source/test/tool blobs remain the exact M2-1 parent; workspaces retains
its connection wiring plus only the explicit page argument. The runtime test
retains M2-1s existing programmatic legacy command after its obsolete button was
removed; this merge adds only the two reviewed short-copy/full-help changes.
Resolve three doc conflicts additively and remove only two exactly duplicated
decision sections. Exact blob audit covers1215 non-doc paths using NUL-delimited
Git paths, including non-ASCII filenames.

Pre-merge install/helper impacts resolve the build caller at LOW risk (3/2
nodes, one flow); unchanged test methods are unittest-discovered boundaries,
not unused code when no callers resolve. The84 affected Qt, connection, page
boundary, document and layer tests pass in29.786s. Prior M2-1 startup evidence
remains source-specific. New complete discovery and actual startup follow on
this composite; no old full/startup evidence is relabeled.

## M2-8 / final composite full and startup evidence

Record finalfdf3914/1593.006s10F22E42skip honestly as a nonzero local suite with
zero new failures. Review all32 actual blocks, including finalE06 WinError32
matching main rather than borrowing the earlier WinError5 cause. Retain original
smoke failure/retry evidence. Both final actual startups return0 with normal owned
cleanup and fake-only broker operations. This commit is documentation only; CI
is checked on the pushed head. No source, assertions, thresholds or skips change.

## M2-8 / explicit new-test inventory registration

A final all-new-Python-path audit found the new cleanup regression module was
not explicitly listed in section2, although architecture tests already passed.
Register only that existing test file and its measured line count in a separate
inventory baseline commit. Test code and every other non-doc blob stay unchanged;
the completed full/startup results remain source-equivalent. This repairs the
specification documentation requirement without changing any test assertion.

## M2-6 / final source-equivalent evidence and omitted test registration

Final4fd1f6e complete discovery is3941/1543.784s10F22E42skip,32blocks/31IDs and
zero new failure identities versus main. Preserve the nonzero result, all actual
cause differences and the original four-new-failure run. The Windows PowerShell5
raw log is UTF-16-LE/BOM with CRCRLF/width119 wrapping; use BOM-aware parsing and
fold only failure identifiers, requiring parsed block count to equal the footer.
An old UTF8 parser's false INCOMPLETE is not the test outcome. Both actual LOCAL
and fake-SIM starts return0 with research/engine shutdown and no real SDK import.

Merge final8 documentation868da0c normally, retaining both appended decision
histories. Keep all1192 non-documentation entries exact at tested4fd1f6e. Repair
only the missing three existing M2-6 test-file registrations in an independent
inventory baseline commit; no Python body, fixture, timing, size limit, skip or
assertion changes. CI must be fully green on the pushed stacked PR; no main merge.
