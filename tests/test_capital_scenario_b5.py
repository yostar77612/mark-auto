"""Cheap synthetic-only B5 contracts; no real OOS values or worker processes."""

import ast
from datetime import date, timedelta
from decimal import Decimal, localcontext
import hashlib
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab import capital_scenario as capital
from quantlab.core import ValidationError, canonical_json
import desktop_app.features.capital_scenario.worker as adapter
from desktop_app.features.capital_scenario import presenter as scenario_presenter

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = dict(start_equity='1000000', threshold='900000', horizon_days=60, paths=1000, seed=1729, cancel=None, deadline=None)


def run(sample=('0.01',), **overrides):
    return capital.simulate(sample, **{**PARAMETERS, **overrides})


def state(values=('0.01',), *, status='excluded_not_evaluated'):
    rows = [{'trade_date': (date(2020, 1, 1) + timedelta(days=i)).isoformat(), 'return': value} for i, value in enumerate(values)]
    return {
        'final_holdout_status': status,
        'folds': [{'index': 0, 'status': 'evaluated', 'oos': {'status': 'evaluated', 'result': {'metrics': {'daily_returns': rows}}}}],
    }


class KernelTests(unittest.TestCase):
    def assert_empty(self, result, status='rejected'):
        self.assertEqual(result['status'], status)
        self.assertTrue(result['reason'])
        for key in ('breach_fraction', 'percentiles', 'actual_paths', 'breached_paths'):
            self.assertIsNone(result[key])

    def test_seed_and_global_random_independence(self):
        sample = ['-0.03', '0.01', '0.04']
        original = list(sample)
        first = run(sample)
        random.seed(123)
        self.assertEqual(canonical_json(first), canonical_json(run(sample)))
        self.assertNotEqual(first, run(sample, seed=1730))
        self.assertEqual(sample, original)
        with localcontext() as context:
            context.prec = 7
            self.assertEqual(first, run(sample))

    def test_positive_negative_and_crossing_stop(self):
        self.assertEqual(run(['0.01'] * 20)['breach_fraction'], D(0))
        self.assertEqual(run(['-0.05'])['breach_fraction'], D(1))
        self.assertEqual(run(['-0.05'], horizon_days=1)['breach_fraction'], D(0))
        crossing = run(['-0.2'])
        self.assertEqual(crossing['breached_paths'], 1000)
        self.assertEqual(set(crossing['percentiles'].values()), {D('800000')})
        # Strictly below: touching the threshold on day one does not breach.
        self.assertEqual(run(['-0.1'], horizon_days=1)['breached_paths'], 0)

    def test_fixed_capital_and_decimal_shape(self):
        result = run()
        self.assertEqual(set(result['percentiles'].values()), {D('1600000')})
        self.assertEqual(result['actual_paths'], 1000)

        def check(value):
            self.assertNotIsInstance(value, float)
            if isinstance(value, D):
                self.assertEqual(value.as_tuple().exponent, -12)
            if isinstance(value, dict):
                for item in value.values():
                    check(item)

        check(result)

    def test_independent_path_recomputation(self):
        sample = [D('-0.03'), D('0.01'), D('0.04')]
        rng = random.Random(1729)
        finals, breached = [], 0
        for _ in range(40):
            equity = D(1000000)
            for _ in range(20):
                equity += D(1000000) * sample[rng.randrange(len(sample))]
                if equity < D(900000):
                    breached += 1
                    break
            finals.append(equity)
        result = run(sample, paths=40, horizon_days=20)
        self.assertEqual(result['breached_paths'], breached)
        self.assertEqual(result['breach_fraction'], (D(breached) / 40).quantize(capital.QUANTUM))
        finals.sort()
        for p in (5, 25, 50, 75, 95):
            position = D(39) * p / 100
            left = int(position)
            expected = finals[left] + (finals[left + 1] - finals[left]) * (position - left)
            self.assertEqual(result['percentiles'][str(p)], expected.quantize(capital.QUANTUM))

    def test_cap_boundary_and_validation_before_callbacks(self):
        self.assertEqual(run(horizon_days=1000, paths=1000)['status'], 'completed')
        callback = Mock(side_effect=AssertionError('simulation started'))
        for changes in ({'paths': 2000, 'horizon_days': 501}, {'paths': 10**9}, {'horizon_days': 10**9}):
            self.assert_empty(run(cancel=callback, **changes))
        callback.assert_not_called()
        for key in ('paths', 'horizon_days'):
            for value in (True, 1.0, 0, -1, '1'):
                self.assert_empty(run(**{key: value}))
        for seed in (True, 1.0, '1', None):
            self.assert_empty(run(seed=seed))

    def test_invalid_money_samples_and_deadline(self):
        for key in ('start_equity', 'threshold'):
            for value in ('NaN', 'Infinity', '0', '-1', 1.0, None):
                self.assert_empty(run(**{key: value}))
        self.assert_empty(run(threshold='1000000'))
        for sample in ([], [None], ['0.01'] * 99 + [None], ['NaN'], ['Infinity'], ['-1'], ['-2']):
            self.assert_empty(run(sample))
        for deadline in ('1', True, float('nan'), D(1)):
            self.assert_empty(run(deadline=deadline))

    def test_iid_uniform_and_type7_percentiles(self):
        result = run(['0', '0.01'], horizon_days=1, paths=100000)
        # One-day bootstrap: median is at either 1m or 1.01m; count draws directly.
        choices = []
        original = random.Random.choice

        def choice(rng, sample):
            value = original(rng, sample)
            choices.append(value)
            return value

        with patch.object(random.Random, 'choice', choice):
            run(['0', '0.01'], horizon_days=1, paths=100000)
        fraction = sum(value > 0 for value in choices) / len(choices)
        self.assertTrue(0.49 < fraction < 0.51)
        with patch.object(random.Random, 'choice', side_effect=[D(0), D(100), D(200), D(300)]):
            small = run(paths=4, horizon_days=1)
        self.assertEqual(small['percentiles'], {str(p): D(1000000) + D(3) * p for p in (5, 25, 50, 75, 95)})
        self.assertEqual(list(result['percentiles'].values()), sorted(result['percentiles'].values()))

    def test_cancel_deadline_and_precedence_are_deterministic(self):
        polls = []

        def cancel():
            polls.append(1)
            return len(polls) == 19

        self.assert_empty(run(cancel=cancel), 'cancelled')
        self.assertEqual(len(polls), 19)
        with patch.object(capital, 'monotonic', side_effect=[0] * 18 + [2]) as clock:
            self.assert_empty(run(deadline=1), 'timed_out')
            self.assertEqual(clock.call_count, 19)
        with patch.object(capital, 'monotonic', side_effect=AssertionError('cancel wins')):
            self.assert_empty(run(cancel=lambda: True, deadline=1), 'cancelled')

    def test_import_boundary(self):
        tree = ast.parse((ROOT / 'quantlab/capital_scenario.py').read_text(encoding='utf-8'))
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(name.startswith(('quantlab', 'desktop', 'PySide6')) for name in modules))


class AdapterTests(unittest.TestCase):
    def payload(self):
        return {'reference': 'a' * 64, **{key: value for key, value in PARAMETERS.items() if key not in ('cancel', 'deadline')}}

    def test_strict_payload_and_traversal(self):
        paths = SimpleNamespace(state=ROOT / 'tests')
        for payload in ({}, {**self.payload(), 'daily_returns': []}, {**self.payload(), 'reference': '../escape'}):
            with self.assertRaises(ValidationError):
                adapter.execute(payload, paths)
        for key in self.payload():
            payload = self.payload()
            del payload[key]
            with self.assertRaises(ValidationError):
                adapter.execute(payload, paths)

    def test_worker_success_and_atomic_missing_return(self):
        for values, expected in ((['0.01'] * 100, 'completed'), (['0.01'] * 99 + [None], 'rejected')):
            with patch.object(adapter, 'read_walk_forward_state', return_value=state(values)):
                result = adapter.execute(self.payload(), SimpleNamespace(state=ROOT))
            self.assertEqual(result['status'], expected)
            self.assertNotIn('daily_returns', result)
            self.assertLess(len(canonical_json(result)), 2048)
            if expected == 'rejected':
                self.assertIsNone(result['breach_fraction'])
                self.assertIsNone(result['actual_paths'])

    def test_worker_reads_evaluated_only_and_never_holdout(self):
        class Guard(dict):
            def get(self, key, default=None):
                if 'holdout' in key and key != 'final_holdout_status':
                    raise AssertionError('holdout access')
                return super().get(key, default)

        full = Guard(state())
        full['folds'].insert(0, {'index': 1, 'status': 'skipped', 'oos': {'daily_returns': ['-0.99']}})
        later = state(['0.02'])['folds'][0]
        later['index'] = 2
        later['oos']['result']['metrics']['daily_returns'][0]['trade_date'] = '2020-01-02'
        full['folds'].append(later)
        with patch.object(adapter, 'read_walk_forward_state', return_value=full), patch.object(adapter, 'simulate', return_value={}) as simulate:
            adapter.execute(self.payload(), SimpleNamespace(state=ROOT))
            self.assertEqual(simulate.call_args.args[0], ['0.01', '0.02'])

    def test_missing_holdout_and_no_evaluated_reject(self):
        for full, reason in (
            (state(status='evaluated'), 'holdout_status_unconfirmed'),
            ({'final_holdout_status': 'excluded_not_evaluated', 'folds': []}, 'no_evaluated_folds'),
        ):
            with patch.object(adapter, 'read_walk_forward_state', return_value=full):
                result = adapter.execute(self.payload(), SimpleNamespace(state=ROOT))
            self.assertEqual(result['reason'], reason)
            self.assertIsNone(result['percentiles'])

    def test_real_journal_read_only_and_no_sample_in_ipc(self):
        # Existing synthetic fixture supplies a real SQLite journal, no subprocess.
        from tests.test_ui_operations_registry import workspace

        # Load integration dependencies only in the relevant test.
        from tests.test_walk_forward import inputs, fake_worker

        # Load integration dependencies only in the relevant test.
        from quantlab.core import to_dict

        # Load integration dependencies only in the relevant test.
        import desktop_app.shell.main_window as ui

        with workspace() as paths:
            data, plan = inputs(process_start_method='spawn')
            # Load integration dependencies only in the relevant test.
            from quantlab.reporting import save_dataset

            save_dataset(data, paths.state / 'dataset.json')
            preview = ui.execute_ui_operation('ui_walk_forward_preview', {'plan': to_dict(plan)}, paths)
            with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker):
                ui.execute_ui_operation('ui_walk_forward_run', {'plan': preview['plan'], 'preview_identity': preview['preview_identity']}, paths)
            # Prime SQLite's read-only WAL sidecars before measuring journal bytes.
            adapter.read_walk_forward_state(adapter._folder(paths, preview['preview_identity']))
            files = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths.root.rglob('*') if path.is_file()}
            result = ui.execute_ui_operation('ui_capital_scenario', {**self.payload(), 'reference': preview['preview_identity']}, paths)
            self.assertEqual(files, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths.root.rglob('*') if path.is_file()})
            self.assertNotIn('daily_returns', result)
            self.assertIsNone(result['percentiles'])  # Existing fake worker intentionally has no daily-return evidence.


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load integration dependencies only in the relevant test.
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_lazy_run_validation_terminal_and_clear(self):
        # Load integration dependencies only in the relevant test.
        from desktop_app.components.result_panels import WalkForwardResults

        # Load integration dependencies only in the relevant test.
        import shiboken6

        panel = WalkForwardResults()
        self.addCleanup(shiboken6.delete, panel)
        self.assertFalse(hasattr(panel, '_scenario'))
        host = SimpleNamespace(start_job=Mock())
        panel.scenario_host = host
        panel.scenario_state = SimpleNamespace(jobs=SimpleNamespace(active=False))
        result = {'reference': 'a' * 64, 'summary': {'evaluated_oos_folds': 1}}
        panel.set_result(result)
        for widget in (*panel._scenario_fields.values(), panel._scenario_run):
            self.assertTrue(widget.objectName() and widget.accessibleName() and widget.toolTip())
        panel._scenario_fields['threshold'].setText('1000000')
        panel._scenario_run.click()
        host.start_job.assert_not_called()
        panel._scenario_fields['threshold'].setText('900000')
        panel._scenario_run.click()
        host.start_job.assert_called_once()
        self.assertEqual(host.start_job.call_args.args[0], 'ui_capital_scenario')
        self.assertNotIn('daily_returns', host.start_job.call_args.args[1])
        panel.set_scenario(run())
        self.assertIn('1600000', panel._scenario_output.text())
        for status in ('cancelled', 'timed_out', 'rejected'):
            panel.set_scenario(capital.empty_result(status, status))
            self.assertNotIn('1600000', panel._scenario_output.text())
        panel.set_result({**result, 'reference': 'b' * 64})
        self.assertEqual(panel._scenario_output.text(), '')

    def test_deadline_event_clears_statistics(self):
        panel = SimpleNamespace(set_scenario=Mock())
        shell = SimpleNamespace(last_operation='ui_capital_scenario', strategy_page=SimpleNamespace(result_panel=panel))
        self.assertTrue(scenario_presenter.event(shell, {'type': 'error', 'error_type': 'DeadlineExceeded'}))
        result = panel.set_scenario.call_args.args[0]
        self.assertEqual(result['status'], 'timed_out')
        self.assertIsNone(result['percentiles'])

    def test_cancel_uses_worker_stop_without_paper_mutation(self):
        # Load only the cancellation boundary for this case.
        from desktop_app.components.job_progress import cancel_allowed

        shell = SimpleNamespace(
            last_operation='ui_capital_scenario',
            jobs=SimpleNamespace(active=True, cancel=Mock()),
            job_feedback=SimpleNamespace(terminal=False),
            status=Mock(),
            freeze_paper=Mock(),
        )
        self.assertFalse(cancel_allowed(shell))
        shell.jobs.cancel.assert_called_once()
        shell.freeze_paper.assert_not_called()

    def test_scenario_event_owns_presentation_without_strategy_refresh(self):
        shell = SimpleNamespace(last_operation='ui_capital_scenario', record_event=Mock(), notify_local=Mock(), status=Mock(), views_page=Mock())
        self.assertTrue(scenario_presenter.event(shell, {'type': 'result', 'result': run()}))
        shell.notify_local.assert_called_once()
        shell.views_page.render_result.assert_not_called()

    def test_close_stops_scenario_without_reconcile_and_preserves_pending_walk_forward(self):
        # Exercise the real close branch with bounded fake process controls.

        # Only enum values are needed; no native dialogs are opened.
        from PySide6.QtWidgets import QMessageBox

        for pending in (False, True):
            jobs = SimpleNamespace(active=True, poll=Mock())
            jobs.close = Mock(side_effect=lambda: setattr(jobs, 'active', False))
            shell = SimpleNamespace(
                jobs=jobs,
                last_operation='ui_capital_scenario',
                chatgpt_panel=Mock(),
                chatgpt_controller=Mock(),
                _quiesce_and_recover=Mock(),
                _wf_pending_reconcile=pending,
                _wf_launch={'reference': 'a' * 64} if pending else None,
                _analysis_running=False,
                _pending_analysis_reconcile=False,
                _subscription_campaign=False,
                _pending_plan_reconcile=False,
                _chatgpt_job_request=None,
                guard=None,
                start_job=Mock(),
                _safe=Mock(),
                save_market_preferences=Mock(),
                market=Mock(),
                timer=Mock(),
                app_header=Mock(),
                status=Mock(),
            )
            event = Mock()
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes) as question:
                # Load the concrete owner only when this test path is exercised.
                from desktop_app.shell.window import MainWindow

                MainWindow.closeEvent(shell, event)
            question.assert_called_once()
            jobs.close.assert_called_once()
            self.assertFalse(jobs.active)
            if pending:
                shell.start_job.assert_called_once_with('ui_walk_forward_reconcile', shell._wf_launch)
                event.ignore.assert_called_once()
            else:
                shell.start_job.assert_not_called()
                event.accept.assert_called_once()

    def test_catalog_feedback_registry_and_ci_shard(self):
        # Load integration dependencies only in the relevant test.
        from desktop_app.strings.catalog import ui_text

        # Load integration dependencies only in the relevant test.
        from quantlab.desktop_feedback import completion_summary

        # Load integration dependencies only in the relevant test.
        from quantlab.desktop_runtime import UI_OPERATIONS

        # Load integration dependencies only in the relevant test.
        from quantlab.analysis_recovery import SAFE_OPERATIONS

        # Load integration dependencies only in the relevant test.
        from desktop_app.shell.notification_log import safe_summary

        # Load integration dependencies only in the relevant test.
        from tools.run_test_group import core_shard_for_module

        self.assertIn('ui_capital_scenario', UI_OPERATIONS & SAFE_OPERATIONS)
        self.assertEqual(core_shard_for_module('test_capital_scenario_b5'), 'remaining')
        for status in ('completed', 'cancelled', 'timed_out', 'rejected'):
            result = {'status': status, 'reason': 'secret exception'}
            self.assertEqual(completion_summary('ui_capital_scenario', result), ui_text('capital.' + status))
            self.assertEqual(safe_summary('ui_capital_scenario', result), ui_text('capital.' + status))
