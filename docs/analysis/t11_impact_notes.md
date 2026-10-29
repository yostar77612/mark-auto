# T11 part A impact analysis

Task override: GitNexus is unavailable in this sandbox. Used AST imports (including local imports), direct source reads, and repository/test caller searches. No commit is requested.

Risk: HIGH for worker dispatch, durable I/O, recovery admission and analysis plan validation. These serve spawn workers, backup/restore, one-call analysis and recovery proofs. The change retains the operation grammar, private worker positional ABI, admission order, error strings and existing validation bodies.

## quantlab/desktop_runtime.py :: RuntimeSafetyError

`quantlab/analysis_recovery_windows.py`, `quantlab/automatic_backup.py`, `quantlab/desktop_errors.py`, `quantlab/desktop_runtime.py`, `tests/smoke_timeout_diagnostics.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_automatic_backup.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_automatic_backup.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_runtime.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_smoke_isolation.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_ui_p0_correctness.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_log_table.py`, `tests/test_native_workspace_guard_packaging.py`, `tests/test_product_ai_boundary.py`, `tests/test_restart_availability_contract.py`, `tests/test_smoke_timeout_diagnostics.py`, `tests/test_workspace_wal_guard.py`, `tests/windows_recovery_diagnostics.py`

## quantlab/desktop_runtime.py :: atomic_write

`desktop.py`, `quantlab/assistant/adapters/chatgpt/auth.py`, `quantlab/analysis_recovery.py`, `quantlab/automatic_backup.py`, `quantlab/desktop_runtime.py`, `tests/test_automatic_backup.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_paper_replay_storage.py`, `tests/test_windows_recovery_feasibility.py`, `tests/test_workspace_wal_guard.py`

## quantlab/desktop_runtime.py :: _sync_directory

`quantlab/analysis_recovery.py`, `quantlab/desktop_runtime.py`

## quantlab/desktop_runtime.py :: _durable_replace

`quantlab/desktop_runtime.py`, `tests/test_desktop_runtime.py`

## quantlab/desktop_runtime.py :: validate_analysis_request

`desktop_app/features/compare/compare.py`, `desktop_app/shell/main_window.py`, `quantlab/analysis_recovery.py`, `quantlab/desktop_runtime.py`, `tests/test_desktop_analysis.py`

## quantlab/desktop_runtime.py :: _job_worker

`quantlab/desktop_runtime.py`, `tests/generic_smoke_phase_diagnostics.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/smoke_timeout_diagnostics.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_generic_smoke_phase_diagnostics.py`, `tests/test_paper_replay_timeout_diagnostics.py`, `tests/test_restart_availability_contract.py`, `tests/test_smoke_timeout_diagnostics.py`, `tools/diagnose_paper_replay.py`

## quantlab/desktop_runtime.py :: JobManager

`desktop.py`, `quantlab/analysis_recovery_windows.py`, `quantlab/desktop_runtime.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/smoke_timeout_diagnostics.py`, `tests/t10_fixture.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_candidate_presentation.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_automatic_backup.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_expiries.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_runtime.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_theme.py`, `tests/test_desktop_ui.py`, `tests/test_desktop_ui_p0_correctness.py`, `tests/test_desktop_ui_polish_a.py`, `tests/test_desktop_ui_polish_b.py`, `tests/test_desktop_ui_recovery.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_smoke.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_market_history_ui.py`, `tests/test_product_ai_boundary.py`, `tests/test_restart_availability_contract.py`, `tests/test_settings_sections.py`, `tests/test_smoke_timeout_diagnostics.py`, `tests/test_t9_expiry_inputs.py`, `tests/test_t9_onboarding.py`, `tests/test_workspace_wal_guard.py`, `tools/diagnose_paper_replay.py`, `tools/ui_snapshot.py`

## quantlab/walk_forward.py :: _bounded_number

`quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`

## quantlab/walk_forward.py :: _exact_number

`quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`

## quantlab/walk_forward.py :: _bounded_value

`quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`

## quantlab/__main__.py :: config_from_json

`desktop_app/components/forms.py`, `desktop_app/features/settings/settings.py`, `desktop_app/features/strategy/strategy.py`, `desktop_app/shell/main_window.py`, `quantlab/__main__.py`, `quantlab/reporting.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`, `research_app.py`, `tests/test_desktop_expiries.py`, `tests/test_desktop_forms.py`, `tests/test_desktop_market_smoke.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_saved_candidate_pool.py`, `tests/test_t9_expiry_inputs.py`, `tests/test_walk_forward.py`, `tools/validate_real_ai.py`

## quantlab/research_analysis.py :: _fail

`quantlab/assistant/adapters/chatgpt/provider.py`, `quantlab/analysis_recovery.py`, `quantlab/chart_data.py`, `quantlab/market_history.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`

## quantlab/research_analysis.py :: _keys

`quantlab/assistant/adapters/chatgpt/auth.py`, `quantlab/analysis_recovery.py`, `quantlab/research.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`

## quantlab/research_analysis.py :: _hash

`desktop_app/components/result_widgets.py`, `desktop_app/components/formatting.py`, `quantlab/analysis_recovery.py`, `quantlab/market_history.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`, `tests/test_analysis_recovery.py`, `tests/test_market_history.py`

## quantlab/research_analysis.py :: _bounded

`quantlab/research_analysis.py`

## quantlab/research_analysis.py :: _number

`desktop_app/components/charts.py`, `quantlab/assistant/adapters/chatgpt/auth.py`, `desktop_app/strings/catalog.py`, `quantlab/indicators.py`, `quantlab/research.py`, `quantlab/research_analysis.py`, `quantlab/strategies.py`, `tests/windows_recovery_diagnostics.py`

## quantlab/research_analysis.py :: validate_analysis_context

`quantlab/assistant/adapters/chatgpt/provider.py`, `quantlab/research_analysis.py`, `tests/test_research_analysis.py`

## quantlab/research_analysis.py :: _validate_packet

`quantlab/research_analysis.py`

## quantlab/research_analysis.py :: validate_analysis_response

`quantlab/assistant/adapters/chatgpt/provider.py`, `desktop_app/shell/main_window.py`, `quantlab/research_analysis.py`, `tests/test_research_analysis.py`

## quantlab/research_analysis.py :: make_analysis_plan

`desktop_app/smoke/recovery.py`, `desktop_app/shell/main_window.py`, `quantlab/research_analysis.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_research_analysis.py`, `tests/test_restart_availability_contract.py`

## quantlab/research_analysis.py :: validate_analysis_plan

`quantlab/assistant/adapters/chatgpt/provider.py`, `desktop_app/shell/main_window.py`, `quantlab/analysis_recovery.py`, `quantlab/research_analysis.py`, `tests/test_recovery_frozen_smoke.py`, `tests/test_research_analysis.py`

## quantlab/research_analysis.py :: expected_provider_descriptor

`quantlab/analysis_recovery.py`, `quantlab/research_analysis.py`, `tests/test_analysis_recovery.py`

## quantlab/research_analysis.py :: analysis_request

`quantlab/analysis_recovery.py`, `quantlab/research_analysis.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_research_analysis.py`, `tests/test_restart_availability_contract.py`

## desktop_app/shell/main_window.py :: research_controls

`desktop_app/components/formatting.py`, `desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `tests/test_desktop_ui.py`, `tests/test_workspace_wal_guard.py`

## desktop_app/shell/main_window.py :: _dataset

`desktop_app/features/settings/settings.py`, `desktop_app/components/formatting.py`, `desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `quantlab/data.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_workspace_wal_guard.py`, `tools/validate_official_history.py`

## desktop_app/shell/main_window.py :: execute_ui_operation

`desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `quantlab/desktop_runtime.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_history_smoke.py`, `tests/test_desktop_market_integration.py`, `tests/test_desktop_paper_exports.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_ui.py`, `tests/test_desktop_walk_forward.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_market_history_ui.py`, `tests/test_product_ai_boundary.py`, `tests/test_quality_gate.py`, `tests/test_t9_onboarding.py`, `tests/test_t9_repair.py`, `tests/test_ui_operations_registry.py`, `tests/test_wf_wizard.py`, `tests/test_workspace_wal_guard.py`

## tools/quality_gate.py :: scan

`quantlab/assistant/adapters/chatgpt/provider.py`, `tests/test_automatic_backup.py`, `tests/test_no_hardcoded_ui_text.py`, `tests/test_quality_gate.py`, `tools/quality_gate.py`, `archives/legacy_autotrading/trader/utils/database/redis.py`, `archives/legacy_autotrading/trader/utils/options.py`

## tools/quality_gate.py :: python_findings

`tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_walk_forward.py`, `tests/test_product_ai_boundary.py`, `tests/test_quality_gate.py`, `tools/quality_gate.py`

## Dependency seams and worker registration

Recovery imports runtime_support and analysis_contracts rather than runtime/research execution. Saved-pool numeric validation imports value_bounds rather than walk_forward. Offline readers import configuration rather than the CLI (which loads reporting). desktop_app.features.walk_forward.presenter imports shared inputs from existing desktop_app.components.formatting; desktop_app.shell.main_window re-exports the previous names.

desktop_app.shell.main_window registers its executor and module:callable entry point after the executor definition. A same-callable registration is idempotent; a different callable fails closed. Entry-point registration has the same equality policy. Runtime access without registration raises RuntimeSafetyError. Each worker gets a fresh registry and resolves its entry point before executing the UI operation; failed imports, missing attributes and noncallables never fall back.

DEFAULT_OPERATION_REGISTRAR is the single documented desktop registrar literal in quantlab. This explicit default retains JobManager(paths), directly called workers and existing diagnostic wrappers without requiring test edits. UI owns the corresponding OPERATION_REGISTRAR protocol constant. Non-default registered entry points are forwarded through the spawn arguments. Dynamic importlib resolution is intentional data-driven dependency injection; the runtime never statically imports desktop modules. Late lookup preserves existing mock adapters as well as spawn behavior.

The new core_import_findings boundary is enforced by scan, including local static imports. python_findings retains its old dependency-classification API for unchanged existing tests; that legacy classification cannot exempt anything from the new scan rule. Literal desktop importlib arguments are also rejected. Existing G4 checks are unchanged.

## Locked sources and profiles

The eight locked files have no edits. Their _fail definitions and any existing import edges remain. saved_candidate_pool producer declarations, pinned source hashes, profile selection logic and _select_producer are untouched; only local shared-validator/configuration imports and explanatory comments change.

## Packaging and verification scope

build_manifest.py inventories quantlab/*.py. All four new quantlab modules have static imports from existing bundled modules, verified by a cheap AST test; no additional PyInstaller hidden imports are required. desktop_app.components.formatting is already in the UI-text inventory; no new desktop module or widget is introduced. Existing stylesheet tests discover all desktop sources automatically.

No existing test was edited (t11_test_edits.json is empty). Focused new tests use AST and in-process units only, with no subprocesses or temporary workspaces. Per the explicit sandbox note, existing application suites are reserved for the controller; only new focused modules and the static gate are run here. No behavior/text referenced by implementation contracts or acceptance scenarios is changed.

## Remaining changed symbols and callers

### desktop_app/components/formatting.py :: _dataset

`desktop_app/features/settings/settings.py`, `desktop_app/components/formatting.py`, `desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `quantlab/data.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_workspace_wal_guard.py`, `tools/validate_official_history.py`

### desktop_app/components/formatting.py :: research_controls

`desktop_app/components/formatting.py`, `desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `tests/test_desktop_ui.py`, `tests/test_workspace_wal_guard.py`

### desktop_app/features/walk_forward/presenter.py :: execute_walk_forward

`desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `tests/test_workspace_wal_guard.py`

### desktop_app/features/walk_forward/presenter.py :: preview_walk_forward

`desktop.py`, `desktop_app/shell/bindings.py`, `desktop_app/shell/mount.py`, `desktop_app/features/strategy/strategy.py`, `desktop_app/features/walk_forward/wf_wizard.py`, `desktop_app/strings/catalog.py`, `desktop_app/features/walk_forward/presenter.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_walk_forward.py`, `tests/test_wf_wizard.py`, `tests/test_workspace_wal_guard.py`

### quantlab/analysis_recovery.py :: _initialize

`quantlab/analysis_recovery.py`

### quantlab/analysis_recovery.py :: plan_bindings

`desktop_app/smoke/recovery.py`, `quantlab/analysis_recovery.py`, `quantlab/desktop_runtime.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_recovery_frozen_smoke.py`

### quantlab/analysis_recovery.py :: register_launch

`desktop_app/smoke/recovery.py`, `quantlab/analysis_recovery.py`, `quantlab/desktop_runtime.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_recovery_frozen_smoke.py`

### quantlab/desktop_runtime.py :: _job_worker

`quantlab/desktop_runtime.py`, `tests/generic_smoke_phase_diagnostics.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/smoke_timeout_diagnostics.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_generic_smoke_phase_diagnostics.py`, `tests/test_paper_replay_timeout_diagnostics.py`, `tests/test_restart_availability_contract.py`, `tests/test_smoke_timeout_diagnostics.py`, `tools/diagnose_paper_replay.py`

### quantlab/desktop_runtime.py :: _operation_executor

`quantlab/desktop_runtime.py`

### quantlab/desktop_runtime.py :: _worker_operation_executor

`quantlab/desktop_runtime.py`

### quantlab/desktop_runtime.py :: executor

`desktop_app/shell/main_window.py`, `quantlab/desktop_runtime.py`, `tests/active_writer_timeout_diagnostics.py`, `tests/test_research.py`, `archives/legacy_autotrading/trader/tasker.py`

### quantlab/desktop_runtime.py :: register

`quantlab/analysis_recovery.py`, `quantlab/analysis_recovery_windows.py`, `quantlab/desktop_runtime.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_chatgpt_plan.py`, `tests/test_test_group.py`, `tests/test_windows_recovery_feasibility.py`, `archives/legacy_autotrading/trader/executor.py`

### quantlab/desktop_runtime.py :: register_operation_executor

`desktop_app/shell/main_window.py`, `quantlab/desktop_runtime.py`

### quantlab/desktop_runtime.py :: register_operation_executor_factory

`desktop_app/shell/main_window.py`, `quantlab/desktop_runtime.py`

### quantlab/desktop_runtime.py :: start

`archives/legacy_create_env_app/__init__.py`, `desktop.py`, `desktop_app/features/settings/automatic_backup.py`, `desktop_app/components/charts.py`, `quantlab/assistant/adapters/chatgpt/auth.py`, `quantlab/assistant/adapters/chatgpt/provider.py`, `desktop_app/features/assistant/connection.py`, `desktop_app/components/forms.py`, `desktop_app/features/compare/compare_table.py`, `desktop_app/features/walk_forward/wf_wizard.py`, `desktop_app/components/formatting.py`, `desktop_app/smoke/recovery.py`, `desktop_app/strings/catalog.py`, `desktop_app/smoke/tls.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `docs/script samples/strategy_sample.py`, `quantlab/analysis_recovery.py`, `quantlab/analysis_recovery_windows.py`, `quantlab/automatic_backup.py`, `quantlab/chart_data.py`, `quantlab/core.py`, `quantlab/data.py`, `quantlab/desktop_runtime.py`, `quantlab/market_history.py`, `quantlab/market_providers.py`, `quantlab/paper_replay.py`, `quantlab/provider.py`, `quantlab/reporting.py`, `quantlab/research.py`, `quantlab/saved_candidate_pool.py`, `quantlab/strategies.py`, `quantlab/walk_forward.py`, `research_app.py`, `tests/generic_smoke_phase_diagnostics.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/saved_pool_fixtures.py`, `tests/smoke_timeout_diagnostics.py`, `tests/test_acceptance_process.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_chart_footer.py`, `tests/test_chatgpt_auth.py`, `tests/test_chatgpt_plan.py`, `tests/test_chatgpt_provenance.py`, `tests/test_chatgpt_research.py`, `tests/test_chatgpt_terminal_reporting.py`, `tests/test_chatgpt_token_formats.py`, `tests/test_chatgpt_windows.py`, `tests/test_clean_windows_kit.py`, `tests/test_compare_table.py`, `tests/test_core.py`, `tests/test_core_shards.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_analysis_discovery.py`, `tests/test_desktop_automatic_backup.py`, `tests/test_desktop_charts.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_chatgpt_ui.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_market.py`, `tests/test_desktop_market_integration.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_paper_exports.py`, `tests/test_desktop_runtime.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_strings.py`, `tests/test_desktop_tls_smoke.py`, `tests/test_desktop_ui.py`, `tests/test_desktop_ui_recovery.py`, `tests/test_desktop_walk_forward.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_smoke.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_generic_smoke_phase_diagnostics.py`, `tests/test_market_history.py`, `tests/test_market_history_ui.py`, `tests/test_native_fixture_cleanup.py`, `tests/test_official_history_validation.py`, `tests/test_paper_diagnostics.py`, `tests/test_paper_replay.py`, `tests/test_paper_replay_policy.py`, `tests/test_paper_replay_storage.py`, `tests/test_paper_replay_timeout_diagnostics.py`, `tests/test_paper_replay_wal.py`, `tests/test_primary_sign_in_host.py`, `tests/test_product_ai_boundary.py`, `tests/test_provider.py`, `tests/test_real_ai_validation.py`, `tests/test_research.py`, `tests/test_research_analysis.py`, `tests/test_restart_availability_contract.py`, `tests/test_smoke_timeout_diagnostics.py`, `tests/test_strategies.py`, `tests/test_t9_onboarding.py`, `tests/test_t9_timeinput.py`, `tests/test_test_group.py`, `tests/test_test_group_retention.py`, `tests/test_ui.py`, `tests/test_walk_forward.py`, `tests/test_walk_forward_initialization.py`, `tests/test_walk_forward_wal.py`, `tests/test_wf_wizard.py`, `tests/test_windows_guest_host.py`, `tests/test_windows_recovery_feasibility.py`, `tests/test_workspace_wal_guard.py`, `tests/windows_recovery_diagnostics.py`, `tools/diagnose_paper_replay.py`, `tools/make_icon.py`, `tools/quality_gate.py`, `tools/run_test_group.py`, `tools/validate_official_history.py`, `tools/validate_real_ai.py`, `archives/legacy_autotrading/trader/performance/base.py`, `archives/legacy_autotrading/trader/performance/reports.py`, `archives/legacy_autotrading/trader/tasker.py`, `archives/legacy_autotrading/trader/utils/accounts.py`, `archives/legacy_autotrading/trader/utils/bot.py`, `archives/legacy_autotrading/trader/utils/crawler.py`, `archives/legacy_autotrading/trader/utils/file.py`, `archives/legacy_autotrading/trader/utils/kbar.py`, `archives/legacy_autotrading/trader/utils/select.py`, `archives/legacy_autotrading/trader/utils/subscribe.py`, `archives/legacy_autotrading/trader/utils/time.py`

### quantlab/research_analysis.py :: build_analysis_packet

`desktop_app/smoke/recovery.py`, `desktop_app/shell/main_window.py`, `quantlab/research_analysis.py`, `tests/test_desktop_analysis.py`, `tests/test_research_analysis.py`

### quantlab/saved_candidate_pool.py :: _json_load

`quantlab/saved_candidate_pool.py`

### quantlab/saved_candidate_pool.py :: _validate_legacy_receipts

`quantlab/saved_candidate_pool.py`

### quantlab/saved_candidate_pool.py :: _validate_original_dataset

`quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`

### quantlab/saved_candidate_pool.py :: _validate_provider

`quantlab/saved_candidate_pool.py`

### quantlab/saved_candidate_pool.py :: admit_saved_campaign_pool

`desktop_app/features/walk_forward/presenter.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`, `tests/test_analysis_capable_producer_profile.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_saved_candidate_pool.py`, `tests/test_scalar_producer_profile.py`, `tests/test_subscription_producer_profile.py`, `tests/test_token_format_producer_profile.py`

### quantlab/saved_candidate_pool.py :: load_original_dataset

`desktop_app/smoke/recovery.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `quantlab/saved_candidate_pool.py`, `tests/test_saved_candidate_pool.py`

### quantlab/walk_forward.py :: walk_forward_plan_from_dict

`desktop_app/components/forms.py`, `desktop_app/features/walk_forward/presenter.py`, `quantlab/desktop_runtime.py`, `quantlab/walk_forward.py`, `tests/test_desktop_walk_forward_smoke.py`, `tests/test_saved_candidate_pool.py`, `tests/test_walk_forward.py`

### tools/quality_gate.py :: core_import_findings

`tools/quality_gate.py`

### tools/quality_gate.py :: scan

`quantlab/assistant/adapters/chatgpt/provider.py`, `tests/test_automatic_backup.py`, `tests/test_no_hardcoded_ui_text.py`, `tests/test_quality_gate.py`, `tools/quality_gate.py`, `archives/legacy_autotrading/trader/utils/database/redis.py`, `archives/legacy_autotrading/trader/utils/options.py`

## Final focused validation

- New focused modules: 15 tests passed in 1.303 s; zero subprocesses added.
- Import graph module alone: 4 tests passed in 0.518 s (under 2 s).
- Static quality gate: exit 0, zero findings.
- Python 3.11 compile of tracked and new Python files: exit 0 (307 files after scratch cleanup).
- 23 extracted definitions were AST-identical to HEAD, including signatures and validation/error bodies.
- Eight locked-source git diffs: empty; producer profile region and both profile-selection helpers unchanged.
- git diff --check: exit 0.
- Existing application suites/full suite and installer build were not run here under the explicit sandbox-only-focused-tests instruction; controller validation remains required.



# T11 part B impact analysis (pre-edit caller searches)

GitNexus unavailable per task; repository-wide text/AST caller searches substituted. HIGH risk: desktop startup, smoke terminal publication, recovery admission and saved-candidate failure classification. Preserve ordering, message bytes, exception identity and patch paths. No commits.

## desktop :: main

Conservative importers/callers: `tests/test_import_graph.py`, `tests/test_t11_boundaries.py`, `desktop.py`, `desktop_app/shell/accessibility.py`, `desktop_app/features/settings/automatic_backup.py`, `desktop_app/components/charts.py`, `quantlab/assistant/adapters/chatgpt/auth.py`, `quantlab/assistant/adapters/chatgpt/provider.py`, `desktop_app/features/assistant/connection.py`, `desktop_app/components/expiry_inputs.py`, `desktop_app/components/forms.py`, `desktop_app/components/help.py`, `desktop_app/features/market/dashboard.py`, `desktop_app/features/backtest/backtest.py`, `desktop_app/features/compare/compare.py`, `desktop_app/features/compare/compare_table.py`, `desktop_app/features/data/data.py`, `desktop_app/components/equity.py`, `desktop_app/shell/host.py`, `desktop_app/features/settings/log_table.py`, `desktop_app/features/market/market.py`, `desktop_app/shell/onboarding.py`, `desktop_app/features/paper/paper.py`, `desktop_app/components/result_layers.py`, `desktop_app/components/result_panels.py`, `desktop_app/components/result_widgets.py`, `desktop_app/features/settings/settings.py`, `desktop_app/features/settings/settings_layout.py`, `desktop_app/shell/shortcuts.py`, `desktop_app/features/strategy/strategy.py`, `desktop_app/features/strategy/strategy_tabs.py`, `desktop_app/shell/views.py`, `desktop_app/features/walk_forward/wf_wizard.py`, `desktop_app/components/widgets.py`, `desktop_app/components/formatting.py`, `desktop_app/smoke/recovery.py`, `desktop_app/strings/catalog.py`, `desktop_app/components/timeinput.py`, `desktop_app/shell/main_window.py`, `desktop_app/shell/polish.py`, `desktop_app/features/walk_forward/presenter.py`, `packaging/build_manifest.py`, `packaging/fetch_baseline.py`, `packaging/validate_tls.py`, `quantlab/analysis_recovery_windows.py`, `quantlab/automatic_backup.py`, `quantlab/desktop_errors.py`, `quantlab/desktop_runtime.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`, `tests/active_writer_timeout_diagnostics.py`, `tests/generic_smoke_phase_diagnostics.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/smoke_timeout_diagnostics.py`, `tests/snapshot_cache.py`, `tests/t10_fixture.py`, `tests/test_acceptance_process.py`, `tests/test_accessibility_walk.py`, `tests/test_active_writer_timeout_diagnostics.py`, `tests/test_analysis_capable_producer_profile.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_application_icon.py`, `tests/test_automatic_backup.py`, `tests/test_backtest_presentation.py`, `tests/test_campaign_catalog_producer_profile.py`, `tests/test_candidate_presentation.py`, `tests/test_chart_footer.py`, `tests/test_chatgpt_auth.py`, `tests/test_chatgpt_model_error_codes.py`, `tests/test_chatgpt_plan.py`, `tests/test_chatgpt_provenance.py`, `tests/test_chatgpt_research.py`, `tests/test_chatgpt_terminal_reporting.py`, `tests/test_chatgpt_tls_context.py`, `tests/test_chatgpt_token_formats.py`, `tests/test_chatgpt_windows.py`, `tests/test_compare_table.py`, `tests/test_core_shards.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_analysis_discovery.py`, `tests/test_desktop_auth_install.py`, `tests/test_desktop_auth_smoke.py`, `tests/test_desktop_automatic_backup.py`, `tests/test_desktop_charts.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_chatgpt_ui.py`, `tests/test_desktop_expiries.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_forms.py`, `tests/test_desktop_history_smoke.py`, `tests/test_desktop_market.py`, `tests/test_desktop_market_acceptance.py`, `tests/test_desktop_market_integration.py`, `tests/test_desktop_market_smoke.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_paper_exports.py`, `tests/test_desktop_runtime.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_smoke_isolation.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_strings.py`, `tests/test_desktop_theme.py`, `tests/test_desktop_tls_smoke.py`, `tests/test_desktop_ui.py`, `tests/test_desktop_ui_p0_correctness.py`, `tests/test_desktop_ui_polish_a.py`, `tests/test_desktop_ui_polish_b.py`, `tests/test_desktop_ui_recovery.py`, `tests/test_desktop_walk_forward.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_smoke.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_desktop_window_position.py`, `tests/test_fail_closed_producer_profile.py`, `tests/test_generic_smoke_phase_diagnostics.py`, `tests/test_help_reachability.py`, `tests/test_log_table.py`, `tests/test_market_history_ui.py`, `tests/test_models_limit_producer_profile.py`, `tests/test_native_fixture_cleanup.py`, `tests/test_native_workspace_guard_packaging.py`, `tests/test_no_hardcoded_ui_text.py`, `tests/test_no_inline_stylesheet.py`, `tests/test_packaging.py`, `tests/test_paper_replay_policy.py`, `tests/test_paper_replay_storage.py`, `tests/test_paper_replay_timeout_diagnostics.py`, `tests/test_prepared_host_session.py`, `tests/test_primary_sign_in_host.py`, `tests/test_product_ai_boundary.py`, `tests/test_provider.py`, `tests/test_quality_gate.py`, `tests/test_recovery_frozen_smoke.py`, `tests/test_research_analysis.py`, `tests/test_restart_availability_contract.py`, `tests/test_result_reference_layers.py`, `tests/test_result_widgets.py`, `tests/test_saved_candidate_pool.py`, `tests/test_scalar_producer_profile.py`, `tests/test_scaled_layouts.py`, `tests/test_settings_sections.py`, `tests/test_smoke_timeout_diagnostics.py`, `tests/test_strategy_tabs.py`, `tests/test_subscription_producer_profile.py`, `tests/test_t9_expiry_inputs.py`, `tests/test_t9_onboarding.py`, `tests/test_t9_repair.py`, `tests/test_t9_timeinput.py`, `tests/test_test_group.py`, `tests/test_tls_anchor_producer_profile.py`, `tests/test_token_format_producer_profile.py`, `tests/test_ui_operations_registry.py`, `tests/test_ui_snapshot.py`, `tests/test_update_recovery.py`, `tests/test_wf_wizard.py`, `tests/test_wfo_storage_ci.py`, `tests/test_windows_recovery_diagnostics.py`, `tests/test_windows_recovery_feasibility.py`, `tests/test_worker_failure_evidence.py`, `tests/test_workspace_wal_guard.py`, `tests/windows_recovery_diagnostics.py`, `tools/diagnose_paper_replay.py`, `tools/install_desktop_auth.py`, `tools/quality_gate.py`, `tools/run_test_group.py`, `tools/ui_snapshot.py`, `tools/ui_theme_diff.py`, `tools/validate_core_shards.py`, `archives/legacy_autotrading/trader/utils/file.py`. Internal `_fail` callers remain in each owning module.

## quantlab.analysis_contracts :: _fail

Conservative importers/callers: `quantlab/analysis_contracts.py`, `tests/test_import_graph.py`, `tests/test_t11_boundaries.py`, `quantlab/analysis_recovery.py`, `quantlab/research_analysis.py`. Internal `_fail` callers remain in each owning module.

## quantlab.analysis_recovery :: _fail, RecoveryError

Conservative importers/callers: `tests/test_import_graph.py`, `desktop.py`, `desktop_app/features/settings/automatic_backup.py`, `desktop_app/shell/bindings.py`, `desktop_app/features/compare/compare.py`, `desktop_app/smoke/recovery.py`, `desktop_app/shell/main_window.py`, `quantlab/analysis_recovery.py`, `quantlab/analysis_recovery_windows.py`, `quantlab/desktop_runtime.py`, `quantlab/research_analysis.py`, `tests/test_analysis_recovery.py`, `tests/test_analysis_recovery_integration.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_analysis_recovery_windows.py`, `tests/test_core_shards.py`, `tests/test_recovery_frozen_smoke.py`, `tests/test_research_phase_diagnostic.py`, `tests/test_strategy_tabs.py`, `tests/test_workspace_wal_guard.py`, `tools/diagnose_research_phases.py`, `tools/diagnose_wfo_storage.py`, `tools/run_test_group.py`. Internal `_fail` callers remain in each owning module.

## quantlab.chart_data :: _fail

Conservative importers/callers: `desktop_app/features/market/dashboard.py`, `quantlab/chart_data.py`, `tests/test_chart_data.py`, `tools/validate_market_history_import.py`. Internal `_fail` callers remain in each owning module.

## quantlab.market_history :: _fail

Conservative importers/callers: `desktop.py`, `desktop_app/features/market/dashboard.py`, `desktop_app/shell/bindings.py`, `desktop_app/features/compare/compare.py`, `desktop_app/features/data/data.py`, `desktop_app/shell/host.py`, `desktop_app/features/market/market.py`, `desktop_app/shell/mount.py`, `desktop_app/strings/catalog.py`, `desktop_app/shell/main_window.py`, `quantlab/market_history.py`, `tests/test_core_shards.py`, `tests/test_desktop_history_smoke.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_smoke_isolation.py`, `tests/test_desktop_window_position.py`, `tests/test_market_history.py`, `tests/test_market_history_ui.py`, `tests/test_t9_expiry_inputs.py`, `tests/test_t9_timeinput.py`, `tools/run_test_group.py`, `tools/validate_market_history_import.py`. Internal `_fail` callers remain in each owning module.

## quantlab.saved_candidate_pool :: _fail, SavedCandidatePoolError

Conservative importers/callers: `tests/test_import_graph.py`, `desktop_app/smoke/recovery.py`, `desktop_app/shell/main_window.py`, `desktop_app/features/walk_forward/presenter.py`, `quantlab/research_analysis.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`, `tests/saved_pool_fixtures.py`, `tests/test_analysis_capable_producer_profile.py`, `tests/test_campaign_catalog_producer_profile.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_fail_closed_producer_profile.py`, `tests/test_models_limit_producer_profile.py`, `tests/test_saved_candidate_pool.py`, `tests/test_scalar_producer_profile.py`, `tests/test_subscription_producer_profile.py`, `tests/test_test_group.py`, `tests/test_tls_anchor_producer_profile.py`, `tests/test_token_format_producer_profile.py`, `tools/diagnose_research_phases.py`, `tools/run_test_group.py`. Internal `_fail` callers remain in each owning module.

## quantlab.desktop_errors :: ErrorText, ERROR_TABLE, ERROR_LABELS, error_message, exception_code, startup_error_code

Conservative importers/callers: `tests/test_t11_boundaries.py`, `desktop.py`, `desktop_app/features/assistant/connection.py`, `desktop_app/features/market/dashboard.py`, `desktop_app/features/backtest/backtest.py`, `desktop_app/features/compare/compare.py`, `desktop_app/features/market/market.py`, `desktop_app/features/settings/settings.py`, `desktop_app/features/strategy/strategy.py`, `desktop_app/shell/views.py`, `desktop_app/shell/main_window.py`, `quantlab/desktop_errors.py`, `quantlab/desktop_runtime.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_ui_p0_correctness.py`. Internal `_fail` callers remain in each owning module.

Six `_fail` definitions: analysis_contracts (Part A moved from research_analysis), analysis_recovery, chart_data, market_history, saved_candidate_pool, quantlab.assistant.adapters.chatgpt.provider. The last is G3 locked and remains unchanged; other locked files define no `_fail`.

New startup helpers are called by main/run_gui. All patched desktop helpers remain module-global lookups, including smoke worker cleanup and history/walk-forward checks. prepare_workspace preserves early return 3; lock failure remains 2. No behavior/text contract changes; G6 documentation does not require changes.

## Part B new symbol callers and packaging

- `desktop.parse_args`: `desktop.main`, `tests/test_t11_part_b.py` (via main).
- `desktop.acquire_instance_lock`: `desktop.run_gui`, `tests/test_t11_part_b.py`.
- `desktop.prepare_workspace`: `desktop.run_gui`; `_prepare_startup_workspace` and `_offer_workspace_after_recovery_block` continue to resolve through desktop globals.
- `desktop.run_smoke`: `desktop.run_gui`; timer callbacks retain module-global checks/cleanup and now capture a shared namespace instead of main locals.
- `desktop.run_gui`: `desktop.main`, `tests/test_t11_part_b.py`.
- `quantlab.errors.fail`: the five unlocked `_fail` wrappers in analysis_contracts, analysis_recovery, chart_data, market_history and saved_candidate_pool. `research_analysis._fail` remains the Part A re-export.
- `quantlab.errors.saved_candidate_reason`: saved_candidate_pool._fail. The ordered fragment classification is unchanged.
- Shared `RecoveryError` and `SavedCandidatePoolError`: original module re-exports and all previously listed importers. Their public `__module__` paths are preserved, as is ErrorText's original path.
- `ErrorCode`, `ErrorText`, `ERROR_TABLE`, `ERROR_LABELS`: desktop_errors re-exports and the new focused coverage tests. ErrorCode is derived from the original catalogue, with no second code list.

`packaging/build_manifest.py` inventories `quantlab/*.py`; errors.py is reached through static imports from desktop_errors and all five wrappers. PyInstaller Analysis starts at desktop.py, imports desktop_errors statically, and therefore discovers errors.py without a hidden import. tests/test_packaging.py inventories only the separately shipped provenance source files; errors.py does not participate in pinned-source reads and needs no new data-file inventory entry. No desktop module was added, so UI-text/style inventories require no additions.

## Part B final validation

- desktop.main: 7 lines (348 before); all five requested helper names exist.
- New focused module: 11 tests passed in 0.243 s, zero subprocesses added, no real workspace or temporary filesystem fixtures.
- Combined new Part A/B focused modules: 26 tests passed in 1.500 s; all existing tests remain unmodified. t11_test_edits.json remains [].
- Baseline AST fingerprints confirm smoke callback bodies, exception handlers and final cleanup are unchanged after normalizing the explicit state carrier and its closure declarations. A mocked GUI lifecycle checks startup/freeze/restore/event-loop/shutdown order.
- Shared wrappers preserve exact exception types, args and attributes; saved-candidate reason ordering and legacy exception-code fallbacks are checked. Every enum code has a non-empty Chinese message, with no orphan table keys.
- Eight G3 locked file diffs are empty. saved_candidate_pool prefix containing all producer definitions/pinned hashes and both profile-selection helpers are byte-identical to HEAD.
- Error catalogue source bytes are identical to HEAD; error_message, exception_code and startup_error_code are AST-identical.
- Static quality gate: exit 0, zero findings. Python 3.11 compile check: 309 tracked/new Python files passed. git diff --check: exit 0.
- Full suite, existing smoke/installer lifecycle suites and installer build are deferred to the controller under the task's explicit sandbox-only-focused-tests note. The CI 15-minute limit is unchanged. Part A changes remain uncommitted and preserved.

## Part C pre-edit impact (text fallback authorized by task)

High risk: admission/worker ownership/OOS consumption/ledger replay. No graph verdict is claimed. Checks and mutation order must remain unchanged.

- `saved_candidate_pool.admit_saved_campaign_pool`: `desktop_app/features/walk_forward/presenter.py`, `tests/test_analysis_capable_producer_profile.py`, `quantlab/saved_candidate_pool.py`, `quantlab/walk_forward.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_saved_candidate_pool.py`, `tests/test_scalar_producer_profile.py`, `tests/test_subscription_producer_profile.py`, `tests/test_token_format_producer_profile.py`.

- `desktop_runtime.JobManager.start`: `desktop.py`, `quantlab/analysis_recovery_windows.py`, `tools/diagnose_paper_replay.py`, `tests/paper_replay_timeout_diagnostics.py`, `tests/smoke_timeout_diagnostics.py`, `tests/t10_fixture.py`, `tools/ui_snapshot.py`, `tests/test_analysis_recovery_integration.py`, `quantlab/desktop_runtime.py`, `tests/test_analysis_recovery_ui.py`, `tests/test_candidate_presentation.py`, `tests/test_desktop_analysis.py`, `tests/test_desktop_automatic_backup.py`, `tests/test_desktop_chatgpt_integration.py`, `tests/test_desktop_expiries.py`, `tests/test_desktop_feedback_p0.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_runtime.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_smoke_terminal.py`, `tests/test_desktop_theme.py`, `tests/test_desktop_ui.py`, `tests/test_desktop_ui_p0_correctness.py`, `tests/test_desktop_ui_polish_a.py`, `tests/test_desktop_ui_polish_b.py`, `tests/test_desktop_ui_recovery.py`, `tests/test_desktop_walk_forward_runtime.py`, `tests/test_desktop_walk_forward_smoke.py`, `tests/test_desktop_walk_forward_terminal.py`, `tests/test_market_history_ui.py`, `tests/test_product_ai_boundary.py`, `tests/test_restart_availability_contract.py`, `tests/test_settings_sections.py`, `tests/test_smoke_timeout_diagnostics.py`, `tests/test_t11_boundaries.py`, `tests/test_t9_expiry_inputs.py`, `tests/test_t9_onboarding.py`, `tests/test_workspace_wal_guard.py`.

- `walk_forward.run_walk_forward`: `desktop_app/strings/catalog.py`, `desktop_app/features/compare/compare.py`, `desktop_app/shell/polish.py`, `desktop_app/shell/bindings.py`, `desktop_app/features/walk_forward/presenter.py`, `desktop_app/shell/mount.py`, `desktop_app/features/strategy/strategy.py`, `tests/smoke_timeout_diagnostics.py`, `tests/test_active_writer_timeout_diagnostics.py`, `quantlab/walk_forward.py`, `tests/test_desktop_pages.py`, `tests/test_desktop_saved_candidate_pool.py`, `tests/test_desktop_walk_forward.py`, `tests/test_holdout_registry_deadline.py`, `tests/test_saved_candidate_pool.py`, `tests/test_walk_forward.py`, `tests/test_walk_forward_initialization.py`, `tests/test_walk_forward_wal.py`, `tests/test_wf_wizard.py`, `tests/test_workspace_wal_guard.py`.

- `paper._reduce`: `quantlab/paper.py`, `tests/test_paper.py`.

- `chart_data.aggregate_bars`: `desktop_app/features/market/dashboard.py`, `quantlab/chart_data.py`, `tools/validate_market_history_import.py`, `tests/test_chart_data.py`.

New private helper callers: original entrypoint and adjacent extracted helpers only. No new product modules; packaging unchanged. Existing engine golden: tests.test_backtest. Controller retains all existing admission/profile, runtime, OOS/WAL, paper and chart suites.

## Part C extraction results and helper callers

| Entry point | Before (Part C baseline) | After |
| --- | ---: | ---: |
| saved_candidate_pool.admit_saved_campaign_pool | 197 | 65 |
| desktop_runtime.JobManager.start | 207 | 42 |
| walk_forward.run_walk_forward | 173 | 45 |
| paper._reduce | 118 | 75 |
| chart_data.aggregate_bars | 117 | 42 |

Counts include the def line through the final AST line, including multiline signatures and docstrings.

- `admit_saved_campaign_pool` calls `_collect_source_attempts`, `_validate_source_selection` and `_saved_pool_snapshot`; `_collect_source_attempts` calls `_admit_source_attempt`. All are private helpers extracted exclusively from the original admission body. Existing profile selection and provider validation calls remain in their original order, inside the original exception translation boundary.
- `JobManager.start` calls `_validate_job_request`, `_prepare_walk_forward_job`, `_prepare_analysis_job`, `_prepare_other_job` and `_launch_job_process`. The helpers have no other product callers. Process argument construction, including Part A's optional executor registrar, is unchanged. Worker admission and owner claims precede spawn; cleanup still retains incomplete recovery ownership before cancellation.
- `run_walk_forward` calls `_run_walk_forward_journal`, which calls `_initial_walk_forward_state` and `_score_walk_forward_state`. The scoring helper calls `_reserve_walk_forward_oos` and `_score_walk_forward_folds`. The original lock surrounds the entire journal lifecycle. WAL guards, initial transaction, interruption recovery, durable evaluation-slot reservation, OOS consumption before scoring, selection freeze before OOS, and stop handling retain their original order.
- `_reduce` calls `_reduce_fill`, which has no other product callers. Decimal operations, FIFO cost allocation, round-trip loss accounting and state mutations retain their exact statement order; the reducer still copies state before mutation.
- `aggregate_bars` calls `_validate_aggregation_source`, `_aggregate_minutes` and `_aggregate_dates`; these have no other product callers. Validation precedes aggregation; ordered numeric expressions, source IDs, warnings and duplicate handling remain unchanged.

No new product modules were introduced, so packaging/build_manifest.py, tests/test_packaging.py and PyInstaller inventories require no changes. No UI module or user-facing text changed; G6 contract updates are unnecessary. Part A/B changes are preserved. No locked edge or locked `_fail` definition was touched.

## Part C behavioral oracles and validation

Before editing, the five original module files were captured outside the repository. Characterization constants were computed by executing those original implementations, never by accepting the refactored outputs. The chart and paper oracle tests were run and passed before their extractions. The additional admission/runtime/walk-forward fixtures execute the saved original implementations to capture their expected constants.

`tests/test_t11_part_c.py` adds nine in-memory checks (including reuse of the existing independent engine golden test): exact chart output hashes for five resolutions with gaps/duplicates/unknown volume/mixed sources; paper replay hashes across partial closes and reversals; full manufactured archived admission snapshot/candidate hash; mocked worker arguments/deadlines/flags with default and custom registrar; exact walk-forward state and durable-save sequence hashes for completion, consumed-range rejection and cancellation; admission/active-job/WAL guard ordering. Filesystem boundaries and workers are mocked; SQLite uses only :memory:. No subprocess is added. Walk-forward's source binding is a fixed fixture in this oracle: normal source provenance hashes continue to reflect actual source text and are not overridden or weakened in product code.

`tests/test_function_lengths.py` adds the five AST length guards and hashes all eight locked sources, normalizing only checkout newline conventions for Windows/Linux portability. Separately, `git diff --exit-code` confirms byte-level empty locked-file diffs in this workspace. All original top-level definitions other than the five targets, all existing JobManager methods other than start, and the entire saved-candidate prefix before admission are text-identical to the Part C baseline. This includes every profile definition, pinned hash, selection/validation function, and provider-validation helper.

- New Part C modules: 11 tests passed (exit 0); well below the 5-second budget, zero subprocesses.
- Combined focused modules: `python -m unittest tests.test_import_graph tests.test_t11_boundaries tests.test_t11_part_b tests.test_t11_part_c tests.test_function_lengths`: 37 passed in 1.804 s, exit 0, QT_QPA_PLATFORM=offscreen.
- `.venv/Scripts/python.exe tools/quality_gate.py`: exit 0, zero findings.
- `py -3.11` compile() over all tracked/new Python files, reading utf-8-sig: 311 files passed, exit 0. No bytecode artifacts generated by this check.
- `git diff --check`: exit 0 after removing two extra trailing blank lines.
- No existing test file was edited; `t11_test_edits.json` remains `[]` (no import-path plumbing needed). No plan, locked source, timeout or CI cap was changed.
- Per the explicit sandbox note, the full unittest suite and existing saved-pool/profile/desktop-runtime/walk-forward/WAL/paper/chart/market suites were not run here; the controller runs them outside the sandbox. The existing engine golden resides in tests.test_backtest, not tests.test_engine_golden; its independent golden case is reused by the new focused module and passed.


## T11 repair: pre-edit impact and causes

The controller requested grep/AST caller analysis in this sandbox in place of GitNexus. Before edits, source/import searches covered the shared failure wrappers, MainWindow initialization/registration, adapter imports, and their tests. Risk is moderate for the shared error constructor (five validation paths), and low for moving the existing window support calls intact. No admission, broker, quota, dataset, OOS, or journal execution statements change.

- `errors.fail`: five wrappers pass their original exception type explicitly; removing the implicit core default avoids importing core without changing any call result.
- `SavedCandidatePoolError`: restored to its original saved_candidate_pool definition and exact ValidationError inheritance. It cannot reside eagerly in core-free errors without importing its locked base. Reason classification remains shared; all callers continue receiving the same original type, fields, args and pickle path. RecoveryError remains core-free and retains its original public pickle path. Locked core.ValidationError and locked `_fail` definitions are retained.
- `MainWindow.__init__`: the existing polish/help/shortcuts/accessibility imports and calls move unchanged, in order, into private module helper `_install_window_support`. The helper's only caller is MainWindow.__init__. Registrar imports become private aliases; only OPERATION_REGISTRAR is an intentional new public name. No new desktop module, stylesheet, widget objectName or text is introduced.
- `execute_walk_forward` / `preview_walk_forward`: no repair product edit. T11 already extracted `_dataset` and `research_controls` into desktop_app.components.formatting. The failing WAL test stub still intercepted desktop_app.shell.main_window, so the adapter reached real load_dataset on a nonexistent dataset; this was stale import-path plumbing, not a change to dataset write/read timing. Exactly two stub-path edits repair it; all assertions remain intact. No stash/baseline flake experiment is needed because the path mismatch is deterministic.

### Caller/importer inventory for repaired product symbols

AST names, attributes and import aliases complement the pre-edit grep searches (line numbers below reflect repaired sources):

- `MainWindow`: `desktop.py:837,838`; `desktop_app/shell/main_window.py:1295`; `tests/t10_fixture.py:15,24`; `tests/test_analysis_recovery_ui.py:37,63,246,255,295,301,314,328,334`; `tests/test_candidate_presentation.py:75,79`; `tests/test_desktop_automatic_backup.py:116,121`; `tests/test_desktop_expiries.py:146,154`; `tests/test_desktop_feedback_p0.py:28,31`; `tests/test_desktop_market_integration.py:150,157`; `tests/test_desktop_pages.py:17,92`; `tests/test_desktop_theme.py:63,71`; `tests/test_desktop_ui.py:25,29`; `tests/test_desktop_ui_p0_correctness.py:31,34`; `tests/test_desktop_ui_polish_a.py:14,29`; `tests/test_desktop_ui_polish_b.py:19,78,103`; `tests/test_desktop_ui_recovery.py:14,32`; `tests/test_market_history_ui.py:178,181`; `tests/test_restart_availability_contract.py:103,105,339,350`; `tests/test_result_reference_layers.py:110,112,164,168,171,178,182,188,190,193,199,204,207,211,216,221,240,249`; `tests/test_settings_sections.py:22,31`; `tests/test_t9_expiry_inputs.py:357,366`; `tests/test_t9_onboarding.py:46,47`; `tests/test_ui_snapshot.py:183`; `tools/ui_snapshot.py:199,226`.

- `fail`: `quantlab/analysis_contracts.py:24,28`; `quantlab/analysis_recovery.py:51,55`; `quantlab/chart_data.py:34,38`; `quantlab/market_history.py:43,46`; `quantlab/saved_candidate_pool.py:827,830`; `tests/test_analysis_recovery_integration.py:140,144`; `tests/test_core_scalar_parity.py:107`; `tests/test_desktop_automatic_backup.py:74`; `tests/test_desktop_runtime.py:591`; `tests/test_desktop_ui_p0_correctness.py:82,88,119,131`; `tests/test_market_download_validation.py:16`; `tests/test_paper.py:293,313,323,569,822`; `tests/test_paper_diagnostics.py:262,268`; `tests/test_paper_replay_timeout_diagnostics.py:153,154`; `tests/test_research.py:315`; `tests/test_research_phase_diagnostic.py:141`; `tests/test_smoke_timeout_diagnostics.py:567`; `tests/test_walk_forward_initialization.py:113`; `tests/test_windows_recovery_diagnostics.py:152,157`; `tests/test_windows_recovery_feasibility.py:623,952`; `tools/diagnose_paper_replay.py:248`.

- `SavedCandidatePoolError`: `desktop_app/features/walk_forward/presenter.py:94,97`; `quantlab/saved_candidate_pool.py:830,838,841,865,889,998,1042,1135,1137,1155,1335,1402,1471,1497`; `tests/test_analysis_capable_producer_profile.py:76,107`; `tests/test_campaign_catalog_producer_profile.py:49`; `tests/test_desktop_saved_candidate_pool.py:305,306`; `tests/test_fail_closed_producer_profile.py:13,111,165,178,185,190,278,291,298`; `tests/test_models_limit_producer_profile.py:53`; `tests/test_saved_candidate_pool.py:20,104,117,125,128,135,139,141,152,165,173,178,180,191,198,206,210,217,219,340,347,358,383,388,394,400,417,427,456,462,466,469,475,484,505,509,515,521,530,546,558,617,626,634,706,724,730,738,855,868,875,880,930`; `tests/test_scalar_producer_profile.py:71,75,77,80,115`; `tests/test_subscription_producer_profile.py:104,109`; `tests/test_t11_part_b.py:13,164,173,175,178,184`; `tests/test_t11_part_c.py:155`; `tests/test_tls_anchor_producer_profile.py:52`; `tests/test_token_format_producer_profile.py:93,98`.

- `register_operation_executor`: `desktop_app/shell/main_window.py:800`; `tests/test_t11_boundaries.py:67,68,72`.

- `register_operation_executor_factory`: `desktop_app/shell/main_window.py:801`; `tests/test_t11_boundaries.py:119,120,123`.

- `_install_window_support`: `desktop_app/shell/main_window.py:1020`.

### Golden proof and changed keys

`research_analysis._implementation` hashes raw bytes of research_analysis.py and indicators.py; only research_analysis.py changed. `walk_forward.walk_forward_binding` content-hashes UTF-8 source text listed in SOURCE_FILES; only walk_forward.py and saved_candidate_pool.py changed. Campaign engine inputs remain pinned and unchanged. In the hermetic existing registry workspace, the legacy oracle with only those three file reads supplied from HEAD exactly matched the original complete golden. Running the legacy oracle against actual sources differed in 25 leaves, containing six unique hash substitutions, across ui_analysis_preview/read/reconcile/run and ui_walk_forward_preview. The fixture was updated by exact hash-token replacement only; recursive comparison verified identical keys, list lengths, wording, paths and other values. Each changed leaf and the before/after source SHA-256 values are recorded in t11_repair_golden_changes.json; t11_test_edits.json lists each test/fixture edit and justification. All eight G3 sources and the entire saved-pool prefix preceding its exception class (including profiles, pins and profile selection) were byte-compared against HEAD with checkout CRLF conversion and matched.

No new product modules; prior T11 modules remain statically imported and this repair introduces no packaging inventory change. No user-visible behavior/text contract change, so IMPLEMENTATION_CONTRACTS.md and ACCEPTANCE.json require no change.

### Repair validation

- `.venv/Scripts/python.exe -m unittest tests.test_t11_repair tests.test_import_graph tests.test_t11_boundaries tests.test_t11_part_b tests.test_t11_part_c tests.test_function_lengths tests.test_ui_operations_registry`: exit 0, 44 tests, 17.209 s. The added AST guard creates zero subprocesses and is included in the 1.796 s / 38-test cheap T11 run; the registry suite is pre-existing.
- Focused original WAL guard and MainWindow class-limit cases: exit 0, 2 tests, 0.095 s, under a runner-only inherited-permission os.mkdir shim (same approach as the existing registry hermetic workspace). No assertion, product file operation or test source is patched by that shim. The unshimmed WAL setup reproduced the documented temp ACL PermissionError before reaching its test body; this is separate from the fixed import-path regression. An initial class-limit invocation used the wrong unittest class name; corrected to PageBoundaryTests and passed.
- Fresh interpreter imports quantlab.errors, then quantlab.market_history: exit 0; quantlab.core/trader/shioaji absent from sys.modules. This is manual verification; the committed new guard uses AST and no subprocess.
- `.venv/Scripts/python.exe tools/quality_gate.py`: exit 0, zero findings.
- `py -3.11` compile() of every tracked/new Python file read with utf-8-sig: exit 0, 312 files; no pyc output generated by this check.
- `git diff --check`: exit 0. Locked files and immutable plan: git diff --exit-code, exit 0. Saved-pool profile prefix byte comparison: passed. MainWindow: 394 lines.
- Per the final sandbox instruction, the full unittest suite and unrelated environment-sensitive existing modules were not run; controller verification remains required. No branch switch, stash, commit, push, PR, timeout or CI-cap change. No scratch artifacts were added to the repository.
