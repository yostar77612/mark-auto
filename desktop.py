"""Frozen Windows desktop entry point; no web server, browser, or Python setup."""

from __future__ import annotations
from desktop_strings import ui_text
from quantlab.desktop_errors import error_message, startup_error_code

import argparse
import multiprocessing
from pathlib import Path
import sys

from desktop_smoke import (
    _SmokeSettingsView,
    _auth_smoke_dependencies,
    _smoke_steps,
    _market_smoke_ui,
    _market_smoke_response,
    _check_market_worker_result,
    _history_smoke_fixture,
    _check_history_worker_result,
    _history_smoke_ui,
    _walk_forward_smoke_fixture,
    _check_walk_forward_smoke_result,
    _start_smoke_job,
    _close_smoke_worker,
    _retain_smoke_directory,
    run_smoke,
)


def _prepare_startup_workspace(paths, backups):
    """Serialize startup recovery; an unresolved analysis is not a global lockout."""
    from quantlab.analysis_recovery import admission, inspect_recovery, recover_control_journal, RecoveryError

    with admission(paths) as token:
        # SQLite may roll back only its own validated original hot journal. No
        # missing ledger or receipt is created; corrupt controls stay unknown.
        try:
            recover_control_journal(paths, admission=token)
            disposition = inspect_recovery(paths)
        except RecoveryError:
            disposition = None
        if disposition is None or disposition.unresolved:
            ambiguous = not paths.state.is_dir() or any(
                path.exists() or path.is_symlink()
                for path in (paths.root / 'state-v1.rollback', paths.root / 'restore-transaction.json', paths.state / '.restore-transaction')
            )
            if ambiguous:
                raise RecoveryError('Unknown original analysis stop state and ambiguous workspace restore layout')
            # Keep intact state in place for bounded non-AI use. None means
            # unknown initialized controls, never a clean/legacy disposition.
        else:
            backups.recover()
        paths.ensure()
        return disposition


def _offer_workspace_after_recovery_block(locator):
    """One bounded, user-directed choice; never repair or reset unknown controls."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    box = QMessageBox(
        QMessageBox.Icon.Warning,
        ui_text('desktop.offer_workspace_after_recovery_block.reconciliation_title'),
        ui_text('desktop.offer_workspace_after_recovery_block.recovery_blocked'),
        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
    )
    box.button(QMessageBox.StandardButton.Open).setText(ui_text('desktop.offer_workspace_after_recovery_block.choose_workspace'))
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    if box.exec() != QMessageBox.StandardButton.Open:
        return
    selected = QFileDialog.getExistingDirectory(None, ui_text('desktop.offer_workspace_after_recovery_block.dialog_title'))
    if not selected:
        return
    try:
        locator.configure(Path(selected))
    except (OSError, ValueError):
        QMessageBox.warning(
            None,
            ui_text('desktop.offer_workspace_after_recovery_block.unchanged_title'),
            ui_text('desktop.offer_workspace_after_recovery_block.invalid_directory'),
        )
        return
    QMessageBox.information(
        None, ui_text('desktop.offer_workspace_after_recovery_block.configured_title'), ui_text('desktop.offer_workspace_after_recovery_block.restart_hint')
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='MarkAuto native desktop research and paper trading')
    parser.add_argument('--smoke-test', type=Path, help='Show real native window, write launch report, then exit')
    parser.add_argument('--smoke-isolated', action='store_true', help='Smoke only: do not discover or read the user bootstrap/settings')
    parser.add_argument('--tls-smoke', type=Path, help='Explicit frozen Python TLS proof against an ephemeral loopback fixture')
    args = parser.parse_args(argv)
    if args.tls_smoke is not None:
        if args.smoke_test or not args.tls_smoke.is_absolute():
            parser.error('--tls-smoke requires an absolute report path and cannot combine with --smoke-test')
    if args.smoke_test is not None and not args.smoke_test.is_absolute():
        parser.error('--smoke-test requires an absolute report path')
    if args.smoke_isolated and args.smoke_test is None:
        parser.error('--smoke-isolated requires --smoke-test')
    return args


def acquire_instance_lock(locator, smoke_startup_directory=None):
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QMessageBox

    lock = QLockFile(str(locator.lock_path))
    lock.setStaleLockTime(0)  # Qt checks process liveness; never steal a live lock by age.
    if not lock.tryLock(0):
        QMessageBox.information(None, ui_text('desktop.main.startup_failed'), error_message('startup_workspace_busy'))
        if smoke_startup_directory is not None:
            smoke_startup_directory.cleanup()
        return None
    return lock


def prepare_workspace(state):
    from quantlab.desktop_runtime import BackupManager, JobManager, RuntimeGuard, SettingsStore, WorkspaceLocator, WindowsAppMutex

    state.installation_guard = WindowsAppMutex()
    state.paths = state.locator.load(probe=False)
    state.backups = BackupManager(state.paths)
    from quantlab.analysis_recovery import RecoveryError

    try:
        _prepare_startup_workspace(state.paths, state.backups)
    except RecoveryError:
        if state.args.smoke_test:
            raise
        _offer_workspace_after_recovery_block(state.locator)
        return False
    state.guard = RuntimeGuard(state.paths)
    state.previous_unclean = state.guard.start()
    use_user_snapshot = state.args.smoke_test and not getattr(state.args, 'smoke_isolated', False)
    state.settings_paths = WorkspaceLocator(state.user_bootstrap).load(probe=False) if use_user_snapshot else state.paths
    state.settings = SettingsStore(state.settings_paths.state / 'settings.json')
    state.validated_settings = state.settings.load()  # Fail closed on incompatible/corrupt state.
    if state.args.smoke_test:
        state.settings = _SmokeSettingsView(state.validated_settings)  # Smoke must preserve saved user bytes.
    state.jobs = JobManager(state.paths)
    state.backups.jobs = state.jobs
    return True


def run_gui(args):
    from types import SimpleNamespace

    state = SimpleNamespace(args=args)
    from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from quantlab import __version__
    from quantlab.desktop_runtime import (
        AppPaths,
        BackupManager,
        JobManager,
        RuntimeGuard,
        SettingsStore,
        WorkspaceLocator,
        WindowsAppMutex,
        atomic_write,
        _json_bytes,
    )

    # Keep existing dependency imports in place; measure only GUI initialization.
    from quantlab.startup_timing import StartupTiming

    state.startup_timing = StartupTiming()
    state.app = QApplication(sys.argv[:1])
    from desktop_icon import application_icon

    state.app.setWindowIcon(application_icon(state.app))
    state.app.setApplicationName('MarkAuto')
    state.app.setOrganizationName('MarkAuto')
    state.app.setApplicationVersion(__version__)
    state.startup_timing.mark('application')
    isolated_smoke = bool(state.args.smoke_test and getattr(state.args, 'smoke_isolated', False))
    state.user_bootstrap = None if isolated_smoke else AppPaths.discover().root
    state.smoke_startup_directory = None
    if state.args.smoke_test:
        import tempfile

        # Isolate even GUI startup, recovery, guards and paper freeze. Only the
        # validated user settings snapshot is read from the configured workspace.
        from quantlab.windows_paths import native_path

        # The extended spelling propagates through recursive fixture cleanup.
        temporary_root = native_path(tempfile.gettempdir(), force=True) if isolated_smoke else None
        state.smoke_startup_directory = tempfile.TemporaryDirectory(prefix='markauto-smoke-startup-', dir=temporary_root)
    state.bootstrap = Path(state.smoke_startup_directory.name) if state.smoke_startup_directory else state.user_bootstrap
    state.bootstrap.mkdir(parents=True, exist_ok=True)
    state.locator = WorkspaceLocator(state.bootstrap)
    state.lock = acquire_instance_lock(state.locator, state.smoke_startup_directory)
    if state.lock is None:
        return 2
    state.startup_timing.mark('bootstrap')
    state.jobs = state.guard = state.installation_guard = None
    state.smoke_jobs = state.smoke_directory = None
    state.settings_paths = None
    state.smoke_cleanup_verified = True
    state.smoke_shutdown_completed = False
    state.smoke_report = None
    try:
        if not prepare_workspace(state):
            return 3
        state.startup_timing.mark('workspace')
        from desktop_ui import MainWindow

        state.window = MainWindow(state.paths, state.jobs, settings=state.settings, backups=state.backups, guard=state.guard)
        page_state = getattr(state.window, 'page_state', None)
        if page_state is not None:
            page_state.startup_timing = state.startup_timing
        state.window.show()
        state.startup_timing.mark('window')
        if hasattr(state.window, 'freeze_paper'):
            state.window.freeze_paper(
                'Previous session ended unexpectedly; reconcile paper account' if state.previous_unclean else 'Startup requires paper reconciliation'
            )
        if not state.args.smoke_test and hasattr(state.window, 'auto_restore_chatgpt'):
            # Remembered login: reload the saved ChatGPT credentials (smoke runs stay inert).
            state.window.auto_restore_chatgpt()

        # Windows suspend/resume notifications complement wall/monotonic checks,
        # including short sleeps and platforms whose monotonic clock pauses.
        class PowerEvents(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if sys.platform == 'win32':
                    import ctypes
                    from ctypes import wintypes

                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0218 and msg.wParam in (4, 6, 7, 18):
                        state.guard.reconciliation_required = True
                        if hasattr(state.window, 'freeze_paper'):
                            state.window._safe(lambda: state.window.freeze_paper('Windows power event; reconcile paper account before resuming'))
                return False, 0

        power_events = PowerEvents()
        state.app.installNativeEventFilter(power_events)
        timer = QTimer(state.window)
        timer.setInterval(1000)

        def clock_tick():
            if state.guard.check_clock():
                if hasattr(state.window, 'freeze_paper'):
                    state.window._safe(lambda: state.window.freeze_paper('Sleep or clock change detected; reconcile paper account before resuming'))

        timer.timeout.connect(clock_tick)
        timer.start()
        state.startup_timing.mark('ready')
        if state.args.smoke_test:
            run_smoke(state)
        status = state.app.exec()
        state.jobs.close()
        state.guard.finish()
        state.smoke_shutdown_completed = True
        return status
    except Exception as exc:
        # No exception values or secret-bearing tracebacks in a general GUI dialog.
        if state.args.smoke_test:
            if state.smoke_report is None:
                state.smoke_report = {
                    'status': 'failed',
                    'version': __version__,
                    'data_dir': str(state.settings_paths.root) if state.settings_paths else None,
                    'smoke_data_dir': str(state.bootstrap),
                    'user_state_read_only': True,
                    'user_state_access': 'none' if getattr(state.args, 'smoke_isolated', False) else 'read_only',
                    'steps': [],
                    'source_type': 'synthetic',
                    'generator': 'fixture',
                    'live_status': 'disabled',
                    'walk_forward_smoke': {
                        'status': 'failed',
                        'error_type': type(exc).__name__,
                        'source_type': 'synthetic',
                        'real_model_status': 'not_verified',
                        'scope': 'engineering synthetic packaging smoke only; never actual research PASS or Windows-client acceptance',
                    },
                    'market_smoke': {
                        'status': 'failed',
                        'error_type': type(exc).__name__,
                        'scope': 'engineering packaging smoke only; not official-data or real-model acceptance',
                    },
                    'history_smoke': {
                        'status': 'failed',
                        'error_type': type(exc).__name__,
                        'source_type': 'synthetic',
                        'scope': 'synthetic packaging proof only; not actual market or Windows-client acceptance',
                    },
                }
            state.smoke_report.setdefault(
                'recovery_helper_smoke',
                {'status': 'not_run', 'cleanup_verified': True, 'scope': 'original Windows helper packaging proof only; not Windows-client acceptance'},
            )
            state.smoke_report.update(status='failed', error_type=type(exc).__name__)
            return 1
        QMessageBox.critical(None, ui_text('desktop.main.startup_failed'), error_message(startup_error_code(exc)))
        return 1
    finally:
        if state.args.smoke_test:
            # Publish exactly once, after every cleanup step, so a late failure
            # cannot leave a successful report or a precomputed zero return code.
            cleanup_errors = []
            for manager in (state.smoke_jobs, state.jobs):
                cleanup = _close_smoke_worker(manager)
                state.smoke_cleanup_verified = state.smoke_cleanup_verified and cleanup['verified']
                if cleanup['error_type'] is not None:
                    cleanup_errors.append(cleanup['error_type'])
            for close in (state.installation_guard.close if state.installation_guard is not None else None, state.lock.unlock):
                if close is not None:
                    try:
                        close()
                    except BaseException as exc:
                        state.smoke_cleanup_verified = False
                        cleanup_errors.append(type(exc).__name__)
            directories = (state.smoke_directory, state.smoke_startup_directory)
            if state.smoke_cleanup_verified:
                for directory in directories:
                    if directory is not None:
                        try:
                            directory.cleanup()
                        except BaseException as exc:
                            state.smoke_cleanup_verified = False
                            cleanup_errors.append(type(exc).__name__)
                            break
            if not state.smoke_cleanup_verified:
                for directory in directories:
                    _retain_smoke_directory(directory)
            if state.smoke_report is None:
                state.smoke_report = {
                    'status': 'failed',
                    'version': __version__,
                    'steps': [],
                    'source_type': 'synthetic',
                    'generator': 'fixture',
                    'live_status': 'disabled',
                    'data_dir': str(state.settings_paths.root) if state.settings_paths else None,
                    'smoke_data_dir': str(state.bootstrap),
                    'user_state_read_only': True,
                    'error_type': 'SmokeDidNotComplete',
                }
            if not state.smoke_cleanup_verified or not state.smoke_shutdown_completed:
                state.smoke_report['status'] = 'failed'
            if not state.smoke_shutdown_completed:
                state.smoke_report.setdefault('error_type', 'ShutdownIncomplete')
            state.smoke_report['worker_cleanup'] = {'verified': state.smoke_cleanup_verified, 'error_types': cleanup_errors}
            try:
                atomic_write(state.args.smoke_test, _json_bytes(state.smoke_report))
            except BaseException:
                return 1  # An unwritable requested report path cannot mean PASS.
            return 0 if state.smoke_report['status'] == 'passed' else 1
        if state.jobs is not None:
            state.jobs.close()
        if state.installation_guard is not None:
            state.installation_guard.close()
        state.lock.unlock()


def main(argv=None):
    args = parse_args(argv)
    if args.tls_smoke is not None:
        from desktop_tls_smoke import write_report

        return write_report(args.tls_smoke)
    return run_gui(args)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
