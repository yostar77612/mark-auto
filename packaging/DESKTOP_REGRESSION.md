# Complete desktop regression before freezing

The Windows installer workflow keeps its original 35-minute build limit and
adds a separate 35-minute complete regression job. The observed 3,531-case run
alone took 1,757.097 seconds before freeze or installer lifecycle checks; those
operations cannot reliably share the remaining build window. No case, native
smoke deadline, dependency preflight or installer lifecycle check is removed.

`build.ps1` with no phase arguments still runs the original complete
`python -m unittest discover -s tests -v` before freezing. `-RegressionOnly`
prepares the same private Python 3.13.16/SQLite runtime, locked dependencies,
native Qt/authentication preflights and runs the existing single-process
`tools/run_test_group.py --group all`. It produces no frozen package.

The designated CI regression job records the exact ordered discovery,
selection, starts/stops, outcomes, complete log bytes and clean source/runtime
identities before/after. Its immutable artifact name includes workflow run,
attempt and exact checkout SHA. The build job depends on successful regression,
downloads only that artifact in the current run and calls `-RegressionReceipt`.
External proof reuse is restricted to these jobs of this workflow, not a local
skip-tests switch or a supplied empty success JSON.

Before freeze, the consumer independently discovers the entire current suite
and verifies the same ordered IDs, completed starts/stops, source file hashes,
head, repository/workflow/event/run/attempt, interpreter identity, actual pinned
SQLite DLL hash and every locked dependency version/metadata/lock hash. It
rejects failures, fixture/discovery errors, missing/duplicate/reordered cases,
expected failures, changed/missing log bytes, stale/future receipts and unknown
skips. The explicit 33 Windows applicability skips in
`desktop_regression_skips.json` are the original platform/optional Streamlit
reasons; they must exactly match both fresh declarations and actual outcomes.
No new skip is introduced by this phase split.

Both full-history checkouts retain the exact legacy compatibility baseline
4095c3e9fdd2e91f1423d6d1bf76466834cdb417. Verified original proof/log/manifest are
retained under `dist/validation/desktop-regression/`, with a separate consumer
verification receipt, and travel with installer evidence. A missing or rejected
proof stops before license collection, PyInstaller and installer compilation.
Publication still requires the existing successful build/quality and exact-head
Quantlab gates; no workflow obtains extra credentials or write permissions.
