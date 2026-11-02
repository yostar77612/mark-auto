# Desktop graceful exit investigation (2026-11-02)

Base: main `e5a5941`; branch: `codex/fix-graceful-exit`.
Scope: desktop composition shutdown in `trading_runtime.py`, plus regression
tests and evidence. LIVE execution, G3, trading feature files and strings unchanged.

## Root cause and measured baseline

The normal v2 desktop returned from the Qt event loop without sending
`SHUTDOWN_ENGINE`. Its final comment explicitly preserved the independent engine.
The engine continued its server accept/heartbeat/coordinator loops and held its
own installer-visible `WindowsAppMutex`. The UI releasing its handle therefore
could not remove the installation guard. This was a missing lifecycle handoff,
not evidence of an IPC shutdown deadlock or a non-daemon UI Python thread.

An isolated native LOCAL window on Windows accepted `window.close()`, returned
0 after **0.012 s**, and had only `MainThread` in Python. At **25.013 s**, its
retained native engine Popen was still alive and its authenticated endpoint still
existed. The same retained child exited 0 in **0.092 s** after an explicit normal
shutdown; no termination was needed. The temporary baseline harness used
`OwnedEngineProcesses` for containment and was removed after recording evidence.

Before the fix, `tests.test_trading_graceful_exit` failed all three real GUI/IPC
cases: LOCAL subscribed, BROKER_SIMULATION subscribed, and BROKER_SIMULATION with
pending history. Every observed engine exit code was None and every endpoint
remained present before fixture containment. This is the regression signal;
fixture cleanup is deliberately outside the passing observation.

## Change

`run_window` snapshots the preexisting retained-child registry inside the UI
installation guard. On normal return or startup failure, it closes only newly
retained Popen objects, including engines opened after context switches. Reused
hosts and earlier handles are untouched. The endpoint PID must match the exact
retained child before sending an authenticated shutdown request. Existing command
version conflicts are refreshed up to three times. A shutdown receipt alone is
insufficient: the original process must return zero before its registry entry is
removed and the UI installation guard is released.

All owned children share a five-second exit wait allowance. Failure stays an
`outcome_unknown` error, retains the process registration and attempts the other
children. There is no process-name discovery, terminate, kill, timeout extension,
or position flattening. Existing engine shutdown semantics stop new activity and
preserve journaled ownership for reconciliation on restart.

GitNexus at the exact worktree/base identified `desktop.main -> run_window ->
_run_window`; both edited existing functions had LOW risk. Server context showed
the existing `cancel_owned_workers -> join handlers -> bundle.close` shutdown
path; that path already exits promptly when requested and was left unchanged.

The initial incremental change scan had an empty symbol UID and incorrectly
expanded a test helper across 653 processes (CRITICAL). This was not accepted as
a clean check. A force rebuild resolved the UIDs; the full rerun identified all
35 changed symbols, including the production shutdown functions, at LOW risk,
without partial/truncated flags. The new helper's upstream impact is also LOW.

## Verification

Windows runtime: repository `.venv` based on private CPython 3.13.11; native
PySide6 windows, actual named pipes, actual engine subprocesses, fake SDK only.
The fixture opens the real isolated embedded research session, then checks its
exact QLockFile can be reacquired. Each case uses a unique native mutex name with
the production `WindowsAppMutex` implementation to avoid other desktop sessions.
It proves the mutex exists before close and disappears afterwards. The parent
waits for the actual GUI process and measures from the first close request.

Observed with research session and lock checks enabled:

| Case | `run_window` return after close | Entire GUI process exit |
| --- | ---: | ---: |
| LOCAL, active subscription | 0.190 s | 1.999 s |
| BROKER_SIMULATION, active subscription | 0.133 s | 0.358 s |
| BROKER_SIMULATION, in-flight history SDK call | 2.145 s | 2.371 s |

All retained engine exit codes were zero; endpoint files disappeared; fake SDK
unsubscription/logout completed; real SDK was not imported; both native mutex
and research QLockFile were released. Engine workspaces were reopened through
the real runtime builder, proving journal leases were released. Further tests
cover multiple children with a preexisting host preserved, startup exceptions,
and mismatched endpoint ownership refusing shutdown while retaining the handle.
The final regression also asserts the pending call has started and has not
finished at the moment close is requested.

Commands (from this worktree; UTF-8 and repo/tests on PYTHONPATH):

```powershell
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest tests.test_trading_graceful_exit
& 'C:\Users\Mark\Desktop\Mark auto\.venv\Scripts\python.exe' -m unittest tests.test_desktop_runtime_bootstrap tests.test_trading_runtime tests.test_trading_engine_cleanup tests.test_trading_installer_guard tests.test_runtime_context_cli_v2 tests.test_desktop_unified_research tests.test_function_lengths tests.test_repo_layout
```

The 90-test combined related-module run had 87 passes, two global mutex assertions
and one cp950 decoding error in an existing git-path listing. Serial rerun with
`PYTHONUTF8=1` passed all 28 repository-layout cases and six installer-guard cases;
the same two native installer-guard assertions still fail because a preexisting
global app mutex remains present. Those tests are byte-identical to main and fail
before invoking the changed UI body. No external process was stopped and no
assertion was changed. The new tests use a separate native mutex namespace and
pass its actual availability/disappearance checks. Full discovery is reserved
for CI; no two full suites run locally.

The installed external processes were identified read-only as PIDs 168580 and
286532, started at 08:31/08:32 from the installed 0.3.0 payload (commit
`8f192ff`). They predate this task and were not touched. The new regression's
final four tests passed in 32.744 s, including the explicit pending-call check.
Python 3.11 syntax (1,144 tracked files), Ruff lint, quality and layer gates
passed. Pre-push exposed one existing main M3-document code-fence CRLF/LF failure;
Ruff changed only line endings, so its text has no git diff. The repair pins that
single document to LF in `.gitattributes`, following the existing Ruff ADR rule,
and is isolated in a separate baseline commit. Full cheap pre-push gates then
passed (Ruff 1,240 files; Python 3.11 syntax 1,145 files; static gate zero findings).

## Frozen scope and remaining owner check

The existing frozen 0.3.0 artifact at
`build/package-sdk-work/dist/MarkAuto/MarkAuto.exe` identifies commit `67249dc`.
Its packaging isolated smoke (`--smoke-test <report> --smoke-isolated`) passed,
exited zero in **18.016 s** including synthetic research/helper exercises, and
reported verified worker cleanup. That is the existing legacy smoke, not the
new v2 close path and not a five-second close measurement.

The source frozen-dispatch tests run unchanged. A new installer containing this
fix has not been built or installed here: packaging requires pinned CPython
3.13.16 while this host's private interpreter is 3.13.11. Final frozen v2 window
closure and installer replacement with the rebuilt artifact remain owner checks.
No real broker, credentials, CA or real/simulation orders were used.
