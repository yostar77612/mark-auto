# Complete-suite failure comparison: market settings fix

Main 0453136: 3,888 tests/1,968.015s, 10 failures, 27 errors, 42 skips.
Market 34673c2: 3,893 tests/2,094.353s, 10 failures, 27 errors, 42 skips.
Both have complete unittest footers. Market has 37 traceback occurrences and 36
distinct IDs, all present on main; there are zero new IDs. This is the owner's
documented unchanged-main failure comparison, **not a claim that the local
suite passed**. Remote CI remains an independent required check.

The coordinator inspected all 37 raw blocks. Thirty-six match ordered frames
and exception-type chains; nineteen referenced repository source files match
main byte-for-byte. Only the generated 16-hex fixture component in one symlink
subtest label was normalized for matching, with raw evidence retained. No test
selection, assertion, timeout, source limit or existing skip was relaxed.

| Occurrences | Actual cause evidence and limits |
|---:|---|
| 20 | Synthetic symlink construction raises WinError 1314 before the product rejection assertion. There are 19 distinct IDs because one has two subtests. |
| 5 | Four initial LOCAL context launches and IndependentEngineRuntime.setUpClass hit the unchanged exact-PID startup deadline. The class-owned wrapper 153036/native 230124 fixture responded to normal authenticated shutdown, then both exited. Do not claim every individual failed launch was separately proven healthy. |
| 1 | Native worker test reaches TemporaryDirectory cleanup and WinError 32 for worker-0.log. Its exact lock holder remains unproven; it is not relabeled as a DuplicateHandle exception. |
| 1 | E06 first fails the same published-vs-retained PID assertion as main. Its secondary cleanup differs: this run has WinError 5 on .sqlite-shm; main has WinError 32 on .sqlite. Those variants are retained rather than called identical cleanup evidence. |
| 3 | A named application mutex remains visible, including an OpenMutex return value. A Windows handle is not a process ID; owner attribution remains unknown. |
| 4 | Paper probes exit1 before the expected checkpoint/observer. Same-source prior diagnostics support the venv parent-PID guard explanation, but fresh child stderr is not present in this complete run. |
| 2 | Native recovery fails DuplicateHandle with Errno 6, followed by failure to confirm cooperative cleanup, matching main's chains. |
| 1 | The remaining native recovery ID is preexisting but reaches a different assertion: retained grandchild already signaled,0 rather than WAIT_TIMEOUT 258. Exact underlying cause is unresolved. See below. |

The variant ID is
`test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_after_gui_before_quiescence_never_publishes_receipt`.
Market reaches line 1165 and observes 0 != 258; main fails earlier receiving a
retained grandchild handle and during cleanup. Its standalone TEST_ONLY
supervision experiment and diagnostics/native-runtime dependencies are
unchanged and do not import either changed product UI module. This bounded
evidence supports retaining the existing failure classification; it does not
establish an identical native cause or infer a product/test correction.

An additional unchanged-main narrow replay had only one starting line, no
completion footer, and no retained Python exit code from its shell wrapper.
It is inconclusive and excluded from all pass/count/cause evidence. Its owned
processes were subsequently confirmed absent. The complete main and market
runs remain the comparative evidence.

Full-log SHA-256 values:

- Main: `9de08cc417a5927ce1b0c9fc868a2bfc1fef06fb07032892a969ae22b27f5fc3`.
- Market: `229b39a17ffb7d193a006f6a87aa2a977d99b4fbf4e315a0f6c4d52af2cfdd87`.

The coordinator retains the full logs and 37-block raw comparison; this concise
record avoids duplicating temporary-path-heavy tracebacks in the repository.
The product fix changes only two UI modules. All tests, protected files,
SDK pin, theme and runtime behavior remain unchanged from the verified source.
