# M1 CI repair: unchanged-main host failure evidence

Baseline: origin/main `ba597b59d72cc5d95a9d260b7453b41cd89496bc`, detached worktree,
same provisioned Windows/Python3.13.11 venv/Qt6.12.0 and offscreen environment.
Complete discovery:3760 tests,1898.475 seconds,10 failures,27 errors,42 original skips.
There are36 distinct failure identities; a parametrized symlink error appears twice.
The unchanged-main checkout's tests, timeouts, safety guards, dependency locks
and skips were not modified for this reproduction.

- Symlink cases fail with Windows privilege error1314 on the unchanged main checkout.
- The venv redirector launches a second interpreter PID; existing identity/parent
  guards refuse that process. Native retained-handle/mutex prerequisites also fail
  unchanged. The named application mutex remained visible after fixture-guard
  closure (OpenMutex returned HANDLE3064, not a PID). Its owning process was not
  identified; that failed assertion itself can retain the handle for subsequent
  tests. No preexisting process was stopped.
- Four paper diagnostics reject the redirector ownership chain before database
  operations. The identical120-FULL delete/reopen case passes with the actual base
  interpreter (2.08s); the original guards and10-second budget remain unchanged.

The repaired branch logs are compared by complete result, full test identity and
exception/assertion evidence. A nonzero exit is not described as a passing suite.
Remote CI is separately verified; a local baseline failure is never used to waive
a new CI regression.

## Exact main failure identities

- `ERROR` `test_analysis_recovery.RecoveryLedgerTests.test_links_hardlinks_and_oversize_are_rejected`
- `ERROR` `test_automatic_backup.AutomaticBackupTests.test_managed_hardlink_and_success_symlink_are_rejected`
- `ERROR` `test_automatic_backup.AutomaticBackupTests.test_managed_links_rejected_despite_incomplete_directory_metadata`
- `ERROR` `test_automatic_backup.AutomaticBackupTests.test_unsafe_destinations_do_not_write_config`
- `ERROR` `test_chatgpt_auth.AuthTests.test_dpapi_rejects_dangling_links_and_junction_lstat_attributes`
- `ERROR` `test_chatgpt_auth.AuthTests.test_first_use_guard_rejects_prior_host_control_and_partial_vault_evidence`
- `ERROR` `test_downloads.DownloadTests.test_failure_preserves_latest_and_refuses_symlink`
- `ERROR` `test_market.MarketTests.test_cache_rejects_symlink`
- `ERROR` `test_market_history.HistoryBoundaryTests.test_cache_tamper_symlinks_and_bad_policy`
- `ERROR` `test_market_history.HistoryTests.test_cache_tamper_symlinks_and_bad_policy`
- `ERROR` `test_notice_collector.ZipCollectorTests.test_dangling_source_parent_fails`
- `ERROR` `test_notice_collector.ZipCollectorTests.test_destination_file_symlink_fails_preserves_target`
- `ERROR` `test_notice_collector.ZipCollectorTests.test_destination_parent_symlink_fails`
- `ERROR` `test_notice_collector.ZipCollectorTests.test_source_file_symlink_fails`
- `ERROR` `test_notice_collector.ZipCollectorTests.test_source_parent_symlink_fails`
- `ERROR` `test_qt_licenses.QtLicenseTests.test_destination_symlink_preserves_target`
- `ERROR` `test_qt_licenses.QtLicenseTests.test_payload_directory_symlink_fails_before_audit`
- `ERROR` `test_qt_licenses.QtLicenseTests.test_source_symlink_and_simulated_junction_fail`
- `ERROR` `test_reporting.ReportingTests.test_symlink_output_refused`
- `ERROR` `test_runtime_context_client_v2.RuntimeContextClientTests.test_failed_profile_target_retains_current_data_and_selector`
- `ERROR` `test_runtime_context_client_v2.RuntimeContextClientTests.test_owned_cleanup_handles_real_ipc_version_change_without_bypassing_cas`
- `ERROR` `test_runtime_context_client_v2.RuntimeContextClientTests.test_standard_disconnected_launch_without_profile_keeps_financial_facts_unknown`
- `ERROR` `test_runtime_context_client_v2.RuntimeContextClientTests.test_three_environments_use_real_ipc_and_never_mix_books_or_implicitly_connect`
- `ERROR` `test_test_group.ParallelResearchGroupTests.test_native_windows_natural_parent_exit_with_descendant_cannot_pass`
- `ERROR` `test_trading_acceptance_combinations.AcceptanceCombinationTests.test_e06_parent_os_kill_before_submit_and_after_remote_accept_preserves_unknown`
- `ERROR` `test_trading_runtime.IndependentEngineRuntimeTests.setUpClass`
- `FAIL` `test_desktop_runtime.WindowsRuntimeTests.test_installer_mutex_lifetime`
- `FAIL` `test_paper_diagnostics.ConnectionDiagnosticTests.test_external_observer_failure_stops_waiting_probe_and_cleans_owned_fixture`
- `FAIL` `test_paper_diagnostics.ConnectionDiagnosticTests.test_fixed_matrix_uses_full_commits_real_external_control_and_owned_cleanup`
- `FAIL` `test_paper_diagnostics.ConnectionDiagnosticTests.test_keyboard_interrupt_joins_probe_and_observer_before_removing_fixture`
- `FAIL` `test_paper_diagnostics.ConnectionDiagnosticTests.test_wrong_commit_count_cannot_be_certified`
- `FAIL` `test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_guard_survives_either_owned_process_exiting_first`
- `FAIL` `test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_ui_exception_releases_guard_without_engine_or_workspace`
- `FAIL` `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_gui_death_quiesces_before_test_only_durable_receipt`
- `FAIL` `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_after_gui_before_quiescence_never_publishes_receipt`
- `FAIL` `test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_before_gui_never_publishes_receipt`
