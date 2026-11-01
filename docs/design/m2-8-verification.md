# M2-8 focused verification

Base: `origin/main@afc45ea888cf744b69db9f48cfd3946c1080e041`.
This branch changes test/developer lifetime only; production runtime, locked
files, SDK pin and PROJECT_STATE remain unchanged.

The regression ran before the fixture correction with the provisioned native
Python and installed package paths:

```
python -m unittest discover -s tests -p test_trading_engine_cleanup.py -v
Ran 1 test in 13.633s
FAILED (failures=1)
AssertionError: None != 0 : failed setUpClass must not leave its engine running
```

The red test's finalizer still normally shut down that one retained engine, so
the red phase itself left no child. After the correction the same case passed
through the original Windows venv launcher in 4.771s. Expanded actual-process
coverage passed 8 tests in 36.446s, then final 9 tests in 49.948s with that same
venv launcher:

- Failed class setup after actual engine readiness.
- Successful body and reused-host retention, including unchanged sentinel data.
- Assertion failure and ordinary exception after actual readiness.
- Caller startup deadline before endpoint publication, followed by normal
  authenticated shutdown of the real native engine (not a mocked engine).
- Per-test setUp and tearDown failures without skipping registered cleanup.
- Native load-probe setup failure before its facade is returned; report remains
  FAIL, acceptance remains false, and normal shutdown is verified.
- Different session PID receives no control command.
- Cleanup error still attempts each retained child and remains a failure.
- Actual synthetic host setup failure plus an unrelated failing cleanup hook
  still closes the retained multiprocessing host normally.

Actual children must exit 0, lose their session file, and leave `_STARTED`.
One real reused engine stays alive and responds until its own outer scope closes.
No SDK is loaded, no credentials are read and no orders are sent by these checks.

Logs are local-only under this worktree `.tmp/m2-8-*`; the controller collects
full-suite, actual-window and CI evidence separately. The native installer-mutex
module ran after the controller's policy full suite finished and its known
test-owned engine was normally closed; the result below remains a host limitation.

All test commands use the provisioned root `.venv/Scripts/python.exe`,
`PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen`, and separate module discovery from
this checkout. Their child roots are fresh isolated fixtures.

| Focused command suffix | Result |
|---|---|
| `-m unittest discover -s tests -p test_trading_engine_cleanup.py -v` | 9 passed, 49.948s |
| `-p test_trading_runtime.py -v` | 12 passed, 15.008s |
| `-p test_runtime_context_client_v2.py -v` | 12 passed, 36.425s |
| `-p test_trading_runtime_context.py -v` | 13 passed, 18.665s |
| `-p test_trading_load_probe.py -v` | 6 passed, 0.002s |
| `-p test_runtime_context_cli_v2.py -v` | 3 passed, 0.160s |
| `-p test_docs_layering.py -v` | 8 passed, 1.675s |
| `-p test_repo_layout.py -v` | 29 passed, 3.699s |
| `-p test_layer_gate.py -v` | 21 passed, 11.835s |
| `-p test_trading_installer_guard.py -v` | 7 run, 5 passed, 2 preexisting-lifetime failures, 0.010s; neither native case reached child/fixture creation |
| `powershell -NoProfile -File tools/prepush.ps1` | PASS: Ruff lint/format (1104 files), Python 3.11 syntax (1039), quality gate (0 findings) |
| `tools/check_layers.py` | PASS, 0 findings |

An initial guessed `test_check_layers.py` pattern matched no module (exit 5,
not passing evidence); the actual `test_layer_gate.py` was then located and its
21 cases passed. No existing test was skipped, removed or weakened.

Post-focused read-only CIM inspection found zero `desktop.py --trading-engine`
processes launched from this exact checkout. Each real regression also retains
and verifies its own native process handle; this scan does not replace that proof.

The incremental graph refresh had invalid empty function/method node identities,
causing `detect_changes` to attribute 603 unrelated flows to a test callback and
report CRITICAL. CLI and MCP both reproduced the missing IDs, including an
existing setUpClass. The authorized local-only forced rebuild restored all
symbol IDs; no test semantics were changed to hide it. Final complete analysis
reports 64 changed symbols, 12 files, nine affected load-probe flows, HIGH risk,
no empty IDs, partial=false and truncated=false. This warning was reviewed
against the direct diff and tests: the new scope is imported by five test/tool
files, production files have no diff, exact PID/authenticated ownership is
preserved and all changed load-probe setup/failure/cleanup paths are covered.
Per-symbol scope risk is MEDIUM; cleanup and load-probe main are LOW.
Dynamically registered hooks are UNKNOWN to the graph and were confirmed by
source references and actual-process tests. No graph extension download was
attempted.

## Native installer host limitation

On the controller-authorized exclusive window, both existing native cases
failed their original precondition `A preexisting app lifetime must not be
disturbed`, before creating any temporary fixture, UI child or engine:

- `WindowsInstallerGuardLifetimeTests.test_native_guard_survives_either_owned_process_exiting_first`
- `WindowsInstallerGuardLifetimeTests.test_native_ui_exception_releases_guard_without_engine_or_workspace`

The controller confirmed the same two identities/reasons in the complete main
baseline. The five boundary cases pass; no assertion, skip, applicability or
deadline was changed. This is not a passing native-lifetime acceptance claim.

Read-only CIM and visible-window inspection found an already installed 0.3.0
MarkAuto UI (PID 292468, created 12:41:34 Asia/Taipei) and installed LOCAL engine
(PID 75892, created 11:29:05) using the user's normal `MarkAuto-v2/local` root.
Both predate this work and are outside every disposable fixture. A zero scan of
Python `desktop.py --trading-engine` processes cannot detect a frozen installed
app. These are consistent lifetime candidates; individual mutex handle ownership
was not inspected. Neither process or its workspace was controlled, modified
or shut down. Candidate/log details remain local-only under `.tmp`.

After this result the controller resumed its serial full-suite queue. No further
engine/native test run was attempted. Source implementation remains commit
`38da68dc1823aa5d070548e0804f29dbba8eb25d`; this evidence update is documentation
only. Subsequent controller evidence follows; all-green CI remains pending.

## Complete discovery and retained smoke failure

Both branch runs used source `8f03a9905c337680f2f963ba284bed5bf3638bcb`.
The comparison baseline is main `045313634a6fe4c33aeacfc972182d00e83cd58e`.

| Complete run | Tests | Seconds | Failures | Errors | Existing skips | New failure IDs versus main |
|---|---:|---:|---:|---:|---:|---:|
| Main | 3888 | 1968.015 | 10 | 27 | 42 | Baseline |
| M2-8 first | 3909 | 1945.460 | 11 | 22 | 42 | 1 |
| M2-8 unchanged retry | 3909 | 1487.114 | 10 | 22 | 42 | 0 |

These are failed local suites, not all-green acceptance. The first NEW identity,
`test_desktop_smoke_terminal.GenericSmokeTerminalProcessTests.test_success_publishes_once_only_after_verified_cleanup`,
remains retained. It reached the unchanged 40-second outer capture deadline
while WFO preview was pending; no WFO run or final report had started. The
timeout artifact verified all 11 recorded workers stopped, no report writes,
and no cleanup error. Cumulative stage latency is observed, but its underlying
cause is unproven; unchanged source does not waive a newly observed failure.

After the controller paused indexing and process-heavy work, the exact unchanged
case ran sequentially: main passed in 15.027s, then M2-8 passed in 13.915s, both
exit 0. Original cleanup, single publication, 22 evaluation and 63 save assertions
remained. This does not establish full-order independence or erase the first run.

The unchanged retry began at 15:33 Asia/Taipei. Its smoke-sensitive prefix was
quiescent and the previously new case passed. After that prefix, the controller
allowed one other-worktree index and small Qt/metadata checks during later tests.
Only the prefix was isolated; the whole retry was not background-free.

## Raw traceback and cause comparison

The retry contains 31 distinct failed identities and 32 traceback blocks (one
subtest adds a second block). Absolute-path-aware review found 30/32 identical
ordered frame sequences, 32/32 identical exception type chains and 15/16
referenced repository blobs identical to main. The two frame differences are
line offsets in the intentionally changed installer cleanup fixture; both stop
at the same original preexisting-lifetime assertion. Type/ID matches alone are
not cause equivalence. Reviewed raw differences are:

| Blocks | Observation relative to main |
|---:|---|
| 20 | Same symlink creation WinError 1314; generated temporary/archive paths differ. |
| 1 | Same repeated WinError 32 on the retained research worker log; temporary path differs. |
| 1 | Same native-versus-launcher PID assertion, with different PID values. Subsequent SQLite cleanup differs: retry WinError 5 on `.sqlite-shm`, main WinError 32 on `.sqlite`. These cleanup causes are not identical. |
| 3 | Nonzero mutex handle value differs in one case; two cases have the exact preexisting-app-lifetime assertion. No installer fixture begins in those two cases. |
| 4 | Same paper-probe return 1/no completed diagnostic, missing `error_type` or return-code assertions; paths, PIDs and timings differ. Those records do not independently prove the child exit cause. |
| 3 | Same Errno 6 receiving a retained grandchild handle, followed by the same unconfirmed cooperative-cleanup assertion. |

Five main failure IDs are absent in the retry: four RuntimeContextClientTests
cases and IndependentEngineRuntimeTests.setUpClass. This is observed comparison,
not a claim that all host failures were fixed. Sanitized per-block identities,
meaningful WinError differences and raw-log SHA256 values are retained in
[m2-8-full-comparison.json](m2-8-full-comparison.json). Raw local logs and the
original smoke artifact remain available to the controller; user paths, generated
PIDs and report dictionaries are excluded from the committed artifact.

## Actual window startup

Controller result JSONs under the disposable launch-probe directory
`.tmp/m2-8-8f03a99/{local,broker}/result.json` identify the same source head above.
Both use the real `_run_window`, TradingWindow and runtime composition, render
seven embedded research pages and 2726 widgets at 780x720, return 0, release the
research session and shut down the owned engine normally, with no errors.

| Mode | Seconds | Broker evidence |
|---|---:|---|
| LOCAL | 8.831 | No real SDK import. |
| BROKER_SIMULATION | 6.087 | Actual authenticated named-pipe server in an owned thread; fake login/logout 1/1, two subscriptions, zero order constructors/orders, no real SDK import. |

These checks establish startup/render/normal-cleanup behavior for these fixtures;
they do not establish real broker login, CA or order acceptance. The local native
installer precondition limitation above remains. GitHub CI is pending and must
be recorded by the controller after push. No formal acceptance score changed.

## Documentation finalization audit

`python -B -m unittest discover -s tests -p test_docs_layering.py -v` passed
all eight checks in 0.973s using the provisioned root venv with `PYTHONUTF8=1`.
`git diff --check` passed. All 1169 tracked non-documentation checkout files
retain their task-entry SHA256 bytes, and the non-documentation diff against
tested source `8f03a99` is empty. No full, native, Qt or engine test was rerun
for this documentation commit. The controller owns subsequent integration,
push and CI; no later main merge is implied by these source-specific results.
After the coordinator released the graph slot, a single-worker local refresh
indexed the new evidence sections. Final all/staged change checks each report
four documentation files, 11 sections, zero affected processes and LOW risk,
without error, partial or truncation flags. Standard whole-index candidate,
cross-language and flow-budget warnings remain in the local log; absent graph
flows are not used as proof about product behavior.
