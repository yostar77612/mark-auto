"""Compose pages and retain the public shell widget/handler aliases."""

from desktop_app.shell.pages import MarketPage, DataPage, StrategyPage, BacktestPage
from desktop_app.features.compare.compare import ComparePage
from desktop_app.features.paper.paper import PaperPage
from desktop_app.features.settings.settings import SettingsPage
from desktop_app.components.widgets import WidgetTools
from desktop_app.shell.views import ViewCoordinator


def mount_pages(shell):
    _register_shell_callbacks(shell)
    _mount_widget_tools(shell)
    _mount_market_page(shell)
    _mount_data_page(shell)
    _mount_strategy_page(shell)
    _copy_strategy_state(shell)
    _mount_backtest_page(shell)
    _mount_compare_page(shell)
    _mount_paper_page(shell)
    _mount_settings_page(shell)
    _mount_view_coordinator(shell)


def _register_shell_callbacks(shell):
    host = shell.page_host
    # Late dispatch preserves patching and the shell's single background-job slot.
    host.callbacks['_advanced'] = lambda *a, **kw: shell._advanced(*a, **kw)
    host.callbacks['_analysis_event'] = lambda *a, **kw: shell._analysis_event(*a, **kw)
    host.callbacks['_analysis_request'] = lambda *a, **kw: shell._analysis_request(*a, **kw)
    host.callbacks['_analysis_saved_changed'] = lambda *a, **kw: shell._analysis_saved_changed(*a, **kw)
    host.callbacks['_analysis_section'] = lambda *a, **kw: shell._analysis_section(*a, **kw)
    host.callbacks['_browse'] = lambda *a, **kw: shell._browse(*a, **kw)
    host.callbacks['_busy'] = lambda *a, **kw: shell._busy(*a, **kw)
    host.callbacks['_button'] = lambda *a, **kw: shell._button(*a, **kw)
    host.callbacks['_chatgpt_cancel'] = lambda *a, **kw: shell._chatgpt_cancel(*a, **kw)
    host.callbacks['_chatgpt_dispatch'] = lambda *a, **kw: shell._chatgpt_dispatch(*a, **kw)
    host.callbacks['_chatgpt_event'] = lambda *a, **kw: shell._chatgpt_event(*a, **kw)
    host.callbacks['_chatgpt_open_browser'] = lambda *a, **kw: shell._chatgpt_open_browser(*a, **kw)
    host.callbacks['_chatgpt_quiesce'] = lambda *a, **kw: shell._chatgpt_quiesce(*a, **kw)
    host.callbacks['_compare_page'] = lambda *a, **kw: shell._compare_page(*a, **kw)
    host.callbacks['_confirm_button'] = lambda *a, **kw: shell._confirm_button(*a, **kw)
    host.callbacks['_current_plan_binding'] = lambda *a, **kw: shell._current_plan_binding(*a, **kw)
    host.callbacks['_invalidate_analysis_preview'] = lambda *a, **kw: shell._invalidate_analysis_preview(*a, **kw)
    host.callbacks['_mount_market'] = lambda *a, **kw: shell._mount_market(*a, **kw)
    host.callbacks['_mount_page'] = lambda *a, **kw: shell._mount_page(*a, **kw)
    host.callbacks['_navigate_selected_page'] = lambda *a, **kw: shell._navigate_selected_page(*a, **kw)
    host.callbacks['_notification_link'] = lambda *a, **kw: shell._notification_link(*a, **kw)
    host.callbacks['_page'] = lambda *a, **kw: shell._page(*a, **kw)
    host.callbacks['_paper_page'] = lambda *a, **kw: shell._paper_page(*a, **kw)
    host.callbacks['_payload'] = lambda *a, **kw: shell._payload(*a, **kw)
    host.callbacks['_plan_usage_request'] = lambda *a, **kw: shell._plan_usage_request(*a, **kw)
    host.callbacks['_quiesce_and_recover'] = lambda *a, **kw: shell._quiesce_and_recover(*a, **kw)
    host.callbacks['_record_connection_error'] = lambda *a, **kw: shell._record_connection_error(*a, **kw)
    host.callbacks['_recovery_display_fingerprint'] = lambda *a, **kw: shell._recovery_display_fingerprint(*a, **kw)
    host.callbacks['_refresh_analysis_saved'] = lambda *a, **kw: shell._refresh_analysis_saved(*a, **kw)
    host.callbacks['_refresh_recovery_controls'] = lambda *a, **kw: shell._refresh_recovery_controls(*a, **kw)
    host.callbacks['_remember'] = lambda *a, **kw: shell._remember(*a, **kw)
    host.callbacks['_remember_stop'] = lambda *a, **kw: shell._remember_stop(*a, **kw)
    host.callbacks['_safe'] = lambda *a, **kw: shell._safe(*a, **kw)
    host.callbacks['_save_section_preferences'] = lambda *a, **kw: shell._save_section_preferences(*a, **kw)
    host.callbacks['_selected_recovery_launch'] = lambda *a, **kw: shell._selected_recovery_launch(*a, **kw)
    host.callbacks['_settings_page'] = lambda *a, **kw: shell._settings_page(*a, **kw)
    host.callbacks['_show_account'] = lambda *a, **kw: shell._show_account(*a, **kw)
    host.callbacks['_text'] = lambda *a, **kw: shell._text(*a, **kw)
    host.callbacks['auto_restore_chatgpt'] = lambda *a, **kw: shell.auto_restore_chatgpt(*a, **kw)
    host.callbacks['backup'] = lambda *a, **kw: shell.backup(*a, **kw)
    host.callbacks['cancel_job'] = lambda *a, **kw: shell.cancel_job(*a, **kw)
    host.callbacks['closeEvent'] = lambda *a, **kw: shell.closeEvent(*a, **kw)
    host.callbacks['configure_workspace'] = lambda *a, **kw: shell.configure_workspace(*a, **kw)
    host.callbacks['demo_paper_policy'] = lambda *a, **kw: shell.demo_paper_policy(*a, **kw)
    host.callbacks['form_feedback'] = lambda *a, **kw: shell.form_feedback(*a, **kw)
    host.callbacks['freeze_paper'] = lambda *a, **kw: shell.freeze_paper(*a, **kw)
    host.callbacks['inspect_plan_usage'] = lambda *a, **kw: shell.inspect_plan_usage(*a, **kw)
    host.callbacks['kill_paper'] = lambda *a, **kw: shell.kill_paper(*a, **kw)
    host.callbacks['load_form_file'] = lambda *a, **kw: shell.load_form_file(*a, **kw)
    host.callbacks['load_settings'] = lambda *a, **kw: shell.load_settings(*a, **kw)
    host.callbacks['notify_local'] = lambda *a, **kw: shell.notify_local(*a, **kw)
    host.callbacks['open_releases'] = lambda *a, **kw: shell.open_releases(*a, **kw)
    host.callbacks['paper_job'] = lambda *a, **kw: shell.paper_job(*a, **kw)
    host.callbacks['pick_analysis_original'] = lambda *a, **kw: shell.pick_analysis_original(*a, **kw)
    host.callbacks['poll_jobs'] = lambda *a, **kw: shell.poll_jobs(*a, **kw)
    host.callbacks['preview_analysis'] = lambda *a, **kw: shell.preview_analysis(*a, **kw)
    host.callbacks['read_analysis'] = lambda *a, **kw: shell.read_analysis(*a, **kw)
    host.callbacks['read_logs'] = lambda *a, **kw: shell.read_logs(*a, **kw)
    host.callbacks['reconcile_saved_analysis'] = lambda *a, **kw: shell.reconcile_saved_analysis(*a, **kw)
    host.callbacks['record_event'] = lambda *a, **kw: shell.record_event(*a, **kw)
    host.callbacks['refresh_views'] = lambda *a, **kw: shell.refresh_views(*a, **kw)
    host.callbacks['run_analysis'] = lambda *a, **kw: shell.run_analysis(*a, **kw)
    host.callbacks['save_settings'] = lambda *a, **kw: shell.save_settings(*a, **kw)
    host.callbacks['select_strategy'] = lambda *a, **kw: shell.select_strategy(*a, **kw)
    host.callbacks['show_chatgpt_sign_in'] = lambda *a, **kw: shell.show_chatgpt_sign_in(*a, **kw)
    host.callbacks['start_job'] = lambda *a, **kw: shell.start_job(*a, **kw)
    host.callbacks.update(shell.page_services())


def _mount_widget_tools(shell):
    host = shell.page_host
    shell.widgets_page = WidgetTools(host)
    shell._button = shell.widgets_page._button
    shell._confirm_button = shell.widgets_page._confirm_button
    shell._text = shell.widgets_page._text
    shell._advanced = shell.widgets_page._advanced
    shell._save_section_preferences = shell.widgets_page._save_section_preferences
    shell._payload = shell.widgets_page._payload
    shell._remember = shell.widgets_page._remember
    shell._browse = shell.widgets_page._browse


def _mount_market_page(shell):
    host = shell.page_host
    shell.market_page = MarketPage(host)
    shell.refresh_market = shell.market_page.refresh_market
    shell.save_market_preferences = shell.market_page.save_market_preferences
    shell.load_market_cache = shell.market_page.load_market_cache
    shell.bind_result_layers = shell.market_page.bind_result_layers
    shell.market = shell.market_page
    host.state.market = shell.market
    host.state.refresh_market = shell.refresh_market
    host.state.save_market_preferences = shell.save_market_preferences
    host.state.load_market_cache = shell.load_market_cache
    host.state.bind_result_layers = shell.bind_result_layers


def _mount_data_page(shell):
    host = shell.page_host
    shell.data_page = DataPage(host)
    shell.bars = shell.data_page.bars
    shell.calendar_path = shell.data_page.calendar_path
    shell.contract = shell.data_page.contract
    shell.data_card = shell.data_page.data_card
    shell.data_detail = shell.data_page.data_detail
    shell.days = shell.data_page.days
    shell.import_kind = shell.data_page.import_kind
    shell.import_path = shell.data_page.import_path
    shell.market_provider = shell.data_page.market_provider
    shell.network_data = shell.data_page.network_data
    shell.overview = shell.data_page.overview
    shell.summary = shell.data_page.summary
    shell.import_market_file = shell.data_page.import_market_file
    shell.import_market_history = shell.data_page.import_market_history
    shell.import_data = shell.data_page.import_data
    shell.download_data = shell.data_page.download_data
    host.state.bars = shell.bars
    host.state.calendar_path = shell.calendar_path
    host.state.contract = shell.contract
    host.state.data_card = shell.data_card
    host.state.data_detail = shell.data_detail
    host.state.days = shell.days
    host.state.import_kind = shell.import_kind
    host.state.import_path = shell.import_path
    host.state.market_provider = shell.market_provider
    host.state.network_data = shell.network_data
    host.state.overview = shell.overview
    host.state.summary = shell.summary
    host.state.import_market_file = shell.import_market_file
    host.state.import_market_history = shell.import_market_history
    host.state.import_data = shell.import_data
    host.state.download_data = shell.download_data


def _mount_strategy_page(shell):
    host = shell.page_host
    shell.strategy_page = StrategyPage(host)
    shell.campaign_config = shell.strategy_page.campaign_config
    shell.campaign_form = shell.strategy_page.campaign_form
    shell.candidate_card = shell.strategy_page.candidate_card
    shell.candidate_choice = shell.strategy_page.candidate_choice
    shell.candidate_detail = shell.strategy_page.candidate_detail
    shell.chatgpt_sign_in_entry = shell.strategy_page.chatgpt_sign_in_entry
    shell.evaluation_table = shell.strategy_page.evaluation_table
    shell.family = shell.strategy_page.family
    shell.history = shell.strategy_page.history
    shell.history_table = shell.strategy_page.history_table
    shell.manual_path = shell.strategy_page.manual_path
    shell.manual_response = shell.strategy_page.manual_response
    shell.parameters = shell.strategy_page.parameters
    shell.provider_mode = shell.strategy_page.provider_mode
    shell.strategy_detail = shell.strategy_page.strategy_detail
    shell.strategy_form = shell.strategy_page.strategy_form
    shell.use_candidate_button = shell.strategy_page.use_candidate_button
    shell.walk_forward_advanced = shell.strategy_page.walk_forward_advanced
    shell.walk_forward_advanced_group = shell.strategy_page.walk_forward_advanced_group
    shell.walk_forward_campaign = shell.strategy_page.walk_forward_campaign
    shell.walk_forward_choice = shell.strategy_page.walk_forward_choice
    shell.walk_forward_consent = shell.strategy_page.walk_forward_consent
    shell.walk_forward_form = shell.strategy_page.walk_forward_form
    shell.walk_forward_original = shell.strategy_page.walk_forward_original
    shell.walk_forward_preview = shell.strategy_page.walk_forward_preview
    shell.walk_forward_results = shell.strategy_page.walk_forward_results
    shell.walk_forward_saved_controls = shell.strategy_page.walk_forward_saved_controls
    shell.walk_forward_start = shell.strategy_page.walk_forward_start
    shell.walk_forward_status = shell.strategy_page.walk_forward_status
    shell._walk_forward_section = shell.strategy_page._walk_forward_section
    shell._connect_walk_forward_inputs = shell.strategy_page._connect_walk_forward_inputs
    shell._walk_forward_origin_changed = shell.strategy_page._walk_forward_origin_changed
    shell.pick_walk_forward_original = shell.strategy_page.pick_walk_forward_original
    shell._walk_forward_saved_source = shell.strategy_page._walk_forward_saved_source
    shell._invalidate_walk_forward_preview = shell.strategy_page._invalidate_walk_forward_preview
    shell._walk_forward_input_key = shell.strategy_page._walk_forward_input_key
    shell.preview_walk_forward = shell.strategy_page.preview_walk_forward
    shell.run_walk_forward = shell.strategy_page.run_walk_forward
    shell.read_walk_forward = shell.strategy_page.read_walk_forward
    shell._refresh_walk_forward_references = shell.strategy_page._refresh_walk_forward_references
    shell._walk_forward_event = shell.strategy_page._walk_forward_event
    shell._family_changed = shell.strategy_page._family_changed
    shell.run_campaign = shell.strategy_page.run_campaign
    shell.export_manual_request = shell.strategy_page.export_manual_request
    shell.inspect_candidate = shell.strategy_page.inspect_candidate
    shell.use_candidate = shell.strategy_page.use_candidate
    shell.use_builtin = shell.strategy_page.use_builtin


def _copy_strategy_state(shell):
    host = shell.page_host
    host.state.campaign_config = shell.campaign_config
    host.state.campaign_form = shell.campaign_form
    host.state.candidate_card = shell.candidate_card
    host.state.candidate_choice = shell.candidate_choice
    host.state.candidate_detail = shell.candidate_detail
    host.state.chatgpt_sign_in_entry = shell.chatgpt_sign_in_entry
    host.state.evaluation_table = shell.evaluation_table
    host.state.family = shell.family
    host.state.history = shell.history
    host.state.history_table = shell.history_table
    host.state.manual_path = shell.manual_path
    host.state.manual_response = shell.manual_response
    host.state.parameters = shell.parameters
    host.state.provider_mode = shell.provider_mode
    host.state.strategy_detail = shell.strategy_detail
    host.state.strategy_form = shell.strategy_form
    host.state.use_candidate_button = shell.use_candidate_button
    host.state.walk_forward_advanced = shell.walk_forward_advanced
    host.state.walk_forward_advanced_group = shell.walk_forward_advanced_group
    host.state.walk_forward_campaign = shell.walk_forward_campaign
    host.state.walk_forward_choice = shell.walk_forward_choice
    host.state.walk_forward_consent = shell.walk_forward_consent
    host.state.walk_forward_form = shell.walk_forward_form
    host.state.walk_forward_original = shell.walk_forward_original
    host.state.walk_forward_preview = shell.walk_forward_preview
    host.state.walk_forward_results = shell.walk_forward_results
    host.state.walk_forward_saved_controls = shell.walk_forward_saved_controls
    host.state.walk_forward_start = shell.walk_forward_start
    host.state.walk_forward_status = shell.walk_forward_status
    host.state._walk_forward_section = shell._walk_forward_section
    host.state._connect_walk_forward_inputs = shell._connect_walk_forward_inputs
    host.state._walk_forward_origin_changed = shell._walk_forward_origin_changed
    host.state.pick_walk_forward_original = shell.pick_walk_forward_original
    host.state._walk_forward_saved_source = shell._walk_forward_saved_source
    host.state._invalidate_walk_forward_preview = shell._invalidate_walk_forward_preview
    host.state._walk_forward_input_key = shell._walk_forward_input_key
    host.state.preview_walk_forward = shell.preview_walk_forward
    host.state.run_walk_forward = shell.run_walk_forward
    host.state.read_walk_forward = shell.read_walk_forward
    host.state._refresh_walk_forward_references = shell._refresh_walk_forward_references
    host.state._walk_forward_event = shell._walk_forward_event
    host.state._family_changed = shell._family_changed
    host.state.run_campaign = shell.run_campaign
    host.state.export_manual_request = shell.export_manual_request
    host.state.inspect_candidate = shell.inspect_candidate
    host.state.use_candidate = shell.use_candidate
    host.state.use_builtin = shell.use_builtin


def _mount_backtest_page(shell):
    host = shell.page_host
    shell.backtest_page = BacktestPage(host)
    shell.backtest_form = shell.backtest_page.backtest_form
    shell.batch = shell.backtest_page.batch
    shell.config = shell.backtest_page.config
    shell.end_date = shell.backtest_page.end_date
    shell.fills_table = shell.backtest_page.fills_table
    shell.plot = shell.backtest_page.plot
    shell.result_card = shell.backtest_page.result_card
    shell.result_choice = shell.backtest_page.result_choice
    shell.result_detail = shell.backtest_page.result_detail
    shell.run_button = shell.backtest_page.run_button
    shell.start_date = shell.backtest_page.start_date
    shell.run_backtest = shell.backtest_page.run_backtest
    shell.show_result = shell.backtest_page.show_result
    host.state.backtest_form = shell.backtest_form
    host.state.batch = shell.batch
    host.state.config = shell.config
    host.state.end_date = shell.end_date
    host.state.fills_table = shell.fills_table
    host.state.plot = shell.plot
    host.state.result_card = shell.result_card
    host.state.result_choice = shell.result_choice
    host.state.result_detail = shell.result_detail
    host.state.run_button = shell.run_button
    host.state.start_date = shell.start_date
    host.state.run_backtest = shell.run_backtest
    host.state.show_result = shell.show_result


def _mount_compare_page(shell):
    host = shell.page_host
    shell.compare_page = ComparePage(host, shell.strategy_page.analysis_layout)
    shell._analysis_section = shell.compare_page._analysis_section
    shell._invalidate_analysis_preview = shell.compare_page._invalidate_analysis_preview
    shell.pick_analysis_original = shell.compare_page.pick_analysis_original
    shell._analysis_request = shell.compare_page._analysis_request
    shell.preview_analysis = shell.compare_page.preview_analysis
    shell.run_analysis = shell.compare_page.run_analysis
    shell.read_analysis = shell.compare_page.read_analysis
    shell._analysis_saved_changed = shell.compare_page._analysis_saved_changed
    shell._selected_recovery_launch = shell.compare_page._selected_recovery_launch
    shell.reconcile_saved_analysis = shell.compare_page.reconcile_saved_analysis
    shell._recovery_display_fingerprint = shell.compare_page._recovery_display_fingerprint
    shell._refresh_recovery_controls = shell.compare_page._refresh_recovery_controls
    shell._analysis_event = shell.compare_page._analysis_event
    shell._refresh_analysis_saved = shell.compare_page._refresh_analysis_saved
    shell.select_strategy = shell.compare_page.select_strategy


def _mount_paper_page(shell):
    host = shell.page_host
    shell.paper_page = PaperPage(host)
    shell.load_form_file = shell.paper_page.load_form_file
    shell.demo_paper_policy = shell.paper_page.demo_paper_policy
    shell.paper_job = shell.paper_page.paper_job
    shell.kill_paper = shell.paper_page.kill_paper
    shell._show_account = shell.paper_page._show_account
    shell._remember_stop = shell.paper_page._remember_stop
    shell.freeze_paper = shell.paper_page.freeze_paper


def _mount_settings_page(shell):
    host = shell.page_host
    shell.settings_page = SettingsPage(host)
    shell.auto_restore_chatgpt = shell.settings_page.auto_restore_chatgpt
    shell.show_chatgpt_sign_in = shell.settings_page.show_chatgpt_sign_in
    shell._chatgpt_quiesce = shell.settings_page._chatgpt_quiesce
    shell._chatgpt_dispatch = shell.settings_page._chatgpt_dispatch
    shell._chatgpt_cancel = shell.settings_page._chatgpt_cancel
    shell._chatgpt_open_browser = shell.settings_page._chatgpt_open_browser
    shell._plan_usage_request = shell.settings_page._plan_usage_request
    shell._current_plan_binding = shell.settings_page._current_plan_binding
    shell.inspect_plan_usage = shell.settings_page.inspect_plan_usage
    shell._record_connection_error = shell.settings_page._record_connection_error
    shell._chatgpt_event = shell.settings_page._chatgpt_event
    shell.save_settings = shell.settings_page.save_settings
    shell.load_settings = shell.settings_page.load_settings
    shell.configure_workspace = shell.settings_page.configure_workspace
    shell.open_releases = shell.settings_page.open_releases
    shell.record_event = shell.settings_page.record_event
    shell.read_logs = shell.settings_page.read_logs
    shell.backup = shell.settings_page.backup
    host.state.chatgpt_panel = shell.chatgpt_panel
    host.state.chatgpt_controller = shell.chatgpt_controller


def _mount_view_coordinator(shell):
    host = shell.page_host
    shell.views_page = ViewCoordinator(host)
    shell.refresh_views = shell.views_page.refresh_views
    host.state.select_button = shell.select_button
    shell.chatgpt_panel.model.currentIndexChanged.connect(shell._invalidate_analysis_preview)
    shell.chatgpt_panel.timeout.valueChanged.connect(shell._invalidate_analysis_preview)
    shell.chatgpt_panel.account.currentIndexChanged.connect(shell._invalidate_analysis_preview)
    shell._connect_walk_forward_inputs()
