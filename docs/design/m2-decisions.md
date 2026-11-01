# M2 implementation decisions

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
