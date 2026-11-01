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
only. Branch full-suite comparison, final actual startup and all-green CI remain
controller-scheduled and must be verified separately before delivery.
