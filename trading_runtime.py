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
    with closing(WindowsAppMutex()):
        previous = dict(_STARTED)
        try:
            return _run_window(
                root,
                environment=environment,
                account_ref=account_ref,
                profile_path=profile_path,
                contexts_path=contexts_path,
                research_bootstrap=research_bootstrap,
            )
        finally:
            _close_window_engines(previous)


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
    from desktop_app.features.trading.market_terminal_layout import PANEL_IDS, terminal_preset
    from desktop_app.components.charts import CandlestickChart
    from quantlab.research_core.adapters.market_layout import LayoutStore
    from desktop_app.features.market.workspace import WorkspacePanel
    from desktop_app.shell.theme import up_down_colors, appearance, _apply_terminal_theme, _apply_trading_page_theme

    # Share the installed product icon without starting its legacy runtime.
    from desktop_app.components.icon import application_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from quantlab import __version__

    app.setApplicationName('MarkAuto')
    app.setOrganizationName('MarkAuto')
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon(app))
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
        root or default_root(), panel_ids=PANEL_IDS, areas=('left', 'center'), file_name='market-terminal-layout-v1.json', default_layout=terminal_preset()
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
    window = TradingWindow(
        facade,
        initial,
        market_watch=terminal,
        **_presentation_options(root or default_root()),
    )
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
