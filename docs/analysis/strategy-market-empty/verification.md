# A — Strategy wizard empty market

Base: main63879689a290aab800f0d3681f4a36ff73ca6018. Step2 now shows the reason,
an accessible secondary settings action and a disabled Next button when no market
is available. Disconnected broker, connected-without-catalogue and LOCAL states
use distinct copy. Existing holding-kind filtering uses its existing explanation.
Settings closes the modal as Rejected, clears the cached wizard and navigates to
settings; reopening uses the new accepted snapshot. No connection/trading command,
strategy creation branch, engine/domain/application or IPC contract changes.

Strings: new desktop_app/strings/strategy_market_empty.py, phase70/orders3104–3107,
following merged M4a3103. Repin once after completion in a separate baseline commit;
four added strings, no changed/removed copy, exact count3108 and one inventory row.

| Check | Command/evidence | Result |
|---|---|---|
| Empty wizard/strategy/LIVE/text guard | python -m unittest tests.test_strategy_market_empty_ui tests.test_u3_strategy_ui tests.test_m2_trading_page tests.test_no_hardcoded_ui_text |51 pass,4.381s|
| Existing UI | python -m unittest discover -s tests -p test_trading_ui.py |32 pass,4.204s|
| Layers/static | check_trading_architecture.py,check_layers.py,quality_gate.py |0|
| CI selection | python tools/affected_tests.py --list |196 modules before evidence/baselines; full suite left to CI|
| Native wizard | wizard-native.json |3 states/2 owner sizes/zero facade commands|
| Native LOCAL | LOCAL.json |7.201s,normal exit0|
| Native fake SIM | BROKER_SIMULATION.json |5.880s,login1/logout1,normal exit0|

Shared interpreter C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe;
tests offscreen, real windows use windows. Both actual startup checks release
research/owned hosts and remove endpoints, never import real SDK or use credentials.
1366x768 exact;1920x1080 requested is1920x1061 client under existing screen fit.
Dialog captures are680x520 under each owner size, without font shrinking or bypass.
Keyboard/default navigation, accessible names and no-send settings route are tested.
The initial new navigation fixture lacked the reused tearDown's drain helper;
that test fixture was corrected, with all product assertions retained.

Fresh local GitNexus index on6387968:25220nodes68856edges1258clusters661flows.
Constructor UNKNOWN supplemented by runtime/tests; refresh_markets2 direct callers,
wizard opening2 callers/1process. Catalogue CRITICAL152 direct readers; partsHIGH.
No lower file-level risk waives those warnings. Complete pre-commit graph follows.

Final graph:39 symbols/3 processes/MEDIUM, all39 returned, no partial/truncated
flag. Python3.11 full syntax scan1247 files and repository lint pass. Fast prepush
reports only main's existing M3 Markdown155 CRLF/LF fence formatting; that file
has no diff. Changed files are formatted. The first repin verification correctly
rejected a missing Lane marker and rolled back the catalogue; the comment was
corrected and the same concentrated baseline generation/self-verification passed.

UI checklist: existing roles, no inline styles, no dangerous action, actionable
empty state, readable two-size captures, no English state/UTC text introduced.
Existing LIVE exact pin, G3/Gate/OOS/budgets/timeouts and acceptance score unchanged.
