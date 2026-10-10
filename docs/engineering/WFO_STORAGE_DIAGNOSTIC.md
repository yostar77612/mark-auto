# Bounded synthetic WFO storage diagnostic

This tool is observation only. The isolated files must be overlaid into the matching checkout before native execution. It changes no application storage profile, test
workload, 30/40-second product gate, or 15-minute CI job cap. A COMPLETE report
means the diagnostic finished and passed its byte/count checks, not that PERSIST
is safe to ship or that any release gate passed. Local Linux results are not
native Windows evidence.

## First native measurement: fixed 180-second budget

Run once alongside the next necessary CI run, in a separate Windows diagnostic
job (job timeout 6 minutes; tool measurement timeout 180 seconds). Reuse the
existing checkout, selected Python 3.12, dependency setup and pinned SQLite
provisioning steps. Do not put it inside the already time-limited research job.
Use the same runner workspace volume as research tests, not an assumed faster
RAM disk. After provisioning into `build/sqlite-runtime`:

```
python tools/diagnose_wfo_storage.py --runtime-root build/sqlite-runtime --storage-root "$env:RUNNER_TEMP" --seconds 180 --fixture smoke --report dist/validation/wfo-storage.json
```

The report parent directory must already exist. Always upload the report even
on exit 2. Exit 2 / INCOMPLETE is missing evidence, never a pass. The supervisor
kills only its own child on the deadline, including if commit blocks. Its final
termination wait is bounded to 10 seconds; if that also expires, the report remains INCOMPLETE and explicitly marks termination unconfirmed. An interrupted disposable directory
can remain under the reported storage parent; it contains only synthetic data.
The runtime verifier refuses a different SQLite source ID, version, loaded
library path or binary hash before measurement. Windows uses the checked-in DLL
hash. For an authorized local Linux observation, additionally pass the SHA256
of the already verified private Linux library with `--library-sha256`.

Default: the entire 63-state synthetic smoke stream, in DELETE/PERSIST/PERSIST/
DELETE order, then one DELETE control with phase timers disabled. Each round has
63 individual INSERT OR REPLACE statements, 63 commits and 63 temporary-file
exports/replacements; modes differ only by journal_mode. Both explicitly verify
FULL (2) and normal locking. Each snapshot is compared with both its committed
SQLite payload and export; final integrity and reopened snapshot are checked.
This is a phase-timing-disabled correctness control, not an instrumentation-free product latency benchmark. Control has exactly the same workload and verification, only no per-phase timer
calls. Report execution/commit/export/verification totals, median and p95;
encoding is measured separately once before replay and is not included in disk
phase timings. It measures canonical hash+JSON encoding of already normalized
synthetic states, not product normalization or summary computation. Total round
time includes setup, checks and close, so do not label it commit time.

The optional complete 574-state stream uses `--fixture large`, also with a
hard 180-second default deadline (maximum permitted explicit deadline 180s).
Do not automatically schedule it or extend its deadline after an incomplete run.
The first short diagnostic determines whether a larger test is justified. Do not
cherry-pick a faster prefix or present one runner's results as a universal gain.
No cache_size/cache_spill changes are made.

## Fixture provenance and bounds

The 63-state stream is the existing synthetic desktop WFO smoke capture (22
isolated evaluations, 7,812,890 UTF-8 snapshot bytes). The 574-state stream was
captured from the unchanged generated
`SavedCandidatePoolTests.test_saved_journal_over_builtin_cap_is_readable_with_global_budget_consumed`
fixture (221 evaluations, fake worker, 63,764,608 snapshot bytes). No network,
model execution, user files, market download or real holdout inputs are used.
Snapshots contain synthetic configuration and results, not an imported dataset.

To avoid duplicating cumulative journals, the checked-in gzip files encode
structural JSON set/delete/append operations. Reconstruction performs the same
canonical encoding and checks every state_hash, total bytes, count and whole
stream SHA256 against the checked-in manifest. Archives are SHA256 pinned and
bounded to128KiB, decompressed operations to1MiB, individual reconstructed
payloads to16MiB and total stream to80MiB. Current compressed sizes are16,573
and63,041 bytes. Fixture edits require an explicit reviewed manifest update;
there is no CLI accepting arbitrary inputs or a dynamically trusted hash.

## Interpretation and next decision

ABBA limits order bias but does not establish repeatability across runners. The
control helps estimate timer overhead, while per-snapshot verification itself can
warm the page cache; both modes use identical checks. Compare phase totals and
individual paired rounds, not just the fastest time. A material repeatable
same-host commit/total benefit would justify a separate fault-parity proposal;
otherwise retain production DELETE/FULL. Even a promising result cannot replace
hot-journal/crash/backup/restore/reconciliation parity or unchanged full native
product gates. PERSIST leaves journal bytes on disk and has separate retention
implications. Never delete a retained journal manually.

## Native research evidence: 17db263a / run38045449459

Intervals below are differences between adjacent timestamped unittest completion
lines, so they include harness/buffering overhead and are not function profiles.
Python3.11 completed227 tests in653.687s (223pass,4skip). Python3.12 had208
completed tests before the15-minute job cancellation; setup was roughly46s on
both. The interrupted test was `test_explicit_gaps_preserved_in_plan_and_excluded_from_splits`,
with one captured stack inside `_save_state` commit. That sample is not proof
that all elapsed time was commit.

| Completed case | Win3.12 seconds | Win3.11 seconds |
|---|---:|---:|
| saved journal above builtin cap / global budget |109.561|38.915|
| actual OOS mutation leaves selection unchanged |54.289|61.427|
| source OOS/future prices do not choose pool/fold |41.265|25.312|
| actual core multifold backtests |39.856|27.554|
| saved execution all candidates, no model |39.353|12.830|
| actual final holdout mutation |31.914|25.350|
| genuine current fixture campaign into saved WFO |24.462|16.064|
| lower budget/cancel/restart/risk gates |23.050|13.432|
| same cosmetic names preserve candidate attribution |21.252|12.907|
| old ChatGPT profile / terminal snapshot |20.493|12.995|

Module intervals: saved_candidate_pool364.002s vs213.169s; walk_forward
223.185s (partial) vs229.319s (complete); research73.420s vs65.167s;
desktop_saved_candidate_pool60.206s vs41.123s; desktop_terminal51.395s vs44.277s.
The saved-pool tests also exercise campaign admission and holdout registry I/O.
Thus the ~587s spent in saved-pool plus partial-WFO groups on3.12 is only an
upper bound on potentially relevant work, not checkpoint time. There is no
measured decomposition showing WFO-only optimization can recover the missing
headroom; uncompleted tests mean total required headroom is unknown. In
particular one real-backtest case was faster on3.12, so a blanket Python3.12 CPU
regression is unsupported. The next diagnostic isolates journal mechanics;
if it is insufficient, separately instrument campaign/registry commit phases
before proposing changes there.

Earlier tiny native replay cursor measurements found PERSIST improvement of
~0% on3.11 and~7.2% total on3.12, with no commit-time benefit. They used a different
workload/runtime and do not support adopting PERSIST for WFO. The buffered local
Linux63-snapshot disk probe was milliseconds and is not predictive of Windows.
