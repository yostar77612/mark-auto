# M2 autonomous decisions

## M2-8 / backport the verified endpoint-removal fix (2026-11-02)

Final documentation-head CI41342046048 exposed RuntimeContextClientTests
.test_owned_cleanup_handles_real_ipc_version_change_without_bypassing_cas: the
normal shutdown removed its endpoint before the owned-process cleanup snapshot.
This is the same FileNotFoundError race already fixed in downstream commit
1ebc27e; leaving that verified fix only in M2-1 was an integration omission.
Backport the identical two source/test blobs to M2-8, then inherit them through
M2-6. The new snapshot/execute control reproduces two errors in0.002s before
the fix; all12 real-process and boundary tests pass in23.693s afterward.
Retained PID/session identity, state-conflict CAS, original15s exit bound and
zero-exit verification remain mandatory; live/abnormal/foreign processes still
fail. No production runtime, assertion, skip or timeout changes.

GitNexus with test callers reports class MEDIUM (five direct importers, seven
total); cleanup method LOW (two direct callers, six total, existing load-probe
flows). Test class UNKNOWN is confirmed through unittest discovery and direct
source references, never treated as unused. The offline index is refreshed;
flow enumeration/callable caps are lower bounds, not evidence of absent calls.
Record the two inventory measurements separately. Repeat complete discovery
and actual LOCAL/fake-SIM launches on both changed branches before pushing;
M2-1/M2-2 already contain these exact corrected blobs and remain source-equivalent.

Latest M2-8 acceptance source `590646058aa73f7084ed310b63dd4b0acad6d491`: complete3916/1422.446s, FAILED (failures=10, errors=22, skipped=42), zero new identities; all32 actual blocks reviewed. Real LOCAL/fake-SIM launches both return0, normal owned cleanup and zero external financial operations. Fresh CI remains a separate gate.

Latest M2-6 acceptance source `b39af9c9e7a148661dfb1bd254c3f4e34157a11a`: complete3943/1456.190s, FAILED (failures=10, errors=22, skipped=42), zero new identities; all32 actual blocks reviewed. Real LOCAL/fake-SIM launches both return0, normal owned cleanup and zero external financial operations. Fresh CI remains a separate gate.

## M2-8 — 2026-11-01 13:09 Asia/Taipei

Problem: on this Windows host the venv executable is a redirector. The retained
Popen PID is the redirector, while the authenticated engine session correctly
publishes the native Python child's PID. `ensure_engine` rejects that mismatch
and times out; a failed unittest `setUpClass` never calls `tearDownClass`.
The completed main and M2-6 runs demonstrated healthy LOCAL engines left alive
with locked SQLite files. Both were separately shut down through authenticated
IPC after verifying their exact fixture path and session/child identity.

Options: weaken the production PID comparison, change production ownership
semantics, or correct test/developer launching and register cleanup before setup.
Choose the last option. `tools/owned_trading_engine.py` scopes only the source
launcher reference in `context_client`: it uses `sys._base_executable` with the
already installed import paths. It does not mutate global `sys.executable` or
the subprocess module, replace a runtime facade, or bypass any PID, account,
environment, authenticated-IPC, engine-owner, handle or installer guard.
Product runtime files remain unchanged.

Each scope records the actual native Popen before startup can fail. It closes
only those handles, validates the session PID before any control command, sends
normal SHUTDOWN_ENGINE, waits for exit, and removes only matching `_STARTED`
entries. A reused host is not registered and is not closed. A failed shutdown
does not prevent attempting the remaining owned children. An unresponsive own
native child may require the retained handle's terminate as failure containment;
that always raises and cannot produce passing acceptance. No process discovery,
broad kill, user-data deletion, timeout extension, skip or applicability change
is used to manufacture a pass.

Class cleanup uses `addClassCleanup`/`enterClassContext`; per-case engines use
`enterContext`. Temp cleanup is registered first, so engine cleanup runs before
fixture data cleanup. Synthetic multiprocessing hosts register their individual
authenticated cleanup hook before `start` and readiness assertions, independently
of UI `tearDown` or other host cleanup failures. The load probe establishes its
owner scope before `ensure_engine`, including partial initialization and report
writing failures; its source identity also includes the new launcher helper.

Tracked launcher coverage:

| Owner | Coverage |
|---|---|
| `tests/test_trading_runtime.py` | Shared class host; per-case shutdown/deep roots; second-owner rejection and standalone UI client use native Python with the same packages. All prior protocol/identity/transport assertions remain. |
| `tests/test_runtime_context_client_v2.py` | Context-manager-created LOCAL/pending hosts use a scope registered in setUp. Synthetic hosts each register separate cleanup before start. Cleanup still runs if UI drain/teardown fails. |
| `tests/test_trading_runtime_context.py` | Every retained synthetic multiprocessing host has a cleanup hook before start; one failure cannot abort cleanup of another hook. |
| `tests/test_trading_installer_guard.py` | Engine scope encloses each guard-lifetime case before temporary-directory cleanup; controlled UI entry uses native Python and cooperative stop before exact-handle failure containment. |
| `tools/trading_load_probe.py` | Scope starts before initialization, normal IPC cleanup in finally even without a returned facade; cleanup failure marks report FAIL. |
| `tests/test_runtime_context_cli_v2.py` | Routing-only calls mock `serve`/`run_window`; no child or engine is launched. |

`git grep -- '--trading-engine'` and all `ensure_engine`/`open_context`/`_run_window`
test/tool references were reviewed after graph discovery. The second-owner
subprocess deliberately cannot acquire an existing root; its direct native
Popen in `subprocess.run` cannot strand a venv grandchild on timeout.

Graph: the new worktree was indexed locally (19,469 nodes, 51,711 edges). Existing
symbols were impacted before edits; test lifecycle dispatch is UNKNOWN in the
graph, so direct source and text references confirmed unittest entry points and
fixture consumers. `start_ui_entry` and load-probe helpers are LOW; synthetic
`start` is MEDIUM with unresolved dynamic receiver sites, cross-checked by text.
No HIGH/CRITICAL pre-edit change was reported. New untracked symbols initially return
UNKNOWN/not-found; they require final indexed change analysis, not an unaffected
claim. Initial discovery used the already indexed source-identical main probe
while the worktree index built; relevant source diff against main was empty.

Final graph analysis is HIGH: 64 changed symbols, 12 files and nine affected
execution flows, all belonging to the existing developer load-probe main entry.
The new scope has five test/tool importers (MEDIUM); its cleanup and load-probe
main are LOW. Callable cleanup/launcher hooks remain UNKNOWN to static dispatch
and were confirmed in the source and real-process tests. The complete result
has no partial/truncated flag or empty IDs. Review covers the launcher binding,
all registered cleanup hooks and truthful load-report failure paths; production
files have no diff. The initial incremental rebuild lost method IDs and falsely
reported CRITICAL/603 unrelated flows. A local-only forced rebuild restored all
IDs and the complete result above; no source/test semantics were changed to
work around the index defect, and no FTS extension was downloaded.

Evidence boundary: offline LOCAL and injected synthetic ports only, no real SDK
login, credentials, CA or order operation. Focused checks are recorded in
[m2-8-verification.md](m2-8-verification.md). Controller schedules the branch full
suite, final real-window startup and CI independently; they are not inferred
from focused tests or a tooling-only launch check.

## M2-8 — 2026-11-01 native installer precondition

The controller granted an exclusive native test window after policy full-suite
completion and normal cleanup of its exact test-owned source engine. The seven
installer-guard cases ran: five boundary cases pass, and both native cases fail
their unchanged preexisting-app assertion before any child or fixture creation.
The controller confirms those same failures in main's complete baseline.
Read-only inspection found the owner's installed 0.3.0 GUI and LOCAL engine,
both older than this task, which the source-Python engine scan does not include.
Choose to preserve the assertions and record the host limitation; never stop
those non-fixture processes, use a different mutex, add a skip, or claim native
acceptance passed. No further engine tests run while the controller resumes
the next full suite. Details and pending full/startup/CI evidence are in
[m2-8-verification.md](m2-8-verification.md).

## M2-8 — 2026-11-01 complete-run evidence boundary

Retain the first complete run's NEW positive-smoke timeout as a real failure,
even though the exact unchanged case subsequently passes sequentially on main
(15.027s) and M2-8 (13.915s). The unchanged full retry completes 3909 tests in
1487.114s with 10 failures, 22 errors, 42 existing skips and no new failed IDs
versus main. Only its smoke-sensitive prefix was quiescent; other-worktree index
and small Qt/metadata checks resumed later. Do not claim full-run isolation,
prove a latency cause from correlation, raise deadlines or label the first
failure a waived flake. Raw review retains the E06 cleanup WinError/path
difference even though exception types and failed IDs match. Normal actual
LOCAL/fake-SIM startup passes at the same source head are independent evidence;
they do not turn failed native-host suites into acceptance. Commit only reviewed,
sanitized evidence and documentation; leave executable/test/tool bytes unchanged
from `8f03a9905c337680f2f963ba284bed5bf3638bcb`. Controller owns push and CI.

## M2-8 — latest-main normal integration

Merge main `67249dc126423212bbcced2048992c4c50a1be48` normally into the M2-8
branch, preserving all market, policy and cleanup decision/contract blocks.
Keep every inherited source/test/baseline blob exact; resolve only appended
documentation, with no rebase, source rewrite or new baseline change. The
result combines separately tested sources and needs new full discovery and
actual startup at the final head. Preserve earlier failed-run evidence under
its original `8f03a99` scope; do not present it as final composite acceptance.
Controller serializes native/engine/full validation after M2-6 completes.

## M2-8 / final composite full and startup evidence

Record finalfdf3914/1593.006s10F22E42skip honestly as a nonzero local suite with
zero new failures. Review all32 actual blocks, including finalE06 WinError32
matching main rather than borrowing the earlier WinError5 cause. Retain original
smoke failure/retry evidence. Both final actual startups return0 with normal owned
cleanup and fake-only broker operations. This commit is documentation only; CI
is checked on the pushed head. No source, assertions, thresholds or skips change.

## M2-8 / explicit new-test inventory registration

A final all-new-Python-path audit found the new cleanup regression module was
not explicitly listed in section2, although architecture tests already passed.
Register only that existing test file and its measured line count in a separate
inventory baseline commit. Test code and every other non-doc blob stay unchanged;
the completed full/startup results remain source-equivalent. This repairs the
specification documentation requirement without changing any test assertion.

## M2-8 / final documentation integration audit (2026-11-02)

Move the M2-8 addenda before the inherited sections and retain main PR #133's
packaging records verbatim at the original append location. This separates
independent documentation edits without importing any program, test or baseline
changes. All previously verified source blobs are unchanged. Require fresh CI
on this documentation head and verify stacked mergeability independently.

## M2-0 / prerequisite evidence — 2026-11-01 12:04–12:12 Asia/Taipei

- Evidence supplied by the coordinating agent: after `git fetch origin`, main
  was `0453136`; specification PR #124 was OPEN at `07d3cc9` on
  `origin/claude/m2-spec`. Both `gh pr list --state all --head
  codex/fix-market-settings` and `git ls-remote --heads origin
  '*market-settings*'` returned no matching prerequisite.
- Decision: start only independent M2-0 and M2-6. M2-1/M2-2 remain unstarted
  until explicit merge evidence for the market-settings prerequisite is
  available. Do not infer completion from a missing branch or merge main.
- Scope: this worktree owns only M2-0. The specification remains implementation
  guidance, not evidence that M2 execution features have been delivered.

## M2-0 / D1 policy and historical boundaries — 2026-11-01 Asia/Taipei

- Authority: owner decision D1 dated 2026-11-01 in
  `origin/claude/m2-spec:docs/design/m2-sinopac-sim-auto-trading-spec.md`.
- Alternatives: retain the old product-wide permanent prohibition; suggest an
  immediate LIVE toggle; or distinguish the v1 research/Paper contract from
  the authorized v2 roadmap. Choose the last: production orders are disabled
  by default, future enablement needs a separate explicit owner decision,
  and M2 continues to hard-disable production orders. The v1 real-order ban
  remains permanent. SinoPac simulation orders are authorized for subsequent
  M2-2 implementation and verification, not enabled by this policy-only PR.
- Update README, contributor safety/mission guidance, the upgrade contract,
  all six ADR policy statements, the glossary and PR risk checklist. Preserve
  historical dates, evidence, budgets, scopes and immutable records. Append
  the current policy to IMPLEMENTATION_CONTRACTS without rewriting its frozen
  historical contracts.
- The passive banner has two existing, deliberately equivalent records:
  `ui.init.research_mode_banner` and `header.live_disabled`. Apply the single
  authorized wording delta, `研究模式・實盤停用` → `研究模式・正式下單停用`, to both;
  do not add or renumber catalog/alias records. Existing HeaderTests require
  equality. Retain the original `ui.__init__.text_3` alias and all provenance.
- Baseline updates belong to a separate commit with this D1 reason. Preserve
  historical source identities and exact unchanged values; admit only this
  banner delta and the ADR safety-policy phrase. Do not regenerate fixtures,
  accept arbitrary current inventories, remove tests or relax safety checks.
- Verification status: focused checks pending during implementation. The
  coordinating agent owns serial full discovery, isolated LOCAL/fake
  BROKER_SIMULATION launch checks, push/PR creation and remote CI. No passing
  full suite, actual broker verification or CI result is inferred here.

## M2-0 / graph and focused verification — 2026-11-01 Asia/Taipei

- Worktree/base: `.worktrees/m2-policy`, `codex/m2-0-policy`, main `0453136`.
  Installed GitNexus 1.6.12 `status` initially reported no index. Offline
  `analyze --index-only` completed in 100.8 seconds with 19,448 nodes,
  51,674 edges and 629 reported flows. Its process-extraction cap warnings are
  not interpreted as proof of absent flows. No extensions were downloaded.
- Upstream impact ran before editing both string ENTRIES records and the
  affected ADR/glossary/alias/R7 test methods. Each reported UNKNOWN/zero
  resolved callers. Direct source and text searches confirmed the static
  translation_parts → catalog_data → catalog assembly, AppHeader badge and
  disclosure consumers, exact header-equality assertion, and unittest
  discovery methods. UNKNOWN was resolved with that evidence, not read as low.
- Source graph change analysis completed: 24 symbols in 14 tracked files,
  zero reported affected processes, low risk, no partial/truncation flag.
  This bounded graph result supplements direct diff and tests.
- Pinned Ruff check/format passed for both changed Python source files.
  `python -m unittest discover -s tests -p test_header_c1.py -v` passed all
  six tests in 2.041 seconds. Exact baseline assertions are intentionally
  updated only in the following, separate D1 baseline commit.


## M2-0 / completed verification and owner follow-up — 2026-11-01T14:57+08:00

- The owner's follow-up assigns the absent market-settings prerequisite to
  this run and permits dependent implementation after its own green CI,
  without a main merge. PR #129 reached all35 SUCCESS on run41279585267,
  attempt2, exact2d8319b. M2-1/M2-2 now proceed in separate worktrees.
  This supersedes the initial wait-for-merge decision; it does not enable
  LIVE or authorize second-round automatic trading.
- Final complete M2-0 discovery on unchanged97e2a8b: 3,888 tests in 2,380.898 s; FAILED (failures=10, errors=27, skipped=42).
  No new failure identities; all actual traceback differences were reviewed.
  Preserve the nonzero main-host result honestly. The initial new smoke-marker
  failure passed on this complete unchanged retry; the separate incomplete
  permission-loop attempt is excluded rather than called a pass.
- Use normal user execution for later full suites after diagnosing the
  restricted-run tempfile retry. Do not change test limits, Windows policy,
  ACLs, application code or dependencies to hide that harness mistake.
- Actual LOCAL and fake BROKER_SIMULATION windows returned0 and released their
  owned resources. Source PR128 had35/35 CI success; final documentation-head
  CI is verified separately before delivery. Evidence and limitations are in
  docs/analysis/m2-policy/verification.md and its companion files.
- This commit adds verification documentation only. No product/test/fixture
  behavior, G3 source, SDK pin, PROJECT_STATE or acceptance score changes.

## Market-settings prerequisite fix / owner steering — 2026-11-01 Asia/Taipei

The owner explicitly assigned the three installed 0.3.0 market regressions in
`build/codex-market-fix-prompt.md` to this work. The previously missing
`codex/fix-market-settings` prerequisite is now an implementation assignment,
not a reason to wait. This worktree starts from `origin/main` `afc45ea` and
owns that fix branch only. The coordinating agent owns complete serial
discovery, actual LOCAL/fake BROKER_SIMULATION startup, push/PR and all-green
CI. M2-1/M2-2 may continue after the fix PR and green CI under this new owner
instruction, without waiting for a main merge. No main merge or round-two
implementation is authorized here.

## Market-settings fix / boundaries and minimal changes — 2026-11-01

- Save: test the actual Qt combo and save button first. Both broker-simulation
  and LIVE selections reproduced zero save signals plus the installed error.
  Qt returns the str-enum payload as a plain string. Reconstruct Environment
  once at the UI boundary, matching the existing BrokerPanel convention;
  retain MarketDataSettings validation, secret-reference-only input and the
  existing explicit save/connect workflow. No real credential is resolved.
- Status: a disabled market panel must display the existing disconnected
  string regardless of the supplied engine-derived status or stale error.
  Add that presentation branch after loading the form fields. Enabled market
  statuses/errors keep their original behavior. Do not change bootstrap's
  market_connection projection or its other consumers.
- Empty chart: actual QPainter text-region observation reproduced legend
  overlap at the terminal's existing 90px minimum for three font sizes.
  Move the centered empty/error message below the legend only when its
  centered bounds would overlap. Preserve normal-size empty positions and
  the entire nonempty rendering path. No string/style/theme change or new
  layout abstraction is needed.
- Tests are at the owner-specified seams: real combo/button signal transport,
  panel apply/display, and actual Qt painter text bounds. No constructor-only
  substitute, safety skip, budget/timeout change or weakened old assertion.

## Market-settings fix / trading currentData audit — 2026-11-01

The audit covers every currentData call in desktop_app/features/trading:

| Consumer | Existing enum handling / conclusion |
|---|---|
| MarketDataPanel save | Missing Environment reconstruction was the reproduced defect; now fixed. |
| BrokerPanel.settings | Already reconstructs Environment. |
| TradingWindow environment navigation | Already reconstructs Environment before use. Account/context/strategy selections are string/tuple identities; settings risk is Decimal, not an enum. |
| StrategyWizard.form | Already reconstructs Market, HoldingKind and Side. Candidate/default/JSON-preview comparisons use the str-enums' value equality; no typed domain value escapes unconverted. |
| AlertRuleDialog.create_rule | Already reconstructs AlertKind. Kind/default/scanner lookup uses value equality; parameter, scope and period values are intentional strings. All twelve actual Qt kind selections create typed rules in the added regression. |
| ResearchPanel navigation | Stores ordinary page-identity strings. |

No other matching typed-boundary bug was found; do not insert redundant
internal validation or change the existing alert/wizard semantics.

## Market-settings fix / graph and verification ownership — 2026-11-01

GitNexus status initially reported no worktree index; installed offline
`analyze --index-only` completed in 166.0s with 19,473 nodes and 51,718 edges.
Worker self-healing and flow-cap warnings were retained, not treated as proof
of absent flows. Before source edits, impacts used the already indexed policy
worktree's byte-identical panel/chart sources while this index was building:
save/paintEvent UNKNOWN were resolved through direct Qt bindings and source;
apply LOW had one direct caller and three unresolved dynamic call sites.
The completed local index repeated paintEvent UNKNOWN and reported the shared
CandlestickChart class MEDIUM, 19 affected symbols / nine direct. Tests remain
required despite those graph results.

All three original feedback loops went red before their corresponding fix,
then green. Five new offline Qt regressions passed, including two saved enum
identities, disabled/error status combinations, enabled states, all twelve
alert kinds, and 18 empty/error paint scenarios. Broader focused/prepush and
pre-commit complete graph evidence will be recorded by this phase; full
discovery, real composition startup and remote CI remain coordinating-agent
checks until their actual results exist. No completion of unrun checks is
claimed.

## Market-settings fix / focused results and prepush limitation — 2026-11-01

- All five new Qt tests pass. Twelve relevant existing modules also pass:
  test_desktop_charts (12), test_market_terminal_ui (12), test_market_watch_ui
  (7), test_chart_data (15), test_chart_footer (3), test_market_empty_ui (5),
  test_alert_ui (4), test_trading_ui (32), test_market_connection (4),
  test_market_session (5), test_r7_characterization (15) and
  test_r7_function_lengths (3): 117 existing + 5 new = 122 tests. The original
  four R7 chart captures, painter-stack counts and eight result snapshots
  pass unchanged. No historical fixture re-pin is needed.
- Exact attempted command: `pwsh -NoProfile -File tools/prepush.ps1 -Tests
  -Base origin/main` from this worktree, with the provisioned root venv,
  QT_QPA_PLATFORM=offscreen, PYTHONUTF8=1 and tests/checkout PYTHONPATH.
  Ruff check/format (1,102 files), Python 3.11 syntax (1,038 tracked sources)
  and the credential/static gate (zero findings) passed. The complete
  prepush command exits 1 and is not reported as passing.
- Cause: its unchanged test selector finds only test_market_settings_fix;
  PowerShell stores the single pipeline result in a scalar string and
  `@modules` splats its characters. A harmless argv probe directly showed
  `t`, `e`, ... `.` as separate arguments; unittest raises Empty module name
  before executing tests. This is the same tools/prepush.ps1 code as main.
  Preserve the three-bug scope and do not alter the gate or conceal its
  failure. The explicitly selected module independently ran all five tests
  successfully; the coordinating agent also requires complete discovery.
- The only separate baseline/inventory change is registering the new
  127-line test module in inventory section 2. Existing module rows, catalog
  count/order, aliases, fixtures, protected files and limits remain unchanged.
- Final offline index refresh completed in 46.8s (19,487 nodes / 51,748 edges).
  Complete pre-commit graph analysis reported 18 symbols / six files / LOW,
  with no partial or truncation flag. Required repo-layout (29) and document
  layering (8) tests also passed, bringing focused verification to 159 tests
  in 15 actual modules; the dependency-layer gate reported zero findings.
  Final commits and the coordinating agent's full/startup/remote checks retain
  their actual evidence separately.

## Market-settings fix / final frozen-source evidence — 2026-11-01

The coordinator verified source head
`34673c269e80ecdc2f9a707e77b22df2fe28e0f2` with complete serial discovery:
3,893 tests in 2,094.353s, 10 failures, 27 errors, 42 existing skips. Main 0453136
has 3,888 tests in 1,968.015s with 10 failures, 27 errors, 42 skips. All 36 failing
IDs are preexisting and there are no new IDs; this local suite is nonzero,
not a pass. Of 37 occurrences, 36 match ordered traceback frames/types. One
unchanged standalone native retained-handle case reaches a different native
assertion (already signaled 0 rather than WAIT_TIMEOUT 258); its exact cause
remains unresolved. E06's same primary PID mismatch has secondary cleanup
WinError 5 on .sqlite-shm instead of main's WinError 32 on .sqlite. Preserve
these limits; do not call every failure's underlying cause identical. An
incomplete extra main replay is excluded from passing/count/cause evidence.

Actual run_window returning 0 checks at this source passed: LOCAL 12.183s and fake
BROKER_SIMULATION 6.173s, each with 7 embedded research pages/2,726 widgets,
clean engine/research release and no real SDK import. Fake broker counts
were 1 login/1 logout/2 subscriptions/0 order constructors/0 orders; broker
financial facts remained unknown. The full-suite-owned wrapper 153036 and
native child 230124 were normally authenticatedly shut down and both exited.
No user application or data was altered.

The new origin/main UI guidelines section 10 was read without merging main
or changing verified source. Real-window fake-facade captures at 1366×768
and 1920×1080 plus 90px empty-chart details were visually inspected. The changed
group has readable controls, no horizontal scrollbar, labeled/named inputs
and buttons, and actual Tab order environment→reference→save→connect→disconnect.
Disabled settings still show 未連線 when supplied a stale CONNECTED value/error.
The isolated capture records 0 commands/0 child processes/no SDK import.

Final screenshots, focused/static limitations, exact startup JSON and bounded
failure comparison are in
[market settings verification](../analysis/market-settings-fix/verification.md).
This evidence commit changes only documents/captures, retaining all product,
test, theme and tool bytes at the frozen source. Existing page architecture,
strings and general UI redesign are outside this three-defect fix. Remote
CI is still pending and required independently before M2-1/M2-2 begin.
Final document/layout checks passed: 37 tests in 4.645s. The offline index
refresh completed; complete change analysis reported 10 document symbols,
12 evidence files and LOW risk with no partial/truncation flag. No graph
absence is used to waive tests or the full-run native-cause limits above.

## Installer SDK inclusion / autonomous decisions — 2026-11-01 20:36 Asia/Taipei

- Scope: owner-requested `codex/package-sdk`, based on `origin/main` 67249dc.
  Reuse the existing broker flavor for the default installer rather than create
  a second SDK packager. `build.ps1` downloads/installs only the hashed official
  1.7.9 Windows wheel and validates installed files; Analysis requires that same
  flavor and wheel. An absent/disabled build flag now fails before collection,
  closing the arbitrary-installed-SDK gap when removing the spec exclusion.
  Check actual Analysis Python/native inputs too, rejecting shadow modules
  selected through pathex, changed bytes and a missing native core. This check
  is at the freezer input boundary; it does not add runtime trading gates.
- Keep all other spec exclusions and original installer lifecycle sections.
  The existing early `--broker-sdk-probe` runs after candidate upgrade through
  the installed shortcut's actual executable, without developer PATH entries.
  Require frozen 1.7.9 import/native-hash evidence, zero SDK clients and no
  login/CA/asset operations. Failure is an installer CI failure; the existing
  full regression, TLS, upgrade/recovery and clean-client gates remain required.
- Keep `requirements-desktop.lock` separate from the existing SDK lock. Include
  the SDK in Windows dependency audit and default regression runtime, and record
  verified wheel/file hashes plus the actual frozen native-core digest in the
  standard manifest. No independently distributed Shioaji CLI/server is selected.
- Preserve the loader's sanitized `capability_missing` contract. In the market
  connection composition only, map it to the new application ErrorText
  `market_sdk_missing`; the panel displays its exact installation guidance.
  Account capability errors elsewhere and all existing login behavior remain.
  Reuse application error copy instead of adding/re-pinning UI catalog fixtures.
- License/source facts were read from the exact SHA256-verified wheel METADATA:
  no SDK license field/expression/file/classifier is declared; homepage is
  sinotrade.github.io and repository is github.com/Sinotrade/Shioaji. Retain
  original metadata and SBOM; do not infer Apache licensing or redistribution
  clearance from MarkAuto. README, BROKER_BUILD and THIRD_PARTY_NOTICES record
  these facts. This task adds no legal approval gate or guessed license.
- No new tracked files are required. One mechanical observer-line baseline
  update is described below and will be committed separately. All tests remain
  enabled; existing assertions for auth provenance, Qt/SQLite, legacy exclusions,
  lifecycle sections and financial safety are retained. G3 files,
  BROKER_SDK_VERSION, PROJECT_STATE and LIVE execution are unchanged.
- Initial focused verification: 111 tests across nine modules passed. Actual
  `_run_window` with the private interpreter and `-S` returned 0 for LOCAL
  (14.599 s) and fake BROKER_SIMULATION (32.702 s), showing seven embedded research
  pages and 2,726 widgets. Both released research/engine normally; fake SDK
  counts were 1 login/1 logout/2 subscriptions/0 order constructors/0 orders.
  Real SDK import and real credential access were forbidden in these launches.
  Complete main/head discovery and remote Windows installer CI are still
  required; this initial focused result does not claim those passed.

### SDK packaging / local frozen verification — 2026-11-01 20:53 Asia/Taipei

- Final focused checks now cover 112 SDK/packaging/market/lifecycle cases and
  72 expiry/bootstrap/layout/version/language cases, all passing. The existing
  expiry provenance harness receives an isolated SDK fixture while retaining
  its original packaged-data and exact source-hash assertions. Final prepush
  passed Ruff check/format, 1,038-source syntax, zero static findings and all
  66 selected changed-module tests. No skip or baseline fixture was added.
- A local real PyInstaller build using the final spec passed actual collection
  source verification. Its `MarkAuto.exe --broker-sdk-probe` returned 0 with
  frozen/module/distribution version 1.7.9, the pinned wheel/native hashes,
  selected-runtime containment and zero clients/login/CA/asset operations.
  This is supplementary local frozen evidence, not installed CI acceptance.
- The first local frozen probe failed because the simultaneously running spec
  unit harness wrote synthetic `broker-build.json` into the real build folder.
  Move that harness's broker outputs into its own TemporaryDirectory; retain
  all spec/provenance assertions. Rebuilding after this isolation produced the
  successful real frozen probe above. No production verification was bypassed.
- Supplementary local Qt audit remains nonzero: this developer private Python
  supplies OpenSSL 3.0.18 (`libcrypto-3.dll` SHA256
  e03dd02fdcfb791981c9962827cfcf495f2a47a514c1526efb57f847a9df514a),
  whereas the unchanged installer notice contract requires reviewed 3.5.9
  (75495fe0e079ab00d49be740d3c710a0b94e3f74f9648cb7cc9f768fc7f52319).
  The collected DLL exactly matches `.runtime-sqlite/DLLs/libcrypto-3.dll`;
  it is not an SDK-supplied DLL. Preserve the Qt audit/pins and all exclusions.
  Canonical CI must still build from pinned CPython 3.13.16 and pass its full
  native notice/TLS/installed-import gates; do not call the local payload a
  releasable installer or the supplementary Qt audit passed.

### SDK packaging / complete-discovery corrections — 2026-11-01 22:01 Asia/Taipei

- Main 67249dc completed 3,893 tests in 2,568.762 s: 11 failures, 27 errors,
  42 skips. One additional main-only failure is the existing ignored legacy
  `archives/legacy_autotrading/trader` residue in the original checkout. It is
  absent from this clean worktree; the user's original directory is preserved.
- First head discovery completed 3,895 tests in 2,019.876 s: 14 failures,
  27 errors, 42 skips. Every shared failing ID had identical normalized traceback
  frames and exception-type chains. Four new failures were NOT accepted:
  two layer/inventory checks observed the root scratch comparison script;
  trading architecture rejected the panel's direct private error-table import;
  page-service inventory observed an existing test patch point moving 25 lines.
- Move the scratch script under ignored build/sdk-qa (not a new tracked module).
  Provide `market_connection_guidance` through the existing public
  application.market_settings boundary and keep the panel free of private
  error-table dependencies. No dependency gate or allowed-layer list changes.
  MarketDataSettings fields/validation/serialization remain unchanged.
- The only baseline update is the existing `host.history` assignment in
  tests/test_t9_expiry_inputs.py moving from line 374 to 399 because the SDK
  packaging fixture above it gained 25 lines. In a separate baseline commit,
  update only that addition's line in e6_service_relocations.json and its exact
  canonical SHA256 guard in tests/page_services_inventory.py. All observer
  identities, multiplicities, services, aliases and state copies stay pinned;
  the historical page_services_inventory.json is untouched.
- Pre-edit GitNexus reported CRITICAL for project_e6_service_refs (75 direct
  references, 152 total, five process groups); this warning was surfaced before
  changing the pin. The literal source consumers were also inspected: the
  reviewed_inventory projection and its exact-regeneration test. This narrow
  two-line update does not waive the warning or any tests. Full discovery is
  repeated after the corrections; the first nonzero head run is not a pass.
- The baseline and first-head leftover LOCAL fixtures were shut down through
  their normal authenticated IPC command. The user's preexisting installed
  application remains untouched; no test data or original directory was erased.

### SDK packaging / final local verification — 2026-11-01 22:41 Asia/Taipei

- Final complete discovery: 3,895 tests in 2,048.750 s, exit 1 with 10 failures,
  27 errors and the same 42 existing skips. Main's 3,893-test baseline has
  11 failures/27 errors/42 skips. There are no new failing IDs or increased
  occurrences; all 36 shared failing identities have identical normalized
  traceback frames and exception-type chains. They are the existing Windows
  symlink/retained-handle/native-process-source/active-application limitations.
  The only removed ID is main's stale ignored legacy-directory failure. This
  is a complete nonzero local run with no new failures, not a claim that every
  local test passed. The final owned LOCAL leftover also shut down normally via
  authenticated IPC; the user's installed application and data were preserved.
- The actual 19 affected test modules independently pass all 229 cases, including
  settings concurrency, layer gates and exact page-service regeneration. One
  earlier manual invocation used a nonexistent module name; it was corrected,
  its error log retained, and every real module rerun successfully. No existing
  test was removed or skipped. Final prepush passes Ruff check/format, the
  1,038-source syntax scan, zero static findings and 67 selected tests.
- Final actual `_run_window` checks both return 0: LOCAL 8.340 s and fake
  BROKER_SIMULATION 5.185 s, seven research pages/2,726 widgets, normal research
  and engine release. Fake counts remain 1 login/1 logout/2 subscriptions and
  zero order constructors/orders. No real SDK/credential access is involved.
- Rebuilding the final spec and running the actual frozen EXE again passes
  the no-login SDK probe: 1.7.9, selected-runtime containment, pinned wheel/core
  hashes and zero clients/login/CA/asset operations. This does not override the
  supplementary developer-runtime Qt audit limitation documented above.
- A forced offline GitNexus rebuild restores the precise test-helper UID.
  Excluding test callers gives UNKNOWN and is not a safety conclusion. Including
  tests reports HIGH: one direct caller (`reviewed_inventory`), nine total
  symbols and one refactor-tool flow rooted in tools/refactor/split_ui_r3d.py.
  The earlier CRITICAL warning and this HIGH warning were both disclosed.
  `riskSharedAxes: LOW` is not used to waive HIGH. Literal consumers, unchanged
  observer identities/counts, exact regeneration and full discovery were checked;
  only the fixture line and corresponding checksum will be committed separately.
- Remote Windows installer/installed-import and all required PR CI remain pending
  until their actual run results exist. No merge or production/broker acceptance
  is claimed by these local checks.

### SDK packaging CI syntax correction (2026-11-01)

- PR #133's Windows workflow initially failed to parse before any job started:
  the hash-pinned audit command's `--only-binary=:all:` ended a plain YAML
  scalar with a colon. Use a literal command block, preserving the exact command,
  dependency audit and security requirements. No product source, fixture or
  baseline changes are involved in this correction.
- GitNexus cannot resolve the workflow file (UNKNOWN); direct workflow and
  packaging-test references were inspected instead. Validate YAML with the
  existing local parser, rerun affected packaging checks and prepush, then
  require fresh CI on the corrected head, including the Windows installer.

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

## 2026-11-01T12:30+08:00 — first-round PR stack and merge

- Merge M2-0 into M2-6 with a normal merge, preserving both source and separate
  baseline commits. M2-6 will target `codex/m2-0-policy`. This removes the
  competing new decision files and retains one exact text/catalog baseline.
- Preserve the common frozen implementation contracts byte-for-byte, then append
  both M2-0 and M2-6 contracts. Preserve both phases' decision history below one
  document heading. No new product behavior is introduced by conflict resolution.
- The catalog combines D1's two approved existing badge changes with M2-6's
  23 additive records (orders 2753–2775). All other existing records, aliases,
  historical identities and exact test assertions stay intact.
- Run full discovery and both actual LOCAL/fake BROKER_SIMULATION startup checks
  on the combined source before pushing M2-6. M2-1/M2-2 remain unstarted because
  the expressly required market-settings merge is still absent; no main merge,
  history rewrite or second-round work is authorized here.

## 2026-11-01 13:17 Asia/Taipei — owner-added M2-6 items 6–8

- The owner expanded this same first-round branch with real Taipei dates,
  first-start overview presentation and plain-language explanations. Normally
  merged documentation-only main `afc45ea` as `12e484e`; no history rewrite.
- Today comes from aware UTC converted through `Asia/Taipei`, independently of
  `UiState.trading_day`. LOCAL labels both dates explicitly; broker environments
  show only today in the compact header/tooltip. Same-version market-only updates
  refresh the date so midnight cannot leave yesterday's label behind. Existing
  detailed book metadata remains available through the context dialog.
- A real fresh `build_runtime(RuntimeLaunch(...))` snapshot has version1 and the
  sole `startup_reconciliation_required` event. Only this empty LOCAL state,
  without strategies/exposure/issues/reconciliation differences, is neutral.
  The real reopened book has version2/two startup events and still warns. UI
  tests also retain warnings for populated/stopped/failed cases. Rendering never
  marks the engine reconciled, resumes it or clears any issue.
- The empty strategy label is hidden in favor of an explicit first-strategy
  button, routed to the strategy workspace and the existing wizard. The new CTA
  changes Dashboard's exact QPushButton inventory from four to five; the separate
  baseline binds all five names/count, not a relaxed button budget.
- Complete former explanations remain in plain-text, keyboard-accessible owned
  QDialogs; short summaries stay visible. This avoids transient popup ownership
  and retains original safety/valuation text. Performance comparison stays in
  round two; only its two technical column captions become plain language.
- Move dashboard's existing inline red/light styling into scoped shell QSS so
  neutral first-start colors and actual warnings can coexist. Theme File impact
  remains CRITICAL; other named flows are LOW, constructor/dynamic dispatch
  UNKNOWN verified against source/call sites. Graph parser/trace caps remain
  acknowledged; no shared-axis risk waiver or import-gate change.
- The overview's existing cancel-entry control now follows the same LIVE UI
  disable rule as its trading-page counterpart; both stop buttons use the precise
  LIVE read-only caption/help. No backend execution capability changes.
- Add 20 literal catalogue keys at orders2776–2795 (total2796); all43
  M2-6 keys across the two slices are additive, with original aliases unchanged.
- The owner assigned the market-settings prerequisite to the root team. M2-1/2
  can stack after that fix's CI is green; they are no longer waiting on another
  person. They remain outside this UI work. The later M2-9 doc addition is
  explicitly second-round and is not implemented here. M2-8 is another owner.
- The old queued M2-6 full run was cancelled before starting. Root will rerun
  complete discovery and both actual LOCAL/fake-SIM starts on the final head.
  The prior79fc99c startup/full-check evidence does not validate this new source.

### 2026-11-01 — M2-6 scoped adoption of merged UI guidelines (PR127)

- Owner explicitly authorized this follow-up before the first M2-6 full run.
  Normally merge documentation-only main; keep full UX-1, header badges and
  complete overview redesign deferred. Preserve this round's date/first-start
  behavior and all prior financial/safety evidence.
- Put the changed explanations' existing help controls at each page title's
  right. Preserve separate complete PlainText content and owned dialog lifetime.
- Reuse theme's role convention: secondary by default, one trade reconcile
  primary, overview empty-strategy primary; stop/cancel/flatten danger. Require
  native Cancel-default confirmation. Reject context/account/environment/book
  changes during the dialog; do not silently retarget the confirmed operation.
- Six default position columns retain product, quantity, sellable, strategy,
  exit and protection. Optional columns remain selectable and fully populated.
  Composition injects a dedicated atomic presentation preference file; UI owns
  no file IO. Failed writes preserve previous choices and explain failure.
- Empty trade tables get explanation and a strategy navigation action, without
  manufacturing rows; retain the overview wizard action and add its reason.
  Display stock lots and Taipei timestamps only; no model/financial conversion.
- Add10 catalogue records2796–2805 (total2806). Source and the exact changed
  presentation/confirmation-aware test baseline remain separate commits.
  Full discovery, actual LOCAL/fake-SIM starts and remote CI remain root-owned.

### 2026-11-01 — Empty projections do not establish zero broker exposure

- Root review identified that empty position/order views can mean missing or
  unverified broker data. Replace only the two existing empty-table messages
  with "尚無可顯示的…資料" wording and direct next-step context. Do not introduce a
  false zero, an automatic-strategy prerequisite or a new framework/state flag.
- Retain both current strategy-navigation CTAs for this slice; M2-2 owns later
  manual-order navigation. Test accepted disconnected SIM/LIVE snapshots with
  unknown financial facts, and refresh both empty screenshot sizes.
- Catalogue maximum stays2805; exactly two existing values change in a separate
  baseline commit. Root repeats actual startup/full checks after this head.

## M2-6 / final policy evidence merge — 2026-11-01 Asia/Taipei

- Normally merge the completed M2-0 verification documentation, preserving
  both decision histories. No product, test, tool, catalogue or fixture content
  changes from tested M2-6 source5285742. No history rewrite or main merge.
- M2-6 actual LOCAL/fake-SIM startup checks already passed on5285742 with
  clean normal release. Final branch full discovery is still scheduled after
  the active M2-8 full suite; no focused/startup pass substitutes for it.

## M2-6 / first complete-run corrections and cleanup prerequisite

Retain the first complete run's 3914/1638.307s, 14 failures, 27 errors and 42
existing skips as FAILED, including all four new identities. Replace the real
page-boundary violation with an explicit owned trading-page argument; do not
relax the original no-parent/shell-discovery test or move that lookup elsewhere.
The established page-3 contract is checked in a real widget regression that
separately supplies a page different from the layout owner.

Commit that source correction with the normal pinned-main `67249dc` merge as
`f98d98c`, then independently update the three feature-caused visible-label test
references. Preserve all identity/finance/repaint assertions and add exact original
full-warning help/accessibility checks. No catalogue value, historical fixture,
skip, cap or timeout is changed to hide a failure. Source and exact text-baseline
changes remain separate commits.

Normally integrate final M2-8 `fdfde06` as the next test-cleanup prerequisite,
retaining its seven source/test/tool blobs exactly. Delivery dependency becomes
M2-8 → M2-6 → M2-1 → M2-2; root runs one new final-composite M2-6 full suite and
actual startup serially after M2-8. Prior runs keep their original source IDs.
No real key, CA, broker operation, installed-app control or git-history rewrite
is performed. Detailed focused evidence and the retained first-run comparison
are in [M2-6 verification](../analysis/m2-trading/verification.md).

## M2-6 / exact cleanup inheritance and two runtime copy oracles

Normal merge `dc58096` preserves all seven M2-8 source/test/tool files exactly.
Only afterward apply a separately authorized presentation-baseline delta to
two RuntimeContextClientTests cases: expect the existing short facts-pending
label, while retaining the complete original warning and its no-empty-exposure
meaning in actual help/accessibility assertions. Their prior startup-PID errors
had hidden these body assertions. Real SIM/LIVE widget surrogates reproduce the
old expectation failure and verify the corrected text plus unknown financial
facts and zero commands. Do not claim the native IPC bodies were rerun alongside
the active M2-8 full suite. Preserve every other context/finance/ownership and
no-engine-creation assertion and all cleanup behavior; no cap, skip, timeout or
catalogue change. Stop the audit after all actual changed-copy references are
accounted for. Final full discovery/startup/CI remain root's serialized gates.

## M2-6 / final source-equivalent evidence and omitted test registration

Final4fd1f6e complete discovery is3941/1543.784s10F22E42skip,32blocks/31IDs and
zero new failure identities versus main. Preserve the nonzero result, all actual
cause differences and the original four-new-failure run. The Windows PowerShell5
raw log is UTF-16-LE/BOM with CRCRLF/width119 wrapping; use BOM-aware parsing and
fold only failure identifiers, requiring parsed block count to equal the footer.
An old UTF8 parser's false INCOMPLETE is not the test outcome. Both actual LOCAL
and fake-SIM starts return0 with research/engine shutdown and no real SDK import.

Merge final8 documentation868da0c normally, retaining both appended decision
histories. Keep all1192 non-documentation entries exact at tested4fd1f6e. Repair
only the missing three existing M2-6 test-file registrations in an independent
inventory baseline commit; no Python body, fixture, timing, size limit, skip or
assertion changes. CI must be fully green on the pushed stacked PR; no main merge.

## M2-1 / authorized foundation — 2026-11-01

The coordinator confirmed prerequisite PR129 all35 checks green on attempt2,
run41279585267, source2d8319b, at14:35 Asia/Taipei. The owner's later steering
authorizes M2-1/M2-2 from dependent branches without merging main. Start this
backend branch at final M2-6 source5285742, then normally merge the market fix
and M2-8 cleanup. Preserve each implementation's source bytes; resolve only
append-only decision/behavior/inventory conflicts by retaining both intents.
No rebase, main merge, user-data deletion or production financial operation.

Initial GitNexus status was unindexed; offline single-worker analysis completed
in143.5s with19,608 nodes and52,009 edges. Index flow/receiver caps remain known
navigation limits, not evidence an omitted path is unused. Before merging,
the existing indexed prerequisite supplied impacts on source-confirmed matching
premerge blobs: shared charts, installer-test and load-probe file targets were
CRITICAL; market panel LOW; unresolved unittest callers were confirmed through
discovery/import references. That warning is retained despite complete low-risk
change detection for the market merge. New own-worktree graph change detection
is required before this merge commit and every subsequent implementation commit.

Only lint and source-byte comparisons run while the coordinator's serial policy
suite is at process-sensitive cases; do not start another full suite or heavy
process-focused tests. Full discovery/startup/push/CI belong to the coordinator.
Next freeze typed Sinopac connection DTO/actions for parallel UI and manual SIM
implementation. No connection or execution behavior is claimed delivered by
this foundation commit.

## M2-1 / shared wire contract first — 2026-11-01

Freeze reference-only SinopacConnectionSettings, masked SinopacAccountView,
four SinopacReadiness facts and SinopacConnectionView in a separate application
module, reexported by contracts.py and explicitly registered in the trusted
codec. New command fields and UiState.sinopac_connection have defaults, so
old wire documents decode without introducing a connection or changing books.
Connection revision/generation are independent of the engine book version;
subsequent runtime acceptance checks them. The only settings are environment,
key reference, optional certificate file/secret reference and fee discount.
No person_id, raw account identity or secret value belongs in these DTOs.

The four actions are save-and-connect, account selection, optional CA activation
and disconnect. A draft SIM environment does not imply changing an accepted
LOCAL trading book. Initial account signed state can be unknown; execution
readiness remains blocked pending dependent M2-2. Reason codes are presentation
keys, never native exception text. The UI agent owns all new catalog strings
from order2806, and the manual agent owns separate manual_contracts.py DTOs.

Pre-edit impact is CRITICAL for UiAction/UiCommand/UiState (37 direct,73 total)
and HIGH for registry initialize (6 direct,19 total). New names were absent in
graph and text. Four pure boundary/codec tests went RED on the missing module,
then passed in0.003s, including old-field omission and malformed settings. This
slice starts no engine, SDK or child process. Inventory/baseline registration
is a separate precise commit; broader runtime implementation is still pending.

## M2-1 / immutable facade environment — 2026-11-01

Require ShioajiSDKFacade(client,module,environment=Environment...) explicitly;
neither native simulation flags nor a LOCAL default establish execution scope.
Expose a getter-only environment property; factory and retained legacy market
construction pass their immutable configured environment. The manual-execution
agent owns guards in the three existing mutation bodies and a central predicate,
so this slice does not replace those bodies or add a second order path.

Two pure tests went RED before implementation and now pass. With existing fake
facade, tick-stream and price-band cases,33 tests passed in4.573s. Existing fake
constructor sites receive only explicit BROKER_SIMULATION arguments; original
assertions and expected requests remain intact. Those fixture edits and new
module inventory rows are a separate commit. Source impacts: facade MEDIUM
(10 direct), factory LOW(4), MarketSession LOW(2). UNKNOWN test/helper file
impacts were confirmed via direct imports and unittest discovery references.

## M2-1 / precise constructor fixtures and inventory — 2026-11-01

This independent fixture commit adds only explicit BROKER_SIMULATION arguments
at the six existing fake facade construction sites across the shared tick fake,
SDK facade and price-band fixtures, plus the required Environment import. All
old assertions, timeout cases, request expectations and failure paths remain.
Register only the three reviewed new DTO/environment-test modules in inventory;
no historical producer hash, appearance baseline, string or SDK pin is repinned.

Complete source/fixture change detection reports16 symbols across9 files and
CRITICAL graph risk with613 listed affected processes, dominated by the shared
tick_gateway test-helper node. Source search confirms its direct consumers are
the tick fixture modules; this does not waive the CRITICAL warning or replace
tests. All33 relevant fake tests passed. Future source PR notes retain this
warning and the index's dynamic receiver/process-cap limitations explicitly.

## M2-1 / shared native owner — 2026-11-01

One SharedSDKSession authenticates with trade reports enabled. Typed facade
consumers retain the same immutable environment and execution guards. Native
callback registration occurs once per event; callback failures are counted,
sanitized and isolated from other consumers. Quote/scanner leases are shared;
consumer logout detaches only its callbacks/subscriptions. Native logout is
the owner's responsibility. Existing MarketSession can adopt a consumer, so
directory, history, tick and scanner services use the authenticated session.

Four new fake-only tests were RED before implementation. With the existing
market session and controller regressions, all13 focused tests pass in0.050s.
No SDK import, real credentials, CA, broker orders or engine process occurred.
MarketSession.connect impact was UNKNOWN (dynamic receivers), confirmed by
runtime and test source references. Disconnect impact was CRITICAL (2direct,
167flows); its existing body remains unchanged. Adoption reuses that body via
the consumer's detach-only logout, preserving legacy independent sessions.

## M2-1 / unified backend acceptance and routing — 2026-11-01

The explicit profile-free RuntimeLaunch.sinopac mode owns a single SDK session
in one stable environment host (SINOPAC:environment). Its process seed stays
sinopac-pending; navigating discovered account aliases changes only the client
view. LOCAL first-connect routes connection/market intents to that host while
preserving LOCAL cash, positions, book version and selected context. Switching
to SIM remains a separate navigation intent. Environment replacement confirms
the previous native logout before constructing/logging in the next client.
Unknown logout remains blocked on retries; no process termination is used.
An existing connected legacy market/profile session is retired through the same
bounded explicit transition before unified login; legacy profile files and
hash-pinned resource loading remain supported for their existing callers.

Connection generation is an opaque UUID. Material accepted state changes use a
persisted monotonic revision, independent of ticks/book version. Composite
projection offsets revisions across environment hosts and maps CAS back without
refreshing a stale intent to a newer native revision. Owned workers have the
existing eight-second acceptance deadline. Disconnect waits on an Event for at
most7.5seconds outside book locks. Expired login/account/CA completions cannot
promote; candidates clean up normally. Close is bounded and reports uncertainty.
Trusted factory/SecretResolver/resource-factory injection passes through
serve/build_runtime for offline integration; startup never resolves secrets.

Discovered aliases derive from the complete environment/account-type/broker/id
identity. Only masked labels, signed tri-state and reason codes cross the wire.
Preferences preserve references, selected aliases and generated masked metadata
with identity hashes; raw account IDs/person_id/passwords are never saved.
Historical/unselected/disappeared aliases remain available for book navigation,
with unknown or unavailable evidence, independently of current selection. This
never removes trading obligations; M2-2 owns canonical ledger reconciliation.
Query readiness requires successful selected-account position queries. Callback
delivery failures explicitly degrade readiness; simulation execution remains
implementation_pending in this M2-1 slice and production is always blocked.

The generated catalogue initially supports ordinary cash security2330 and the
nearest actual, unexpired TMF month. Native ContractV2 supplies lot, multiplier,
month/expiry, ticks and optional daily price limits. Missing limits remain
missing. Stock classification comes from bounded automatic public ISIN data,
not SDK industry codes or symbol guesses. Publication date and full response
SHA are retained. The official page observed2026-11-01 was10,186,180bytes,
SHA256 de68b53f834f4b17dab7a9125f932c4a270c202ec9deed7e672d564ddf170e54;
its2330 row parsed TW0002330008/ESVUFR with publication2026-11-01. Read budget
is2.5seconds and32MiB; unavailable/stale classification blocks that stock's
resource generation while market/account services remain usable.

Calendar coverage is explicitly2026 only:242 positive scheduled common dates,
after excluding the independently recorded July10 TAIFEX closure. Its window
09:00<=t<13:30 is a conservative shared manual window, not full TMF hours or an
actual-open/emergency-completeness guarantee. 2027 is unavailable, never guessed.
M1 quote/history sessions retain their independent received-timestamp behavior.
Fees are versioned application estimates (adjustable stock-fee discount), not
broker billing. TMF35050TWD initial margin is the dated TAIFEX exchange reference
2026-08-12 observed2026-11-01, never fabricated broker funds. No positive broker
cash/equity or global atomic order observation is inferred from simulation zeros.

New CA enrollment stores only ca_password under the certificate reference. The
legacy triple credential schema remains intact for its existing path. Explicit
optional activation derives person_id from selected native accounts and uses a
user-selected PFX path; references alone cross UI/IPC. SIM defaults NOT_REQUIRED
based on official documentation, not owner real-SIM verification. Tests use an
invalid fake certificate file and fake SDK callable only; no real CA was used.

Pre-edit routing impacts are CRITICAL for RuntimeLaunch, RuntimeBundle,
RuntimeContextManager/_Entry, ContextIpcFacade, CompositeFacade, desktop entry
points and server dispatch/serve (broad160+flow attribution). Resolver impact is
CRITICAL as previously recorded. UNKNOWN targets were checked against source.
The new calendar builder's first symbol lookup occurred after initial creation;
this local workflow miss is retained rather than represented as a pre-edit
check. Subsequent source review, fake boundary tests and full change detection
cover the resulting definition. No FTS/vector extension was installed.

## M2-1 / exact inventory baseline — 2026-11-01

The source commit e640eb0 is followed by an independent inventory-only change
for the seventeen new backend/test/tool modules since af262ab. Each row retains
its actual path, line count and reviewed layer. The three DTO/environment rows
already added by af262ab remain unchanged. Historical rows/producer hashes and
all existing assertions remain intact; no appearance/catalog baseline is reset.
The existing bootstrap module remains an explicit composition boundary rather
than moving its public lifecycle during this feature; new owner/resource modules
are bounded and their functions meet the50-line readability target.

Complete source detect reported130symbols/29files/608flows at CRITICAL risk,
with no partial/truncated flags. One existing desktop.py parse_args record has
an empty graph UID (its pre-edit impact still reported187direct callers). This
is retained as an index limitation, not an unused/unaffected claim. Actual parser
source and existing CLI tests were independently verified. Raw CLI report and
structured flag/UID summary are in ignored .tmp/m2-backend-detect files.
# M2-2 manual simulation core decisions (2026-11-01)

- A confirmed app-owned virtual book provides source-tagged internal risk
  capacity. It never replaces broker balances, actual PnL, or the automatic
  previous-close/OOS evidence. Capital remains bounded by the existing account
  allocation buckets and single 100000 platform cap, including multiple aliases
  of the same market. Re-enabling a book cannot reset capital, loss or stop state.
- A private durable manual intent enters TradingEngine.submit's narrow branch.
  It creates no ACTIVE StrategyRecord. The sole state-bearing commit caller,
  locked RiskService preview/rejection, reservation, SUBMITTING and fence remain.
- One current-login-generation diagnostic proof requires a known TMF broker
  reference and subsequently confirmed canceled/unfilled state. It permits
  explicit SIM attempts from other accepted confirmed books, while each account
  still requires signed/market/risk/reconciliation checks. This is not verified
  stock trading permission. UNKNOWN, partial/full fills and a changed generation
  do not pass. Only a backend-minted legal distant-price diagnostic may be used.
- A manual stop price estimates sizing risk; it creates neither a protective
  broker order nor automatic management. Manual positions are UNPROTECTED.
  STOP_NEW latches books; bare RESUME and adding another book cannot clear it.
- Price-only amendments may not increase committed risk; quantity amendment is
  explicitly unsupported rather than guessing the pinned SDK's reduction units.
  Mutations receive a fresh admission TTL, retain original conservative reserves
  until observed evidence, and never turn SDK timeout into retry permission.
- Owner direction permits conservative app-derived exits for settled owned
  cash-long stock. This uses durable per-fill acquisition tranches matured T+2
  on the explicit calendar, exact fresh native-position reconciliation, healthy
  scoped orders and existing pending-exit reservation. It is not a native
  free-share certificate. StockPosition.yd_quantity and reserve available_share
  are not substituted for sellability. Non-cash, financed/collateral, external,
  mismatched, missing-date or unknown scopes remain blocked. SDK rejection is
  still possible. The automatic stock-availability path remains unchanged.
- Stock acquisitions and virtual sale receivables are written atomically by the
  existing fill reducer. Unsettled sale proceeds remain unavailable until T+2
  from their conservatively observed session. No second fill reducer is added.
  A missing manual closing baseline keeps cross-day new risk stopped, while a
  verified settled owned stock exit can still proceed. No previous-close value
  or calendar fallback is invented.

## M2-1 / single three-step connection presentation — 2026-11-01

Use one visible BrokerPanel for environment/key save-and-connect, discovered
masked accounts and optional certificate references. Remove the independent
MarketDataPanel and twelve-reference primary form rather than keeping hidden
obsolete controls. Retain the existing legacy profile import in the collapsed
advanced section, and preserve offline legacy metadata persistence/readiness
coverage through its typed commands. Account identities, SDK objects, secrets,
person_id and certificate contents never enter the widget implementation.

The connection draft defaults to broker simulation and the documented OS key
reference. It is separate from the accepted Trade/Settings book selectors;
connecting, a failed request or an unacknowledged request cannot switch a LOCAL
book. Connection generation/revision are submitted independently of engine
version. Render the connection view before same-book, stale-book and market-only
shortcuts; reject older connection revisions. User-edited references and Decimal
fee discount survive polling and book navigation, and only a matching accepted
receipt clears those drafts. Checkbox clicks submit aliases then immediately
restore accepted selection until the acknowledgement. An IPC failure shows
unknown liveness rather than retaining a successful connection status.

Certificate selection is reference-only and optional. Simulation's NOT_REQUIRED
status follows the official contract, not a real-credential experiment. The
shared runtime owns credential resolution, connection reuse, signed/permission
validation and CA activation. Production readiness is always rendered blocked,
including an inconsistent READY DTO; signed/account discovery alone never grants
execution. Simulation execution remains pending dependent M2-2. Fee discount is
editable as Decimal (0 < d <= 1, default1), with built-in estimate assumptions
explained in help; M2-9 tax/calendar/expiry UX remains second-round scope.

The four intents run through the existing asynchronous worker. Duplicate requests
are disabled, pending status is neutral, account/CA controls open progressively,
and disconnect requires native confirmation with Cancel as default. Capture its
revision/generation before the dialog and reject a connection replaced while the
dialog is open. Reasons are mapped to literal Chinese catalogue keys, never
vendor text. Account-data absence does not assert that the broker has zero
accounts. Help remains title-right; style rules are scoped in theme.py.

Work is exclusive to codex/m2-1-connection-ui, normally merged with frozen DTO
986f7cf. Catalogue phase62 owns orders2806–2877; M2-2 starts phase63/order2878.
Pre-edit graph risks are retained: Window.command/_run and theme/catalog are
CRITICAL; translation_parts HIGH. Dynamic/unittest UNKNOWN callers were checked
against source/discovery. The current UI source has no real SDK import or
financial operation. Full discovery, real startup and remote CI are coordinator
steps after normal integration with the shared backend; fake-Qt proofs here do
not establish the M2-2 engine LIVE invariant.

M2-1 integration followup: account/context discovery may change selector choices
without incrementing the accepted engine book version. A RED/GREEN real-widget
case required invalidating only presentation before the same-version/market-only
shortcut; the accepted LOCAL account, positions and dirty connection reference
remain unchanged. Its named helper impact is CRITICAL (45 upstream sites,
3 processes,5 modules), retained as a warning alongside source checks rather than
waived by the graph's shared-name/dynamic gaps. Final backend accounts_unavailable
and callback_failed reasons map to existing Chinese next-step copy, with explicit
unknown-readiness tests; no new catalogue records were needed.
## M2-1 / explicit unified broker startup identity — 2026-11-01

Static review of the prepared actual-startup probe found a genuine entry-path
gap: configure_launch handled explicit LOCAL/profile requests, then hashed every
profile-free broker alias into an UNCONFIGURED host. An already registered
unified alias therefore lost its stable SINOPAC environment host when launched
directly through _run_window(environment=BROKER_SIMULATION, account_ref=alias).

Before the existing generic fallback, reuse a registered explicit unified entry
with the same environment and known alias. Keep LOCAL, selected-profile and
unregistered legacy-alias behavior unchanged. This is metadata routing only;
it performs no SDK login, host startup, automatic selection or snapshot synthesis.
The real direct-SIM window probe must use this path, with natural prior owner
discovery/selection, rather than patching configuration or read models.

The new metadata regression was RED for both SIM and LIVE (hashed contexts
instead of the registered unified context). After the four-line correction,
all three UnifiedRegistryTests pass in 0.072s; ensure_engine is mocked and its
single registration call is checked. No Qt app, host, SDK or process test ran.
Ruff check/format pass. configure_launch impact is LOW (one direct caller,
two modules); cached graph/source were read during the coordinator's isolated
full-suite window. Full index refresh/change analysis and separate commits wait
for the coordinator to release that exclusive window.

Initial integrated source 90bdda8's prior 96 focused results remain attributed
to that source only. They are not relabeled as verification of this correction;
actual direct-SIM startup, updated focused/full and CI remain separate gates.

## M2-1 / LIVE CA remains outside query-only scope — 2026-11-01

The specification limits LIVE to login, market and account queries. The unified
CA flow is therefore accepted only for BROKER_SIMULATION when explicitly used;
this does not change the legacy connector CA path. Reject a LIVE CA intent at
the owner boundary before creating a worker and independently at the executor
before file/password/native SDK access. Return the existing
production_orders_disabled reason, which already renders the formal query-only
Chinese guidance; do not add/reorder catalogue strings or imply LIVE opt-in.

The LIVE certificate path, picker, password-reference and activation controls
are disabled, with existing formal-readonly guidance in status/tooltips. The
panel helper stays in the same module and BrokerPanel remains292 lines, below
its300-line cap. Valid optional SIM activation remains tested with an invalid
fake PFX file, fake password and fake SDK only.

Both new backend/UI cases were RED first (LIVE request accepted/controls enabled).
After correction,23 fake, metadata and small-widget tests pass in0.558s. The
backend test also calls the executor independently and proves zero password
reads/native CA calls and unchanged accepted view on refusal. Existing SIM
activation assertions are intact. Impact is LOW for the executor, MEDIUM for
panel enablement (nine direct,two flows); UNKNOWN dynamic command/test targets
were confirmed by actual RuntimeBundle callers and unittest references.

After the isolated full8 smoke-sensitive prefix completed, the coordinator
released a single-worker offline index and these small tests. This does not
claim the entire full retry ran without later index/Qt activity. Actual startup
and process-heavy verification remain coordinator-only until that full ends.

## M2-1 / merge graph evidence chronology — 2026-11-01

Documentation merge3623c4447f2e45e55fe6fa8970d37c2589834eaf was committed after
staged analysis showed59symbols/eight docs/zero flows, LOW, with no missing IDs
or truncation. At that time scope-all still had an empty UID for the new
_certificate_controls helper. Using the clean staged subset while that all-scope
issue remained was a workflow gap; it is not represented as clean precommit
all-scope validation, and history is not rewritten to obscure the sequence.

An offline forced single-worker rebuild then restored symbol identities
(20,092nodes/641flows,28.0s). Retrospective exact committed comparison
90bdda8..3623c44 reports59symbols/eight documentation files/zero flows, LOW,
zero empty IDs and no partial/truncated flags. Source-all subsequently reports
21symbols/nine files/eight flows, HIGH, all21returned with zero empty IDs and no
partial/truncated flags. The HIGH warning is retained alongside actual focused
tests; it is not lowered through riskSharedAxes or graph absence. These checks
precede the separate source-fix commit, not the documentation merge.

## M2-1 / scoped LIVE evidence recapture — 2026-11-01

Source36fc1e8 passed23 updated fake/small-widget/metadata tests, Python3.11
compilation, Ruff and complete all/staged graph checks (23symbols/10files/eight
flows, HIGH, zero missing IDs/truncation). Under the coordinator's explicit
lightweight Qt allowance, replace only1366×768/1920×1080 LIVE visual fixtures.
The audited helper uses public fake DTOs/RecordingFacade and the real window/
theme, with SDK imports forbidden, no engine/runtime/login/commands. It checks
CA controls while expanded before restoring the original collapsed capture state.
Both images retain the LOCAL book, formal connection label and readable readonly
CA guidance; visual inspection passes and horizontal scrollbar maxima are zero.
Other scenes and unrelated historical baselines are not regenerated. The capture
record pins36fc1e8 and each image hash. Actual startup/full/CI stay separate.
# M2-2 manual simulation core decisions (2026-11-01)

## M2-1 / source-identical M2-8 documentation integration and startup

Normally merge final M2-8 `fdfde06` into M2-1 `8d98564`, retaining every M2-1,
M2-6, policy, market and cleanup decision/contract section. Resolve only the two
documentation conflicts. All 1202 non-documentation checkout byte hashes and
all non-documentation Git blobs remain identical to `8d98564`; no fixture or
source change is introduced. Review and sanitize the three actual startup result
JSONs, retaining their original source identity, guard/cleanup facts and explicit
resource_calls=0 limitation. Their source-equivalent applicability is stated;
they are not falsely described as rerun on the new documentation commit. Full
discovery and current-head CI remain separate coordinator gates. No engine,
native lifetime, Qt or startup test is executed for this documentation merge.

## M2-1 / inherit the final M2-6 full-suite corrections

Normally merge M2-6 `4fd1f6e` into M2-1. Only six non-documentation paths
change: the explicit trading page owner, its real Qt regression and five
feature-specific visible-label oracles (four test files). Preserve full help,
unknown financial facts, ownership and no-implicit-connection assertions. All
other source/test/tool blobs remain the exact M2-1 parent; workspaces retains
its connection wiring plus only the explicit page argument. The runtime test
retains M2-1s existing programmatic legacy command after its obsolete button was
removed; this merge adds only the two reviewed short-copy/full-help changes.
Resolve three doc conflicts additively and remove only two exactly duplicated
decision sections. Exact blob audit covers1215 non-doc paths using NUL-delimited
Git paths, including non-ASCII filenames.

Pre-merge install/helper impacts resolve the build caller at LOW risk (3/2
nodes, one flow); unchanged test methods are unittest-discovered boundaries,
not unused code when no callers resolve. The84 affected Qt, connection, page
boundary, document and layer tests pass in29.786s. Prior M2-1 startup evidence
remains source-specific. New complete discovery and actual startup follow on
this composite; no old full/startup evidence is relabeled.

## M2-1 / complete-discovery frozen-probe correction

The first final M2-1 full run completed3996 tests in1416.477s with10 failures,
23 errors and42 existing skips. One NEW error was a real compatibility omission:
packaging/broker_probe.py still constructed ShioajiSDKFacade without the newly
required immutable environment. Its existing strict mocked frozen test reproduces
the TypeError; no assertion changes are needed. Pass Environment.LIVE explicitly
in this inert metadata-only probe: the SDK constructor remains replaced by the
existing denial function, and the test proves zero construction/login/operations.
Exact probe impact is LOW (2 nodes, one packaging caller); its nine existing
checks pass0.426s after the correction. Record the failed complete run rather than
waiving it. A new complete suite follows on the corrected source. No SDK pin,
execution guard, test limit, skip or real credential/broker operation changes.


## 2026-11-01T21:26+08:00 — M2-1 legacy unknown-logout admission closure

A separate read-only Standards review found three internal lifecycle flags were
read through getattr defaults instead of initialized, contrary to CONTRIBUTING
section4. Initialize legacy_disconnected, legacy_disconnecting and
legacy_cleanup_unconfirmed in RuntimeBundle.__post_init__ and read them directly.
The class impact is LOW13; the generated dataclass constructor gives UNKNOWN
for __post_init__, so confirm its two production factories and seven direct
unit-test construction sites by text, rather than treating an empty graph as
unused. Exact execute/connect/legacy-retirement impacts each resolve3 nodes;
execute retains97 unresolved receiver sites, so these are lower-bound results.
The pre-change indexed bootstrap/legacy files equal the current9f source blobs;
metadata lag is documentation/probe history, not a different lifecycle body.

A Spec follow-up then confirmed a functional gap: after unconfirmed legacy
logout, retirement clears the session and latches cleanup_unconfirmed but the
old CONNECT_MARKET_DATA and profile CONNECT_READ_ONLY gates checked only the
other two flags. The latter is reachable with valid legacy resources and no
engine yet. An old public command could therefore reopen an SDK session before
release was proved. Include the existing unknown-cleanup latch in both refusal
gates; do not clear it, retry login, create another owner or change any deadline.
The old group of market commands remains uniformly blocked during retirement.

Two exact fake regressions were first RED (five failure occurrences, including
three market-command subtests and the profile path), then pass5.093s. The47-case
existing routing/readiness/market transport group passes40.057s without native
processes, real SDK or credentials. Test formatting preserves the complete AST.
No old assertion, skip, risk rule, timeout or SDK pin changes. This is a new source
correction; prior9f full/startup results remain historical, and both actual starts
plus full discovery must be repeated before push. The pending event-wait helper
was stopped before native probes; its earlier identity/PowerShell syntax errors
are harness-only and not product startup evidence.

The duplicate lock-order pattern is retained as an explicit safety sequence;
its P3 smell is a nonblocking maintenance judgement, not a standards violation.
Record the actual bootstrap/readability measurements and routing test count in
an independent inventory baseline, with a narrow future split plan; no limit is
raised. No second-round feature or actual broker operation is added.


The additional gateway-return hypothesis was checked against the real port:
ReadOnlyGatewayCache.disconnect forwards ShioajiAdapter.disconnect, which turns
native logout False into DomainError(outcome_unknown); the cache does not swallow
it. ConnectionPort.disconnect returns None by contract. Keep that existing safe
boundary and do not add a redundant internal False fallback based on an invalid
fake gateway. The confirmed defects are the two old admission gates above, not
the gateway's already-protected logout result handling.

## M2-1 / final source-specific acceptance evidence

2026-11-01/02 Asia/Taipei. Publish exact 897df1b complete discovery 3998/2123.797s and all 32 manually reviewed inherited failure occurrences honestly, with zero new failures. Preserve failed prior attempts and raw SHA256. Final private-interpreter LOCAL/fake-SIM starts close every owned lifetime normally; fake clock functional order flow is explicitly separate from real Sunday availability. No real SDK/key/CA/actual real or SIM order. This evidence-only finalization changes no executable/test/tool/fixture bytes. Source-equivalence audit and complete graph detection precede commit; current pushed head CI is still an independent required gate.

## 2026-11-01 — M2-1 CI / owned shutdown endpoint race

- CI for PR132 head65e7d7f, offline run41316970314/job124878999508, fails one
  of422 cases after393.130s: RuntimeContextClientTests' original CAS cleanup
  test completes its explicit shutdown, then its registered owned cleanup
  observes FileNotFoundError. Preserve this first failure; do not call it a
  timeout or waive it merely because the prior complete local run had no new IDs.
- Rank possible timing paths: normal shutdown removes its endpoint before native
  exit becomes visible; a snapshot/command version-conflict retry reaches that
  removed endpoint; an endpoint disappears while the owned process stays alive.
  Reproduce the exact error at both snapshot and execute boundaries with fake
  retained processes: four boundary tests initially have two error subtests in
  0.005s. The unchanged original native IPC/CAS test remains required later.
- At the IPC/filesystem boundary only, catch FileNotFoundError and join the exact
  retained process under the unchanged15s allowance. Passing still requires
  observed exit0. An alive process/timeout or abnormal exit remains FAILED with
  the original owned-handle containment and explicit cleanup error. Foreign PID
  refusal and current-version CAS remain unchanged; no financial path changes.
- Both new methods plus the existing two pure boundaries pass in0.003s. This is
  a deterministic fake seam, not a claim that native or complete discovery has
  already been repeated. Defer native tests/index/static scans until the active
  source799efad manual full suite ends naturally; preserve that intermediate run,
  then repeat complete discovery on both branches after inheriting this fix.
- Pre-edit exact method impact is LOW: close -> context-manager cleanup / load
  probe, four resolved symbols and nine load-probe flows. Boundary test class
  impact is UNKNOWN; direct source search and the actual four-case invocation
  prove unittest discovery usage, not an unused-class assumption.
- Files: tools/owned_trading_engine.py, tests/test_trading_engine_cleanup.py;
  measured inventory changes will use a separate explained baseline commit.
  G3/PROJECT_STATE/SDK1.7.9/acceptance, existing assertions/timeouts/skips and all
  product application/runtime files stay untouched by this correction.

### Owner time constraint / verification scheduling

After the owner requested completion within one hour, prepare the two-file
formatting and graph/commit work during the older799 manual run, which must
therefore be labelled intermediate and not fully isolated. The scoped native
cleanup group and static/index preparation overlap this intermediate attempt;
no second full suite does. Final corrected full suites remain serialized and quiet.
Bundle the final run report in the last PR's final CI head; validate that exact
head before delivery, rather than wait for a green feature head and only then
start another whole CI run for the report. Record only results actually known
when written and link the final PR/checks as the authoritative final CI evidence.

The original CI IPC/CAS case plus the11-case cleanup module now pass12/24.115s
using real owned processes and the existing fake broker fixtures. All original
assertions remain, including foreign-host preservation and cleanup failures.
Whole-project prepush passes Ruff lint,1154 formatted/1071 Python3.11 syntax
files and credential/static gate0 findings. Fresh offline all/staged graph
checks each return10 unique symbols/3files, LOW, no error/partial/truncation;
all3 added qualified definitions and the required method/class are represented.
No final corrected complete discovery or current-head CI is claimed yet.

## connection-cleanup-retry / complete corrected source evidence

Publish exact f77d2b0 complete discovery 4000/1436.847s, zero new failures and all32 actual causes reviewed. Keep earlier failed local/CI attempts, explicit secondary cleanup differences and exact fake-only actual startup facts. Only documentation changes after the tested source; prove non-documentation Git blobs identical and detect graph changes before commit. Require final current-head CI separately.
The prior4000-case attempt has one new M1 alert-store WinError5. Neither100 main nor100 unchanged-source controls reproduce it. Keep it outside the allowed main baseline and avoid speculative production storage retries; acceptance requires this actual complete unchanged-source retry to have zero new failures. Both failed attempt and successful controls remain retained.

## M2-1 / schedule frozen recovery within the unchanged shared budget

2026-11-02 Asia/Taipei: corrected-head Windows installer41323736442 fails
twice with InsufficientExistingSmokeBudget. Attempt1 fails retained-candidate
smoke (artifact13091592701); attempt2 fails recovered-candidate smoke
(artifact13092473832). Both have successful seven original UI operations,
market/auth/history/walk-forward checks and verified worker cleanup. The
expected released0.2.1 WAL-workspace refusal is unrelated. Neither failure is
added to the main allowance or described as accepted CI.

Ranked hypotheses: variable earlier worker time, recovery scheduled after the
walk-forward tail, or bad deadline arithmetic. Actual runner callback control
with completed original/history work at70s and walk-forward at102s reproduces
the failed final status under the unchanged120s deadline in0.209s. Admission
needs its existing full40s even though successful native recovery often takes
about1s. Running only after the tail therefore makes successful earlier work
consume the reservation. The controlled positive case is RED; existing
insufficient-budget and total-timeout cases remain negative.

Move the exact recovery call to the existing original-manager close boundary
before creating the walk-forward manager. Stop/restart the Qt timer around the
same synchronous hook; retain uncertain-cleanup evidence. Reuse the verified
original completed campaign and cache the report for final aggregation. Keep
every original/manual/history/walk-forward operation and validation; keep the
120s outer deadline,40s recovery cap,6s preparation cap and actual frozen/zero
exit/cleanup requirements. Do not extend deadlines, reduce the fixture or add
skips. No G3 or broker path changes.

The same callback control becomes GREEN. Three new scheduling controls prove
ordering after joined original work, insufficient-budget refusal and unchanged
total timeout. Related modules:29 tests OK with4 existing skips in14.966s;
inventory/layer/page/M2 readability:43 PASS11.414s. These are source/mocked
scheduling evidence, not actual frozen proof; new complete discovery, actual
fake-SDK startup and current-head installer CI are still required.

Pre-edit GitNexus run_smoke upstream risk LOW: desktop.run_gui is its direct
caller,11 upstream symbols,1 affected process. complete_smoke risk LOW with1
direct timer-guard caller. Index differs only by documentation from the inspected
smoke blobs. Fresh complete graph and added-definition coverage precede commit;
measured runner size deltas get a separate explained baseline commit.

## M2-1 / actual installer failure: floating-point endpoint comparison

2026-11-02 Asia/Taipei: attempt2 retry-install.log closes at17:07:07.695 UTC;
the recovered executable fails by17:07:38.054 UTC. Its entire lifetime is at
most30.359s, so ordinary exhaustion of the120s smoke budget down below40s
cannot explain that actual CI guard result. The earlier callback control
establishes a possible late-admission scheduling failure, not this actual
installer root cause. Keep that small joined-manager ordering improvement and
its unchanged-budget negative controls, but do not claim it alone fixes CI.

The original admission arithmetic is independently red-capable: started
511.00000000000006 and end=min(started+120,started+40)=551.0 produce
end-started=39.99999999999994, falsely below40. The same error occurs across
the1024 and2048 exponent boundaries. The actual installed uptime was not
recorded; these are controlled exact inputs, not claimed CI measurements.
Actual function controls stop before any native preparation: all three full
budget subcases are RED under the original condition (2methods/0.004s),
while deadline=nextafter(started+40,-infinity) still correctly refuses.

Change only the predicate to end < started + CAP_SECONDS. Keep the exact same
end=min(deadline,started+40), watchdog end,40s helper cap,6s preparation cap
and120s outer deadline. Compare the clamped endpoints instead of subtracting
nearly equal floats; add no epsilon, grace time, retry or fallback. The exact
three full-budget controls become admitted, and all three immediately-shorter
endpoints still fail before timer/preparation/process creation. GREEN2methods
0.061s; the injected preparation error proves admission without native work.

Interrupt only the stale db1ccd5 validation session after identifying this
additional root cause; retain its partial raw log and never count it as a
complete full suite. A read-only census immediately after interruption finds
zero full-run Python processes and zero known M2-worktree trading engines.
New exact-source complete discovery and actual fake startup are required for
both branches. No raw log or history is rewritten. Recovery module/function
line counts are unchanged, so this one-line fix needs no unrelated baseline
refresh. Pre-edit recovery upstream impact LOW:4 direct callers,5 total,
with the shared timer flow still separately treated as HIGH.

## M2-1 / independent smoke AST baseline and full repeat

Exact caa6636 complete discovery4005/1427.181s records11 failures,22 errors,
42 existing skips. Its sole new failed identity is the locked canonical smoke
AST fingerprint in test_t11_part_b; the deliberate earlier joined-manager
recovery call/timer stop-restart/cached report changed that exact body. Keep the
whole raw run SHA2566a630a4a425fdedea69cb7fda9271299656829b198d6ea3f64f1103c991a68cd
as failed history, not a zero-new-failure acceptance claim.

Use an independent fixture-only commit to change ONLY SMOKE_DIGEST from
b69ea4fa50829c6303ea9b8ba46c2f84d52a74948d828b8fadd46e54ea4e70cc to
3737569e56810e75e96316e518479adf1d7f034f453d4930de2c997aeac93fe4.
The original equality assertion, canonicalization, metadata expected counts,
handler and terminal-finally hashes, budgets and all skip conditions stay
unchanged. All11 startup-contract tests PASS0.180s after the baseline update.
Repeat complete discovery on both final branches before push; do not waive this
new failure or infer the new complete result solely from the focused check.

## connection-recovery-budget-verified / final complete source evidence

Publish exactb605466455655b17251122347ba28da202776653 complete discovery 4005/1426.235s with zero new failures after individual actual-cause review. Retain previous failed CI/full attempts and previous successful source evidence. Only documentation changes follow; final runtime blobs must match this full/actual source. Do not reuse historical CI as the new final-head result.

## M2-2 / precise LIVE policy oracle — 2026-11-01

Owner D1 supersedes the earlier controlled LIVE-positive environment fixture.
Retain both environment setups and the real fixture's validation/research/deploy
steps. At LIVE submission now assert production_orders_disabled, no port delivery,
zero broker submissions and no orders/positions. SIM retains every original
entry/fill/protection/performance assertion, quantity, timeout and risk limit.
This is an independent baseline commit; no test is removed or skipped. The new
fake-only guard module additionally checks direct SDK/adapter/service/engine/UI
stop/cancel/flatten paths and SIM delegation. The source guard is separate.

Before source changes the original environment module passed2/2. With the guard
and the old oracle it reports exactly one LIVE policy error; its original log
is .tmp/m2-2-live-old-oracle-red.log. After the precise oracle update both cases
are required to pass. Graph reports UNKNOWN static callers for the test method;
direct source and unittest discovery establish its actual invocation.

## M2-2 D1 coordinator oracle baseline

The older coordinator fixture still expected an armed LIVE strategy cycle to
submit. D1 supersedes only that LIVE-positive expectation. Its independent
baseline now requires production_orders_disabled, zero production deliveries
and no submitted order before separately observing a historical order/fill
seeded only in the local exchange double through the read-only cycle. The
original SIM branch and all of its quantity/fill/clock assertions remain intact.
This introduces no production submit caller or permission exception.

## M2-2 confirmed-request preflight rejection

The UI must retain an unknown financial request until matching authoritative
request evidence arrives. A preflight refusal is therefore journaled as a known
REJECTED result only after current typed inner/outer native scope validation,
while holding the existing writer, and only if both the manual request key and
canonical order key are absent. A healthy writer fence and durable append are
required. The exact original form hash, scope and request identity are retained;
no error-code whitelist and no empty broker-cache inference provide certainty.
Existing known/unknown keys replay unchanged. Sealing the rejected key also
prevents a delayed original command from later admitting a different outcome.

UiCommand.manual_no_admission defaults to false for existing wire clients. It is
a deny-only forwarding marker for an outer CAS refusal: after native/account
scope and existing-book checks it can only reject/seal an absent key. It never
executes the financial body, even when its version would otherwise be current.
The runtime/Composite owner preserves the original request scope and handles
its separate outer-boundary forwarding regressions. Invalid/stale native scope,
closed/failed storage or lost writer ownership cannot mint known admission
outcomes. LIVE remains denied independently before any mutation.

## M2-2 / scoped manual intent contracts — 2026-11-01

Manual intents carry context id/epoch, environment/account, shared connection's
opaque string generation and revision; UiCommand.expected_version remains the
separate book CAS. A backend must match every accepted scope before execution.
No submitted object is a grant, ACTIVE strategy or research/OOS evidence.

**M2-2 runtime integration (2026-11-01).**

The query worker materializes one canonical TradingEngine only after explicit
authenticated account selection. This is composition, not permission to trade:
each manual book still requires a confirmed application virtual allocation,
complete fresh account observations, current scope, and the diagnostic policy.
Canonical 60,000/40,000 application buckets and the global 100,000 limit remain
unchanged. Broker funds remain unavailable; no zero simulation reply becomes
positive broker financial evidence.

One execution consumer shares the existing authenticated SDK owner. A narrow
ExecutionPort wrapper serializes its mutable cache with query collection; it
only forwards the existing canonical ExecutionService call. SDK observations
run outside the writer. Collection releases its mutex before adopting reports,
and a batch collected across a committed book mutation is discarded. Failed
queries call service.adopt(()) so previous observations cannot remain usable.
Each collection has an eight-second acceptance bound, without increasing the
existing SDK, command or intent deadlines. Runtime pumping never calls the
automatic strategy cycle, automatic exits or legacy financial reconciliation.

ManualScope retains the broker owner's native generation and revision. The
CompositeFacade projects only the current scope's context identity/epoch;
preview, pending and result scopes retain their original admission identity.
The authenticated request account/environment, outer command, inner form,
accepted account selection and materialized owner stamp must agree. UI-only
connection revision offsets never become manual authority.

A small version-one Ledger retains masked alias/market facts and typed contract
bindings needed to reconstruct prior obligations. No native account identifiers
or credentials are stored there. Reconnection and contract changes preserve all
books/orders/positions. Missing or unselected historical obligations remain
blocked rather than disappearing. Observed-time-only resource renewals refresh
limits/capabilities without rewriting contract economics or silently resuming a
book. Economic/calendar/cost changes rematerialize and require confirmation.

Simulation readiness is computed for the selected book. READY requires a known
canceled/unfilled TMF diagnostic in the current native generation and current
book submission readiness. It does not certify stock or other key permissions.
The pending-account control host and a LOCAL book cannot borrow another book's
READY. These computed read models do not advance the native CAS token. LIVE
remains rejected before manual execution; production readiness remains blocked.

An optional trusted Python sinopac_clock dependency passes through existing host
composition into the owner's existing Clock port. Defaults and all real UTC
journal leases/fences remain unchanged; there is no CLI/config/environment
activation. The positive fake uses an actual covered trading date; the unchanged
built-in calendar rejects Sunday 2026-11-01. Required real-clock startup remains
separate and must produce no Sunday orders.

The exact additive submit-caller inventory records only the ExecutionPort
forwarder (runtime/manual_trading.py, submit, self.adapter). It adds no reservation
or commit authority: ManualTradingService._submit -> TradingEngine.submit ->
ExecutionService.commit remains the sole financial admission/journal path.
Historical v1 submit callers, the sole execution.commit assertion, protected
files, risk limits and all existing test assertions remain intact.

## M2-2 D1 coordinator oracle baseline

Book allocation is explicitly APP_VIRTUAL_SIMULATION, requires user confirmation
and fresh verified account observations, and never replaces unknown broker funds
or automatic daily-baseline rules. Preview returns backend cash/risk/fee amounts
and sources. Canonical quantities are integer shares/contracts with an explicit
whole-lot step. stop_price is a sizing estimate, not a placed protection order;
the view explicitly remains UNPROTECTED. Existing protection/STOP_NEW latches
cannot be cleared by a manual-book label. Automatic stop/strategy cycles are not
part of this round.

Pending and last_result retain exact request identity and known/unknown outcome.
An empty snapshot is not evidence that a timed-out command was never admitted.
The user-confirmed diagnostic shares the normal submit/cancel path; its purpose
is narrow, quantities/prices require verified facts, and it never promises no fill
or automatically retries/reverses partial/full fills. Full dispatch is subsequent
work; the contract slice starts no SDK, engine or financial operation.

Own pre-edit graph reports CRITICAL for UiAction/UiCommand/UiState and HIGH for
registry.initialize; warnings and exact source checks are recorded in
m2-2-verification.md. Four new boundary/codec tests pass, preserving old messages
and rejecting malformed money/quantity/scope input. The early foundation merge
missed the own precommit check; its actual postmerge comparison is documented
without rewriting history or retroactively claiming compliance.

## M2-2 / manual simulation presentation and independent review — 2026-11-01

The manual form uses the existing command worker and public typed contracts.
Only an accepted SIM context/account/generation/revision may prepare a virtual
book or order. Decimal prices and backend lot-size conversion preserve canonical
quantities; Qt does not calculate risk, margin, fees or execution permission.
The preview discloses app-owned funds, estimated costs, Taipei quote/expiry and
the absence of an actual protective stop. A diagnostic preparation has no order
intent; its separate confirmation can submit only the exact backend preview.
It may fill, so no unfilled promise, automatic retry or reversal is offered.
Price-only amendments avoid guessing the pinned SDK's ambiguous quantity API.

Confirmation defaults to Cancel and captures book version and connection scope
before the modal loop. Confirmed mutation requests retain their original identity
through transport errors, absent projections and subsequent login generations.
Only a matching server last_result with outcome_known can clear that UI latch;
even a false operation_failed/state_conflict receipt is not proof of non-admission.
The UI latch is observation state, not a replacement for the durable backend
journal. Existing LOCAL automatic controls remain separate; SIM resume always
requires an explicit unchanged manual book and fresh reconciliation eligibility.

Independent read-only review reproduced missing-projection/unknown-resume,
unknown arriving inside confirmation, and indistinguishable diagnostic results.
Four focused regressions were first observed failing (the resume test waits for
the real worker to avoid a scheduling false positive), then the source was fixed.
The accepted context identifies retained pending requests even when manual.scope
is absent; resume rechecks after confirmation; persisted test results/reasons are
localized. Dynamic catalogue keys were replaced by literal calls and source/model
codes were moved into tooltips. Strict presentation imports use contracts reexports.
The first integrated UI batch after these fixes passed84 tests in11.035seconds.
This is focused fake-Qt evidence, not full-suite or broker acceptance.

Own pre-edit graph: TradingWindow.command/_run CRITICAL (13/17 upstream symbols,
eight reported flows), catalogue CRITICAL (140 direct importers), translation_parts
HIGH. Other changed hooks were LOW; dynamic test callers were UNKNOWN and checked
against source/discovery. Index-wide process extraction has documented coverage
caps and does not certify absent flows. Complete change detection is required
before the forthcoming source/baseline commits. New phase63 strings follow the
frozen M2-1 phase62 ending2877; final merged catalogue/appearance pins will be an
independent explained baseline commit. The exact LIVE action-set oracle adds all
six manual actions without deriving expected values from the implementation.

A broad focused run accidentally used the restricted execution context and
stalled in tempfile._mkstemp_inner while the existing preference test performed
atomic_write. Its exact owned interpreter was verified by process handle, parent,
creation time and no descendants before terminating that incomplete QA run.
It is excluded from passing evidence; normal-user execution completed and exposed
real primary/help placement failures, subsequently fixed. Future filesystem and
complete suites use normal user execution. No engine/user app, ACL, deadline,
assertion, skip, G3 source, SDK pin or PROJECT_STATE was changed by this diagnosis.

The integrated manual transport must retain the accepted context_epoch even when
the context selector list is empty: the authoritative ManualScope still names
that epoch. The existing legacy command convention omitted it without navigation
choices. Restrict the change to the six manual commands and explicit manual-book
resume; keep unrelated legacy commands intact. A real-window regression exercises
the actual command builder for all seven intents. It is prepared but not yet run
while the coordinator's isolated M2-8 complete discovery owns the process window.
Fresh command#16 impact is CRITICAL:10 direct/13 total symbols,8 flows, with25
unresolved receiver call sites; source bindings confirm the manual calls. This
does not justify skipping the subsequent focused/full/runtime checks.

Second UI-only review reproduced three further real-widget defects before
fixing them: a confirmed virtual amount could differ from a still-editable
pending input; empty SIM tables navigated to the strategy wizard; and a failed
read-only poll left prior manual readiness actionable. The accepted amount now
replaces the input after confirmation, pending/unreachable fields are disabled,
SIM empty states navigate to manual preparation or connection, and the common
accepted-scope predicate also requires a reachable engine. A successful fresh
snapshot restores availability; no financial permission is inferred from this
presentation predicate. LOCAL strategy navigation remains unchanged.

All20 manual widget/worker tests now pass in2.077s, including the independent
outer-epoch regression without navigation choices. The three new defect tests
were first RED; no existing assertion was weakened. Runtime backend authority,
final integrated catalog pins, full discovery and startup remain separate gates.
Graph render_manual/matches/trading-page impacts are LOW; resume's dynamic
binding was UNKNOWN and confirmed at workspaces' actual button callback. These
checks resumed only after the coordinator's M2-8 retry passed its complete
smoke-sensitive desktop prefix; no second full suite or engine startup overlapped.

ManualScope is the server's native admission scope. The UI compares its accepted
context ID, epoch, environment and account to that scope, then forwards its native
connection generation/revision unchanged. The global connection panel may be
showing another host and may carry a presentation revision offset; it cannot
replace or invalidate that native CAS token. Confirmations still compare the
entire current ManualScope before and after the dialog. Preview and unknown
request identities remain bound to their original admission scope. Two pure
projection regressions first failed and then passed; real-window regressions
also cover an offset panel revision and a native scope change during confirmation.

A confirmed canceled/unfilled micro-Taiwan diagnostic proves only that diagnostic
for the current SDK generation. Its UI says “微台已通過（其他商品依券商回報）”,
never that stock permission was independently tested. Stock accounts cannot run
the TMF diagnostic and display a concrete switch-to-futures instruction. The
backend remains responsible for each account's actual permissions, observation,
funds, existing risk limits and native admission checks.

The resulting23 real-widget/worker tests pass in2.556s, with both offset and
native-scope-change cases exercised. They ran only after full M2-6 had completed
its desktop smoke prefix. These remain UI fake evidence; no SDK or engine
process was created and final integration/full discovery is still required.

## M2-2 / integrated manual exit and literal quantity units

Normal merge cf5582e retains the final M2-1 connection projection before manual
rendering and both command-completion paths. The next normal merge bb7b9c8 retains
the exact reviewed SDK execution guards, detached-consumer revocation and preview
quantity metadata. Duplicate contract paragraphs were removed only after exact
byte comparison proved the same text was already retained elsewhere. Focused
groups passed96 and40 tests respectively; these are not complete-suite results.

The existing explicit selected-position FLATTEN is the covered manual exit.
No stock lot is guessed from an instrument and no short cash-stock permission is
invented. The manual stock SELL form directs users to the position page. An actual
manual exit carries the reviewed native ManualScope, accepted epoch, target lot
and confirmed unchanged capital through the existing UiCommand/worker path.
It allows the backend's risk-reducing exit checks while new entries are halted,
but refuses an unreachable engine, unknown request, foreign book, or scope change
during confirmation. Both UI and backend validate ownership independently.

Manual stock sellability is an app-derived conservative estimate on reconciled,
owned, matured cash lots; it is not a broker-certified free-share field. The
confirmation says this explicitly and leaves native refusal/partial execution
possible. The backend retains existing risk/reservation/fence/journal behavior.
Selected PositionView.strategy_id equals the explicit ManualTradingView.book_id;
UI does not infer ownership from an order-ID/lot-ID coincidence or string prefix.

Preview text uses server-provided quantity_unit/lot_size: canonical shares display
in whole lots, futures in contracts, absent units as unknown. New readiness codes
map to existing literal Chinese manual guidance. A confirmed-not-submitted result
has its own message; it never clears a different unknown request's identity.

The29 manual real-widget tests initially exposed five failures across scoped
flatten, units, stock-exit guidance and readiness labels. The corrected integrated
group passed102 tests in9.156s. Qt converts string-enum item data to a string, so
the stock-side comparison uses value equality, not Python object identity.
The additional baseline group passed64 tests in18.598s after pinning exactly71
phase63 records at2878–2948. Historical locales, aliases and insertion order were
independently compared after removing only those71 keys. No unrelated appearance,
page-service or privacy baseline was changed; their original assertions passed.
Source and catalogue pins are committed separately. Final full discovery,
actual runtime startup and remote CI remain independent delivery gates.

The final backend allocation check adds one precise readiness explanation:
lowering current settings below previously confirmed manual capital blocks new
risk without erasing the book/loss history or legal exits. Both connection and
manual views map manual_allocation_exceeds_settings to that explanation. Final
phase63 is72 records at2878–2949 (literal global total2950). The catalogue pins
were regenerated from the committed parent, again proving every prior value,
alias and ordering unchanged; both exact catalogue tests pass at72. The64-test
baseline batch above remains correctly attributed to the preceding71-key source.

A further real-widget regression first failed because a selected SIM position
kept the shared flatten button enabled while a request was unknown. The manual
presenter now uses the selected explicit book/account, confirmed capital and
backend can_mutate flag, together with the existing reachability/busy/scope checks.
Selection changes refresh this state. The independent action-side checks remain;
owned halted-book exits still work. The unchanged new assertion and all29 manual
widget tests passed in2.553s after the correction.

The final72-key state also passed all64 catalogue, aliases, appearance, privacy,
page-service and architecture baseline checks in17.532s. The global total2950 is
literal and contiguous. Ruff check and formatting verification passed for all
seven modified Python sources/tests. These focused checks complement, and do
not replace, the final integrated full-suite and actual-startup gates.

The complete static pre-push initially found only a CRLF/LF formatting mismatch
in the changed catalogue-count test. Normalizing to the repository LF rule
leaves its sole Git difference2878→2950. The repeated static pre-push passed:
Ruff lint, formatting1166files, Python3.11 syntax1082trackedfiles and the
unchanged quality gate with zero findings.

## M2-2 / prepared-book exit baseline after final M2-1 integration

The normal M2-1 merge preserves the explicit page-owner API and all full-help
assertions. Its first93-check batch exposed one obsolete positive expectation:
leaving LIVE for SIM with the default unconfirmed ManualTradingView expected
flatten enabled. The implemented owned-book exit gate correctly keeps it disabled.
Update only that feature oracle to assert unconfirmed and disabled; retain both
selector acceptance, pending LIVE prohibition and no-command assertions. The
independent29 real-widget cases prove owned confirmed halted-book exits remain
possible and unknown/foreign exits remain blocked. The unchanged93-test batch
then passes in28.500s. Commit this feature baseline independently of the merge;
no guard, timeout, skip or existing assertion is removed.

UiCommand.manual_no_admission defaults to false for existing wire clients. It is
a deny-only forwarding marker for an outer CAS refusal: after native/account
scope and existing-book checks it can only reject/seal an absent key. It never
executes the financial body, even when its version would otherwise be current.
The runtime/Composite owner preserves the original request scope and handles
its separate outer-boundary forwarding regressions. Invalid/stale native scope,
closed/failed storage or lost writer ownership cannot mint known admission
outcomes. LIVE remains denied independently before any mutation.

## M2-2 / outer-CAS known-no-admission routing — 2026-11-01

Keep the original confirmed form, request ID, context/epoch and native owner CAS
when a boundary refuses admission. The default-false manual_no_admission field
is deny-only: core may seal a proven absent key under its existing writer/fence,
or replay an existing known/UNKNOWN request unchanged; it cannot execute the
financial body. A pure helper limits forwarding to typed confirmed SIM submit,
prepared diagnostic, cancel and amend forms with equal inner/outer scopes.
Composite uses only its already-held current book or same-native-owner control
port; it never opens/switches a host for a refusal. The authenticated server
turns a mismatched envelope into the same deny-only path without rescoping.
LIVE, malformed markers and unsupported/unconfirmed actions fail before fallback.
The runtime retains a false-receipt scope only when a matching server-known
result exists. Transport failures and preexisting UNKNOWN remain uncertain; no
generic state_conflict whitelist clears pending state or manufactures a result.

## M2-2 / explicit readability debt in the delivery inventory

Record exact file/class/function target exceptions and the required narrow split
plan for the manual application coordinator and strict-fake fixture. These targets
are not claimed as met and no limit or privacy assertion is changed. Preserve the
one canonical writer, journal, admission/absence proof, existing risk/fence and
all test cases. This is a separate documentation baseline after source integration;
actual class decomposition is outside this frozen safety handoff.

## M2-2 / six default order columns and exact display units

Visual review found the inherited seven-column order table. Reuse the existing
column selector with table-sized bounds, six default order columns and an optional
account column. Persist each choice by merging the dedicated presentation store
so order, position and future preferences do not erase one another. Keep canonical
order IDs, hidden full account values and native confirmation account text. Display
stock total/partial fills in exact fractional lots (500shares=0.5lots), with canonical
share-count tooltips; futures remain contracts. No financial or scope data changes.
The six new real-widget tests first failed3/error2 and then passed with the existing
nine guideline checks (15 total). Two literal phase63 strings use2950/2951; only
those keys extend the historical catalogue and contiguous total2952 in a separate
baseline commit. Root takes over this follow-up after the agent usage limit.


## 2026-11-01T20:39+08:00 — M2-2 final table evidence and precise inventory

Retain all ordinary parent merges and feature-specific independent baselines.
The final table component keeps six default columns, canonical quantity/account
identity and merge-based local preferences. Reject malformed incremental graph
UIDs and force only the local offline index; no FTS repair/download is requested.
Verify all13 added qualified definitions and both complete change scopes before
committing. Inventory line count is measured321, including the extra six LIVE
manual action entries and one unconfirmed-book assertion; an earlier scratch
assumption307 failed before editing anything and is not committed as a baseline.

Review consistent synthetic-budget/price visual fixtures only. A first scratch
capture still used old form inputs while previews were updated; correct the
capture helper values, rerun it, keep earlier evidence local and publish only
the consistent repeat. Neither helper alters product code or authenticates a
broker. The30-scene metrics,13 representative PNGs and checklist are distinct
from canonical fake order/startup/full-suite proofs. No second-round work is added.

## 2026-11-01T21:49+08:00 — M2-2 inherits confirmed legacy retirement refusal

Normally merge M2-1 sourcea7a6738 and independent inventory897df1b. Preserve all
manual service, outer-CAS no-admission routing, canonical execution, current
scope and UI code; source conflicts are absent. Keep both appended decisions
and readability inventories verbatim, then measure this branch's additional
bootstrap composition in its own independent baseline. Do not discard the
M2-1 source-specific evidence or relabel it as a manual execution proof.

Pre-merge exact class impact is LOW13; execute/connect/retirement each LOW3.
Execute has175 unresolved receiver sites, so its result is a lower bound.
Constructor hook remains UNKNOWN; the dataclass and two production factories
plus seven direct test construction sites are confirmed by source. No empty
caller set is treated as unused. Refresh the sole offline index and require
complete all/staged identities plus all newly added methods before the merge
commit. No SDK, catalogue, risk limit, timeout or existing assertion changes.

## M2-2 / prebuilt cleanup integration worktree

To shorten owner-requested delivery, prepare this normal merge in a separate
worktree while the unchanged799 manual full run finishes. Preserve both additive
decision histories and every M2-2 inventory row; replace only the old cleanup
test211-line measurement with its separately committed267-line measurement.
The only non-documentation delta799 is the exact owned cleanup tool and two new
regressions from M2-1; all application/runtime/manual/UI/financial blobs remain
identical. Pre-merge source2 method impact is LOW4 and nine load-probe flows;
the original tool/test blobs match the reviewed65e7d7f source exactly.
After the old run ends, fast-forward the official manual branch to this ordinary
merge without history rewriting, then run complete final discovery in its own
official checkout. New native/startup/full/CI results remain source-specific.

## M2-2 / native confirmation harness owns its application loop

Intermediate source799efad complete discovery4118/1548.934s has11F22E42skip,
33 traceback blocks/32 identities, oneNEW: the native confirmation test observes
no modal dialog. RawSHAfa0f1b2374193cae8d2d54dd3abdcf7668057ce3e3163b18e120ebc98176809e.
Keep this failed run, not passing acceptance. The new failure precedes owner-time
index/native preparation in the recorded traversal; overlap alone is not blamed.

Tight loop: original case alone PASS0.148s; a fresh QApplication.exit(0) prefix
reproduces the exact empty-observation assertion in0.168s. Ranked causes were
inherited application quit state, expired preview and a leaked confirmation
patch. The prefix reproduces without either other cause and _preview still
proves the Submit control enabled. No production defect is inferred from this
harness-only state; the real application already owns QApplication.exec().

Run the original button click from an owned application-loop callback, schedule
Escape inside it, then exit that outer loop. Explicitly prefix app.exit(0) to
lock down the dirty shared-Qt state. Preserve every original assertion and add
an outer return-code assertion: real QMessageBox, Cancel default, Escape and
exactly one preview command/no submit. No mocked dialog, skip, deadline, preview
expiry or financial predicate changes. Prefixed case GREEN0.131s;55 related
manual/UI-guideline/trading-page/order-report cases PASS5.428s.

Pre-edit method impact is UNKNOWN, not unused: the source was exact to799 and
the actual failed/controlled unittest invocations prove discovery. Fresh graph
and qualified new nested-definition coverage are required before commit.
Only tests/test_m2_manual_ui.py and this decision change; the resulting actual
module/class line measurements get an independent baseline commit. Product
GUI/theme/runtime/SDK/financial source remains identical; existing visual and
positive functional source equivalence remains explicit. Final corrected full
branch discovery and current-head CI remain required before push/delivery.

## M2-2 / final parent evidence prepared independently

Prepare the completed M2-1 evidence-only parent merge in this separate documentation worktree while the official32ad manual checkout remains frozen for complete discovery. Preserve both appended histories and verify zero non-documentation differences from32ad. Do not commit before actual full-result review and complete graph analysis. No index/native/Qt/static workload overlaps that final manual full.

## manual-cleanup-final / complete corrected source evidence

Publish exact 32ad384 complete discovery 4120/1508.968s, zero new failures and all32 actual causes reviewed. Keep earlier failed local/CI attempts, explicit secondary cleanup differences and exact fake-only actual startup facts. Only documentation changes after the tested source; prove non-documentation Git blobs identical and detect graph changes before commit. Require final current-head CI separately.

## M2-1 / corrected-head installer recovery budget evidence

The a62a110 offline workflow41323736469 passes all35 jobs. Windows installer
workflow41323736442 attempt1 fails the retained-candidate smoke after a real
same-version reinstall: recovery_helper_smoke.error_type is
InsufficientExistingSmokeBudget, timed_out is false and worker_cleanup.verified
is true. All seven UI operations and market/auth/history/walk-forward smokes
pass; baseline, interrupted-baseline and recovered-candidate smoke also pass.
The baseline WAL-workspace refusal deliberately records RuntimeSafetyError;
that expected refusal is not this failure. Artifact13091592701 preserves the
actual evidence. The prior65e7d7f installer workflow41316970379 passed all three
applicable jobs, and packaging source is unchanged between those heads.

Do not declare this a permitted main failure or claim a proven timing cause.
Retain the failed artifact, rerun the entire workflow with gh run rerun
41323736442 and require every applicable current-head job to pass. Do not
extend budgets, omit recovery checks or weaken their assertions. Further
failures require their own actual evidence review. This is documentation only;
all non-documentation blobs must remain identical to full-tested32ad384.

## manual-recovery-budget-verified / final complete source evidence

Publish exact7d72c5f38ac32d38709a39bcfb6ecb0ce23c7177 complete discovery 4125/1442.544s with zero new failures after individual actual-cause review. Retain previous failed CI/full attempts and previous successful source evidence. Only documentation changes follow; final runtime blobs must match this full/actual source. Do not reuse historical CI as the new final-head result.

## First-round final delivery and whole-workflow Qt control — 2026-11-02

Keep the already complete-tested M2-1 d2c11f2 program exactly equal to b605466.
Its real merge-tree against final M2-6 58a233a is clean and produces the same
non-documentation blobs. Preserve that active installer run; include the latest
M2-6/M2-8 evidence through a separate normal merge into the final M2-2 report,
whose program/test/fixture content must stay exactly equal to 7d72c5f. This
removes redundant documentation-only installer restarts without omitting any
required CI or complete source validation. Both changed upstream programs
actually repeated complete discovery and real LOCAL/fake-SIM startup before push.

Retain #132 offline41344493949 attempt1 Linux3.11 Qt segmentation fault at
command_palette.populate99/toggle137 and the existing real-controls test264.
Both source/test blobs equal original main0453136; no cause is established.
Do not call it a fixed bug or add it to the allowed main-host failures. Preserve
the native trace and rerun the entire workflow with gh run rerun, not one job.
Attempt2 passes the former crash group; all applicable final-head gates still
must finish successfully. No assertion, limit, skip or program source changes.
The original failed attempt remains evidence even if the complete rerun passes.

Latest upstream complete sources5906460 andb39af9c run3916/1422.446s and
3943/1456.190s, both10F22E42existing skips with zero new identities, all32
actual occurrences independently reviewed (30/32frames,32/32type chains,
15/16source files). Original launcher assertion and doubleWin32/.sqlite
secondary cleanup match main; original installer assertions only change line
offsets. Actual LOCAL5.692/5.496s and fakeSIM3.718/3.557s return0, real window
and seven research pages, normal exact-owned cleanup, endpoints removed and
zero real SDK/financial operations. Final read-only census0 own engines.

Include the final report itself in the final CI head and use live PR Checks
as the handoff gate. Earlier literal head/run/status rows are historical
snapshots. Do not create another cosmetic commit merely to copy a green badge
back into a report and restart validation. No second-round work or main merge.

Final metadata observes an external merge of #130 at2026-11-01T20:34:42Z
and #131 retargeted to main. Record that actor boundary in the report and
describe four delivery PRs rather than four open PRs. No main merge was
performed by this agent; all runtime/test/fixture blobs remain unchanged.

## M2 second round: engine decisions (2026-11-02)

M2-4 keeps legacy StrategyForm unchanged so historical daily research material
keeps its identity. New typed creation supplies separate StrategyParameters on
StrategyRecord. New restrictions apply at that explicit input boundary; a legacy
strategy is not implicitly converted or enabled. Parameters join the research
fingerprint only for typed versions. No v1/G3 or cost implementation is changed.

Estimated active engineering time: M2-4 45 min, M2-5 35 min, M2-3 55 min.
At 1.5x, deliver a tested mergeable slice with remaining scope explicit.
GitNexus pre-edit: UiAction/UiCommand/StrategyView CRITICAL (49 direct imports),
StrategyRecord HIGH (15 direct imports); additive defaults preserve old decoding.
Source confirms facade.snapshot despite graph UNKNOWN. No process membership was
reported; graph receiver gaps are not a claim of no runtime effect.

M2-4 chooses an all-in stock entry amount (principal plus the existing shared
FeeSchedule costs/slippage) and a conservative missing-margin fallback of50000
TWD/TMF contract, labelled BUILTIN_CONSERVATIVE in views/sizing. It is a local
assumption, not a claimed current broker margin. One active owner per account
and instrument is retained for future M3 target-position execution. Deletion is
a hidden tombstone, not erasure of journal/audit identity. Disable does not
transfer positions or erase their protective policy. UI remains another lane.

M2-4 offline verification: domain22 and management27 new tests pass; domain
mutants30/30 and management mutants18/18 killed in fresh subprocesses without
rewriting product source. Existing application29, selected coordinator/LIVE/
draft/scope/environment/valuation41 tests pass. Broader affected checks and CI
are still pending; these local results do not claim full acceptance.

M2-4 final local updates: management30 tests pass and20/20 management mutants
killed, including cumulative losses and a no-profit-expansion allocation ceiling.
Near-month View DTO tests cover rollover, settlement-day block and missing next
contract. See m2-4-engine-verification.md/.json for evidence and exact limitations.

M2-4 independent review corrected a mixed legacy/typed allocation bypass, JSON
rule-preserving parameter revisions, and rollover margin provenance. An account
adopts the M2 allocation contract persistently when its first typed version is
created (including later tombstones), so the old creation entry point cannot
bypass the new account ceiling. Legacy-only ledgers retain their original
contract. Management36 tests and27/27 mutants pass; existing margin/coordinator
regression13 pass. JSON interval/holding changes still preserve entry/exit rules
and clear all research evidence for the new version.

## M2-5 account risk and preflight — 2026-11-02

Use per-account 3% of confirmed allocation, with independent day latches. Choose
1000000 TWD maximum entry notional and five instrument/side positions as the
unspecified initial defaults. They are editable typed limits, not broker facts.
Pending entries, including UNKNOWN/cancellation, occupy slots; reductions do not.
Explicit limits also adopt manual/legacy accounts, so no entry owner bypasses
limits merely because it predates typed strategies. Saving limits cannot erase
history or release retained reservations.

Extend the existing prior-close evidence with an optional exact account split.
Never divide a multi-account total by allocation or sample the current mark as
a new baseline. Only a proven empty genesis (including confirmed known canceled
zero-fill SIM diagnostics) seeds zero. LOCAL explicit day-step carries account
marks forward and collects that new day's trusted preflight.

Preflight facts are server-owned, cached and immutable at the command boundary.
SIM permission requires the successful diagnostic in the actual SDK generation,
not login/signature or an attempted order. CA is NOT_REQUIRED in LOCAL/SIM.
A failed or unknown check blocks the whole trading day and preserves reasons.
Connection/lifecycle changes during collection invalidate the result through a
final owner/version comparison under bundle → engine → owner lock ordering.
No balance-query fallback, credentials, CA activation or power-setting change.

Keep STOP_NEW's existing cancellation semantics and protective-exit behavior.
New modules are application/account_risk.py, application/preflight.py and
runtime/preflight.py; inventory registration is generated once with
repin_baselines.py and committed separately. M2-4 PR143 completed35 green checks
on4350f05 and merged as6d50129 before this branch was opened directly from main.

M2-5 independent review reproduced a manual SELL amendment whose lower stop
risk hid higher notional (TMF25000→25001 across a250000 account cap). Reapply
account admission to the amended entry plan before recording/calling the SDK;
protective reductions remain exempt. Three regressions and three independent
guard mutants pass, plus96 nearby manual/recovery/risk/LIVE tests. No existing
assertion or price-risk guard was weakened.

## M2-3 minute execution and R5 delivery — 2026-11-02

Use one materialized engine/journal/shared SDK and confirmed virtual capital for
manual and automatic orders. Do not invent financial snapshots or manual intent.
Persist completed-bar claims before both entry and normal-exit signals; pumps
only maintain protection/time rules. Automatic resume is a separate user action.
Current-entry permission must be actual diagnostic proof in the current owner
generation, and a final owner lock spans the bounded SDK call and forced cancel.
This fixes the independently reproduced preview-to-send disconnection race.

Keep the original per-account report validation as the only authority; retain
independently validated fresh scopes for protection when another account fails.
All entry risk remains stopped; SDK failure, empty observation or changed owner
cannot borrow that proof. This fixes the native reproduction where a stock
external order suppressed an already confirmed futures protective reduction.
The earlier same-epoch writer-version cache contract is preserved.

Use official per-product DAY hours on the supplied verified date set. The M1
terminal supports stocks/indices, so consume actual TMF callbacks through its
separate execution-consumer queue on the same SDK, not a second market engine.
Do not infer holidays or next-month contracts. Only BROKER_VERIFIED margin source
attests broker margin; otherwise typed TMF uses labelled50000 TWD. Research,
deployment and commitment use the same effective spec/calendar/fee fingerprint.
Typed EXACT as well as NEAR new entries stop on settlement day.

R5 scope: first M2-3 draft09:13:15; at10:36:06 elapsed82m51s exceeds the82m30s
limit from estimate55min. Deliver completed1m/5m cycles with verified safety;
defer daily signal persistence/next-session dispatch (another estimated2–3h)
to the next round. Typed broker1d new entries explicitly fail with
automatic_daily_execution_pending and View DTO PAUSED/block code. LOCAL1d
research/day advancement and legal reductions remain available. Minute research
is M2-7's evidence port, not replaced by this lane's synthetic fixtures.

Final relevant local tests354+398 pass and original LOCAL/fake-SIM windows return0
with owned cleanup. Mutation evidence and final graph/static/CI status are in
m2-3-engine-verification.md/.json and the PR checks. No complete acceptance is
claimed for the deferred daily path, UI, M2-7/9 or real broker automation.
