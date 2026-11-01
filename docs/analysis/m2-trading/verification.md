# M2-6 first-round offline verification

Scope follows `origin/claude/m2-spec:docs/design/m2-sinopac-sim-auto-trading-spec.md`
sections 4/M2-6 and 7. Performance comparison remains round two. These are fake
read-model/widget checks, not broker or owner acceptance.

Implemented: right-aligned environment selector synchronized with accepted
settings state; pending/rejected/unavailable switches retain the previous state;
LOCAL grey-blue/SIM green/LIVE red band and LIVE outline; disabled LIVE order
controls plus direct-command refusal; plain-language tooltips; twelve populated
position columns without first-column clipping or a horizontal scroll range.
Independent tests enumerate all five existing order-capable actions and prove
STOP_NEW and RECONCILE still dispatch. The engine/gateway LIVE guarantee belongs
to M2-2 and is not inferred from UI tests.

Focused evidence (shared root `.venv/Scripts/python.exe`, no installed packages):

- `-m unittest tests.test_m2_trading_page -v`: 10 passed, including reproduced
  nested-confirmation polling and first broker-profile import/cancellation.
- Existing `tests.test_trading_ui`: 32 passed.
- Final offscreen batch (`test_m2_trading_page`, `test_trading_ui`,
  `test_trading_navigation_observation`, `test_context_navigation_v2`,
  `test_trading_architecture`, `test_no_inline_stylesheet`): 70 passed. An earlier
  84-test related batch also covered UI integration and existing M1 corrections.
- `tools/check_layers.py`: zero findings; `tools/check_trading_architecture.py`:
  zero violations; changed-file Ruff check/format and `git diff --check`: passed.
- Catalogue/appearance/string/placeholders batch: 30 ran, only the two exact
  catalogue pins rejected the expected additive records. These pins are
  updated separately for exactly 23 new records; no historical assertion is
  removed or relaxed.

Six screenshots show the actual `TradingWindow` at client sizes 1366×768 and
1920×1080, with three full position rows, a long futures identity, long strategy
references and a fake order. They use the real scoped stylesheet. Captures run
offscreen; the already installed Windows `msjh.ttc` font is loaded into that
capture process only. Screen fitting is suppressed only for this fixed-size
capture. No product font or screen behavior is changed.

`metrics.json` records every size/environment. At 1366, the first-column width is
119px for 112px of text, last-column right edge equals the 1140px viewport and
the horizontal maximum is zero. All environments preserve the same column/data
contract. Screenshots are synthetic visual evidence, not live account data.

Full-suite, actual `_run_window` LOCAL/SIM startup and CI remain pending root
coordination. No real credentials, SDK login, CA activation or order operation
was used. G3, SDK pin, PROJECT_STATE, timeouts and existing test limits are intact.
