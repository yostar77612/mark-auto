# T14 P3-01 - intermittent CI timeouts: evidence and conclusion

No timeout, retry count or sleep was changed (G5). Subprocess isolation is untouched.

## Census (GitHub Actions, workflow `quantlab.yml`, last 30 runs)

* Failing jobs are different tests each time, all of which launch real child processes
  under small fixed budgets: Paper connection diagnostics (10 s observer window),
  Walk-forward terminal cleanup ("Owned smoke cleanup failed within the unchanged
  reserve"), `test_concurrent_same_output_does_not_duplicate_work`, the 40 s smokes.
  Example failing runs: 39179407200 (main, `offline research (windows-latest, 3.11)`:
  `test_concurrent_same_output_does_not_duplicate_work`), 39185965707 (PR #45:
  `test_poll_exception_cancels_real_spawned_worker_and_proves_cleanup`). Each passed
  when all jobs were re-run on the same commit; there is no deterministic failure.
* Linux `offline (ubuntu-latest)` wall time for the *identical* suite ranged 7.5-14.3 min
  in 54 completed jobs, and six jobs were cancelled at the fixed 15 min cap (15.2-15.3 min).
  A 1.9x runner-speed spread against a ~13 min typical run leaves ~2 min of headroom.

## Per-phase measurements (this repo, quiet Windows 10 machine, Python 3.13.11)

`python tools/measure_ci_margin.py --repeats 5` (median seconds; headroom = 10 s budget / median):

| Phase | median | headroom |
|---|---:|---:|
| `python -c pass` start | 0.039 | 254x |
| `import quantlab.desktop_runtime` in a fresh interpreter | 0.160 | 62x |
| 120 fully-synced SQLite commits (the probe's commit block) | 0.309 | 32x |

Worker phases from `tools/bench_worker_latency.py` (docs/analysis/t14_p3_latency.md):
subprocess start 0.34 s, executor import 0.40 s, one isolated Walk-forward evaluation 0.49 s.

## Root cause

Every fixed budget has at least 20-250x headroom on a quiet machine, and the code paths
contain no sleeps longer than their polling interval, so no systematic algorithmic cost
explains the failures. The evidence points to **environmental stalls on shared
GitHub-hosted runners** (process creation/antivirus scanning on Windows, fsync latency
on SQLite commits, noisy neighbours): occasional multi-second stalls hit whichever
process-spawning test is running, and the suite wall time on Linux varies 1.9x. This
could not be proven further here because GitHub runner internals are not observable
from this machine; it is recorded in plan section 5.1 as pending external evidence.

On this machine the Paper diagnostics child exits immediately (`returncode` 1) and
`campaign.json.tmp` replace raises `PermissionError [WinError 5]` in several
unrelated tests: a local file-lock effect (antivirus/indexer) that is a different, local
phenomenon and is not claimed to explain the CI behaviour.

## What was and was not done

* Added the opt-in measurement tool `tools/measure_ci_margin.py` (+ cheap arithmetic test
  `tests/test_ci_margin_tool.py`, pinning the 10 s / 40 s reference budgets as unchanged),
  so the same per-phase numbers can be collected on a runner.
* No safe code fix exists for runner stalls without loosening a budget or removing process
  isolation, both forbidden. The remaining mitigation is reducing Linux suite wall time
  (for example sharding the Linux job like the Windows shards); that needs a workflow and
  exact-skip aggregation change and is deferred to a dedicated CI batch.

## Addendum (T16): a measured Linux-suite time sink

Per-test gaps in the `ui` job log (`unittest discover -s tests -v`, timestamps per line) showed
two gaps of 123 s and 137 s on Linux: `tests.test_desktop_pages.PageSnapshotTests` (first call of the
shared metrics capture) and the first test of a new T16 test class that called
`QApplication.setStyle('Fusion')`. `setStyle`/`setFont` on the application re-polish every live widget,
and earlier test modules leave many windows alive, so each call costs minutes on a software-rendering
runner (about 0.9 s on a quiet desktop). Fixes without touching any timeout: the T16 tests no longer call
`setStyle` and never show the window; `tools/ui_snapshot.capture` skips `setStyle` when the style is
already Fusion (the Linux default). The remaining measured Linux cost of the first capture should be
re-read from the next CI log (`tools/measure_ci_margin.py` and the per-line timestamps are the method).
