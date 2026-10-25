"""Desktop composition root for v2 process launch and legacy navigation."""

from pathlib import Path
import os
import subprocess
import sys
import time

from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.ipc import IpcFacade, read_session

_STARTED: dict[Path, subprocess.Popen] = {}


def default_root() -> Path:
    # Additive v2-only location. Never discovers v1 data or credential stores.
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'MarkAuto-v2' / 'local'


def ensure_engine(root: Path) -> IpcFacade:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    facade = IpcFacade(root)
    try:
        facade.snapshot()
        return facade
    except (OSError, EOFError, ValueError, DomainError):
        pass
    executable = Path(sys.executable).resolve()
    args = [str(executable)]
    if not getattr(sys, 'frozen', False):
        args.append(str(Path(__file__).with_name('desktop.py')))
    args.extend(('--trading-engine', str(root)))
    with (root / 'engine-startup.log').open('ab') as log:
        process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, close_fds=True
        )
        _STARTED[root] = process
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DomainError('startup_failed', 'v2 engine did not start; existing state retained')
        try:
            session = read_session(root)
            if session.process_id == process.pid:
                facade.snapshot()
                return facade
        except (OSError, EOFError, ValueError, DomainError):
            pass
        time.sleep(0.1)
    raise DomainError('startup_failed', 'v2 startup deadline; inspect owned process before retry')


def run_window(root: Path | None = None) -> int:
    from PySide6.QtWidgets import QApplication
    from desktop_trading import TradingWindow
    from desktop_icon import application_icon

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('MarkAuto v2')
    app.setWindowIcon(application_icon(app))
    facade = ensure_engine(root or default_root())
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


def shutdown(root: Path) -> None:
    facade = IpcFacade(root)
    state = facade.snapshot()
    receipt = facade.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
    if not receipt.accepted:
        raise DomainError(receipt.code)
    process = _STARTED.pop(root.resolve(), None)
    if process is not None:
        if process.wait(timeout=15) != 0:
            raise DomainError('operation_failed', 'owned engine did not exit cleanly')
