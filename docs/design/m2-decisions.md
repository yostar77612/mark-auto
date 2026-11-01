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
