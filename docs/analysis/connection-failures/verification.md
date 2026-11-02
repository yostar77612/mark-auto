# B — Connection failure stage copy

Base: latest main48675498ac0513bd9f590ebb3f87f4bc2fc593b8, after A merged.
No branch stacking. The existing error boundary now distinguishes a failed login
from a failure after successful login. A connected symbol subscription failure
uses sanitized history-only guidance; a fresh disconnected status never claims
that the connection survived. ErrorText entries include the corresponding next
step. SDK exception details, account names and credentials never reach the copy.

Only error classification/copy and its UI mapping change. The same SDK calls,
cleanup, logout, subscription rollback, connection phases, generation guards and
special expiry/permission/reconciliation classifications remain. No new retry,
connection, order action, IPC shape or automatic execution behavior. Startup's
existing best-effort subscription loop remains unchanged; this UI reports an
observed selection failure and does not infer one from missing ticks.

Strings: new desktop_app/strings/connection_failures.py, phase71/orders3108–3110,
following A3107. Existing historical desktop copy is retained. Baselines are
generated once after feature completion, in a separate commit; expected change
is three added strings, no changed/removed strings, exact count3111 and one new
string-module inventory row.

Shared interpreter: C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe
(Python3.13.11). Related tests use QT_QPA_PLATFORM=offscreen and PYTHONPATH=tests.
Native captures use windows and production theme/error-copy mappings.

| Check | Command/evidence | Result |
|---|---|---|
| Stage/lifecycle/terminal/LIVE regression | python -m unittest tests.test_connection_failure_stages tests.test_sinopac_connection tests.test_market_connection tests.test_market_session tests.test_market_terminal_ui tests.test_market_terminal_theme tests.test_market_terminal_service tests.test_sinopac_panel_ui tests.test_m2_trading_page |83 pass,5.977s|
| Error table/adoption/resources/routing/window/text regression | python -m unittest tests.test_paper_lock_b2 tests.test_market_settings_fix tests.test_sinopac_market_adoption tests.test_sinopac_resources tests.test_sinopac_runtime_routing tests.test_sinopac_window_ui tests.test_no_hardcoded_ui_text |67 pass,30.214s|
| Repository lint | ruff0.16.10 check . |0|
| Changed Python format | ruff0.16.10 format --check,13 changed Python files |0|
| Layer gates | python tools/check_layers.py; python tools/check_trading_architecture.py |0 findings/violations|
| Static gate | python tools/quality_gate.py |0|
| Affected selection | python tools/affected_tests.py --list |288 modules before docs/baselines; full suite left to CI|
| Native failure copy | native.json and login/initialization/subscription PNGs |three stages/two sizes/zero facade commands|
| Native LOCAL startup | LOCAL.json |7.802s,normal exit0|
| Native fake BROKER_SIMULATION startup | BROKER_SIMULATION.json |7.643s,login1/logout1,normal exit0|

Both actual startup checks release research and owned engines and remove their
endpoints, without importing the real SDK or using credentials. Requested
1366x768 remains exact;1920x1080 fits to1920x1061 client under the existing screen
fit. The small-window initialization/subscription screenshots were visually
checked: text is readable and both freshness/chart labels say history-only.
Keyboard controls and accessible names are retained; no input or action is added.

Fresh GitNexus index: main4867549,25252nodes/68912edges/1259clusters/661flows.
Pre-edit risk: select_instrument HIGH,8 direct callers/2 process families;
render HIGH,5 direct callers/2 process families; catalogue CRITICAL,152 direct
readers; translation_parts HIGH. connect_candidate has one direct transition
caller; attach_authenticated has one caller. Dynamic worker/session calls and
bare table composition are UNKNOWN in the graph, confirmed against actual
Thread targets, service.session.subscribe and MappingProxyType composition.
Unittest discovers modified test methods dynamically; their UNKNOWN caller
sets are not interpreted as unused. Index process traces have existing caps;
graph results supplement source reads and tests, never replace them.

No G3, Gate/OOS/budget/timeout, acceptance score or LIVE action pin changes.
No production order opt-in. Real broker acceptance remains an owner check;
all evidence here is offline fake SDK/native Windows evidence.

Concentrated repin: all six plans succeeded/self-verified, catalogue +3/0/0,
aliases unchanged, count3111 and one inventory row. Stylesheets, observers,
settings input counts and platform applicability remain current without changes.

Fast prepush: repository lint, Python3.11 syntax scan1249 files and static gate
passed. Its only failure is main's existing M3 Markdown155 CRLF/LF fence format;
that file has no diff here (the same local issue was recorded for A, whose full
remote formatting gate passed). All13 changed Python files pass format checks.

Final graph:25298nodes/69005edges/1267clusters/663flows. Complete pre-commit
detect_changes reports57/57 symbols,29 affected processes,CRITICAL, with no
partial/truncated result. The full result is graph-changes.json; catalogue
registration and connection/selection presentation account for the broad reach.
This risk is retained for review and full CI, not downgraded by file/node axes.
