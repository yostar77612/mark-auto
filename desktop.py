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


def _market_smoke_ui(app):
    """Disposable engineering-fixture widgets; never bind user persistence signals."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import hashlib
    import shiboken6
    from desktop_market import MarketDashboard
    from desktop_charts import CandlestickChart
    from desktop_forms import StrategyForm, CampaignForm
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance
    from quantlab.core import canonical_json
    widgets = []
    try:
        dashboard = MarketDashboard(); widgets.append(dashboard)
        dashboard.setWindowTitle('SYNTHETIC ENGINEERING FIXTURE — not market acceptance')
        dashboard.resize(1280, 900)
        instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202610', '202610')
        start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
        bars = tuple(MarketBar(instrument, '2026-10-01', 'day', Decimal(100 + i % 7),
            Decimal(111), Decimal(90), Decimal(101 + i % 7), 100 + i, interval='1m',
            timestamp=start + timedelta(minutes=i), end=start + timedelta(minutes=i + 1),
            session_open=start, session_end=start + timedelta(minutes=120)) for i in range(120))
        fixture_hash = hashlib.sha256(canonical_json(bars).encode('utf-8')).hexdigest()
        source = SourceProvenance('https://example.invalid/synthetic-engineering-fixture', fixture_hash,
            'SYNTHETIC ENGINEERING FIXTURE — not official market data',
            'https://example.invalid/fixture-not-a-license', start, '2026-10-01', '2026-10-01',
            '2026-10-01', mode='offline', warnings=('Synthetic packaging smoke only; no market acceptance.',))
        dashboard.set_market_series(MarketSeries(instrument, bars, source))
        if not isinstance(dashboard.chart, CandlestickChart):
            raise ValueError('Market chart module contract failed')
        counts = {}
        for timeframe in ('1m', '5m', '1d', '1w'):
            dashboard.timeframe_combo.setCurrentIndex(dashboard.timeframe_combo.findData(timeframe))
            counts[timeframe] = len(dashboard.chart.bars)
        if counts != {'1m': 120, '5m': 24, '1d': 1, '1w': 1}:
            raise ValueError('Market timeframe aggregation failed')
        dashboard.timeframe_combo.setCurrentIndex(dashboard.timeframe_combo.findData('1m'))
        for checkbox, controls in dashboard._indicator_widgets.values():
            checkbox.setChecked(True)
        if not dashboard.chart.overlays or not dashboard.chart.panes:
            raise ValueError('Market indicators missing')
        if not all(any(value is not None for value in values)
                   for values in (*dashboard.chart.overlays.values(), *dashboard.chart.panes.values())):
            raise ValueError('Market indicators did not warm up')
        dashboard.show(); app.processEvents()
        pixmap = dashboard.chart.grab()
        image = pixmap.toImage()
        colors = {image.pixel(x, y) for x in range(0, image.width(), max(1, image.width() // 20))
                  for y in range(0, image.height(), max(1, image.height() // 20))}
        if pixmap.isNull() or dashboard.chart.last_rendered_bar_count < 1 or len(colors) < 4:
            raise ValueError('Market chart did not render nonempty candles')
        strategy = StrategyForm(); campaign = CampaignForm(); widgets.extend((strategy, campaign))
        strategy.fields['fast'].setText('5'); strategy.fields['slow'].setText('20')
        candidate = strategy.build_payload()
        config = _smoke_steps()[3][1]['config']
        # No selection/holdout reuse in this additional packaging-only evaluation.
        config['ranking']['minimum'] = '1000000000000'
        campaign.from_payload(config)
        typed_config = campaign.build_payload()
        if candidate['family'] != 'trend' or candidate['parameters']['fast'] != 5 or typed_config['max_trials'] != 1:
            raise ValueError('Typed forms changed the bounded smoke payload')
        return {'status': 'pending', 'source_type': 'synthetic', 'generator': 'fixture',
            'scope': 'engineering packaging smoke only; not official-data or real-model acceptance',
            'network_used': False, 'live_status': 'disabled', 'fixture_sha256': fixture_hash,
            'modules': ['desktop_market', 'desktop_charts', 'desktop_forms'],
            'chart_rendered_bars': dashboard.chart.last_rendered_bar_count,
            'timeframe_bars': counts, 'indicator_series': len(dashboard.chart.overlays) + len(dashboard.chart.panes),
            'typed_payload': True, 'steps': []}, typed_config, candidate
    finally:
        for widget in reversed(widgets):
            widget.close(); shiboken6.delete(widget)


def _market_smoke_response(request, candidate):
    """Create a clearly synthetic response from typed local input, never a model call."""
    from quantlab.core import canonical_json
    response = {key: request[key] for key in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
    response['candidates'] = [{'family': 'trend', 'context_hash': request['families'][0]['context_hash'],
                               'candidate': candidate}]
    return canonical_json(response)


def _check_market_worker_result(phase, result, export_path):
    """Fail closed on missing provenance, bundled-source failures or fake completion."""
    import re
    from quantlab.core import content_hash
    if phase == 'manual_export':
        import json
        from quantlab import manual_exchange
        request = result['request']
        if result.get('mode') != 'manual_unverified' or json.loads(export_path.read_text(encoding='utf-8')) != request:
            raise ValueError('Manual export was not written by the worker')
        expected_source = content_hash(Path(manual_exchange.__file__).read_text(encoding='utf-8'))
        if request['module_source_hash'] != expected_source or not re.fullmatch('[0-9a-f]{64}', request['request_id']):
            raise ValueError('Manual source provenance missing or mismatched')
        return {'module_source_hash': expected_source, 'request_id': request['request_id']}
    if phase != 'manual_import':
        raise ValueError('Unknown market smoke phase')
    hashes = result.get('binding', {}).get('engine_source_hashes', {})
    from quantlab import research
    expected = {name: content_hash(Path(research.__file__).with_name(name).read_text(encoding='utf-8'))
                for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py')}
    if (result.get('status') != 'completed' or result.get('real_model_status') != 'not_verified'
            or result.get('binding', {}).get('provider', {}).get('mode') != 'manual_unverified'
            or result.get('source_manifest', {}).get('source_type') != 'synthetic'
            or hashes != expected or len(result.get('attempts', [])) != 1
            or result['attempts'][0].get('status') != 'evaluated'):
        raise ValueError('Manual import or frozen source provenance failed')
    return {'engine_source_hashes': hashes, 'real_model_status': 'not_verified'}


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
    smoke_jobs = smoke_directory = None
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
            smoke_deadline = time.monotonic() + 120
            market_report, manual_config, manual_candidate = _market_smoke_ui(app)
            manual_export_path = Path(smoke_directory.name) / 'manual-request.json'
            market_results = {}
            smoke_steps = _smoke_steps()
            original_step_count = len(smoke_steps)
            smoke_steps.extend([
                ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}, 'manual_export': str(manual_export_path)}),
                ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}}),
            ])
            smoke_index = 0
            smoke_jobs.start(*smoke_steps[0])
            smoke_result = {'failed': False, 'results': {}, 'steps': []}
            smoke_timer = QTimer(window)
            smoke_timer.setInterval(100)
            def complete_smoke():
                nonlocal smoke_index
                operation = smoke_steps[smoke_index][0]
                market_phase = ('manual_export' if smoke_index == original_step_count else 'manual_import') if smoke_index >= original_step_count else None
                for event in smoke_jobs.poll():
                    if event['type'] == 'result':
                        result = event.get('result', {})
                        if market_phase:
                            try:
                                evidence = _check_market_worker_result(market_phase, result, manual_export_path)
                                if market_phase == 'manual_export':
                                    smoke_steps[original_step_count + 1][1]['provider']['response_text'] = _market_smoke_response(result['request'], manual_candidate)
                                market_results[market_phase] = result
                                market_report.update(evidence)
                                market_report['steps'].append({'operation': market_phase, 'passed': True})
                            except Exception as exc:
                                smoke_result['failed'] = True
                                market_report['steps'].append({'operation': market_phase, 'passed': False, 'error_type': type(exc).__name__})
                            continue
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
                        (market_report['steps'] if market_phase else smoke_result['steps']).append({'operation': market_phase or operation, 'passed': False, 'error_type': event.get('error_type', event['type'])})
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
                completed = len(smoke_result['results']) == original_step_count
                market_report['status'] = 'passed' if len(market_results) == 2 and not smoke_result['failed'] and not timed_out else 'failed'
                passed = completed and market_report['status'] == 'passed' and not smoke_result['failed'] and not timed_out and window.isVisible()
                completed_operations = {row['operation'] for row in smoke_result['steps'] if row['passed']}
                report = {'status': 'passed' if passed else 'failed', 'data_dir': str(paths.root),
                    'version': __version__, 'native_window_visible': window.isVisible(), 'worker_completed': completed,
                    'backtest_completed': 'ui_backtest' in completed_operations,
                    'campaign_completed': 'ui_campaign' in completed_operations,
                    'paper_completed': {'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'} <= completed_operations,
                    'source_type': 'synthetic', 'generator': 'fixture', 'real_model_status': 'not_verified',
                    'live_status': 'disabled', 'timed_out': timed_out, 'steps': smoke_result['steps'], 'market_smoke': market_report}
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
        if args.smoke_test:
            atomic_write(args.smoke_test, _json_bytes({'status': 'failed', 'version': __version__,
                'steps': [], 'source_type': 'synthetic', 'generator': 'fixture', 'live_status': 'disabled',
                'market_smoke': {'status': 'failed', 'error_type': type(exc).__name__,
                    'scope': 'engineering packaging smoke only; not official-data or real-model acceptance'}}))
            return 1
        QMessageBox.critical(None, 'MarkAuto could not start', f'{type(exc).__name__}: startup failed. Your existing data has been preserved. Restore a compatible backup or reinstall the previous version.')
        return 1
    finally:
        if smoke_jobs is not None:
            smoke_jobs.close()
        if smoke_directory is not None:
            smoke_directory.cleanup()
        if jobs is not None:
            jobs.close()
        if installation_guard is not None:
            installation_guard.close()
        lock.unlock()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
