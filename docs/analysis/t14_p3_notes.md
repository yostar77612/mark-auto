# T14 part A — P3-02 and P3-12

TLS uses a shared standard-library builder in downloads and market_providers.
Only Windows ROOT-store entries with server-auth trust are loaded; the CA store
(including expired cross-signed intermediates) is never enumerated. Unsupported
or empty/unusable stores fall back to the platform's verified default context.
OpenSSL continues to enforce certificate validity and hostname verification.
provider.py remains on its default context because it is a G3 locked input.
No new cryptography dependency: offline tests inject ROOT/CA store entries and
verify selection/loading and secure context properties; they do not claim a real
certificate-chain handshake or live endpoint verification.

Worker errors gain a fixed stage code. UI campaign/backtest adapters mark data
loading and candidate/config/provider preparation. Backtest also marks engine
execution and report writing. The locked run_campaign call is one coarse
run_campaign stage: candidate generation, engine backtests, and internal result
writes cannot be distinguished without editing a locked file. CLI campaign uses
the same coarse stage; other CLI execution and UI operations use run_operation.
Preparation/recovery admission uses prepare_operation; final serialization and
publication use write_result. These are operation boundaries, not inferred
exception diagnoses. Payloads and exception attributes cannot select a stage.
Unexpected stage values become unknown. UI failure notifications use only the
fixed desktop_app.strings.catalog catalog and ignore event message/error_type values.

GitNexus was bound to C:/Users/Mark/Desktop/Mark auto. Its existing index is 18
commits behind HEAD. Refresh was attempted; sandbox CLI respawn failed EPERM.
Existing graph reports LOW for worker/HTTPS handler and UNKNOWN for callback
registries/default-argument transport. Direct source checks confirm executor
registry entries, transport defaults, timer bindings and test references.
Final detect_changes (scope all) reports CRITICAL catalog fan-out: 17 mapped
symbols and 51 flows, with no partial/truncated flag. The ui_text function body
is unchanged; the nearby new catalog/helper is mapped against the stale index.
New untracked modules are outside this graph report and were checked directly.

Verification: 35 focused tests passed, including 15 new tests (slowest 0.779 s).
Ruff check and format check passed for all 10 touched Python files. Quality gate
reported zero findings; new untracked product modules also passed its dependency
and core-import AST checks directly. Python 3.11 compiled 322 tracked/new Python
files using utf-8-sig. G3 files, saved_candidate_pool.py and the plan have empty
diffs. Full-suite/native endpoint checks are controller-owned and were not run.

## Part B — P3-10 / P3-11

Added opt-in stdlib benchmark harnesses for real spawned UI jobs / isolated
Walk-forward evaluation and 1,000/10,000-bar builtin backtests. Deferred only
backup-specific zipfile imports; unchanged worker isolation, timeouts, engine
sources, producer profiles, registry and goldens. The existing poll_jobs import
gained its required adjacent reason comment; no logic changed there.

Fresh runtime import median: 90.94 ms before, 83.14 ms after (N=5). Real worker
and isolated evaluation attempts fail at Windows Pipe CreateFile with sandbox
WinError 5 in both runs; their stage times remain unavailable. No overall worker
speedup is claimed. The measured-evaluation constant remains None and the
Walk-forward preview explicitly says the duration estimate is unknown. Zero or
invalid counts omit the duration wording. Estimate arithmetic is presentation
only and changes no admission, budgets, evidence or OOS rules.

Scale medians: 0.068885 s / 0.730551 s; dataset sizes: 242,030 / 2,411,032 bytes.
See t14_p3_latency.md, t14_p3_scale.md and t14_p3_storage_design.md for raw
samples, missing evidence, methodology, extrapolation limits and recommendation.
Keep JSON authoritative; consider disposable verified caches only after profiling,
and defer engine/storage migration to a new planned producer profile.

GitNexus refresh was attempted and failed with spawn EPERM. Existing index is
19 commits stale. Worker LOW; preview and poll_jobs UNKNOWN, with actual calls
confirmed in strategy.py, timer hookup and tests. BackupManager HIGH fan-out was
reported before editing; specific _create and _restore import-only edits have
LOW indexed impact through create/restore and UI backup handlers. No backup
validation/durability logic changed.

## Section 5 pending evidence

| Evidence | Owner | Status | Verification procedure |
|---|---|---|---|
| Real-network TLS on a machine with the expired ISRG Root X2 cross-sign | user | pending | On an affected Windows machine, retain the expired CA entry, run the part A TLS smoke against the real configured HTTPS endpoint with hostname/date verification enabled; record Windows/OpenSSL versions, trust-store classification and handshake outcome. Never disable verification or change provider.py. |
| GitHub-hosted runner timing/fsync | user | pending | Run both opt-in benchmark commands with the release interpreter on a GitHub-hosted Windows runner, N >= 5; archive JSON and importtime output, filesystem/runner details and job/journal fsync timing from the existing diagnostics. Complete worker start/compute/write-back evidence and rerun unchanged registry goldens/full suite outside sandbox. |
| Linux/Windows benchmark differences | user | pending | Run the same revision, dataset/config, interpreter version and N >= 5 on Linux and Windows; record median/min/max, process start method, filesystem and load. Compare spawn/evaluation and backtest stages separately. Update the estimate constant only from verified real isolated-evaluation samples, recording the machine and limits. |

Part B verification: 10 focused tests passed (exit 0, 0.994 s), including six
new estimate/import tests. Ruff check and format check passed for all nine
touched Python files. Quality gate: zero findings, exit 0; new untracked Python
files additionally passed explicit syntax/secret/research-boundary scans.
Python 3.11 compiled all 326 tracked/new Python files with utf-8-sig.
MainWindow is 397 lines; WalkForwardWizard is 220 lines. Locked sources,
producer profile, plan and operation golden have empty diffs. Full suite and
unchanged registry/golden execution were not run, per sandbox instructions.
Snapshot baseline unchanged: no default empty-workspace layout change.

Final GitNexus detect_changes(scope=all): eight mapped symbols, 41 affected
flows, CRITICAL risk; no partial/truncated flag. Catalog fan-out maps adjacent
new strings to ui_text in the stale index; its body is unchanged. MainWindow
change is an import-reason comment only; backup methods only gain local imports.
Untracked modules are not represented in this graph report and were checked
directly. No commit, branch switch, push or PR was performed.
