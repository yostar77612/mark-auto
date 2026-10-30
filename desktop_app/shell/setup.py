from desktop_app.shell.theme import apply_theme
from desktop_app.strings.catalog import ui_text
from PySide6.QtCore import QTimer, QPoint
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QStackedWidget, QFileDialog, QMessageBox, QApplication
from desktop_app.features.market.history_dialog import MarketHistoryDialog
from desktop_app.shell.mount import mount_pages
import desktop_app.components.job_progress as _job_progress
import desktop_app.shell.app_header as _app_header
import desktop_app.shell.notifications as _notifications
from desktop_app.shell.host import PageHost, PageState


def _install_window_support(window):
    from desktop_app.shell.polish import install_polish

    apply_theme(window)
    install_polish(window)
    from desktop_app.components.help import install_page_help

    install_page_help(window)
    from desktop_app.shell.shortcuts import install_shortcuts
    from desktop_app.shell.accessibility import install_accessibility

    install_shortcuts(window)
    install_accessibility(window)
    window.app_header.refresh()


def _initialize_window_state(window, paths, jobs, settings, backups, guard):
    window.page_state = PageState()
    from desktop_app.components.icon import application_icon

    window.setWindowIcon(application_icon(QApplication.instance()))
    window.paths, window.jobs, window.settings, window.backups, window.guard = (paths, jobs, settings, backups, guard)
    window.root = window.services.state_root(paths)
    window.actions = []
    window.last_operation = None
    window._ui_job_id = None
    window._wf_preview = None
    window._wf_request_key = None
    window._wf_launch = None
    window._wf_pending_reconcile = False
    window._wf_source_stamp = None
    window.active_candidate = None
    window._advanced_values = {}
    window._section_toggles = {}
    window._market_outcomes = {}
    window._campaign_data_hash = None
    window._chatgpt_job_request = None
    window._chatgpt_job_id = None
    window._plan_usage_binding = None
    window._subscription_campaign = False
    window._plan_launch = None
    window._pending_plan_reconcile = False
    window._pending_usage_refresh = False
    window._pending_chatgpt_restore = False
    window._analysis_preview = None
    window._analysis_request_key = None
    window._analysis_launch = None
    window._analysis_running = False
    window._pending_analysis_reconcile = False


def _build_window_chrome(window):
    window.setWindowTitle(ui_text('ui.init.window_title'))
    from desktop_app.shell.theme import MINIMUM_WINDOW_SIZE

    window.setMinimumSize(*MINIMUM_WINDOW_SIZE)
    window.resize(1366, 768)
    apply_theme(window)
    body = QWidget()
    outer = QVBoxLayout(body)
    _app_header.install_header(window, outer, window.services.paper_risk_limits().max_quote_age_seconds)
    horizontal = QHBoxLayout()
    outer.addLayout(horizontal, 1)
    window.navigation = QListWidget()
    window.navigation.setObjectName('navigation')
    window.navigation.setMaximumWidth(180)
    window.stack = QStackedWidget()
    from desktop_app.features.settings.preferences import install_sidebar

    install_sidebar(window, horizontal)
    window.status = QLabel(ui_text('ui.init.ready'))
    window.status.setObjectName('status')
    window.status.setWordWrap(True)
    outer.addWidget(window.status)
    _notifications.install_notifications(window, outer)
    _job_progress.install_progress(window, outer)
    window.setCentralWidget(body)


def _wire_page_host(window):
    window.page_state._section_toggles = window._section_toggles
    window.page_state._advanced_values = window._advanced_values
    window.page_state.paths = window.paths
    window.page_state.jobs = window.jobs
    window.page_state.settings = window.settings
    window.page_state.root = window.root
    window.page_state.status = window.status
    window.page_host = _create_page_host(window)
    window.page_state.save_sections = lambda: window.page_host.safe(window.page_host.save_sections)


def _mount_window_pages(window):
    mount_pages(window)
    window.strategy_page.bind_connection(window.chatgpt_controller, window.chatgpt_panel)
    window.app_header.bind_controls()
    window.privacy.attach_previews()
    from desktop_app.shell.onboarding import install_onboarding

    install_onboarding(window)
    window.navigation.currentRowChanged.connect(window.stack.setCurrentIndex)
    window.navigation.itemSelectionChanged.connect(window._navigate_selected_page)
    window.navigation.setCurrentRow(0)
    window.timer = QTimer(window)
    window.timer.timeout.connect(window.poll_jobs)
    window.timer.start(150)
    window._safe(window.refresh_views)
    window._safe(window.load_settings)
    window._busy(False)
    window.onboarding.refresh()
    window.onboarding.restore_visibility()
    _install_window_support(window)


def _create_page_host(window):
    return PageHost(
        state=window.page_state,
        callbacks={},
        find_child=window.findChild,
        window_screen=window.screen,
        resize_window=window.resize,
        move_window=window.move,
        question=lambda *a: QMessageBox.question(window, *a),
        open_file=lambda *a: QFileDialog.getOpenFileName(window, *a),
        save_file=lambda *a: QFileDialog.getSaveFileName(window, *a),
        market_history_dialog=lambda: MarketHistoryDialog(window),
        mount_market=lambda *a, **kw: window._mount_market(*a, **kw),
        mount_page=lambda *a, **kw: window._mount_page(*a, **kw),
        advanced=lambda *a, **kw: window._advanced(*a, **kw),
        bind_result_layers=lambda *a, **kw: window.market_page.bind_result_layers(*a, **kw),
        browse=lambda *a, **kw: window._browse(*a, **kw),
        button=lambda *a, **kw: window._button(*a, **kw),
        candidate_record=window.services.candidate_record,
        dataset=window.services.dataset,
        dataset_market_series=window.services.dataset_market_series,
        form_feedback=lambda *a, **kw: window.form_feedback(*a, **kw),
        inspect_plan_usage=lambda *a, **kw: window.inspect_plan_usage(*a, **kw),
        latest_market_observations=window.services.latest_market_observations,
        payload=lambda *a, **kw: window._payload(*a, **kw),
        plan_provider=window.services.plan_provider,
        record_event=lambda *a, **kw: window.record_event(*a, **kw),
        remember=lambda *a, **kw: window._remember(*a, **kw),
        result_snapshot_lines=lambda *a, **kw: window._result_snapshot_lines(*a, **kw),
        safe=lambda *a, **kw: window._safe(*a, **kw),
        save_sections=lambda *a, **kw: window._save_section_preferences(*a, **kw),
        show_account=lambda *a, **kw: window._show_account(*a, **kw),
        show_sign_in=lambda *a, **kw: window.show_chatgpt_sign_in(*a, **kw),
        start_job=lambda *a, **kw: window.start_job(*a, **kw),
        text=lambda *a, **kw: window._text(*a, **kw),
        window_geometry=lambda *a, **kw: window.geometry(*a, **kw),
        window_position=lambda: QPoint(window.x(), window.y()),
        window_minimum_size=lambda: (window.minimumWidth(), window.minimumHeight()),
        idea_records=window.services.idea_records,
        sample_market_series=window.services.sample_market_series,
    )


def configure_window(window, paths, jobs, settings=None, backups=None, guard=None):
    _initialize_window_state(window, paths, jobs, settings, backups, guard)
    _build_window_chrome(window)
    _wire_page_host(window)
    _mount_window_pages(window)
