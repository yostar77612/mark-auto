# Owner-added M2-6 verification

This extends the first-round UI with specification items6–8 from main's
documentation-only afc45ea. M2-9 remains second-round. No broker session, order
path, financial calculation, budget, timeout or engine-state mutation is added.

Seven new widget regressions first failed on the old source, then passed with
all ten original M2-6 cases. They cover UTC→Taipei midnight, market-only updates,
broker headers without the simulated date, an actual fresh LOCAL runtime and its
actual restart, populated/stopped/error warnings, wizard navigation, complete
help text/geometry/keyboard activation/Escape, and plain performance captions.
Each direct runtime fixture closes its owned RuntimeBundle; no engine process
or real SDK is started by these tests.

The 86-case affected batch (`test_m2_readability`, `test_m2_trading_page`,
`test_dashboard_rows`, `test_dashboard_ui`, `test_trading_ui`,
`test_trading_ui_integration`, `test_trading_architecture`,
`test_no_inline_stylesheet`) found only three expected old presentation pins:
the exact four-button dashboard inventory and two performance-heading checks.
Their financial assertions, original full tooltip equality and operation wiring
are retained in the separate precise baseline change. No limit is increased.

All six populated 1366×768/1920×1080 trading images were recaptured with real today
and short explanations. Additional1366 images show the actual first LOCAL
snapshot's neutral overview/CTA, a synthetic real-error presentation, and short
performance/settings pages. Separate620×200 help images show complete text.
`readability-metrics.json` records the first-start and error colors/labels.
Captures use disposable data and the existing local Chinese font, never real
accounts; the only fixed-size screen-fit override is in the scratch capture.

Final focused/static results and exact new catalogue pins are recorded with the
delivery commits. Previous79fc99c startup evidence predates this source. Full
discovery, actual LOCAL/fake-SIM starts and remote CI remain root coordination.
