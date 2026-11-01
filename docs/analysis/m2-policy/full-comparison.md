# policy-isolated: exact full-suite traceback review

Log SHA256: `e766c5ffa28256b2b1fdb600c38cacf242ac863df677021c10955fee74162e5c`

37 traceback occurrences; 36 distinct test identities.

Exact ordered frame match: 37/37.
Exception type-chain match: 37/37.
Referenced repository sources byte-identical to main: 19/19.

## test_analysis_recovery.RecoveryLedgerTests.test_links_hardlinks_and_oversize_are_rejected

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpwzrl62mi\\bootstrap\\control-v1\\analysis-recovery-v1.saved' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpwzrl62mi\\bootstrap\\control-v1\\analysis-recovery-v1.sqlite3'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp96wozt6h\\bootstrap\\control-v1\\analysis-recovery-v1.saved' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp96wozt6h\\bootstrap\\control-v1\\analysis-recovery-v1.sqlite3'
```

## test_automatic_backup.AutomaticBackupTests.test_managed_hardlink_and_success_symlink_are_rejected

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpda4huyyc\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpda4huyyc\\archives\\markauto-4d13b5edd26bedbb-20000-c0da951388e64947b185b08e63245cbd.zip'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpbfh736p8\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpbfh736p8\\archives\\markauto-ef7ceb0286d73a55-20000-d2ec56d0bf6546e98b89621329b6cc89.zip'
```

## test_automatic_backup.AutomaticBackupTests.test_managed_links_rejected_despite_incomplete_directory_metadata (name='markauto-a90f7b51af39f721-linked.zip', kind='symlink')

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpx0h8641o\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpx0h8641o\\archives\\markauto-a90f7b51af39f721-linked.zip'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp_sslwkji\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp_sslwkji\\archives\\markauto-3c492d00d987dc32-linked.zip'
```

## test_automatic_backup.AutomaticBackupTests.test_managed_links_rejected_despite_incomplete_directory_metadata (name='orphan.zip.tmp', kind='symlink')

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpx0h8641o\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpx0h8641o\\archives\\orphan.zip.tmp'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp_sslwkji\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp_sslwkji\\archives\\orphan.zip.tmp'
```

## test_automatic_backup.AutomaticBackupTests.test_unsafe_destinations_do_not_write_config

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpynkmnxzh\\workspace' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpynkmnxzh\\linked'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpwdbewqcj\\workspace' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpwdbewqcj\\linked'
```

## test_chatgpt_auth.AuthTests.test_dpapi_rejects_dangling_links_and_junction_lstat_attributes

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpls3ocem3\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpls3ocem3\\dangling'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp44g7kgfp\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp44g7kgfp\\dangling'
```

## test_chatgpt_auth.AuthTests.test_first_use_guard_rejects_prior_host_control_and_partial_vault_evidence

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpgpprd4ee\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpgpprd4ee\\chatgpt-oauth-host-v1.marker'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpz_s5yhyw\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpz_s5yhyw\\chatgpt-oauth-host-v1.marker'
```

## test_downloads.DownloadTests.test_failure_preserves_latest_and_refuses_symlink

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpcs3hv5p8\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpcs3hv5p8\\link'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpg9_tbcm2\\target' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpg9_tbcm2\\link'
```

## test_market.MarketTests.test_cache_rejects_symlink

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpdbjtq19c\\real' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpdbjtq19c\\link'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmps45icyyh\\real' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmps45icyyh\\link'
```

## test_market_history.HistoryBoundaryTests.test_cache_tamper_symlinks_and_bad_policy

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpuzyfpism\\input.csv' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpuzyfpism\\link'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp32xafai7\\input.csv' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp32xafai7\\link'
```

## test_market_history.HistoryTests.test_cache_tamper_symlinks_and_bad_policy

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmph71geuh7\\input.csv' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmph71geuh7\\link'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpq_xgx0hf\\input.csv' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpq_xgx0hf\\link'
```

## test_notice_collector.ZipCollectorTests.test_dangling_source_parent_fails

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphmhmr2tw\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphmhmr2tw\\packaging\\third_party'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp0u8kiaq7\\missing' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp0u8kiaq7\\packaging\\third_party'
```

## test_notice_collector.ZipCollectorTests.test_destination_file_symlink_fails_preserves_target

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpehy__eph\\outside-sentinel' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpehy__eph\\build\\licenses\\chatgpt-auth-native-notices.zip'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp5f4ws8cf\\outside-sentinel' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp5f4ws8cf\\build\\licenses\\chatgpt-auth-native-notices.zip'
```

## test_notice_collector.ZipCollectorTests.test_destination_parent_symlink_fails

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp9edu4umg\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp9edu4umg\\build'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpv29o_630\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpv29o_630\\build'
```

## test_notice_collector.ZipCollectorTests.test_source_file_symlink_fails

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpnu1vv8m3\\actual.zip' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpnu1vv8m3\\packaging\\third_party\\chatgpt-auth-native-notices.zip'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpa_ndv0p2\\actual.zip' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpa_ndv0p2\\packaging\\third_party\\chatgpt-auth-native-notices.zip'
```

## test_notice_collector.ZipCollectorTests.test_source_parent_symlink_fails

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpxw65kmhv\\actual-parent' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpxw65kmhv\\packaging\\third_party'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp8_f3yx14\\actual-parent' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp8_f3yx14\\packaging\\third_party'
```

## test_qt_licenses.QtLicenseTests.test_destination_symlink_preserves_target

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpiy3utrtm\\sentinel' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpiy3utrtm\\target\\GPL-3.0-only.txt'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp3anxwevc\\sentinel' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp3anxwevc\\target\\GPL-3.0-only.txt'
```

## test_qt_licenses.QtLicenseTests.test_payload_directory_symlink_fails_before_audit

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp3d4pwaw9\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp3d4pwaw9\\MarkAuto\\_internal\\linked-directory'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpboo5cq5w\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpboo5cq5w\\MarkAuto\\_internal\\linked-directory'
```

## test_qt_licenses.QtLicenseTests.test_source_symlink_and_simulated_junction_fail

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpr6rc6cm4\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpr6rc6cm4\\qt\\GPL-3.0-only.txt'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpcayglws8\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpcayglws8\\qt\\GPL-3.0-only.txt'
```

## test_reporting.ReportingTests.test_symlink_output_refused

Category: symlink_privilege_1314; frames=True; types=True

Current:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpvqufsw1h\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmpvqufsw1h\\f02a7f8a08fb7ade12ac4d65c74cd1bfb5581636f5735d05f0ad462fe1ae767b'
```
Main:
```text
OSError: [WinError 1314] 用戶端沒有這項特殊權限。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphxsgosda\\outside' -> 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphxsgosda\\f02a7f8a08fb7ade12ac4d65c74cd1bfb5581636f5735d05f0ad462fe1ae767b'
```

## test_runtime_context_client_v2.RuntimeContextClientTests.test_failed_profile_target_retains_current_data_and_selector

Category: runtime_startup_pid_guard; frames=True; types=True

Current:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```
Main:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```

## test_runtime_context_client_v2.RuntimeContextClientTests.test_owned_cleanup_handles_real_ipc_version_change_without_bypassing_cas

Category: runtime_startup_pid_guard; frames=True; types=True

Current:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```
Main:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```

## test_runtime_context_client_v2.RuntimeContextClientTests.test_standard_disconnected_launch_without_profile_keeps_financial_facts_unknown

Category: runtime_startup_pid_guard; frames=True; types=True

Current:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```
Main:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```

## test_runtime_context_client_v2.RuntimeContextClientTests.test_three_environments_use_real_ipc_and_never_mix_books_or_implicitly_connect

Category: runtime_startup_pid_guard; frames=True; types=True

Current:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```
Main:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```

## test_test_group.ParallelResearchGroupTests.test_native_windows_natural_parent_exit_with_descendant_cannot_pass

Category: native_worker_cleanup_file_lock; frames=True; types=True

Current:
```text
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphigf2qd_\\research-workers-dsgu04om\\worker-0.log'
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphigf2qd_\\research-workers-dsgu04om\\worker-0.log'
```
Main:
```text
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphbhkt4mg\\research-workers-e2kv7yzx\\worker-0.log'
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmphbhkt4mg\\research-workers-e2kv7yzx\\worker-0.log'
```

## test_trading_acceptance_combinations.AcceptanceCombinationTests.test_e06_parent_os_kill_before_submit_and_after_remote_accept_preserves_unknown

Category: crash_driver_pid_mismatch; frames=True; types=True

Current:
```text
AssertionError: 198848 != 98320
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\Desktop\\Mark auto\\.worktrees\\t\\v2-application-0exgv7cd\\platform\\simulated-exchange-v2.sqlite'
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\Desktop\\Mark auto\\.worktrees\\t\\v2-application-0exgv7cd\\platform\\simulated-exchange-v2.sqlite'
```
Main:
```text
AssertionError: 306352 != 256312
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\Desktop\\Mark auto\\.worktrees\\t\\v2-application-loztlf5y\\platform\\simulated-exchange-v2.sqlite'
PermissionError: [WinError 32] 程序無法存取檔案，因為檔案正由另一個程序使用。: 'C:\\Users\\Mark\\Desktop\\Mark auto\\.worktrees\\t\\v2-application-loztlf5y\\platform\\simulated-exchange-v2.sqlite'
```

## test_trading_runtime.IndependentEngineRuntimeTests.setUpClass

Category: runtime_startup_pid_guard; frames=True; types=True

Current:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```
Main:
```text
quantlab.trading.domain.validation.DomainError: startup_failed: runtime startup deadline; inspect the owned process before retry
```

## test_desktop_runtime.WindowsRuntimeTests.test_installer_mutex_lifetime

Category: named_mutex_visibility; frames=True; types=True

Current:
```text
AssertionError: 3208 is not false
```
Main:
```text
AssertionError: 2448 is not false
```

## test_paper_diagnostics.ConnectionDiagnosticTests.test_external_observer_failure_stops_waiting_probe_and_cleans_owned_fixture

Category: paper_probe_parent_pid_guard; frames=True; types=True

Current:
```text
AssertionError: 'error_type' not found in {'profile': 'persist-step', 'complete': False, 'workers_stopped': True, 'returncode': 1, 'controller_milestones': {'owner_file_written': 0.00208020000718534, 'probe_launch_requested': 0.002404300030320883, 'probe_launch_returned': 0.01233600004343316, 'probe_exit_observed': 0.39061729999957606, 'process_cleanup_started': 0.3906188000109978, 'process_cleanup_finished': 0.3906441000290215}, 'fixture_root': 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmps1p8mrzx\\paper-connection-probe-xivzse7k', 'children': [{'pid': 189668, 'returncode': 1}], 'observer_actions_completed': [], 'fixture_removed': True, 'seconds': 0.3921258000191301} : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.3921258000191301, 'observer_actions_completed': [], 'phase': None, 'commits_completed': None, 'cursor_commit_calls': None, 'probe_error_type': None, 'probe_seconds': None, 'child_exits': [{'role': 'probe', 'returncode': 1}]}
```
Main:
```text
AssertionError: 'error_type' not found in {'profile': 'persist-step', 'complete': False, 'workers_stopped': True, 'returncode': 1, 'controller_milestones': {'owner_file_written': 0.0017458000220358372, 'probe_launch_requested': 0.0020414000027813017, 'probe_launch_returned': 0.013368099986109883, 'probe_exit_observed': 0.24260040000081062, 'process_cleanup_started': 0.2426022000145167, 'process_cleanup_finished': 0.24262120004277676}, 'fixture_root': 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp0v5h0qsy\\paper-connection-probe-3t2_wyry', 'children': [{'pid': 140164, 'returncode': 1}], 'observer_actions_completed': [], 'fixture_removed': True, 'seconds': 0.24330880003981292} : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.24330880003981292, 'observer_actions_completed': [], 'phase': None, 'commits_completed': None, 'cursor_commit_calls': None, 'probe_error_type': None, 'probe_seconds': None, 'child_exits': [{'role': 'probe', 'returncode': 1}]}
```

## test_paper_diagnostics.ConnectionDiagnosticTests.test_fixed_matrix_uses_full_commits_real_external_control_and_owned_cleanup

Category: paper_probe_parent_pid_guard; frames=True; types=True

Current:
```text
AssertionError: 1 != 0
```
Main:
```text
AssertionError: 1 != 0
```

## test_paper_diagnostics.ConnectionDiagnosticTests.test_keyboard_interrupt_joins_probe_and_observer_before_removing_fixture

Category: paper_probe_parent_pid_guard; frames=True; types=True

Current:
```text
AssertionError: 'error_type' not found in {'profile': 'persist-step', 'complete': False, 'workers_stopped': True, 'returncode': 1, 'controller_milestones': {'owner_file_written': 0.001372799975797534, 'probe_launch_requested': 0.0016624999698251486, 'probe_launch_returned': 0.009295900003053248, 'probe_exit_observed': 0.21734380000270903, 'process_cleanup_started': 0.21734559995820746, 'process_cleanup_finished': 0.2173670000047423}, 'fixture_root': 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp8g1z_s5t\\paper-connection-probe-ny2hf6zj', 'children': [{'pid': 28352, 'returncode': 1}], 'observer_actions_completed': [], 'fixture_removed': True, 'seconds': 0.21819359995424747} : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.21819359995424747, 'child_exits': [{'pid': 28352, 'returncode': 1}], 'checkpoint_semantics': 'last completed progress record, not deadline state; blocked native call/report write may leave it stale', 'controller_milestone_semantics': 'seconds from controller entry; first output is detection time', 'controller_milestones': {'owner_file_written': 0.001372799975797534, 'probe_launch_requested': 0.0016624999698251486, 'probe_launch_returned': 0.009295900003053248, 'probe_exit_observed': 0.21734380000270903, 'process_cleanup_started': 0.21734559995820746, 'process_cleanup_finished': 0.2173670000047423}, 'controller_observation_failed': False, 'probe_clock_semantics': {'elapsed_seconds': 'since Timings creation after ownership and path setup', 'pre_timing_seconds': 'probe function entry through setup before Timings creation', 'probe_entry_seconds': 'since probe function entry, excluding imports', 'process_cpu_seconds': 'cumulative process CPU, including startup and imports'}, 'probe_clocks': {}, 'checkpoint_timings': {}, 'checkpoint_last_completed': {}, 'checkpoint_progress': {}, 'iteration_sample_semantics': 'total completed iteration wall/CPU costs; excludes checkpoint publication', 'checkpoint_active': []}
```
Main:
```text
AssertionError: 'error_type' not found in {'profile': 'persist-step', 'complete': False, 'workers_stopped': True, 'returncode': 1, 'controller_milestones': {'owner_file_written': 0.0016071999561972916, 'probe_launch_requested': 0.0019561999943107367, 'probe_launch_returned': 0.009327000007033348, 'probe_exit_observed': 0.2182537000044249, 'process_cleanup_started': 0.21825549995992333, 'process_cleanup_finished': 0.21827499999199063}, 'fixture_root': 'C:\\Users\\Mark\\AppData\\Local\\Temp\\tmp0r0r4fly\\paper-connection-probe-imk6rmi_', 'children': [{'pid': 30968, 'returncode': 1}], 'observer_actions_completed': [], 'fixture_removed': True, 'seconds': 0.21897049999097362} : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.21897049999097362, 'child_exits': [{'pid': 30968, 'returncode': 1}], 'checkpoint_semantics': 'last completed progress record, not deadline state; blocked native call/report write may leave it stale', 'controller_milestone_semantics': 'seconds from controller entry; first output is detection time', 'controller_milestones': {'owner_file_written': 0.0016071999561972916, 'probe_launch_requested': 0.0019561999943107367, 'probe_launch_returned': 0.009327000007033348, 'probe_exit_observed': 0.2182537000044249, 'process_cleanup_started': 0.21825549995992333, 'process_cleanup_finished': 0.21827499999199063}, 'controller_observation_failed': False, 'probe_clock_semantics': {'elapsed_seconds': 'since Timings creation after ownership and path setup', 'pre_timing_seconds': 'probe function entry through setup before Timings creation', 'probe_entry_seconds': 'since probe function entry, excluding imports', 'process_cpu_seconds': 'cumulative process CPU, including startup and imports'}, 'probe_clocks': {}, 'checkpoint_timings': {}, 'checkpoint_last_completed': {}, 'checkpoint_progress': {}, 'iteration_sample_semantics': 'total completed iteration wall/CPU costs; excludes checkpoint publication', 'checkpoint_active': []}
```

## test_paper_diagnostics.ConnectionDiagnosticTests.test_wrong_commit_count_cannot_be_certified

Category: paper_probe_parent_pid_guard; frames=True; types=True

Current:
```text
AssertionError: 1 != 0 : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.21728709997842088, 'phase': None, 'commits_completed': None, 'cursor_commit_calls': None, 'probe_error_type': None, 'probe_seconds': None, 'checkpoint_semantics': 'last completed progress record, not deadline state; blocked native call/report write may leave it stale', 'controller_milestone_semantics': 'seconds from controller entry; first output is detection time', 'controller_milestones': {'owner_file_written': 0.0017420999938622117, 'probe_launch_requested': 0.0020311999833211303, 'probe_launch_returned': 0.008548300014808774, 'probe_exit_observed': 0.21649959997739643, 'process_cleanup_started': 0.21650139999110252, 'process_cleanup_finished': 0.21652189997257665}, 'controller_observation_failed': False, 'probe_clock_semantics': {'elapsed_seconds': 'since Timings creation after ownership and path setup', 'pre_timing_seconds': 'probe function entry through setup before Timings creation', 'probe_entry_seconds': 'since probe function entry, excluding imports', 'process_cpu_seconds': 'cumulative process CPU, including startup and imports'}, 'probe_clocks': {}, 'checkpoint_timings': {}, 'checkpoint_last_completed': {}, 'checkpoint_progress': {}, 'iteration_sample_semantics': 'total completed iteration wall/CPU costs; excludes checkpoint publication', 'checkpoint_active': []}
```
Main:
```text
AssertionError: 1 != 0 : {'returncode': 1, 'timed_out': None, 'error_type': None, 'cleanup_error_type': None, 'workers_stopped': True, 'fixture_removed': True, 'seconds': 0.21788070001639426, 'phase': None, 'commits_completed': None, 'cursor_commit_calls': None, 'probe_error_type': None, 'probe_seconds': None, 'checkpoint_semantics': 'last completed progress record, not deadline state; blocked native call/report write may leave it stale', 'controller_milestone_semantics': 'seconds from controller entry; first output is detection time', 'controller_milestones': {'owner_file_written': 0.001455899968277663, 'probe_launch_requested': 0.001686599978711456, 'probe_launch_returned': 0.009452099970076233, 'probe_exit_observed': 0.21708799997577444, 'process_cleanup_started': 0.21708969998871908, 'process_cleanup_finished': 0.2171097999671474}, 'controller_observation_failed': False, 'probe_clock_semantics': {'elapsed_seconds': 'since Timings creation after ownership and path setup', 'pre_timing_seconds': 'probe function entry through setup before Timings creation', 'probe_entry_seconds': 'since probe function entry, excluding imports', 'process_cpu_seconds': 'cumulative process CPU, including startup and imports'}, 'probe_clocks': {}, 'checkpoint_timings': {}, 'checkpoint_last_completed': {}, 'checkpoint_progress': {}, 'iteration_sample_semantics': 'total completed iteration wall/CPU costs; excludes checkpoint publication', 'checkpoint_active': []}
```

## test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_guard_survives_either_owned_process_exiting_first

Category: named_mutex_visibility; frames=True; types=True

Current:
```text
AssertionError: True is not false : A preexisting app lifetime must not be disturbed
```
Main:
```text
AssertionError: True is not false : A preexisting app lifetime must not be disturbed
```

## test_trading_installer_guard.WindowsInstallerGuardLifetimeTests.test_native_ui_exception_releases_guard_without_engine_or_workspace

Category: named_mutex_visibility; frames=True; types=True

Current:
```text
AssertionError: True is not false : A preexisting app lifetime must not be disturbed
```
Main:
```text
AssertionError: True is not false : A preexisting app lifetime must not be disturbed
```

## test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_gui_death_quiesces_before_test_only_durable_receipt

Category: retained_grandchild_handle_invalid; frames=True; types=True

Current:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```
Main:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```

## test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_after_gui_before_quiescence_never_publishes_receipt

Category: retained_grandchild_handle_invalid; frames=True; types=True

Current:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```
Main:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```

## test_windows_recovery_feasibility.WindowsRecoveryFeasibilityTests.test_helper_death_before_gui_never_publishes_receipt

Category: retained_grandchild_handle_invalid; frames=True; types=True

Current:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```
Main:
```text
OSError: [Errno 6] receive retained grandchild handle
AssertionError: ['cleanup-request: [Errno 6] receive retained grandchild handle', 'helper did not confirm cooperative cleanup'] is not false : fixture cleanup failed: cleanup-request: [Errno 6] receive retained grandchild handle; helper did not confirm cooperative cleanup
```
All37 traceback blocks match main's ordered file/line/function frames and
exception-type chains; all19 referenced repository sources are byte-identical.
The coordinator also checked the actual exception messages and causal chains:

| Occurrences | Final retry evidence |
| ---: | --- |
| 20 | WinError1314 while creating the synthetic symlink, before product rejection assertions;19 IDs, with both archive-name and orphan-name subtests retained. |
| 5 | The same initial LOCAL `ensure_engine` deadline:four context-client cases and the IndependentEngineRuntime class setup. |
| 1 | Native worker cleanup raises WinError32 for worker-0.log; exact holder is still unproven. |
| 1 | E06 first reports actual198848 versus retained98320, then WinError32 on simulated-exchange-v2.sqlite; same primary/secondary families and frames as main. |
| 3 | Named mutex remains visible; HANDLE3208 is not a PID. The later installer cases reject a preexisting lifetime before creating their native fixtures. |
| 4 | Paper probes exit1 before checkpoints; cleanup is recorded and the same unchanged-source prior parent-PID diagnosis applies, without claiming fresh child-stderr evidence. |
| 3 | Retained-grandchild DuplicateHandle Errno6 and unconfirmed cooperative cleanup, matching main. No already-signaled variant occurs in this retry. |

Temporary paths, generated archive IDs, process/handle numbers and elapsed
measurements differ as expected between runs. Matching normalizes only the
generated16-hex archive component in the subtest label. Full raw logs remain
unchanged. One earlier comparison-summary field reused the sibling subtest's
exception text; it was corrected from the already retained, correctly matched
raw traceback. Both real subtests raise1314, and this correction changes no
test identity, frame/type result, source or verdict.

The final log's SHA256 is
`e766c5ffa28256b2b1fdb600c38cacf242ac863df677021c10955fee74162e5c`.
The original complete main log's SHA256 remains
`9de08cc417a5927ce1b0c9fc868a2bfc1fef06fb07032892a969ae22b27f5fc3`.
The previously additional smoke cleanup-marker case now explicitly reports
`ok` in this complete run; its original assertion and1s deadline are unchanged.

After the full runner224972 exited, fresh process inspection revalidated only
the disposable class fixture:wrapper155812/native268268, their parent chain,
creation times and exact `v2-runtime-os87smf1/isolated` root. Its authenticated
LOCAL snapshot was WAITING_RECONCILIATION/version1. Normal SHUTDOWN_ENGINE was
accepted and returned CLOSED/version2; both exact processes were then confirmed
gone. No forceful termination, user application control or data deletion was
used. This verifies that one fixture's later normal cleanup, not a passing
startup test or the individual health of the other four failed launches.

The owner-installed application remains outside this cleanup. The result is
the same nonzero host baseline, not an all-passing local suite. Source PR128's
remote35/35 result and final documentation-head CI are separate checks.
