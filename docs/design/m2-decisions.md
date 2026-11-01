# M2 autonomous decisions

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
