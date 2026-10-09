"""Frozen Windows desktop entry point; no web server, browser, or Python setup."""
from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path
import sys


def _smoke_steps():
    """Fixed offline fixtures only. No endpoints, credentials, or arbitrary commands."""
    from quantlab.core import to_dict
    from quantlab.reporting import demo_config, synthetic_dataset
    from quantlab.research import demo_campaign_config
    campaign = to_dict(demo_campaign_config(synthetic_dataset(120), demo_config()))
    campaign.update(families=['trend'], max_trials=1, max_improvements=0, max_runtime_seconds=45)
    campaign['ranking']['minimum'] = '-100000000'
    contract = 'TAIFEX:TMF:202601'
    policy = {'contract_id': contract, 'risk_sessions': [{'open': '2026-01-05T00:45:00Z',
        'end': '2026-01-05T02:45:00Z', 'trade_date': '2026-01-05', 'session': 'day',
        'contract_id': contract, 'source': 'explicit synthetic smoke fixture'}],
        'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}]}
    snapshot = {'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}
    return [
        ('ui_demo', {'bars': 120}),
        ('ui_backtest', {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'config': to_dict(demo_config()), 'batch': False}),
        ('ui_select', {}),  # Filled only from the preceding verified report result.
        ('ui_campaign', {'config': campaign, 'provider': {'mode': 'fixture'}}),
        ('ui_paper_reconcile', {'policy': policy, 'snapshot': snapshot}),
        ('ui_paper_replay', {'policy': policy, 'snapshot': snapshot, 'reconcile_confirmed': True, 'max_bars': 25}),
        ('ui_paper_kill', {'policy': policy}),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description='MarkAuto native desktop research and paper trading')
    parser.add_argument('--smoke-test', type=Path, help='Show real native window, write launch report, then exit')
    args = parser.parse_args(argv)
    if args.smoke_test is not None and not args.smoke_test.is_absolute():
        parser.error('--smoke-test requires an absolute report path')
    from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from quantlab import __version__
    from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, RuntimeGuard, SettingsStore, WorkspaceLocator, WindowsAppMutex, atomic_write, _json_bytes
    app = QApplication(sys.argv[:1])
    app.setApplicationName('MarkAuto')
    app.setOrganizationName('MarkAuto')
    app.setApplicationVersion(__version__)
    bootstrap = AppPaths.discover().root
    bootstrap.mkdir(parents=True, exist_ok=True)
    locator = WorkspaceLocator(bootstrap)
    lock = QLockFile(str(locator.lock_path))
    lock.setStaleLockTime(0)  # Qt checks process liveness; never steal a live lock by age.
    if not lock.tryLock(0):
        QMessageBox.information(None, 'MarkAuto is already running', 'Use the existing MarkAuto window. A second worker will not be started.')
        return 2
    jobs = guard = installation_guard = None
    try:
        installation_guard = WindowsAppMutex()
        paths = locator.load()
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
                        backups.recover()
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
                backups.recover()
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
            smoke_steps = _smoke_steps()
            smoke_index = 0
            smoke_jobs.start(*smoke_steps[0])
            smoke_deadline = time.monotonic() + 120
            smoke_result = {'failed': False, 'results': {}, 'steps': []}
            smoke_timer = QTimer(window)
            smoke_timer.setInterval(100)
            def complete_smoke():
                nonlocal smoke_index
                operation = smoke_steps[smoke_index][0]
                for event in smoke_jobs.poll():
                    if event['type'] == 'result':
                        result = event.get('result', {})
                        smoke_result['results'][operation] = result
                        valid = True
                        if operation == 'ui_demo':
                            valid = result.get('source_type') == 'synthetic' and result.get('bars') == 120
                        elif operation == 'ui_backtest':
                            valid = bool(result.get('reports')) and result.get('source_type') == 'synthetic'
                        elif operation == 'ui_campaign':
                            valid = result.get('status') == 'completed' and bool(result.get('attempts')) and all(row.get('status') == 'evaluated' for row in result['attempts']) and result.get('real_model_status') == 'not_verified'
                        elif operation == 'ui_paper_replay':
                            valid = result.get('replay', {}).get('cursor') == 25 and result.get('account', {}).get('kill_switch') is True
                        elif operation == 'ui_paper_kill':
                            valid = result.get('account', {}).get('kill_switch') is True
                        smoke_result['steps'].append({'operation': operation, 'passed': valid})
                        smoke_result['failed'] |= not valid
                    elif event['type'] in ('error', 'cancelled'):
                        smoke_result['failed'] = True
                        smoke_result['steps'].append({'operation': operation, 'passed': False, 'error_type': event.get('error_type', event['type'])})
                timed_out = time.monotonic() > smoke_deadline
                if smoke_jobs.active and not timed_out:
                    return
                if not smoke_result['failed'] and not timed_out and smoke_index + 1 < len(smoke_steps):
                    smoke_index += 1
                    next_operation, payload = smoke_steps[smoke_index]
                    if next_operation == 'ui_select':
                        payload = {'result': smoke_result['results']['ui_backtest']['reports'][0]['result']}
                    smoke_jobs.start(next_operation, payload)
                    return
                smoke_timer.stop()
                smoke_jobs.close()
                completed = len(smoke_result['results']) == len(smoke_steps)
                passed = completed and not smoke_result['failed'] and not timed_out and window.isVisible()
                completed_operations = {row['operation'] for row in smoke_result['steps'] if row['passed']}
                report = {'status': 'passed' if passed else 'failed', 'data_dir': str(paths.root),
                    'version': __version__, 'native_window_visible': window.isVisible(), 'worker_completed': completed,
                    'backtest_completed': 'ui_backtest' in completed_operations,
                    'campaign_completed': 'ui_campaign' in completed_operations,
                    'paper_completed': {'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'} <= completed_operations,
                    'source_type': 'synthetic', 'generator': 'fixture', 'real_model_status': 'not_verified',
                    'live_status': 'disabled', 'timed_out': timed_out, 'steps': smoke_result['steps']}
                atomic_write(args.smoke_test, _json_bytes(report))
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
        if installation_guard is not None:
            installation_guard.close()
        lock.unlock()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
