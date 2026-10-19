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
fixed desktop_strings catalog and ignore event message/error_type values.

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
