# M2-2 manual order UI verification

Source: `e8336226868c4355fb54a3d9740ac4c18c78a20f`.
The actual TradingWindow/theme renders fake immutable DTOs with a command-refusing
facade. This visual process starts no engine, credential resolver or SDK. It is
separate from the actual `_run_window`/authenticated IPC acceptance. The default
wall clock is used only to create visual timestamps; no financial readiness is
proved by these fixtures.

Thirty scene/size records cover 15 scenarios at exactly1366x768 and1920x1080.
All page, position and order horizontal ranges are0; visible primary count<=1.
Default order columns are0..5; canonical account column6 remains optional and
available through the persisted selector. Stock/future quantities use lots/contracts;
raw units and complete account identities remain in tooltips/confirmations.
The raw/sanitized report records controls, accessible names, full text, primary
roles, dialog defaults and image SHA256 values.

Synthetic stock capital60000, price20 and2lots imply40000 principal plus the
explicit fake fee1. Futures capital40000 exceeds the fixture initial margin35050
plus fake fee1. No preview exceeds its fixture budget. Fake cost/risk fixtures are
presentation evidence, not broker billing or actual exchange quote evidence.
An earlier scratch capture retained obsolete form input prices despite updated
preview fixtures; it is retained as diagnostic evidence and is not published here.
Only the consistent repeat is included.

## UI guidelines section10

- [x] Page layout and title-right help; at most one primary; dangerous confirmations default Cancel.
- [x] Theme-only role styles; unchanged no-inline-QSS checks cover the source.
- [x] Actionable empty tables; SIM routes to manual preparation, LIVE to connection settings.
- [x] Both exact screen sizes; inspected stock/future preview, owned-order, LIVE and unknown-state PNGs; no clipped controls or needless horizontal scrolling.
- [x] Chinese operation/status text, Taipei timestamps and explicit stock/future units. Instrument IDs/account aliases retain their identity; no raw environment/purpose enums appear.
- [x] Accessible control names; Space opens full plain-text help, Escape closes it; diagnostic/cancel dialogs default Cancel and dispatch no commands.
- [x] Unknown/missing scope/transport failure blocks mutation; no previous ready-state reuse.
- [x] Pending capital is disabled; accepted capital replaces a stale draft, covered by real Qt regressions.

Representative screenshots are linked by filename alongside this checklist.
The full30-record machine-readable evidence is [visual-report.json](visual-report.json).
Full discovery, actual startup and remote CI are separate delivery gates.
