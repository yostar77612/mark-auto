"""Real GUI/engine process exit, subscription cleanup and workspace release."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import unittest

from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime import context_client
from quantlab.trading.runtime.ipc import read_session
from tools.owned_trading_engine import OwnedEngineProcesses, source_environment, source_python

ROOT = Path(__file__).resolve().parents[1]


class SourceEngines(OwnedEngineProcesses):
    """Inject only the fake provider inside an otherwise real engine child."""

    def __init__(self, mutex_name):
        super().__init__()
        self.mutex_name = mutex_name

    def _start(self, arguments, **options):
        arguments = list(arguments)
        arguments[1] = str(Path(__file__).resolve())
        arguments.insert(1, '-S')
        arguments.extend(('--test-host', '--test-mutex', self.mutex_name))
        return super()._start(arguments, **options)


def mutex_exists(name):
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenMutexW(0x00100000, False, name)
    if handle:
        kernel.CloseHandle(handle)
        return True
    assert ctypes.get_last_error() == 2, 'mutex availability could not be verified'
    return False


def host(args):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from quantlab.trading.adapters.shioaji.market_session import MarketSession
    from quantlab.trading.adapters.shioaji.sdk import SDK_VERSION
    from quantlab.trading.runtime import server
    from quantlab.trading.runtime.config import RuntimeLaunch
    from tests.test_alert_service import fake_sdk
    from tests.test_market_session import FakeApi, FakeSecrets

    root = args.trading_engine

    class Api(FakeApi):
        def subscribe(self, contract, **kwargs):
            super().subscribe(contract, **kwargs)
            (root / 'subscribed').touch()

        def kbars(self, **kwargs):
            (root / 'history-started').touch()
            if (root / 'pending').exists():
                # A real in-flight provider call; logout releases the fixture.
                (root / 'history-pending').touch()
                until = time.monotonic() + 8
                while not (root / 'logged-out').exists() and time.monotonic() < until:
                    time.sleep(0.01)
            result = super().kbars(**kwargs)
            (root / 'history-finished').touch()
            return result

        def logout(self):
            super().logout()
            (root / 'logged-out').touch()

        def unsubscribe(self, contract, **kwargs):
            super().unsubscribe(contract, **kwargs)
            (root / 'unsubscribed').touch()

    api = Api()
    sdk = fake_sdk()
    sdk.__version__ = SDK_VERSION
    sdk.Shioaji = lambda **kwargs: api
    sdk.QuoteType = sdk.QuoteVersion = lambda value: value
    clock = SimpleNamespace(now=lambda: datetime.now(timezone.utc))
    build = server.build_runtime

    def compose(*values, **keywords):
        bundle = build(*values, **keywords)
        bundle.market_connection.factory = lambda settings, directory: MarketSession(settings, FakeSecrets(), sdk, clock, directory)
        return bundle

    launch = RuntimeLaunch(root, Environment(args.trading_environment), account_ref=args.trading_account)
    with patch.object(server, 'build_runtime', side_effect=compose), patch('quantlab.runtime_support.WINDOWS_APP_MUTEX', args.test_mutex):
        return server.serve(root, launch=launch)


def window(args):
    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtWidgets import QApplication

    from desktop_app.features.trading import TradingWindow
    from quantlab.trading.application.market_settings import MarketDataSettings
    from quantlab.trading.runtime.ipc import IpcFacade
    import trading_runtime

    app = QApplication([])
    root = args.window
    root.mkdir()
    report = {'mode': args.mode, 'pending': args.pending}
    mutex_name = 'Local\\MarkAuto.ExitTest.' + sha256(str(root).encode()).hexdigest()[:24]
    show = TradingWindow.show
    closed_at = []

    def shown(widget):
        show(widget)
        report['visible'] = widget.isVisible()
        assert widget.unified_research.ensure_open(), 'real isolated research workspace did not open'
        report['research_lock_path'] = str(widget.unified_research.session.state.locator.lock_path)
        widget.setProperty('allow_close_for_tests', True)
        engine_root, process = next(reversed(context_client._STARTED.items()))
        report['engine_pid'] = process.pid
        if args.pending:
            (engine_root / 'pending').touch()
        facade = IpcFacade(engine_root, environment=Environment(args.mode), account_ref='local-stock' if args.mode == 'LOCAL' else 'simulation-stock')
        settings = MarketDataSettings(Environment.BROKER_SIMULATION, enabled=True)
        for action in (UiAction.SAVE_MARKET_DATA_SETTINGS, UiAction.CONNECT_MARKET_DATA):
            state = facade.snapshot()
            receipt = facade.execute(UiCommand(action, state.version, market_data_settings=settings))
            assert receipt.accepted, receipt
        until = time.monotonic() + 10

        def close_when_ready():
            try:
                subscribed = (engine_root / 'subscribed').exists()
                pending = (engine_root / 'history-started').exists()
                if not subscribed or args.pending and not pending:
                    assert time.monotonic() < until, 'fixture did not reach subscribed/pending state'
                    QTimer.singleShot(20, close_when_ready)
                    return
                report['subscribed_at_close'] = subscribed
                report['history_started_at_close'] = pending
                report['history_pending_at_close'] = (engine_root / 'history-pending').exists() and not (engine_root / 'history-finished').exists()
                report['mutex_present_before_close'] = mutex_exists(mutex_name)
                if not closed_at:
                    closed_at.append(time.monotonic())
                    (root / 'close-requested.json').write_text(json.dumps(closed_at[-1]))
                accepted = widget.close()
                if not accepted:
                    assert time.monotonic() < until, 'window kept rejecting close'
                    QTimer.singleShot(20, close_when_ready)
            except BaseException as error:
                report['error'] = str(error)
                app.exit(1)

        QTimer.singleShot(100, close_when_ready)

    with SourceEngines(mutex_name) as owned, patch.object(TradingWindow, 'show', shown), patch('quantlab.runtime_support.WINDOWS_APP_MUTEX', mutex_name):
        report['return_code'] = trading_runtime.run_window(
            root,
            environment=Environment(args.mode),
            account_ref='local-stock' if args.mode == 'LOCAL' else 'simulation-stock',
            research_bootstrap=root / 'display-bootstrap',
        )
        report['close_seconds'] = time.monotonic() - closed_at[-1] if closed_at else None
        # Observe BEFORE test containment, so fixture cleanup cannot hide a leak.
        report['engines'] = [{'pid': p.pid, 'exit_code': p.poll()} for p, _ in owned.owned]
        report['endpoints_removed'] = not tuple(root.rglob('engine-session-v2.json'))
        report['sdk_logged_out'] = all((launch.root / 'logged-out').exists() for _, launch in owned.owned)
        report['unsubscribed'] = all((launch.root / 'unsubscribed').exists() for _, launch in owned.owned)
        report['mutex_released'] = mutex_exists(mutex_name) is False if os.name == 'nt' else None
        lock = QLockFile(report['research_lock_path'])
        report['research_lock_released'] = lock.tryLock(0)
        if report['research_lock_released']:
            lock.unlock()
        report['real_sdk_imported'] = 'shioaji' in sys.modules
        # Reopening the exact engine workspace proves the journal lease released.
        from quantlab.trading.runtime.bootstrap import build_runtime

        for p, launch in owned.owned:
            if p.poll() == 0:
                bundle = build_runtime(launch)
                bundle.close()
    print(json.dumps(report), flush=True)
    return 0


class GracefulExitProcessTests(unittest.TestCase):
    def test_subscribed_windows_and_pending_history_exit_with_all_owned_children(self):
        for mode, pending in (('LOCAL', False), ('BROKER_SIMULATION', False), ('BROKER_SIMULATION', True)):
            with self.subTest(mode=mode, pending=pending), tempfile.TemporaryDirectory(prefix='markauto-exit-') as folder:
                args = [source_python(), '-S', str(Path(__file__).resolve()), '--window', str(Path(folder) / 'workspace'), '--mode', mode]
                if pending:
                    args.append('--pending')
                result = subprocess.run(args, cwd=ROOT, env=source_environment(), capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, 0, result.stderr)
                process_exit_seconds = time.monotonic() - json.loads((Path(folder) / 'workspace' / 'close-requested.json').read_text())
                report = json.loads(result.stdout.splitlines()[-1])
                report['process_exit_seconds'] = process_exit_seconds
                print(json.dumps(report), flush=True)
                self.assertNotIn('error', report)
                self.assertTrue(report['visible'])
                self.assertTrue(report['subscribed_at_close'])
                self.assertEqual(report['return_code'], 0)
                self.assertLess(report['close_seconds'], 5)
                self.assertLess(report['process_exit_seconds'], 5)
                self.assertTrue(report['engines'])
                self.assertTrue(all(row['exit_code'] == 0 for row in report['engines']), report)
                self.assertTrue(report['endpoints_removed'])
                self.assertTrue(report['sdk_logged_out'])
                self.assertTrue(report['unsubscribed'])
                self.assertTrue(report['research_lock_released'])
                if os.name == 'nt':
                    self.assertTrue(report['mutex_present_before_close'])
                    self.assertTrue(report['mutex_released'])
                self.assertFalse(report['real_sdk_imported'])
                if pending:
                    self.assertTrue(report['history_started_at_close'])
                    self.assertTrue(report['history_pending_at_close'])


class OwnedWindowEngineTests(unittest.TestCase):
    def setUp(self):
        scope = self.enterContext(tempfile.TemporaryDirectory(dir=ROOT))
        self.root = Path(scope)
        self.owned = self.enterContext(OwnedEngineProcesses())

    def test_multiple_children_exit_but_preexisting_host_is_untouched(self):
        import trading_runtime

        foreign = context_client.ensure_engine(self.root / 'foreign')
        previous = dict(context_client._STARTED)
        for name in ('first', 'second'):
            context_client.ensure_engine(self.root / name)
        start = time.monotonic()
        trading_runtime._close_window_engines(previous)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual([p.poll() for p, _ in self.owned.owned], [None, 0, 0])
        self.assertEqual(foreign.snapshot().environment, Environment.LOCAL)

    def test_startup_body_exception_still_closes_exact_owned_child(self):
        import trading_runtime

        def fail(*args, **kwargs):
            context_client.ensure_engine(self.root / 'failed-window')
            raise RuntimeError('controlled window startup failure')

        with patch.object(trading_runtime, '_run_window', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'controlled window startup failure'):
            trading_runtime.run_window(self.root)
        self.assertEqual(self.owned.owned[0][0].poll(), 0)

    def test_changed_endpoint_owner_is_not_sent_shutdown_and_handle_is_retained(self):
        import trading_runtime

        root = self.root / 'identity'
        facade = context_client.ensure_engine(root)
        process = self.owned.owned[0][0]
        path = root / 'engine-session-v2.json'
        original = path.read_bytes()
        body = json.loads(original)
        body['process_id'] = os.getpid()
        path.write_text(json.dumps(body))
        try:
            from quantlab.trading.domain.validation import DomainError

            with self.assertRaises(DomainError):
                trading_runtime._close_window_engines({})
            self.assertIsNone(process.poll())
            self.assertIs(context_client._STARTED[root], process)
        finally:
            path.write_bytes(original)
        self.assertEqual(read_session(root).process_id, process.pid)
        self.assertNotEqual(facade.snapshot().engine_state, 'CLOSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-host', action='store_true')
    parser.add_argument('--test-mutex')
    parser.add_argument('--trading-engine', type=Path)
    parser.add_argument('--trading-environment')
    parser.add_argument('--trading-account')
    parser.add_argument('--window', type=Path)
    parser.add_argument('--mode', default='LOCAL')
    parser.add_argument('--pending', action='store_true')
    options = parser.parse_args()
    if options.test_host:
        raise SystemExit(host(options))
    if options.window:
        raise SystemExit(window(options))
    unittest.main()
