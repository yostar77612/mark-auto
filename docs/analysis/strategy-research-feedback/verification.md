# Strategy research feedback

Independent branch from latest main5652457. Research and rule-validation commands
are unchanged. After the existing worker admits either action, the research tab
immediately displays its submitted strategy/version and research-in-progress
state; both submit buttons are disabled until that worker finishes. A separate
status widget survives polling and selection changes; it does not depend on the
header detail dialog, which is normally closed.

The composition root injects the existing AsyncStatus factory, like the existing
theme/market presentation dependencies. Presentation imports remain within the
unchanged layer rules. Constructor-only legacy hosts can omit this dependency;
the actual product entry always supplies it, verified in both native startups.
Child text is repolished against the existing parent-state selectors; no inline
style, theme rule or stylesheet changes are introduced.

Accepted research names LOCAL_SYNTHETIC_TRAINING as local synthetic data and
OFFICIAL_DAILY_TRAINING as official daily K, from the exact returned target View,
never inferred from environment. Validation success explicitly says research is
still required and its next action only focuses the existing research control.
Research success offers return-to-list/activation; that action selects the exact
submitted version and focuses the existing activation control, without sending
a command. LIVE retains its disabled activation and neutral list-navigation copy.

Rejected receipts display injected ERROR_TABLE explanation plus next step,
without receipt.message or raw exception text. Unknown evidence/transport/stale
results remain unconfirmed and offer no activation. Results from a changed
context/epoch/account/environment are hidden. The original admission, worker
lifecycle, stop priority, stale-state checks and all financial actions remain.

New files: desktop_app/features/trading/strategy_research_feedback.py,
desktop_app/strings/strategy_research_feedback.py and
tests/test_strategy_research_feedback_ui.py. Strings phase72/orders3111–3123,
after merged B3110;13 additions, expected catalogue3124, no legacy copy changes.
Generate baselines once after completion in a separate baseline commit.

| Check | Command/evidence | Result |
|---|---|---|
| Related UI, real research lifecycle and LIVE | python -m unittest tests.test_strategy_research_feedback_ui tests.test_u3_strategy_ui tests.test_trading_ui tests.test_m2_trading_page tests.test_desktop_unified_research tests.test_trading_ui_integration tests.test_no_hardcoded_ui_text |121 pass,92.991s|
| Final status text styling/feedback | python -m unittest tests.test_strategy_research_feedback_ui |13 pass,1.364s; native recaptured after child-text repolish|
| Lint/changed format | ruff0.16.10 check .; ruff format --check on8 changed Python files |0|
| Architecture/layers | python tools/check_trading_architecture.py; python tools/check_layers.py |0 violations/findings|
| Static gate | python tools/quality_gate.py |0|
| Affected tests | python tools/affected_tests.py --list |199 modules before docs/baselines; full suite only in CI|
| Native feedback | native.json; five states/two sizes |pending/local/official/validated/failed readable, zero order commands|
| Native LOCAL product startup | LOCAL.json |6.672s,normal exit0,feedback installed|
| Native fake BROKER_SIMULATION startup | BROKER_SIMULATION.json |5.456s,normal exit0,feedback installed,login1/logout1|

Interpreter C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe (3.13.11).
Unit tests use QT_QPA_PLATFORM=offscreen/PYTHONPATH=tests; native checks use windows.
Actual startups release research/owned hosts and remove endpoints; no real SDK,
keys or broker orders. Native source labels use typed offline result fixtures,
not an official download claim. Two requested sizes1366x768 and1920x1080;
existing screen fit makes the latter1920x1061 client. No font/fit bypass.
Keyboard return/focus and accessible text are tested. The existing stop-priority
test is also reused with the real injected status component.

Pre-edit graph: shared worker-admission display hook HIGH (4 direct callers,
3 process families), catalogue CRITICAL (152 direct readers), parts HIGH.
StrategyControls.render has2 direct callers; runtime composition has1 direct
caller/LOW. Constructor UNKNOWN is confirmed by actual workspace/runtime calls,
not treated as unused. The initial incremental graph missed existing symbols;
a full local rebuild restored them before existing-method edits. No FTS repair
or network install. Indexed base5652457:25332nodes/69092edges/1267clusters/663flows.
Existing graph process caps do not replace source reads or regression tests.

No quantlab/engine/domain/application/IPC changes, new UiAction or LIVE pin edits.
G3/Gate/OOS/budgets/timeouts and ACCEPTANCE230/300 remain unchanged. The user
explicitly authorized merging this appearance-only PR after full CI is green.

Concentrated repin completed/self-verified: catalogue +13/0/0,count3124,
two new module rows, aliases unchanged. Stylesheets/observers/settings inputs/
platform applicability remain current without changes. Assertions are intact.
Feedback PNGs use research-* names to avoid case-insensitive collisions with
LOCAL startup captures; the final native evidence contains both sets separately.

Fast prepush: lint, all1253 Python files under3.11 syntax and static checks pass.
Only main's existing M3 Markdown155 CRLF/LF fence formatting differs locally;
that file has no diff here. The eight changed Python files pass format checks;
full remote formatting remains required before merge.

Complete final detect_changes:52/52 changed symbols,6 affected processes,HIGH,
no partial/truncated flag. Flows are the existing new-version/transfer feedback
paths and new admitted-research display paths. The final UI/catalog check is
15 tests passed in1.436s; new strings use literal ui_text keys throughout.
