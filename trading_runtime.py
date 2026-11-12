"""Desktop composition root for v2 process launch and legacy navigation."""

from contextlib import closing
from pathlib import Path
import logging
import os
import subprocess
import sys
from time import monotonic, sleep

from desktop_app.strings.catalog import ui_text
from quantlab.runtime_support import WindowsAppMutex
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.context_client import RuntimeContextManager
from quantlab.trading.runtime.context_client import _STARTED as _STARTED, ensure_engine as ensure_engine, shutdown as shutdown
from quantlab.trading.runtime.ipc import IpcFacade, read_session


def _close_window_engines(previous: dict) -> None:
    """Close only retained children launched during this desktop lifetime.

    Discovered/reused hosts have no new Popen handle and remain independent.
    A shutdown receipt is only an acknowledgement: success requires zero exit
    from the original retained process. Never terminate or search by name.
    """
    started = monotonic()
    deadline = started + 5
    errors = []
    for root, process in tuple(_STARTED.items()):
        if previous.get(root) is process:
            continue
        try:
            while process.poll() is None:
                try:
                    session = read_session(root)
                except FileNotFoundError:
                    # Startup can fail before publishing its endpoint. Give
                    # only this retained child the remaining close allowance.
                    if monotonic() >= deadline:
                        raise DomainError('outcome_unknown', 'owned engine endpoint unavailable') from None
                    sleep(0.02)
                    continue
                if session.process_id != process.pid:
                    raise DomainError('startup_workspace_busy', 'owned engine endpoint identity changed')
                args = process.args
                facade = IpcFacade(
                    root,
                    environment=Environment(args[args.index('--trading-environment') + 1]),
                    account_ref=args[args.index('--trading-account') + 1],
                )
                try:
                    for _ in range(3):
                        state = facade.snapshot()
                        if state.engine_state == 'CLOSED':
                            break
                        receipt = facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
                        if receipt.accepted:
                            break
                        if receipt.code != 'state_conflict':
                            raise DomainError(receipt.code)
                    else:
                        raise DomainError('state_conflict', 'owned engine shutdown remained stale')
                except FileNotFoundError:
                    # A concurrent normal close may remove the endpoint first.
                    # The original Popen must still confirm its own zero exit.
                    pass
                break
            if process.wait(timeout=max(0, deadline - monotonic())) != 0:
                raise DomainError('operation_failed', 'owned engine exited abnormally')
            if _STARTED.get(root) is process:
                _STARTED.pop(root)
            logging.getLogger(__name__).info('Owned engine %s exited normally after %.3fs', process.pid, monotonic() - started)
        except (DomainError, OSError, EOFError, subprocess.TimeoutExpired) as exc:
            errors.append(exc)
            logging.getLogger(__name__).error('Owned engine %s shutdown unconfirmed (%s)', process.pid, type(exc).__name__)
    if errors:
        raise DomainError('outcome_unknown', 'owned engine shutdown unconfirmed; retained processes were not terminated') from errors[0]


def default_root() -> Path:
    # Additive v2-only location. Never discovers v1 data or credential stores.
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'MarkAuto-v2' / 'local'


def run_window(
    root: Path | None = None,
    *,
    environment: Environment | None = None,
    account_ref: str | None = None,
    profile_path: Path | None = None,
    contexts_path: Path | None = None,
    research_bootstrap: Path | None = None,
) -> int:
    # UI and independent engine each own a handle to the existing installer
    # presence guard. Closing one lifetime must not expose the other's files.
    from quantlab.update_install import cancel_pending_install, launch_pending_install, pending_install

    try:
        with closing(WindowsAppMutex()):
            previous = dict(_STARTED)
            try:
                result = _run_window(
                    root,
                    environment=environment,
                    account_ref=account_ref,
                    profile_path=profile_path,
                    contexts_path=contexts_path,
                    research_bootstrap=research_bootstrap,
                )
            finally:
                _close_window_engines(previous)
    except (DomainError, OSError):
        if not pending_install():
            raise
        _abort_update('update_shutdown_failed')
        return 1
    if result != 0:
        cancel_pending_install()
        return result
    # All retained child exits are confirmed and our guard has been released.
    # The independent helper additionally waits for this exact desktop PID and
    # refuses another application/engine's still-present installation guard.
    try:
        launch_pending_install(
            lambda command: subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        )
    except OSError:
        _abort_update('update_install_start_failed')
        return 1
    return result


def _abort_update(code: str) -> None:
    from PySide6.QtWidgets import QMessageBox
    from quantlab.desktop_errors import error_message
    from quantlab.update_install import cancel_pending_install

    try:
        cancel_pending_install()
    except OSError:
        # A complete download can remain when the OS refuses removal; no
        # installer is launched and no installed/user file has been touched.
        logging.getLogger(__name__).error('Update temporary download cleanup refused')
    QMessageBox.critical(None, 'MarkAuto', error_message(code))


def _presentation_options(root: Path) -> dict:
    from quantlab.research_core.adapters.settings_store import SettingsStore

    store = SettingsStore(root / 'trading-presentation-v1.json')
    try:
        saved = store.load()
    except (OSError, ValueError, RuntimeError):
        saved = {}

    def save(key, values):
        current = store.load()
        current[key] = list(values)
        store.save(current)

    return {
        'position_columns': saved.get('position_columns'),
        'save_position_columns': lambda values: save('position_columns', values),
        'order_columns': saved.get('order_columns'),
        'save_order_columns': lambda values: save('order_columns', values),
        'strategy_columns': saved.get('strategy_columns'),
        'save_strategy_columns': lambda values: save('strategy_columns', values),
    }


def _run_window(
    root: Path | None = None,
    *,
    environment: Environment | None = None,
    account_ref: str | None = None,
    profile_path: Path | None = None,
    contexts_path: Path | None = None,
    research_bootstrap: Path | None = None,
) -> int:
    # Qt remains optional until the desktop entry is explicitly selected.
    from PySide6.QtWidgets import QApplication, QMessageBox

    # Presentation is assembled here, not imported by the application core.
    from desktop_app.features.trading import TradingWindow
    from desktop_app.features.trading.market_terminal import MarketTerminalWidget
    from desktop_app.features.trading.market_alerts_ui import AlertPanelController
    from desktop_app.features.trading.market_terminal_layout import OPTIONAL_PANELS, PANEL_IDS, terminal_preset
    from desktop_app.components.charts import CandlestickChart
    from quantlab.research_core.adapters.market_layout import LayoutStore
    from quantlab.trading.adapters.storage.startup_preferences import StartupPreferences
    from desktop_app.features.market.workspace import WorkspacePanel
    from desktop_app.shell.theme import (
        up_down_colors,
        appearance,
        _apply_terminal_theme,
        _apply_trading_page_theme,
        style_strategy_table,
        style_automatic_controls,
    )

    # Share the installed product icon without starting its legacy runtime.
    from desktop_app.components.icon import application_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from quantlab import __version__

    app.setApplicationName('MarkAuto')
    app.setOrganizationName('MarkAuto')
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon(app))
    from quantlab.autostart import installed_autostart, repair_autostart
    from quantlab.desktop_errors import error_message
    from quantlab.update_download import download_installer
    from quantlab.update_install import can_install, cancel_pending_install, queue_install

    app.setProperty('autostartController', installed_autostart())
    app.setProperty('maintenanceDownload', download_installer)
    app.setProperty('maintenanceCanInstall', can_install)
    app.setProperty('maintenanceQueueInstall', queue_install)
    app.setProperty('maintenanceCancelInstall', cancel_pending_install)

    autostart_error = repair_autostart()
    if autostart_error:
        QMessageBox.warning(None, 'MarkAuto', error_message(autostart_error))
    try:
        contexts = RuntimeContextManager(root or default_root(), contexts_path)
        selected, account = contexts.selected_context, account_ref or contexts.selected_account
        if environment is not None:
            account = account_ref or ('local-stock' if environment is Environment.LOCAL else '')
            if not account:
                raise DomainError('validation_failed', 'non-local account alias must be explicitly selected')
            selected = contexts.configure_launch(environment, account, profile_path)
        current = contexts.open_context(selected, account)
        contexts.persist_selection(selected, account)
        facade = CompositeFacade(contexts, selected, current)
    except (OSError, ValueError) as exc:
        error = ERROR_TABLE.get(exc.code if isinstance(exc, DomainError) else 'startup_failed', ERROR_TABLE['startup_failed'])
        QMessageBox.critical(None, ui_text('v2.title'), error.explanation + ' ' + error.action)
        return 1
    initial = facade.snapshot()
    layout_store = LayoutStore(
        root or default_root(),
        panel_ids=PANEL_IDS,
        areas=('left', 'center', 'right'),
        file_name='market-terminal-layout-v1.json',
        default_layout=terminal_preset(),
        optional_panels=OPTIONAL_PANELS,
    )

    def notify_alert(message):
        host = research.session.window
        if host is not None:
            host.notify_local(message, completion=True)

    # The alert panel renders restored events while it is constructed, before the
    # terminal that hosts it exists: names fall back to codes, colours to defaults.
    terminal = None
    alerts = AlertPanelController(
        facade.alerts,
        lambda operation, completed: terminal._submit(operation, completed),
        lambda: terminal.current_instrument,
        lambda key, occurred_at: terminal.select_instrument(key, occurred_at),
        lambda key: next((item.name for item in (terminal._directory if terminal else ()) if item.instrument_id == key), key.split(':')[-1]),
        notify_alert,
        lambda: up_down_colors(appearance(terminal)[1]),
    )
    terminal = MarketTerminalWidget(
        facade,
        CandlestickChart(),
        initial,
        layout_store=layout_store,
        index_chart=CandlestickChart(show_volume=False),
        panel_factory=WorkspacePanel,
        colours=lambda widget: up_down_colors(appearance(widget)[1]),
        alerts_panel=alerts.panel,
        style_terminal=_apply_terminal_theme,
    )
    from desktop_app.components.async_status import AsyncStatus

    from desktop_app.features.trading.sector_board import SectorBoardWidget

    sector_board = SectorBoardWidget(
        facade,
        CandlestickChart(),
        colours=lambda widget: up_down_colors(appearance(widget)[1]),
        open_in_watch=lambda key: (window.market_tabs.setCurrentWidget(terminal), terminal.select_instrument(key)),
        add_to_watch=lambda key: terminal.add_watch(key),
    )
    alerts.panel.select_sector = lambda group_id: (window.market_tabs.setCurrentWidget(sector_board), sector_board.select_group(group_id))
    window = TradingWindow(
        facade,
        initial,
        market_watch=terminal,
        sector_board=sector_board,
        strategy_error_texts={code: (text.explanation, text.action) for code, text in ERROR_TABLE.items()},
        style_strategy_table=style_strategy_table,
        style_automatic_controls=style_automatic_controls,
        research_status_factory=AsyncStatus,
        startup_preferences=StartupPreferences(root or default_root()),
        auto_preflight=True,
        **_presentation_options(root or default_root()),
    )
    app.setProperty('maintenanceRequestClose', window.close)
    _apply_trading_page_theme(window)
    from desktop_app.research_session import ResearchSession, UnifiedResearch

    # One presenter/controller/session in the same Qt application. Explicit
    # test bootstraps never discover or restore the user's remembered login.
    research = UnifiedResearch(window, session=ResearchSession(window, bootstrap=research_bootstrap, restore_login=research_bootstrap is None))
    window.unified_research = research
    alerts.setParent(window)
    window.alert_controller = alerts
    alerts.panel.latest_changed.connect(terminal.set_latest_alert)
    app.aboutToQuit.connect(alerts.stop)
    alerts.start()
    window.show()
    result = app.exec()
    # The normal close path already joins original workers and reconciles. An
    # externally requested event-loop exit must not unlock a still-busy session.
    if research.session.window is not None and not research.session._released:
        if not research.session.request_close():
            return 1
    # run_window confirms all children started by this desktop have exited
    # before releasing the install guard. Reused hosts remain independent.
    return result
