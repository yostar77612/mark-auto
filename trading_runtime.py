"""Desktop composition root for v2 process launch and legacy navigation."""

from pathlib import Path
import os
import subprocess
import sys

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
) -> int:
    # Qt remains optional until the desktop entry is explicitly selected.
    from PySide6.QtWidgets import QApplication, QMessageBox

    # Presentation is assembled here, not imported by the application core.
    from desktop_trading import TradingWindow

    # Share the installed product icon without starting its legacy runtime.
    from desktop_icon import application_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('MarkAuto v2')
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
        QMessageBox.critical(None, 'MarkAuto v2', error.explanation + ' ' + error.action)
        return 1
    window = TradingWindow(facade, facade.snapshot())
    legacy = []

    def show_legacy(_page: str) -> None:
        # Reuse the complete existing desktop, rather than reimplementing its
        # research controls or touching any research data from v2.
        if legacy and legacy[0].poll() is None:
            return
        args = [sys.executable]
        if not getattr(sys, 'frozen', False):
            args.append(str(Path(__file__).with_name('desktop.py')))
        legacy[:] = [subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)]

    window.legacy_requested.connect(show_legacy)
    window.close_ui_requested.connect(window.close)
    window.show()
    result = app.exec()
    # Engine intentionally remains independent when the interface closes.
    return result
