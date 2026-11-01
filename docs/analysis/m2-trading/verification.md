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

## First complete run and four-failure follow-up

The complete run on `6950a0c07bceb1f8b5a58d1bd9950cb33ad0fcc9` ran 3914 tests
in 1638.307s: FAILED, 14 failures, 27 errors, 42 existing skips. All main failure
IDs remain; four NEW IDs are retained in [the comparison](first-full-comparison.json).
Raw traceback review matches 37/41 ordered frames and exception type chains;
22/22 referenced repository source blobs match main. These are comparison facts,
not a passing full-suite claim.

One new failure was a real page-boundary violation. Source commit `f98d98c`
normally merges pinned main `67249dc126423212bbcced2048992c4c50a1be48` and changes
`install_trading_environment(window, layout, page)` to receive the explicit owned
trading-page widget from its caller. No parent/shell discovery is moved elsewhere.
The unchanged negative-rule scan is RED at the old parentWidget call and GREEN
across all 239 page-source files after the fix. A new real-widget case supplies
an explicit page distinct from the layout owner and also verifies the real
TradingWindow's stable page-3 content/LOCAL styling target. The original
PageBoundaryTests assertion remains unchanged.

Exact parent-blob audit verifies 1173 inherited non-documentation files; only the
two reviewed UI source paths and their added regression differ. The three
incoming market files match pinned main exactly. There are no baseline re-pins
in the source commit. Complete all/staged graph review reports 42 symbols,
20 files, two chart-paint flows and MEDIUM risk, no error/partial/truncation
flags or empty IDs. Dynamic Qt callers remain UNKNOWN and were checked against
actual bindings; source/caller impact is LOW. Global graph caps are retained.

Small offscreen checks after the M2-8 full run's smoke-sensitive prefix passed
used the provisioned root venv, `PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen` and
checkout/tests plus checkout on PYTHONPATH:

| Command suffix | Result |
|---|---|
| `-B -m unittest test_m2_trading_page test_m2_readability test_m2_guidelines test_market_settings_fix test_desktop_pages.PageBoundaryTests -v` | 35 passed, 7.271s |
| Three exact original short-copy cases plus unchanged architecture case and new explicit-owner case, before text-oracle update | Five run, three expected text failures; both architecture/owner cases pass, 2.358s |
| `-B -m unittest test_dashboard_characterization test_trading_valuation_freshness test_desktop_pages.PageBoundaryTests test_m2_trading_page.M2TradingPageTests.test_environment_installation_uses_the_explicit_page_owner -v` | 12 passed, 11.425s after the separate exact oracle update |

The latter two modules now expect only the existing M2 short visible labels.
Five added assertions bind the original complete v2 safety text in the actual
help details/accessibility description. All original control identities,
row-preservation, financial-unknown, same-stamp repaint and no-None-money
assertions remain. No production copy, catalogue record, skip, cap or timeout
changes. Changed-file Ruff check/format and diff checks pass.
The separate baseline/evidence commit also passes 37 document/layout checks in
2.138s. Complete all/staged graph checks report eight symbols across five files,
LOW risk and zero affected processes, no error/partial/truncation flags or empty
IDs. Unittest dispatch is confirmed by the exact exercised cases, not absent
graph caller edges.

M2-8's exact test/developer ownership cleanup is a prerequisite of the next
complete run; final source integrates that dependency normally, without rewriting
its seven source/test/tool files. Actual startup, new full discovery and CI on
the final composite remain PENDING controller execution. Small checks resumed
only after the other run's smoke prefix; this is not whole-run isolation. No
native engine process, installed app or full test suite was launched or stopped
by this follow-up agent.

## Final cleanup integration and newly reachable text oracles

Normal dependency merge `dc580963b18830fef9478bff99073e8328a1f2ca` retains all
seven incoming M2-8 test/tool blobs exactly from `fdfde06`. All 1178 staged
non-documentation blobs match the intended parent. The source fix remains
`f98d98c`, and the initial three text-oracle correction remains separate `7ca917a`.
Merge all/staged graph review is complete: 76/74 symbols respectively (the
licensed later text baseline is unstaged), 13 files, nine load-probe flows and
HIGH risk; no error/partial/truncation flags or empty IDs. The inherited exact
ownership/normal-shutdown behavior and its original focused tests were reviewed;
UNKNOWN dynamic callbacks are not unused-code claims. Final focused widget,
finance repaint, architecture, market and pure-fake cleanup/load tests pass
51 cases in 21.006s. Actual-process cleanup cases are still deferred.

Literal audit also found two old visible-label expectations in
`RuntimeContextClientTests.test_three_environments_use_real_ipc_and_never_mix_books_or_implicitly_connect`
and `test_standard_disconnected_launch_without_profile_keeps_financial_facts_unknown`.
Their native bodies were previously blocked by the main host's startup-PID
failures. The first expects the full v2 warning; the second expects its original
"空表不代表沒有持倉" substring in the now-short label. A separate feature-baseline
delta expects only `m2t.facts_pending` visibly and preserves the exact old warning
in full help/accessibility, including that substring. All original unknown
money, account/context identity, no-implicit-login and no-engine-creation
assertions are unchanged; ownership cleanup code is unchanged.

Both predicates were RED on actual TradingWindow widgets with the original old
text oracle and GREEN with the corrected expectation. The fake read models
explicitly use disconnected SIM/LIVE, empty accounts/exposure, NO_DATA and None
financial facts; full warning details/accessibility remain exact and zero
commands are emitted. This is real-widget surrogate evidence, not execution of
the native IPC test bodies. Those cases must run in the new final full suite.
The audit found no other old short-label references in visible-text assertions;
remaining old keys intentionally bind complete help/tooltips. No speculative
baseline, catalogue, skip, timing or cap changes were made. Complete full-suite,
actual startup and remote CI remain PENDING on the final composite.
Final document/layout checks pass 37 cases in 2.791s. The separate two-oracle
baseline's complete all/staged graph checks report seven symbols/three files,
LOW risk, zero affected processes and no error/partial/truncation flags or empty
IDs; inherited production/cleanup behavior remains unchanged.

## Final source-equivalent validation

Final source `4fd1f6e36d28315b871db66322ad78666fe18055` completes 3941 tests in
1543.784s: FAILED, 10 failures, 22 errors, 42 existing skips. The BOM-aware
[comparison](final-full-comparison.json) records all 32 traceback occurrences,
31 distinct failed IDs and zero new IDs versus main `0453136`; five prior
runtime/startup failure identities no longer occur. This is a nonzero local
suite with reviewed existing host limitations, not an all-green suite claim.

All 32 actual exception-type chains match main. Manual cause review retains
20 symbolic-link privilege failures (WinError1314), one retained worker-log
WinError32 cleanup, the original crash-driver native/launcher PID assertion
followed by WinError32 on the same simulated-exchange database, three mutex/
preexisting-app assertions, four incomplete diagnostic-probe assertions and
three invalid retained-grandchild-handle/cleanup failures. Temporary paths,
PIDs and timing differ. The 30/32 traceback occurrences with unchanged test
files are byte-identical to main; the other two come from the inherited cleanup
fixture update, with the identical preexisting-app guard failing before fixture
creation. Incomplete diagnostic records are not proof of another child cause.

The raw log SHA256 is
`c1b1f6232656f48ce95ac9448ba497fa3e622efc91bb8b96e166d049392ec9aa`.
Windows PowerShell5 emitted UTF-16-LE/BOM, CRCRLF and width119 wrapping. Decode
the BOM, normalize CRCRLF, fold only unittest failure-identifier headers and
assert 32 parsed blocks equals footer failures+errors. The older UTF8 comparator's
INCOMPLETE output is retained as a parser mismatch, not a missing full run.
Do not globally join traceback bodies or claim exact frame equality from wrapped
lines. Only the smoke-sensitive prefix was quiescent; other-worktree indexes and
small Qt/metadata checks resumed later. No deadline, skip or test cap changed.

Both actual `_run_window` starts at the same source return0: LOCAL6.075s and
fake BROKER_SIMULATION3.969s. [Startup facts](final-startup.json) retain real
window/research/runtime composition, research release and normal engine
shutdown. SIM uses one fake login/logout and zero order constructions/orders;
no Shioaji module or real credentials are used. The two runtime short-copy test
bodies previously hidden by startup failure now execute in complete discovery.

Normal merge of final M2-8 documentation/inventory `868da0c` preserves the tested
source. Final delivery is documentation only: all1192 non-documentation Git
entries remain exact at4fd1f6e. Three existing M2-6 test-module registrations are
committed independently; inherited cleanup registration comes from M2-8. Remote
CI is checked on the pushed PR head and remains pending at this evidence commit.
Earlier PENDING statements above describe their original verification stage;
this section is the final local full/startup record. First-run failures remain
in their original source scope and are not waived by this later result.


## Upstream endpoint-cleanup backport verification — 2026-11-02

Exact frozen source `b39af9c9e7a148661dfb1bd254c3f4e34157a11a` completed 3943 tests in
1456.190s: FAILED (failures=10, errors=22, skipped=42). This is a nonzero local
suite with zero new failed identities versus original main0453136, not an
all-passing local result. All32 occurrences were individually reviewed;
30/32 ordered frames and
32/32 exception chains match.
Per-occurrence Windows/SQLite secondary differences, source comparisons and
raw log SHA256 are retained in `endpoint-backport-full-comparison.json`. No expanded main allowance.

The pre-fix CI FileNotFoundError is a real endpoint-removal race, not waived:
the same downstream correction was backported unchanged with its two methods
and snapshot/execute plus live/abnormal negative controls. Retained PID, CAS,
zero exit and15s bound remain. The original actual failing IPC case and
all12 focused process/boundary checks pass; original RED evidence is retained.

Actual original `_run_window` LOCAL5.496s and
fake BROKER_SIMULATION3.557s both return0,
render the real trading window and seven research pages, release research
and normally close exact owned lifetimes with endpoints removed. The SIM
host is an authenticated server in an owned thread, not a real broker:
fake login/logout1 each, zero order constructors/orders, no real SDK import.
Whitelisted source/PNG hashes and launch facts: `endpoint-backport-startup.json`.
Full and startup evidence are tied to this source; final documentation
heads retain identical program/test blobs and require fresh remote CI.
