"""Frozen Windows desktop entry point; no web server, browser, or Python setup."""
from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='MarkAuto native desktop research and paper trading')
    parser.add_argument('--smoke-test', type=Path, help='Show real native window, write launch report, then exit')
    args = parser.parse_args(argv)
    if args.smoke_test is not None and not args.smoke_test.is_absolute():
        parser.error('--smoke-test requires an absolute report path')
    from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from quantlab import __version__
    from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, RuntimeGuard, SettingsStore, atomic_write, _json_bytes
    app = QApplication(sys.argv[:1])
    app.setApplicationName('MarkAuto')
    app.setOrganizationName('MarkAuto')
    app.setApplicationVersion(__version__)
    paths = AppPaths.discover()
    paths.root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(paths.root / 'desktop.lock'))
    lock.setStaleLockTime(0)  # Qt checks process liveness; never steal a live lock by age.
    if not lock.tryLock(0):
        QMessageBox.information(None, 'MarkAuto is already running', 'Use the existing MarkAuto window. A second worker will not be started.')
        return 2
    jobs = guard = None
    try:
        backups = BackupManager(paths)
        backups.recover()  # Recover directory switch before creating the state directory.
        paths.ensure()
        guard = RuntimeGuard(paths)
        previous_unclean = guard.start()
        settings = SettingsStore(paths.state / 'settings.json')
        settings.load()  # Fail closed on incompatible/corrupt state; never overwrite it.
        jobs = JobManager(paths)
        backups.jobs = jobs
        from desktop_ui import MainWindow
        window = MainWindow(paths, jobs, settings=settings, backups=backups, guard=guard)
        window.show()
        if hasattr(window, 'freeze_paper'):
            window.freeze_paper('Previous session ended unexpectedly; reconcile paper account' if previous_unclean else 'Startup requires paper reconciliation')
        # Windows suspend/resume notifications complement wall/monotonic checks,
        # including short sleeps and platforms whose monotonic clock pauses.
        class PowerEvents(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if sys.platform == 'win32':
                    import ctypes
                    from ctypes import wintypes
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0218 and msg.wParam in (4, 6, 7, 18):
                        guard.reconciliation_required = True
                        jobs.cancel()
                        if hasattr(window, 'freeze_paper'):
                            window.freeze_paper('Windows power event; reconcile paper account before resuming')
                return False, 0
        power_events = PowerEvents()
        app.installNativeEventFilter(power_events)
        timer = QTimer(window)
        timer.setInterval(1000)
        def clock_tick():
            if guard.check_clock():
                jobs.cancel()
                if hasattr(window, 'freeze_paper'):
                    window.freeze_paper('Sleep or clock change detected; reconcile paper account before resuming')
        timer.timeout.connect(clock_tick)
        timer.start()
        if args.smoke_test:
            import tempfile
            import time
            # Exercise the real frozen multiprocessing bootstrap in disposable
            # cache state, never replacing the user's research dataset.
            smoke_directory = tempfile.TemporaryDirectory(prefix='smoke-', dir=paths.cache)
            smoke_jobs = JobManager(AppPaths(Path(smoke_directory.name)))
            smoke_jobs.start('demo', {'bars': 30})
            smoke_deadline = time.monotonic() + 45
            smoke_result = {'completed': False, 'failed': False}
            smoke_timer = QTimer(window)
            smoke_timer.setInterval(100)
            def complete_smoke():
                for event in smoke_jobs.poll():
                    if event['type'] == 'result':
                        smoke_result['completed'] = True
                    elif event['type'] in ('error', 'cancelled'):
                        smoke_result['failed'] = True
                timed_out = time.monotonic() > smoke_deadline
                if smoke_jobs.active and not timed_out:
                    return
                smoke_timer.stop()
                smoke_jobs.close()
                passed = smoke_result['completed'] and not smoke_result['failed'] and not timed_out and window.isVisible()
                atomic_write(args.smoke_test, _json_bytes({'status': 'passed' if passed else 'failed', 'data_dir': str(paths.root), 'version': __version__, 'native_window_visible': window.isVisible(), 'worker_completed': smoke_result['completed']}))
                smoke_directory.cleanup()
                window.close()
                app.exit(0 if passed else 1)
            smoke_timer.timeout.connect(complete_smoke)
            smoke_timer.start()
        status = app.exec()
        jobs.close()
        guard.finish()
        return status
    except Exception as exc:
        # No exception values or secret-bearing tracebacks in a general GUI dialog.
        QMessageBox.critical(None, 'MarkAuto could not start', f'{type(exc).__name__}: startup failed. Your existing data has been preserved. Restore a compatible backup or reinstall the previous version.')
        return 1
    finally:
        if jobs is not None:
            jobs.close()
        lock.unlock()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
