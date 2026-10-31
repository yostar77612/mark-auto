"""Offline smoke runner; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations

from pathlib import Path
import sys
from desktop_app.smoke.fixtures import _smoke_steps
from desktop_app.smoke.auth import _auth_smoke_dependencies
from desktop_app.smoke.market import _market_smoke_ui, _market_smoke_response, _check_market_worker_result
from desktop_app.smoke.history import _history_smoke_fixture, _check_history_worker_result, _history_smoke_ui
from desktop_app.smoke.walk_forward import _walk_forward_smoke_fixture, _check_walk_forward_smoke_result
from desktop_app.smoke.lifecycle import _start_smoke_job, _close_smoke_worker


def run_smoke(state):
    from PySide6.QtCore import QTimer
    from quantlab import __version__
    from quantlab.research_core.adapters.workspace_store import AppPaths
    from desktop_app.research_bootstrap import create_job_manager
    import tempfile
    import time
    from desktop_app.smoke.recovery import run_recovery_smoke

    # Exercise the real frozen multiprocessing bootstrap in disposable
    # cache state, never replacing the user's research dataset.
    state.smoke_directory = tempfile.TemporaryDirectory(prefix='smoke-', dir=state.paths.cache)
    state.smoke_jobs = create_job_manager(AppPaths(Path(state.smoke_directory.name)))
    smoke_deadline = time.monotonic() + 120
    auth_report = _auth_smoke_dependencies()
    market_report, manual_config, manual_candidate = _market_smoke_ui(state.app)
    history_report, history_payload = _history_smoke_fixture(Path(state.smoke_directory.name))
    walk_forward_paths = AppPaths(Path(state.smoke_directory.name) / 'walk-forward-fixture')
    walk_forward_report, walk_forward_payload = _walk_forward_smoke_fixture(walk_forward_paths)
    manual_export_path = Path(state.smoke_directory.name) / 'manual-request.json'
    market_results = {}
    smoke_steps = _smoke_steps()
    original_step_count = len(smoke_steps)
    smoke_steps.extend(
        [
            ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}, 'manual_export': str(manual_export_path)}),
            ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}}),
            ('ui_market_refresh', history_payload),
            ('ui_walk_forward_preview', walk_forward_payload),
            ('ui_walk_forward_run', {}),  # Bound only to the verified preview.
            ('ui_walk_forward_read', {}),  # Reopen the same immutable journal.
        ]
    )
    smoke_index = 0
    _start_smoke_job(state.smoke_jobs, *smoke_steps[0])
    smoke_result = {'failed': False, 'results': {}, 'steps': []}
    recovery_report = {
        'status': 'pending',
        'cleanup_verified': True,
        'source_type': 'synthetic',
        'scope': 'original Windows helper packaging proof only; not Windows-client acceptance',
    }
    smoke_timer = QTimer(state.window)
    smoke_timer.setInterval(100)

    def complete_smoke():
        nonlocal smoke_index, recovery_report
        operation = smoke_steps[smoke_index][0]
        market_phase = (
            ('manual_export' if smoke_index == original_step_count else 'manual_import')
            if original_step_count <= smoke_index < original_step_count + 2
            else None
        )
        history_phase = smoke_index == original_step_count + 2
        walk_forward_phase = operation.startswith('ui_walk_forward_')
        for event in state.smoke_jobs.poll():
            if event['type'] == 'result':
                result = event.get('result', {})
                if walk_forward_phase:
                    try:
                        evidence = _check_walk_forward_smoke_result(operation, result, state.smoke_jobs.paths, walk_forward_payload, walk_forward_report)
                        walk_forward_report.update(evidence)
                        walk_forward_report['steps'].append({'operation': operation, 'passed': True})
                    except Exception as exc:
                        smoke_result['failed'] = True
                        walk_forward_report['steps'].append({'operation': operation, 'passed': False, 'error_type': type(exc).__name__})
                    continue
                if history_phase:
                    try:
                        series, evidence = _check_history_worker_result(result, state.smoke_jobs.paths, history_payload, history_report['fixture_sha256'])
                        history_report.update(evidence)
                        history_report.update(_history_smoke_ui(state.app, series))
                        history_report['steps'].append({'operation': 'history_import', 'passed': True})
                    except Exception as exc:
                        smoke_result['failed'] = True
                        history_report['steps'].append({'operation': 'history_import', 'passed': False, 'error_type': type(exc).__name__})
                    continue
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
                    valid = (
                        result.get('status') == 'completed'
                        and bool(result.get('attempts'))
                        and all(row.get('status') == 'evaluated' for row in result['attempts'])
                        and result.get('real_model_status') == 'not_verified'
                    )
                elif operation == 'ui_paper_replay':
                    valid = result.get('replay', {}).get('cursor') == 25 and result.get('account', {}).get('kill_switch') is True
                elif operation == 'ui_paper_kill':
                    valid = result.get('account', {}).get('kill_switch') is True
                smoke_result['steps'].append({'operation': operation, 'passed': valid})
                smoke_result['failed'] |= not valid
            elif event['type'] in ('error', 'cancelled'):
                smoke_result['failed'] = True
                step_report = (
                    walk_forward_report['steps']
                    if walk_forward_phase
                    else history_report['steps']
                    if history_phase
                    else market_report['steps']
                    if market_phase
                    else smoke_result['steps']
                )
                step_report.append(
                    {
                        'operation': 'history_import' if history_phase else market_phase or operation,
                        'passed': False,
                        'error_type': event.get('error_type', event['type']),
                    }
                )
        timed_out = time.monotonic() > smoke_deadline
        if state.smoke_jobs.active and not timed_out:
            return
        if not smoke_result['failed'] and not timed_out and smoke_index + 1 < len(smoke_steps):
            smoke_index += 1
            next_operation, payload = smoke_steps[smoke_index]
            if next_operation == 'ui_select':
                payload = {'result': smoke_result['results']['ui_backtest']['reports'][0]['result']}
            try:
                if next_operation == 'ui_walk_forward_preview':
                    state.smoke_jobs.close()
                    state.smoke_jobs = create_job_manager(walk_forward_paths)
                elif next_operation == 'ui_walk_forward_run':
                    payload = {**walk_forward_payload, 'preview_identity': walk_forward_report['reference']}
                elif next_operation == 'ui_walk_forward_read':
                    payload = {'reference': walk_forward_report['reference']}
                _start_smoke_job(state.smoke_jobs, next_operation, payload)
                return
            except Exception as exc:
                smoke_result['failed'] = True
                rows = walk_forward_report['steps'] if next_operation.startswith('ui_walk_forward_') else smoke_result['steps']
                rows.append({'operation': next_operation, 'passed': False, 'error_type': type(exc).__name__})
        smoke_timer.stop()
        state.smoke_jobs.close()
        prior_cleanup_verified = state.smoke_cleanup_verified
        state.smoke_cleanup_verified = False  # Unexpected hook failure must retain disposable evidence.
        recovery_report = run_recovery_smoke(AppPaths(Path(state.smoke_directory.name)), smoke_result['results'].get('ui_campaign'), deadline=smoke_deadline)
        state.smoke_cleanup_verified = prior_cleanup_verified and recovery_report.get('cleanup_verified') is True
        recovery_required = sys.platform == 'win32' and bool(getattr(sys, 'frozen', False))
        recovery_passed = (
            (recovery_report['status'] == 'passed' and recovery_report.get('frozen') is True)
            if recovery_required
            else recovery_report['status'] == 'not_applicable'
        )
        timed_out = timed_out or time.monotonic() > smoke_deadline
        completed = len(smoke_result['results']) == original_step_count
        market_report['status'] = 'passed' if len(market_results) == 2 and not smoke_result['failed'] and not timed_out else 'failed'
        history_report['status'] = (
            'passed'
            if len(history_report['steps']) == 1 and history_report['steps'][0]['passed'] and not smoke_result['failed'] and not timed_out
            else 'failed'
        )
        walk_forward_report['status'] = (
            'passed'
            if [row['operation'] for row in walk_forward_report['steps']] == ['ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read']
            and all(row['passed'] for row in walk_forward_report['steps'])
            and walk_forward_report.get('read_verified')
            and not smoke_result['failed']
            and not timed_out
            else 'failed'
        )
        passed = (
            recovery_passed
            and state.smoke_cleanup_verified
            and walk_forward_report['status'] == 'passed'
            and completed
            and auth_report['status'] == 'passed'
            and market_report['status'] == 'passed'
            and history_report['status'] == 'passed'
            and not smoke_result['failed']
            and not timed_out
            and state.window.isVisible()
        )
        completed_operations = {row['operation'] for row in smoke_result['steps'] if row['passed']}
        # data_dir remains the inspected settings location for installer
        # compatibility; mutable execution uses smoke_data_dir. The
        # explicitly requested report path is also written by the caller
        # contract and is excluded from the user-state read-only claim.
        state.smoke_report = {
            'status': 'passed' if passed else 'failed',
            'data_dir': str(state.settings_paths.root),
            'smoke_data_dir': str(state.paths.root),
            'user_state_read_only': True,
            'user_state_access': 'none' if getattr(state.args, 'smoke_isolated', False) else 'read_only',
            'version': __version__,
            'native_window_visible': state.window.isVisible(),
            'worker_completed': completed,
            'backtest_completed': 'ui_backtest' in completed_operations,
            'campaign_completed': 'ui_campaign' in completed_operations,
            'paper_completed': {'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'} <= completed_operations,
            'source_type': 'synthetic',
            'generator': 'fixture',
            'real_model_status': 'not_verified',
            'live_status': 'disabled',
            'timed_out': timed_out,
            'steps': smoke_result['steps'],
            'market_smoke': market_report,
            'auth_smoke': auth_report,
            'history_smoke': history_report,
            'walk_forward_smoke': walk_forward_report,
            'recovery_helper_smoke': recovery_report,
        }
        state.window.close()
        state.app.exit(0 if passed else 1)

    def guarded_complete_smoke():
        pass
        try:
            complete_smoke()
        except BaseException as exc:
            # Qt swallows timer exceptions. Always emit terminal failure
            # and stop scheduling, without echoing exception values.
            smoke_timer.stop()
            cleanup = _close_smoke_worker(state.smoke_jobs)
            state.smoke_cleanup_verified = state.smoke_cleanup_verified and cleanup['verified']
            operation = smoke_steps[smoke_index][0]
            rows = walk_forward_report['steps'] if operation.startswith('ui_walk_forward_') else smoke_result['steps']
            rows.append({'operation': operation, 'passed': False, 'error_type': type(exc).__name__})
            walk_forward_report['status'] = 'failed'
            state.smoke_report = {
                'status': 'failed',
                'version': __version__,
                'data_dir': str(state.settings_paths.root),
                'smoke_data_dir': str(state.paths.root),
                'user_state_read_only': True,
                'user_state_access': 'none' if getattr(state.args, 'smoke_isolated', False) else 'read_only',
                'source_type': 'synthetic',
                'generator': 'fixture',
                'live_status': 'disabled',
                'real_model_status': 'not_verified',
                'native_window_visible': state.window.isVisible(),
                'worker_completed': False,
                'timed_out': time.monotonic() > smoke_deadline,
                'error_type': type(exc).__name__,
                'worker_cleanup': cleanup,
                'steps': smoke_result['steps'],
                'auth_smoke': auth_report,
                'market_smoke': market_report,
                'history_smoke': history_report,
                'walk_forward_smoke': walk_forward_report,
                'recovery_helper_smoke': recovery_report,
            }
            state.app.exit(1)

    smoke_timer.timeout.connect(guarded_complete_smoke)
    smoke_timer.start()
