# U4 risk and automatic execution presentation

Base: latest merged main f0e974fd5237c539bdb7f97cc78366adffbf2f3d (U3 PR153).
Only desktop presentation, composition, strings, tests and documentation change.
No quantlab, engine/domain/application or IPC contract changes. Full tests run in
CI; the local checks below are related modules only.

## Behavior

- Account risk settings use the accepted AccountRiskLimits and SAVE_ACCOUNT_RISK:
  default daily loss3% of allocated capital, per-order amount and maximum positions.
  Drafts are scoped to context/epoch/environment/account and survive polling.
- Persistent danger all-stop is visible on every page. Its confirmation defaults
  to Cancel and uses existing STOP_NEW: stop new entries/cancel entry orders while
  protective exits remain. LIVE retains its backend-supported stop-only meaning.
- Overview shows seven backend preflight facts with explanations and next steps.
  Missing checks never imply success; simulation CA says it is not required.
  Keeping the computer on during trading is a reminder only.
- Overview, trading and header show pause/reasons; the two pages also display
  latest evaluation, next evaluation and last order result in Taipei time.
  Only an accepted AUTO_RECONCILE for the current scope plus verified state enables
  a separate user-confirmed AUTO_RESUME. Changing scope/version during confirmation
  sends nothing. No automatic resume or retry is introduced.
- AUTO_RESUME joins the exact pinned LIVE_ORDER_ACTIONS set. Widgets, direct
  handler and shared command boundary refuse LIVE resume. Existing pins/assertions
  are preserved and expanded; no production-order opt-in exists.
- Merged PR147's DailyIntentView is rendered read-only. WAITING_SESSION is normal,
  neutral scheduling and does not require resume. The table displays exact backend
  target trade day/window; UNKNOWN cannot resend, DISPATCHED does not imply a fill,
  EXPIRED never moves to another date. Current price/size/reapproval stay backend
  decisions. No new action is added for daily signals.

## Local validation

Interpreter: C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe (3.13);
syntax: py -3.11; Ruff0.16.10 from the same shared .venv.
Tests use QT_QPA_PLATFORM=offscreen; native checks use windows.

| Check | Exact command / evidence | Result |
|---|---|---|
| Automatic/risk/LIVE/strategy | python -m unittest tests.test_u4_automatic_ui tests.test_m2_trading_page tests.test_u3_strategy_ui |40 pass,4.773s|
| Existing UI | python -m unittest discover -s tests -p test_trading_ui.py |32 pass,3.682s|
| Actual IPC integration | python -m unittest discover -s tests -p test_trading_ui_integration.py |12 pass,43.592s|
| Related source lint/format | Ruff check and format --check on13 source/test files |pass|
| Python3.11 syntax | compile of the same13 changed files |pass|
| Trading architecture | python tools/check_trading_architecture.py |0 violations|
| Repository layers | python tools/check_layers.py |0 findings|
| Static gate | python tools/quality_gate.py |0 findings|
| CI selection | python tools/affected_tests.py --list |232 modules selected before evidence/baselines; full execution left to CI|
| Native LOCAL | LOCAL.json |7.816s,normal return0|
| Native fake BROKER_SIMULATION | BROKER_SIMULATION.json |6.891s,normal return0|

The first IPC integration attempt under restricted temporary-folder access failed
with WinError5 creating/cleaning its temp directory. The same module passed with
normal user access; no product or timing changes were made. Both native startup
checks had visible actual Windows widgets, released research, normal owned-engine
exit0 and removed endpoints. Fake-SIM login/logout1/1; neither imported real SDK
nor used credentials/orders. Synthetic DTO screenshots additionally assert zero
facade commands and show keyboard-accessible controls. Unit tests verify keyboard
risk entry/Space activation, accessible names and default-Cancel confirmations.

## Strings, baselines and graph

New desktop_app/strings/automatic_risk.py: phase68, orders3032–3085,54 records,
directly following merged U3 order3031. New presentation files: automatic_status.py,
account_risk_controls.py, daily_execution.py. New test:test_u4_automatic_ui.py.
Run repin_baselines.py once after feature completion; generated snapshot/count/
module inventory changes belong in their own commit, without weaker assertions.

Fresh local index is bound to this worktree/main f0e974f:23871nodes/65041edges,
1175clusters/664flows. MCP retained stale state, so the authoritative pre-edit
checks used the CLI against this actual worktree. Shared command is CRITICAL
(8 direct/11 total,6 process families;60 unresolved receiver sites require source
checks), catalog CRITICAL180, translation_parts HIGH150, theme CRITICAL71.
TradingWindow constructor is UNKNOWN, not unused: source confirms runtime and UI
test construction. Qt/dynamic apply_state calls were checked in source. No lower
file rating waives a higher symbol warning. New styling is composition-injected;
existing shutdown functions, order confirmations and U3 unchanged-poll guard remain.
Complete pre-commit graph results are saved alongside this document.

Final indexed diff:73 symbols/10 affected processes, HIGH; all73 symbols returned,
no partial/truncated flag. The source commit is followed by an isolated generated
baseline commit:54 added strings, no removed/changed strings, exact count3086 and
four new inventory rows. The repin tool's own verification passed. No stylesheet
hash or observer baseline changed. Fast prepush passed repository lint, Python3.11
scan1201 files and static gate; whole-repository format remains blocked only by
main's existing M3 Markdown fence CRLF/LF formatting at155. That unrelated file
has no U4 diff. Changed U4 files are formatted; CI is the full-suite authority.

## Visual checks and limits

1366x768 is exact. Requested1920x1080 uses1920x1061 client under existing screen
fit; actual geometry is recorded in JSON and screenshot names. Header42px at both
sizes; no font shrinking or screen-fit bypass. Overview/trading/settings, normal
daily waiting and unknown-result pause are captured at both sizes. Lower overview
checks remain reachable by scrolling. Header rework and existing-wide code/text
cleanup are U5. No hardware sleep prevention is installed.

Roles use existing theme tokens; persistent stop is danger, confirmations Cancel;
daily table has6 elided columns/full tooltips and actionable empty state. Paused
status includes text and reasons, normal waiting is neutral. LIVE behavior is tested
without broker I/O. Performance aggregate and editable-strategy DTO gaps remain
the separate existing engine requests. CI and Claude review remain required before
merging this PR, which includes an automatic-order authorization path.
