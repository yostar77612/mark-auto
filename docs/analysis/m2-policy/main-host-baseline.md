# M2 unchanged-main full-suite failure review

Baseline: `045313634a6fe4c33aeacfc972182d00e83cd58e`, worktree `.worktrees/m2-main-baseline`.
Log: `.tmp-m2-main-full.log`. The exact test-owned Python PID **48188** was observed exiting before this review was finalized.

**Complete result: 3,888 tests in 1,968.015 s; FAILED (failures=10, errors=27, skipped=42).**
This is a complete nonzero baseline, not a passing suite. All 37 ERROR/FAIL traceback blocks were read, including chained primary/cleanup exceptions. They represent 36 distinct IDs because one symlink case has two subtests. The ID set equals the prior complete unchanged-main log `.tmp-m1-ci-main-full-verbose.log`: no added/missing failure IDs. This ID comparison alone is not the cause evidence; the traceback/source review below supplies that evidence.

## Classification

| Observed category | Records | Direct evidence and scope |
|---|---:|---|
| Symlink privilege | 20 ERROR / 19 IDs | Every block ends in `os.symlink`/`Path.symlink_to`, `OSError [WinError 1314]`. Failure occurs while constructing the synthetic link, not in the product's link-rejection assertion. |
| Initial LOCAL runtime launch deadline | 5 ERROR | Four RuntimeContextClient tests fail in their initial `manager.open_context` → `ensure_engine:148`; one IndependentEngineRuntime class fails in setUpClass at the same deadline. These do not reach the named test behavior. See PID evidence below; do not claim every individual child was separately proven healthy. |
| Native worker fixture cleanup | 1 ERROR | `test_native_windows_natural_parent_exit_with_descendant_cannot_pass` reaches TemporaryDirectory exit and raises `PermissionError [WinError 32]` for `tmphbhkt4mg/research-workers-e2kv7yzx/worker-0.log`. The case body's original cleanup/report assertions therefore completed; retained file ownership still prevented actual cleanup. The retained log itself shows its two synthetic tests passed, not an import error. This block contains no DuplicateHandle failure, so its precise lock-holder cause remains unproven. |
| Crash-driver process identity | 1 ERROR | E06 first fails its actual PID check: published **306352** != retained Popen **256312**. Cleanup then raises WinError32 for the same owned fixture's simulated-exchange-v2.sqlite. The cleanup error masks a directly logged redirector PID mismatch; this is not an unexplained SQLite/order regression. |
| Paper diagnostic parent ownership | 4 FAIL | Exit1 in ~0.22–0.24 s, no first checkpoint/observer, missing expected controller error field, or comparison result1. Controller writes its own PID but child validates os.getppid; it launches sys.executable with stderr discarded. Earlier captured stderr proved the ownership ValueError on the same host. Both diagnostic source and tests are byte-identical to that diagnosed baseline. This run did not capture fresh child stderr, and no new diagnostic was run here. |
| Named application mutex visibility | 3 FAIL | OpenMutex after guard.close returns HANDLE **2448**; two later cases refuse an already visible named mutex. A HANDLE is not a PID. No evidence identifies a user application as owner. The first failed assert itself does not close its returned handle and can preserve the object for subsequent cases. |
| Native retained grandchild handle | 3 FAIL | All three blocks first raise `OSError [Errno 6] receive retained grandchild handle` from `DuplicateHandle`; each then fails required cooperative-cleanup confirmation. Source duplicates a handle published by the Python worker using the retained Popen worker handle. This is consistent with the documented venv redirector handle-table mismatch and prior host reproduction; no weaker containment/cleanup oracle was substituted. |

## Startup identity evidence and limits

Source read: `quantlab/trading/runtime/context_client.py:91–148`. The launch uses `sys.executable`, retains Popen.pid, and returns success only when the published session.process_id equals that exact PID. It preserves the original 15-second deadline. Its bytes match the indexed policy-worktree copy used for graph navigation.

After the full baseline ended, its ResourceWarning named Popen **307132**. Read-only process metadata showed that PID's parent was baseline **48188**, executable `.venv/Scripts/python.exe`, and command line selected the exact fixture `.worktrees/t/v2-runtime-u_a71tyo/isolated`, LOCAL/local-stock. Its actual `.runtime-sqlite/python.exe` child was **333180**, parent **307132**. Reading only the session's `process_id` field gave **333180**. Thus this full-run IndependentEngineRuntime fixture cannot satisfy the exact retained-PID equality despite publishing a session. No protected key was printed/decrypted. A successful authenticated snapshot for this full-run orphan was not performed by this reviewer; coordinating-agent evidence separately confirmed a healthy same-path startup in prepush.

The four RuntimeContextClient failures are specifically the initial LOCAL startup deadline from this same launch/guard path. Their per-case PID/session values were not retained in the log. Their common launcher explanation is source-supported, not a claim of five separately captured healthy-engine probes. No production gate, startup deadline, test assertion, Windows policy or dependency was changed to hide this baseline behavior.

## Concerns / handoff

- Reported to the coordinator: the exact test-owned fixture/wrapper/child above was still present during this audit. Only its owner should perform authenticated normal shutdown after verifying the exact fixture and session. This reviewer sent no process signals, shutdown commands or deletions. Process presence is an observation at audit time, not a later live-state claim.
- Native worker cleanup is a real baseline failure, not permission to call its suite successful. Its exact process/file holder was not captured; do not relabel it as a proven DuplicateHandle exception or a generic missing-dependency issue.
- Named-mutex ownership is unresolved. Do not terminate a user process or attribute the mutex to it based on visibility alone.
- No unrelated new failure identity/exception family or native access violation was found in these 37 blocks. This does not waive any branch regression: compare complete branch results and actual exception evidence, and require the mandatory remote CI independently.
- No test, product source, setting, dependency, permission, Git object or branch was modified by this QA task. Only this scratch Markdown and `.tmp-m2-main-failure-ids.json` were written. The queued policy full suite was not started, stopped or otherwise touched by this reviewer.

## Machine-readable evidence

`.tmp-m2-main-failure-ids.json` retains every exact ID, subtest, category, confidence, traceback exception chain and source-log line number. It records all 37 occurrences instead of collapsing the duplicated symlink subtests. Log SHA-256: `9de08cc417a5927ce1b0c9fc868a2bfc1fef06fb07032892a969ae22b27f5fc3`.
