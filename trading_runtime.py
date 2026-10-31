"""Desktop composition root for v2 process launch and legacy navigation."""

from contextlib import closing
from pathlib import Path
import os
import sys

from desktop_app.strings.catalog import ui_text
from quantlab.runtime_support import WindowsAppMutex
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.context_client import RuntimeContextManager
from quantlab.trading.runtime.context_client import _STARTED as _STARTED, ensure_engine as ensure_engine, shutdown as shutdown


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
        return _run_window(
            root,
            environment=environment,
            account_ref=account_ref,
            profile_path=profile_path,
            contexts_path=contexts_path,
            research_bootstrap=research_bootstrap,
        )


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
    from desktop_app.features.trading.market_watch import MarketWatchWidget
    from desktop_app.components.charts import CandlestickChart

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
    window = TradingWindow(facade, initial, market_watch=MarketWatchWidget(facade, CandlestickChart(), initial))
    from desktop_app.research_session import ResearchSession, UnifiedResearch

    # One presenter/controller/session in the same Qt application. Explicit
    # test bootstraps never discover or restore the user's remembered login.
    research = UnifiedResearch(window, session=ResearchSession(window, bootstrap=research_bootstrap, restore_login=research_bootstrap is None))
    window.unified_research = research
    window.show()
    result = app.exec()
    # The normal close path already joins original workers and reconciles. An
    # externally requested event-loop exit must not unlock a still-busy session.
    if research.session.window is not None and not research.session._released:
        if not research.session.request_close():
            return 1
    # Engine intentionally remains independent when the interface closes.
    return result
