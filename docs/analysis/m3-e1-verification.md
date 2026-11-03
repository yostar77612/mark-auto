# M3 prospective E1 verification record

Date: 2026-11-03. Scope: synthetic/mock engineering verification only.
No real user OOS data or results were accessed, no real OOS evaluation or official
market-data request was run, and no real broker/account/order/LIVE action occurred.

## Implementation and review

The host-only E1 producer/reader and ordinary campaign exposure accounting are
specified in [ADR 0007](../adr/0007-prospective-e1-qualification.md) and the
[host protocol](../design/m3-e1-host-protocol.md). Independent review identified
and verified fixes for future-date relabeling, reservation commit timing, redirect
admission, capture/evaluation concurrency, stale-source history and acquisition
before close. No remaining critical blocker was identified within the explicitly
trusted-registry scope. The reader checks consistency, not hostile authority
rewriting, and does not select captured payload columns.

## Single full-suite attempt

Command: `python tools/run_test_group.py --group all --manifest <report>`.
Runtime: isolated Linux Python 3.12.14, SQLite 3.53.1, PySide6 Essentials 6.12.0,
and repository hash-locked desktop authentication dependencies. This is not a
Windows installer run. The run finished in 1,379.018 seconds and was **not green**.

- Discovered/selected: 5,996 / 5,996, zero discovery errors.
- Started/stopped: 5,984 / 5,984. Twelve cases were blocked by class setup.
- Outcome records: 32 failures, 20 errors, 53 existing skips. These include
  subtests and cleanup duplicates, not 52 distinct failing cases.
- Full per-case manifest retained unchanged, SHA-256:
  `895de93542ada9caed213fd1ad43128df5b43547ef25c6e619045d72942bf47c`.
- No second full suite was run. No assertion, deadline or applicability guard was
  weakened, and no new skip was introduced.

The full run exposed ADR metadata/safety wording and two exact-current-source
assertions (the G3 research blob and desktop market smoke). Those were corrected
without removing their checks. All 30 G3 entries remain pinned to exact approved
blobs; only the explicitly authorized research source moves from the old base.
All 30 historical immutable producer literal blocks remain byte-identical.
Application source bytes on the final publication branch match the full-run
application bytes; only documentation and exact-source assertions changed later.

Other full-run failures remain bounded and visible:

- Two PowerShell-dependent tests could not launch `pwsh`, unavailable on this host.
- Four optional broker-packaging tests lacked `packaging.requirements`; installing
  packaging 25.0 resolved all ten tests in that module.
- Local IPC/engine lifecycle cases encountered sandbox `PermissionError` during
  socket creation. A separately approved targeted retry still could not create
  those sockets. They remain unverified here, not converted into passing/skipped
  cases; CI or an appropriate native host must complete them.
- Existing skips cover native Windows/PowerShell behavior and the absent optional
  Streamlit UI. No complete UI or Windows acceptance claim is made.

## Targeted results after repairs

- Final sanitized tree: 81 tests ran, zero failures/errors, one existing
  PowerShell-parser skip. Modules cover E1 qualification/boundaries, campaign
  exposure, candidate catalog, signal identity, ADR contracts and packaging.
- ADR, signal identity and actual synthetic desktop market-smoke recheck:
  18 tests passed. Existing seven smoke steps, no-network claims and settings
  preservation remain asserted.
- Optional broker packaging: 10 tests passed after dependency installation.
- Earlier focused campaign, saved-pool, historical profile, research and WF checks
  passed. The full attempt preserves their exact per-case outcomes.
- Ruff, format, compile, static quality, repository layers, trading architecture,
  mechanical baseline checks and Python 3.11 grammar checks passed. A Python 3.11
  runtime was unavailable, so grammar checks are not runtime certification.

## Cases blocked by class setup

- `test_trading_runtime.IndependentEngineRuntimeTests.test_deep_engine_root_uses_private_native_transport_and_cleans_it`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_engine_is_independent_native_local_process_and_second_client_reuses_it`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_expired_deadline_future_deadline_and_foreign_account_rejected`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_float_or_nonfinite_money_cannot_cross_wire_boundary`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_malformed_utf8_json_duplicate_fields_and_unknown_schema_are_rejected`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_oversize_message_is_closed_or_rejected_and_engine_stays_alive`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_second_engine_process_cannot_steal_active_owner`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_shutdown_separate_engine_releases_all_owned_handles`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_state_version_conflict_does_not_execute_command`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_ui_client_process_can_close_without_shutting_down_engine`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_unknown_wire_fields_and_protocol_schema_cannot_be_ignored`
- `test_trading_runtime.IndependentEngineRuntimeTests.test_wrong_hmac_key_is_rejected_without_crashing_engine`

## Required integration checks

Default catalog behavior stays unavailable without explicit authoritative registry
composition. Desktop actions and E2 execution-data admission are separate work.
Combining the independent stock and E1 branches requires one new combined exact
producer profile, explicit OOS-plus-holdout semantics for that profile, and ADR
number reconciliation. Neither standalone profile can be relabeled as the
combined producer. Formal CI must verify the final integrated tree; this report
does not authorize merge, release, LIVE operation or real-data evaluation.
