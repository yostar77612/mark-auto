# M2-0 first full-suite failure comparison

Policy source/baseline head: `97e2a8bd1c774fff9d90f9b5d973048efc112fd3`. Main baseline: `045313634a6fe4c33aeacfc972182d00e83cd58e`. Both logs have complete unittest footers:

- Main `.tmp-m2-main-full.log`: **3,888 tests, 1,968.015 seconds, FAILED (failures=10, errors=27, skipped=42)**.
- Policy `.tmp-m2-policy-full.log`: **3,888 tests, 2,245.634 seconds, FAILED (failures=11, errors=27, skipped=42)**.

Every policy ERROR/FAIL traceback and its exception chain was inspected: **38 occurrences, 37 distinct IDs**. Main has 37 occurrences/36 IDs. All 36 main IDs remain; policy adds exactly `test_smoke_timeout_diagnostics.SmokeTimeoutDiagnosticTests.test_failed_tree_cleanup_stops_readers_without_claiming_cleanup`. This first full policy run is not a pass, nor an exact baseline-only result. Root will queue an isolated complete retry after the active market full suite; preserve this first-run evidence and original assertions/timeouts.

## Existing failure comparison, beyond identities

All **37 common occurrences** have the same ordered traceback file/line/function locations after removing only the explicitly named checkout prefix. All **20 repository source files appearing in these traceback frames** are byte-equal between main and policy; their exact SHA-256 values are retained in the JSON. Raw tracebacks, headers, subtest identities, and original exception messages remain retained. No executable/fixture normalization, test exclusion or softened assertion was used.

| Category | Policy records | Actual comparison evidence and limit |
|---|---:|---|
| Symlink privilege | 20 errors / 19 IDs | Each fails constructing `Path.symlink_to`, at pathlib line789, with WinError1314; the same test/source line and exception family occur on main. The product's subsequent rejection assertion is not reached. Both named subtests of the duplicated ID are preserved. |
| Initial LOCAL runtime deadline | 5 errors | Four RuntimeContextClient cases fail their initial manager.open_context at `context_client.py:148`; IndependentEngineRuntime fails setUpClass at that exact guard. Both logs have the same complete stacks. Main's separate actual wrapper/session PID evidence explains that fixture, but these five policy tracebacks alone do not establish each child's health. Root owns exact policy-orphan observation/shutdown; this review sends no shutdown or process signal to those full-suite processes. |
| Native worker cleanup | 1 error | Both runs reach `test_test_group.py:402` TemporaryDirectory exit, then WinError32 for `research-workers-*/worker-0.log`. The exact lock holder is not established by the traceback. Do not relabel it as a proven DuplicateHandle error or import failure. |
| Crash-driver identity then cleanup | 1 error | Policy first asserts published PID371320 != retained Popen PID89244 at acceptance test line174; main first asserts306352 !=256312 at the same line. Both then fail fixture cleanup with WinError32 for simulated-exchange-v2.sqlite. The initial identity assertion is preserved despite the cleanup masking exception. |
| Named mutex visibility | 3 failures | Policy `test_installer_mutex_lifetime` sees OpenMutex HANDLE2892 after guard.close; main sees HANDLE2448. Both later installer cases reject an already visible named mutex at lines177/237. These are handles, not process IDs; owner attribution is unproven, and the first failed assertion can retain its own unclosed handle. |
| Paper diagnostic pre-checkpoint exit | 4 failures | Same assertion lines and exit1 before the expected observer/checkpoints. Policy diagnostic examples exit in ~0.24–0.31s and carry no probe phase/clock evidence; main ~0.22–0.24s. Same-source prior captured stderr supports the parent-PID ownership/venv redirector diagnosis, but neither complete run captured fresh child stderr. Preserve that confidence limit; don't claim each case freshly proved its internal exception. |
| Retained grandchild handle | 3 failures | Every policy and main stack first fails DuplicateHandle in `collect`→`_check`, with Errno6 `receive retained grandchild handle`, followed by the same cooperative-cleanup assertion. This is distinct from the native worker's WinError32-only case. Prior redirector/handle-table evidence supports the host explanation; it does not waive failed cleanup. |

## New first-run smoke failure

The additional failure is at `tests/test_smoke_timeout_diagnostics.py:307`: expected `[{'stage': 'cleanup_start'}]`, observed `[]`. Earlier assertions in that same unchanged case completed, so its collected artifact still reported cleanup_verified=false, cleanup_error_type=RuntimeSafetyError, and stopped reader threads. This was not an incorrect claim of successful cleanup or a policy-banner assertion.

Source sequence: the synthetic child must pass Windows Job Object admission, import standard modules, launch its sleeping child, write the PID file, then print/flush the diagnostic marker. The original deadline is one second. `SmokeOutputCapture` reads on background threads; timeout handling intentionally forces cleanup failure, snapshots the buffers, then stops readers. There is no explicit marker-ready handshake before that one-second clock. An unobserved marker can therefore reflect startup/child creation delay or delayed pipe reading; the full-run traceback does not distinguish those conditions. Its TemporaryDirectory artifact is no longer available after context exit. Do not invent full-run byte counts, worker counts, event timing, or CPU saturation evidence.

Focused, authorized diagnostic evidence on unchanged main sources (no source edits):

1. The original exact case ran **five times, all passed, 5.266 seconds**. Log `.tmp-m2-policy-new-failure-repro.log`. This shows the failure is not deterministic in isolation; it does not establish the complete policy run passed.
2. A separate controlled diagnostic inserted **1.25 seconds of child startup latency after admission**, preserving the original **one-second timeout and every assertion**. It reproduced exactly line307's missing-event failure on main. Its artifact had zero stderr bytes, cleanup_verified=false and RuntimeSafetyError, and no recorded worker because that deliberately delayed child had not reached its spawn/PID-file step. Artifact/log: `.tmp-m2-policy-new-failure-controlled-delay.json` / `.log`.
3. Exact-byte equality was confirmed for test_smoke_timeout_diagnostics.py, smoke_timeout_diagnostics.py, and job_process.py between the two checkouts. Respectively SHA-256: `f5d4b5e158692cb5a3ff517eb00ca6cdd173daa9b1537d4cac358727e7963eb1`, `4f3b15ca546bdc064bbbe6dcc3828571152de77aed7b75af9f463fc6b3559d78`, `cd13b142be43c03a08119934805463a5f50639913994e75896c663a74f703b35`.

Conclusion: the controlled run proves an existing sufficient deadline-before-marker failure condition. **It does not prove that artificial latency was the cause of the actual first full run.** Retain this as one new complete-run failure awaiting the coordinator's isolated full retry. No assertion, timeout, capture logic, product source, dependency, Windows permission or setting was changed. No further focused repetitions are needed or planned for this review.

## Output and cleanup boundaries

`.tmp-m2-policy-failure-review.json` preserves every exact occurrence, both raw traceback versions for common records, source lines, exception chains, comparison metadata, source hashes and the controlled-evidence limit. Footer-after-exit weakref cleanup also reports WinError32 for the test-owned `v2-runtime-j15ah9f2/isolated/market/klines.sqlite3`; this is retained as post-footer cleanup evidence, not silently counted as another unittest ID. Root owns normal authenticated shutdown of that exact fixture and its related process checks. This reviewer did not stop, kill, modify or delete full-suite/user processes or data.

Only root scratch review/diagnostic files were written. The policy checkout stayed unchanged. The narrow diagnostic's synthetic processes used their original owned cleanup; no broker client, key, account or order operation was involved. No remote CI outcome is claimed.

## Exact occurrence index

The following index lists all 38 occurrences; detailed raw evidence is in the JSON. `P` and `M` are original one-based source-log lines.

| Exact ID / subtest | P | M | Actual symptom |
|---|---:|---:|---|
| `test_analysis_recovery.RecoveryLedgerTests.test_links_hardlinks_and_oversize_are_rejected` | 3951 | 3951 | WinError1314 creating symlink |
| `test_automatic_backup.AutomaticBackupTests.test_managed_hardlink_and_success_symlink_are_rejected` | 3963 | 3963 | WinError1314 creating symlink |
| `test_automatic_backup.AutomaticBackupTests.test_managed_links_rejected_despite_incomplete_directory_metadata (name='markauto-5f25dde39cf3ae23-linked.zip', kind='symlink')` | 3975 | 3975 | WinError1314 creating symlink |
| `test_automatic_backup.AutomaticBackupTests.test_managed_links_rejected_despite_incomplete_directory_metadata (name='orphan.zip.tmp', kind='symlink')` | 3987 | 3987 | WinError1314 creating symlink |
| `test_automatic_backup.AutomaticBackupTests.test_unsafe_destinations_do_not_write_config` | 3999 | 3999 | WinError1314 creating symlink |
| `test_chatgpt_auth.AuthTests.test_dpapi_rejects_dangling_links_and_junction_lstat_attributes` | 4011 | 4011 | WinError1314 creating symlink |
| `test_chatgpt_auth.AuthTests.test_first_use_guard_rejects_prior_host_control_and_partial_vault_evidence` | 4023 | 4023 | WinError1314 creating symlink |
| `test_downloads.DownloadTests.test_failure_preserves_latest_and_refuses_symlink` | 4035 | 4035 | WinError1314 creating symlink |
| `test_market.MarketTests.test_cache_rejects_symlink` | 4047 | 4047 | WinError1314 creating symlink |
| `test_market_history.HistoryBoundaryTests.test_cache_tamper_symlinks_and_bad_policy` | 4059 | 4059 | WinError1314 creating symlink |
| `test_market_history.HistoryTests.test_cache_tamper_symlinks_and_bad_policy` | 4071 | 4071 | WinError1314 creating symlink |
| `test_notice_collector.ZipCollectorTests.test_dangling_source_parent_fails` | 4083 | 4083 | WinError1314 creating symlink |
| `test_notice_collector.ZipCollectorTests.test_destination_file_symlink_fails_preserves_target` | 4101 | 4101 | WinError1314 creating symlink |
| `test_notice_collector.ZipCollectorTests.test_destination_parent_symlink_fails` | 4119 | 4119 | WinError1314 creating symlink |
| `test_notice_collector.ZipCollectorTests.test_source_file_symlink_fails` | 4137 | 4137 | WinError1314 creating symlink |
| `test_notice_collector.ZipCollectorTests.test_source_parent_symlink_fails` | 4155 | 4155 | WinError1314 creating symlink |
| `test_qt_licenses.QtLicenseTests.test_destination_symlink_preserves_target` | 4173 | 4173 | WinError1314 creating symlink |
| `test_qt_licenses.QtLicenseTests.test_payload_directory_symlink_fails_before_audit` | 4185 | 4185 | WinError1314 creating symlink |
| `test_qt_licenses.QtLicenseTests.test_source_symlink_and_simulated_junction_fail` | 4197 | 4197 | WinError1314 creating symlink |
| `test_reporting.ReportingTests.test_symlink_output_refused` | 4209 | 4209 | WinError1314 creating symlink |
| `test_runtime_context_client_v2.RuntimeContextClientTests.test_failed_profile_target_retains_current_data_and_selector` | 4221 | 4221 | initial LOCAL startup deadline |
| `test_runtime_context_client_v2.RuntimeContextClientTests.test_owned_cleanup_handles_real_ipc_version_change_without_bypassing_cas` | 4236 | 4236 | initial LOCAL startup deadline |
| `test_runtime_context_client_v2.RuntimeContextClientTests.test_standard_disconnected_launch_without_profile_keeps_financial_facts_unknown` | 4248 | 4248 | initial LOCAL startup deadline |
| `test_runtime_context_client_v2.RuntimeContextClientTests.test_three_environments_use_real_ipc_and_never_mix_books_or_implicitly_connect` | 4263 | 4263 | initial LOCAL startup deadline |
| `test_test_group.ParallelResearchGroupTests.test_native_windows_natural_parent_exit_with_descendant_cannot_pass` | 4277 | 4277 | WinError32 worker-0.log cleanup |
| `test_trading_acceptance_combinations.AcceptanceCombinationTests.test_e06_parent_os_kill_before_submit_and_after_remote_accept_preserves_unknown` | 4311 | 4311 | PID mismatch then WinError32 SQLite cleanup |
| `test_trading_runtime.IndependentEngineRuntimeTests.setUpClass` | 4353 | 4353 | initial LOCAL startup deadline |
| `test_desktop_runtime.WindowsRuntimeTests.test_installer_mutex_lifetime` | 4364 | 4364 | named mutex remains visible |
| `test_paper_diagnostics.ConnectionDiagnosticTests.test_external_observer_failure_stops_waiting_probe_and_cleans_owned_fixture` | 4373 | 4373 | probe exit1 before expected checkpoint |
| `test_paper_diagnostics.ConnectionDiagnosticTests.test_fixed_matrix_uses_full_commits_real_external_control_and_owned_cleanup` | 4382 | 4382 | probe exit1 before expected checkpoint |
| `test_paper_diagnostics.ConnectionDiagnosticTests.test_keyboard_interrupt_joins_probe_and_observer_before_removing_fixture` | 4391 | 4391 | probe exit1 before expected checkpoint |
| `test_paper_diagnostics.ConnectionDiagnosticTests.test_wrong_commit_count_cannot_be_certified` | 4400 | 4400 | probe exit1 before expected checkpoint |
| `test_smoke_timeout_diagnostics.SmokeTimeoutDiagnosticTests.test_failed_tree_cleanup_stops_readers_without_claiming_cleanup` | 4409 | — | NEW: missing stderr cleanup_start marker |
| `test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_guard_survives_either_owned_process_exiting_first` | 4425 | 4409 | named mutex remains visible |
| `test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_ui_exception_releases_guard_without_engine_or_workspace` | 4434 | 4418 | named mutex remains visible |
| `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_gui_death_quiesces_before_test_only_durable_receipt` | 4443 | 4427 | DuplicateHandle Errno6 then cleanup assertion |
| `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_after_gui_before_quiescence_never_publishes_receipt` | 4488 | 4472 | DuplicateHandle Errno6 then cleanup assertion |
| `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_before_gui_never_publishes_receipt` | 4533 | 4517 | DuplicateHandle Errno6 then cleanup assertion |
