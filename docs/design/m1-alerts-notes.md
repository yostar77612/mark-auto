# M1-3 implementation handoff notes

Status: implemented components; integrated engine/UI wiring and final PR gates are owned by the controller.
All verification here is offline fake/fixture evidence. No credential, login, CA, account or order operation ran.

## Autonomous decisions (2026-11-01, Asia/Taipei)

- Scope M1-3: retain and complete the interrupted `alerts.py`, `alert_service.py`,
  `alert_store.py`, `alert_panel.py` and alert strings rather than discard reusable behavior.
  New indicator/condition functions use Decimal. Immutable rules validate only at user/file/wire boundaries.
- Scope M1-3: scanner callbacks are discrete server signal events. Drain a false/true
  observation pulse for each event, retaining cooldown per rule and instrument. This permits
  later server events after cooldown without requiring an SDK "condition cleared" message
  that the actual 1.7.9 SDK does not provide. The callback uses the actual local SDK
  `_core.pyi` presets, `scanner.id`, `quote.code`, `quote.close`, `quote.datetime` and exchange.
  Only TW/Stock/TSE+OTC subscriptions exist. No optional SDK version fallback is added.
- Scope M1-3: retain each successful individual scanner subscription leg so an SDK
  failure halfway through subscribing both exchanges cannot leak that leg on disconnect.
  Unknown vendor text never appears in the returned error or callback log.
- Scope M1-3: data marked incomplete is ineligible in addition to `final=False`;
  missing indicator windows and unknown references produce no signal. Stock-only rules
  reject an individual index target; watchlist rules filter indices at evaluation.
- Scope M1-3: persisted events retain their immutable UTC time and direction in
  `message_args`; presentation alone formats Taipei time and colors via an injected
  rise/fall palette. Initial historical events populate the table without desktop notifications.
- Scope M1-3: clear records clears the visible in-memory session log, preserving local
  audit events. The explicit 30-day retention policy is applied on startup. Corrupt files
  are renamed to `.bad-<UTC>` and surfaced by a catalog warning.
- Scope M1-3: the GUI and engine run separately, so new immutable AlertCommand,
  AlertRuleData (tuple parameters), AlertSnapshot and an AlertProxy cross the existing
  registered codec. MappingProxyType rules do not cross IPC directly. AlertActions is
  a real two-implementation protocol (service/proxy), not a facade or re-export shim.
- Scope M1-3: live observation seeds cached official history once per instrument/day,
  never evaluates historical startup bars, and filters future bar ends. Tick observations
  and completed-period observations have distinct eligibility; the minute/period ending
  is evaluated once. Session-end finalization can call `on_bars` without inventing a tick.
- Scope M1-3: all UI lookups use literal `ui_text('key')` calls, including lookup tables.
  Normalize Qt combo-box values to AlertKind at the user-input boundary because Qt converts
  str-backed enums to ordinary strings.
- Scope M1-3: the strict legacy trading gate only allowed application.contracts and
  domain.models in presentation. General check_layers is already satisfied. The controller
  is adding precise allowances for application.alert_contracts, domain.alerts and
  domain.validation, with negative tests for SDK/infrastructure/execution imports.
- Scope M1-3 verification: restricted Windows test processes can create a tempfile but
  cannot then read/write descendants. Rerunning the same original test commands with
  normal filesystem permissions passes; no tests, assertions or timeouts were weakened.

## Verification

The following modules ran as separate invocations using the provisioned root `.venv/Scripts/python.exe`,
`PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen` where relevant. All returned exit 0:

| Invocation | Cases |
| --- | ---: |
| `-m unittest tests.test_alert_rules` | 6 |
| `-m unittest tests.test_alert_service` | 9 |
| `-m unittest tests.test_alert_ui` | 4 |
| `-m unittest tests.test_alert_transport` | 3 |

Domain tests cover each of the 12 kinds, true once, held true, false re-arm, cooldown,
then true after cooldown. They include deliberately signal-producing forming and
incomplete bars, non-live/backfill ticks, insufficient histories, reference unknown,
stock/index applicability, numeric ranges and hand-calculated Decimal SMA/KD.
Service tests cover persistence/restart, corrupt-file preservation, 100-rule application
bound, 500-event memory, 30-day disk retention, watchlist/fixed-index scope, scanner
subscription toggling, pulse/cooldown and partial-subscription cleanup.
Transport tests round-trip actual codec commands and snapshots through the application
proxy and verify live observer timing. UI tests verify exact 12 labels/order,
parameters, scopes, adjacent field errors, accessibility, record navigation, timestamps,
colors and notification deduplication.

`ruff check` and `ruff format` on all 15 owned Python files return 0.
`tools/check_layers.py` returns 0 findings.
The strict trading architecture check requires the explicit module allowances described
above and will be rerun by the controller after composition. Full prepush, complete
integration, and protected-file review are controller-owned and not claimed here.

## Screenshots

`docs/analysis/m1-alerts/records.png`, `kd-rule.png` and `metrics.json` use the
`tools/ui_snapshot.py` rendering/metrics helpers on disposable fake data, Fusion style,
and explicitly loaded Windows Microsoft JhengHei fonts. Both rendered images were
inspected: readable Chinese, complete dialog fields, no missing glyph boxes.
Native application/broker callback delivery and human visual approval remain pending owner testing.

## Integration API

- `AlertService(JsonAlertStore(workspace), now=UTC)` is owned by the engine.
- `service.execute(AlertCommand)->AlertSnapshot` handles snapshot/add/enable/delete/clear.
- `service.set_scanner(ShioajiScannerStream(session.facade, session.sdk_module))` after
  connection; `set_scanner(None)` before disconnect; `poll_scanner()` in the engine loop.
- `service.watchlist` contains canonical IDs; fixed indices are `INDEX:IX0001`, `INDEX:IX0043`.
- `AlertProxy(call)` is GUI-owned; the call must use the existing authenticated IPC.
  Refresh proxy on the UI poll cycle, then refresh the panel.
- `AlertPanel(proxy,current_instrument,select_instrument, instrument_name=...,notify=...,rise_fall_colors=...)`;
  `latest_changed(str)` updates terminal status. `select_instrument(id,UTC time)` should
  switch the chart and scroll to the event. Inject existing local notification callback
  with `completion=True` to respect the user's toggle, and the shared appearance palette.
- `AlertTickObserver(service,facts,history,backfilling).on_tick(tick,memory)` uses facts
  from MarketWatchView, official cached 1m bars for seed, and the current backfill flag.
  Its `on_bars(id,memory,occurred_at,trade_date)` handles newly finalized minutes without
  a new tick; caller must only call for live, non-backfilling data.

## Behavior contract for controller to append

M1-3 adds local typed alert rules, Decimal indicators/conditions, enabled-only stock
scanner subscriptions, cooldown and edge state, atomic bounded rule persistence,
retained local event logging, an authenticated DTO/proxy presentation boundary and
accessible parameterized rule/record UI. No alert owns an execution capability or
performs financial actions. Existing strategy risk, execution, credentials, SDK pin,
G3, historical profiles and project acceptance state remain unchanged.
