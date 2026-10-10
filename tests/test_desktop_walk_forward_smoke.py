"""Bounded generated-bar packaging smoke; never actual research/Windows acceptance."""
import copy
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ['ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read']


def run_job(manager, operation, payload):
    """Use the real spawn worker and nested evaluators, never fabricated scores."""
    manager.start(operation, payload)
    events = []
    deadline = time.monotonic() + 45
    while manager.active and time.monotonic() < deadline:
        events.extend(manager.poll())
        time.sleep(.01)
    events.extend(manager.poll())
    if manager.active:
        manager.close()
        raise AssertionError('Bounded synthetic worker did not stop')
    failures = [event for event in events if event['type'] in ('error', 'cancelled')]
    results = [event['result'] for event in events if event['type'] == 'result']
    if failures or len(results) != 1:
        raise AssertionError(str(failures or events))
    return results[0]


class WalkForwardSmokeFixtureTests(unittest.TestCase):
    def test_fixed_two_fold_five_builtin_plan_and_explicit_nonacceptance(self):
        from desktop import _walk_forward_smoke_fixture, _smoke_steps
        from quantlab.core import to_dict
        from quantlab.desktop_runtime import AppPaths
        from quantlab.reporting import load_dataset
        from quantlab.strategies import builtin_strategies
        from quantlab.walk_forward import walk_forward_plan_from_dict, _validate_source
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary))
            with patch('socket.create_connection', side_effect=AssertionError('No network')):
                report, payload = _walk_forward_smoke_fixture(paths)
            data = load_dataset(paths.state / 'dataset.json')
            plan = walk_forward_plan_from_dict(payload['plan'])
            _validate_source(data, plan)
            self.assertEqual(len(data.bars), 200)
            self.assertEqual(data.manifest['data_hash'], report['fixture_data_hash'])
            self.assertEqual(report['fixture_data_hash'], '9616690f184fa8705a4c1e6c38d726e6f6b0f76f7d2aa121bbd5f74116314f28')
            self.assertEqual([to_dict(s) for s in plan.candidate_pool], [to_dict(s) for s in builtin_strategies()])
            self.assertEqual(plan.ranking, {'metric': 'net_pnl', 'minimum': '0', 'min_trades': 1, 'max_drawdown_pct': '0.10'})
            self.assertEqual([to_dict(f) for f in plan.folds], [
                {'train': [0, 60], 'validation': [60, 100], 'oos': [100, 140]},
                {'train': [40, 100], 'validation': [100, 140], 'oos': [140, 180]}])
            self.assertEqual(plan.final_holdout, (180, 200))
            self.assertEqual((plan.max_evaluations, plan.max_runtime_seconds, plan.max_bars), (22, 30, 200))
            self.assertEqual(plan.process_start_method, 'spawn')
            self.assertEqual(plan.max_ipc_bytes, 65536)
            self.assertEqual(report['source_type'], 'synthetic')
            self.assertEqual(report['model_calls'], 0)
            for name in ('network_used', 'paper_eligible', 'independent_oos', 'ranking_eligible'):
                self.assertIs(report[name], False)
            for name in ('real_market_status', 'real_model_status', 'windows_client_status'):
                self.assertEqual(report[name], 'not_verified')
            self.assertIn('never actual research PASS', report['scope'])
            self.assertEqual({p.name for p in paths.state.iterdir()}, {'dataset.json'})
            self.assertFalse((paths.controls / 'holdout-registry.sqlite3').exists())
        self.assertEqual([operation for operation, _ in _smoke_steps()],
            ['ui_demo', 'ui_backtest', 'ui_select', 'ui_campaign', 'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'])
        source = (ROOT / 'desktop.py').read_text(encoding='utf-8')
        self.assertIn('smoke_deadline = time.monotonic() + 120', source)

    def test_omitted_core_module_cannot_prepare_smoke(self):
        from desktop import _walk_forward_smoke_fixture
        from quantlab.desktop_runtime import AppPaths
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {'quantlab.walk_forward': None}):
            with self.assertRaises(ImportError):
                _walk_forward_smoke_fixture(AppPaths(Path(temporary)))


@unittest.skipUnless(HAS_QT, 'Pinned Qt required by desktop worker adapter')
class WalkForwardSmokeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from desktop import _walk_forward_smoke_fixture, _check_walk_forward_smoke_result
        from quantlab.desktop_runtime import AppPaths, JobManager
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.paths = AppPaths(Path(cls.temporary.name))
        cls.report, cls.payload = _walk_forward_smoke_fixture(cls.paths)
        with closing(JobManager(cls.paths)) as manager:
            preview = run_job(manager, OPERATIONS[0], cls.payload)
            cls.report.update(_check_walk_forward_smoke_result(OPERATIONS[0], preview, cls.paths, cls.payload, cls.report))
            cls.result = run_job(manager, OPERATIONS[1], {**cls.payload, 'preview_identity': cls.report['reference']})
            cls.report.update(_check_walk_forward_smoke_result(OPERATIONS[1], cls.result, cls.paths, cls.payload, cls.report))
            cls.read_result = run_job(manager, OPERATIONS[2], {'reference': cls.report['reference']})
            cls.report.update(_check_walk_forward_smoke_result(OPERATIONS[2], cls.read_result, cls.paths, cls.payload, cls.report))
        cls.journal = cls.paths.state / 'walk_forward' / cls.report['reference'] / 'walk_forward.sqlite3'
        cls.original_journal = cls.journal.read_bytes()

    def check(self, result=None, operation='ui_walk_forward_read'):
        from desktop import _check_walk_forward_smoke_result
        return _check_walk_forward_smoke_result(operation, self.result if result is None else result,
                                               self.paths, self.payload, self.report)

    def test_real_nested_spawn_evaluations_and_read_only_journal(self):
        from quantlab.walk_forward import SOURCE_FILES, read_walk_forward_state
        self.assertEqual(self.result, self.read_result)
        evidence = self.check()
        self.assertTrue(evidence['journal_reloaded']); self.assertTrue(evidence['read_verified'])
        self.assertLess(evidence['compact_result_bytes'], 65536)
        self.assertLessEqual(evidence['journal_bytes'], 1048576)
        self.assertEqual(evidence['summary']['evaluations_reserved'], 22)
        self.assertEqual(evidence['summary']['evaluated_oos_folds'], 2)
        self.assertEqual([f['winner'] for f in evidence['folds']], ['mean_reversion-v1'] * 2)
        self.assertEqual([f['validation_closed_lots'] for f in evidence['folds']], [2, 3])
        self.assertEqual([f['oos_closed_lots'] for f in evidence['folds']], [3, 3])
        self.assertEqual([f['zero_trade_candidates_excluded'] for f in evidence['folds']], [2, 2])
        state = read_walk_forward_state(self.journal.parent)
        self.assertEqual(set(self.report['engine_source_hashes']), set(SOURCE_FILES))
        self.assertIn('walk_forward.py', self.report['engine_source_hashes'])
        self.assertEqual(state['registry_reservation']['status'], 'reserved_consumed')
        self.assertTrue(all(r['status'] == 'evaluated' for r in state['evaluations']))
        self.assertEqual(self.journal.read_bytes(), self.original_journal)

    def test_malformed_references_compact_results_and_evidence_fail_closed(self):
        variants = [{}, {'status': 'completed'}, dict(self.result, reference='../outside'),
                    dict(self.result, reference='0' * 64), dict(self.result, status='completed_with_errors'),
                    dict(self.result, journal='outside.sqlite3'), dict(self.result, evaluations=[]),
                    dict(self.result, padding='x' * 65536)]
        for key, value in [('model_calls', 1), ('paper_eligible', True), ('evaluated_oos_folds', 0),
                           ('final_holdout_status', 'evaluated')]:
            variants.append({**self.result, 'summary': {**self.result['summary'], key: value}})
        for value in variants:
            with self.subTest(result=str(value)[:70]), self.assertRaises(ValueError):
                self.check(value)

    def test_missing_oversized_and_redigested_corrupt_journal_rejected(self):
        from quantlab.core import canonical_json, content_hash
        from quantlab.walk_forward import read_walk_forward_state
        original = read_walk_forward_state(self.journal.parent)
        try:
            self.journal.unlink()
            with self.assertRaises((ValueError, OSError)): self.check()
            self.journal.write_bytes(self.original_journal + b'x' * 1048576)
            with self.assertRaisesRegex(ValueError, 'fixture bound'): self.check()
            for name in ('model_calls', 'winner', 'source_binding', 'final_holdout'):
                self.journal.write_bytes(self.original_journal)
                state = copy.deepcopy(original)
                if name == 'model_calls': state['model_calls'] = 1
                elif name == 'winner': state['folds'][0]['selection']['pool_index'] = 2
                elif name == 'source_binding': state['binding']['source_data_hash'] = '0' * 64
                else: state['final_holdout_status'] = 'evaluated'
                state['state_hash'] = content_hash({k: v for k, v in state.items() if k != 'state_hash'})
                # A transaction context commits but does not close the Windows file handle.
                with closing(sqlite3.connect(self.journal)) as db, db:
                    db.execute('UPDATE state SET payload=? WHERE id=1', (canonical_json(state),))
                with self.subTest(corruption=name), self.assertRaises(ValueError): self.check()
        finally:
            self.journal.write_bytes(self.original_journal)

    def test_journal_read_and_no_paper_side_effects_are_required(self):
        from desktop import _check_walk_forward_smoke_result
        with self.assertRaisesRegex(ValueError, 'read mutated'):
            _check_walk_forward_smoke_result(OPERATIONS[2], self.result, self.paths, self.payload,
                                             {**self.report, 'journal_sha256': '0' * 64})
        sentinel = self.paths.state / 'selection.json'
        try:
            sentinel.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'AI or paper'): self.check()
        finally:
            sentinel.unlink()

    def test_real_no_winner_decision_cannot_satisfy_smoke_by_skipping_oos(self):
        from desktop import _walk_forward_smoke_fixture, _check_walk_forward_smoke_result
        from quantlab.desktop_runtime import AppPaths, JobManager
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary)); report, payload = _walk_forward_smoke_fixture(paths)
            payload['plan']['ranking']['minimum'] = '1000000'
            with closing(JobManager(paths)) as manager:
                preview = run_job(manager, OPERATIONS[0], payload)
                report.update(_check_walk_forward_smoke_result(OPERATIONS[0], preview, paths, payload, report))
                result = run_job(manager, OPERATIONS[1], {**payload, 'preview_identity': report['reference']})
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['summary']['evaluations_reserved'], 20)
            self.assertEqual(result['summary']['evaluated_oos_folds'], 0)
            self.assertTrue(all(f['status'] == 'no_eligible_candidate' and f['winner'] is None
                                and f['oos']['status'] == 'not_evaluated' for f in result['folds']))
            with self.assertRaisesRegex(ValueError, 'journal or result mismatch'):
                _check_walk_forward_smoke_result(OPERATIONS[1], result, paths, payload, report)


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for full smoke')
@unittest.skipIf(sys.platform == 'win32', 'Frozen installer harness owns isolated Windows profile smoke')
class WalkForwardSmokeProcessTests(unittest.TestCase):
    def smoke(self, injected=''):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary); report = home / 'report.json'
            settings = home / '.local/share/MarkAuto/state-v1/settings.json'
            settings.parent.mkdir(parents=True)
            original = b'{\n "schema_version": 1, "settings": {"sentinel": "preserve exact bytes", "persist_logs": false}\n}\n'
            settings.write_bytes(original)
            # Inherited by every genuine spawn evaluator: accidental network fails.
            (home / 'sitecustomize.py').write_text(
                "import socket\n"
                "def denied(*args, **kwargs): raise AssertionError('Network forbidden in smoke')\n"
                "socket.create_connection = socket.getaddrinfo = denied\n"
                "original_connect = socket.socket.connect\n"
                "def connect(self, address):\n"
                " if self.family in (socket.AF_INET, socket.AF_INET6): return denied()\n"
                " return original_connect(self, address)\n"
                "socket.socket.connect = socket.socket.connect_ex = connect\n")
            env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM='offscreen',
                       XDG_CACHE_HOME=str(home / 'cache'), PYTHONPATH=str(home) + os.pathsep + str(ROOT))
            code = ('import sys\nimport desktop\nfrom PySide6.QtWidgets import QMessageBox\n'
                    "def no_modal(*args): raise AssertionError('Smoke must never open a modal')\n"
                    'QMessageBox.critical = QMessageBox.information = no_modal\n' + injected +
                    "raise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))\n")
            started = time.monotonic()
            result = subprocess.run([sys.executable, '-c', code, str(report)], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=150)
            elapsed = time.monotonic() - started
            self.assertEqual(settings.read_bytes(), original, 'Smoke must preserve settings bytes on success and failure')
            self.assertTrue(report.exists(), result.stderr[-2000:])
            return result, json.loads(report.read_text()), elapsed

    def test_full_smoke_preserves_all_gates_settings_and_120_second_budget(self):
        result, value, elapsed = self.smoke()
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(value['status'], 'passed')
        self.assertFalse(value['timed_out']); self.assertLess(elapsed, 120)
        self.assertEqual(len(value['steps']), 7)
        self.assertTrue(all(row['passed'] for row in value['steps']))
        self.assertEqual(value['auth_smoke']['status'], 'passed')
        self.assertEqual(value['market_smoke']['status'], 'passed')
        self.assertEqual([r['operation'] for r in value['market_smoke']['steps']], ['manual_export', 'manual_import'])
        self.assertEqual(value['history_smoke']['status'], 'passed')
        self.assertEqual(value['history_smoke']['chart_render_checks'], 24)
        wf = value['walk_forward_smoke']
        self.assertEqual(wf['status'], 'passed')
        self.assertEqual(wf['steps'], [{'operation': op, 'passed': True} for op in OPERATIONS])
        self.assertEqual(wf['summary']['evaluations_reserved'], 22)
        self.assertEqual(wf['summary']['evaluated_oos_folds'], 2)
        self.assertTrue(wf['journal_reloaded']); self.assertTrue(wf['read_verified'])
        self.assertEqual(wf['final_holdout_status'], 'excluded_not_evaluated')
        self.assertEqual(wf['real_model_status'], 'not_verified')
        self.assertEqual(wf['real_market_status'], 'not_verified')
        self.assertEqual(wf['windows_client_status'], 'not_verified')
        self.assertFalse(wf['paper_eligible']); self.assertFalse(wf['network_used'])
        self.assertIn('never actual research PASS', wf['scope'])

    def test_omitted_module_malformed_result_reference_and_worker_failure_fail_overall(self):
        variants = {
            'missing_module': "sys.modules['quantlab.walk_forward'] = None\n",
            'bad_result': "original = desktop._check_walk_forward_smoke_result\ndef bad(op, result, *args):\n if op == 'ui_walk_forward_run': result = dict(result, summary={})\n return original(op, result, *args)\ndesktop._check_walk_forward_smoke_result = bad\n",
            'bad_reference': "original = desktop._check_walk_forward_smoke_result\ndef bad(op, result, *args):\n if op == 'ui_walk_forward_read': result = dict(result, reference='../outside')\n return original(op, result, *args)\ndesktop._check_walk_forward_smoke_result = bad\n",
            'worker_failure': "original = desktop._check_walk_forward_smoke_result\ndef bad(op, result, paths, *args):\n evidence = original(op, result, paths, *args)\n if op == 'ui_walk_forward_preview': (paths.state / 'dataset.json').unlink()\n return evidence\ndesktop._check_walk_forward_smoke_result = bad\n",
            'launch_failure': "from quantlab.desktop_runtime import JobManager\noriginal = JobManager.start\ndef bad(self, op, payload):\n if op == 'ui_walk_forward_run': raise RuntimeError('Injected launch failure')\n return original(self, op, payload)\nJobManager.start = bad\n",
        }
        for name, injected in variants.items():
            with self.subTest(failure=name):
                result, value, elapsed = self.smoke(injected)
                self.assertEqual(result.returncode, 1, result.stderr[-2000:])
                self.assertLess(elapsed, 120)
                self.assertEqual(value['status'], 'failed')
                wf = value['walk_forward_smoke']; self.assertEqual(wf['status'], 'failed')
                if name == 'missing_module':
                    self.assertIn(wf['error_type'], ('ImportError', 'ModuleNotFoundError'))
                else:
                    self.assertEqual(len(value['steps']), 7)
                    self.assertTrue(all(row['passed'] for row in value['steps']))
                    self.assertEqual(len(value['market_smoke']['steps']), 2)
                    self.assertTrue(all(row['passed'] for row in value['market_smoke']['steps']))
                    self.assertEqual(value['history_smoke']['chart_render_checks'], 24)
                    self.assertTrue(value['history_smoke']['steps'][0]['passed'])
                    self.assertFalse(wf['steps'][-1]['passed'])
                    self.assertIn(wf['steps'][-1]['operation'], OPERATIONS)


if __name__ == '__main__':
    unittest.main()
