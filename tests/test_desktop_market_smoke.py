"""Packaging smoke contracts; synthetic fixtures are not market-data acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
ROOT = Path(__file__).resolve().parents[1]


class MarketSmokeContractTests(unittest.TestCase):
    def test_original_seven_operations_remain_unchanged(self):
        from desktop import _smoke_steps
        self.assertEqual([step[0] for step in _smoke_steps()], [
            'ui_demo', 'ui_backtest', 'ui_select', 'ui_campaign',
            'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'])
        script = (ROOT / 'desktop.py').read_text()
        self.assertIn('smoke_deadline = time.monotonic() + 120', script)
        self.assertIn("market_report['status'] == 'passed'", script)
        self.assertIn("'market_smoke': market_report", script)

    def test_manual_result_without_provenance_cannot_pass(self):
        from desktop import _check_market_worker_result
        for phase, value in [('manual_export', {}), ('manual_import', {'status': 'completed'}),
                             ('unknown', {})]:
            with self.subTest(phase=phase), self.assertRaises((ValueError, KeyError)):
                _check_market_worker_result(phase, value, Path('does-not-exist.json'))

    def test_export_requires_actual_file_and_matching_bundled_source(self):
        from desktop import _check_market_worker_result, _market_smoke_response, _smoke_steps
        from quantlab.manual_exchange import export_request_file, import_response
        from quantlab.reporting import synthetic_dataset
        from quantlab.__main__ import config_from_json
        from quantlab.core import to_dict
        from quantlab.strategies import builtin_strategies
        config = _smoke_steps()[3][1]['config']
        config['backtest_config'] = config_from_json(config['backtest_config'])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, 'manual.json')
            request = export_request_file(synthetic_dataset(120), config, path)
            result = {'mode': 'manual_unverified', 'request': request}
            evidence = _check_market_worker_result('manual_export', result, path)
            self.assertEqual(evidence['module_source_hash'], request['module_source_hash'])
            generator = import_response(synthetic_dataset(120), config,
                _market_smoke_response(request, to_dict(builtin_strategies()[0])))
            self.assertEqual(generator.mode, 'manual_unverified')
            with patch('desktop.Path.read_text', side_effect=FileNotFoundError('missing bundled source')):
                with self.assertRaises(FileNotFoundError):
                    _check_market_worker_result('manual_export', result, path)
            request['module_source_hash'] = '0' * 64
            path.write_text(json.dumps(request), encoding='utf-8')
            with self.assertRaises(ValueError):
                _check_market_worker_result('manual_export', result, path)


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for packaging widget smoke')
class MarketSmokeWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_render_indicators_timeframes_and_typed_payload_are_honest_fixtures(self):
        from desktop import _market_smoke_ui
        report, config, candidate = _market_smoke_ui(self.app)
        self.assertEqual(report['source_type'], 'synthetic')
        self.assertEqual(report['generator'], 'fixture')
        self.assertIn('not official-data or real-model acceptance', report['scope'])
        self.assertFalse(report['network_used'])
        self.assertEqual(report['live_status'], 'disabled')
        self.assertGreater(report['chart_rendered_bars'], 0)
        self.assertGreaterEqual(report['indicator_series'], 7)
        self.assertEqual(report['timeframe_bars'], {'1m':120, '5m':24, '1d':1, '1w':1})
        self.assertEqual(config['max_trials'], 1)
        self.assertEqual(candidate['parameters']['fast'], 5)

    def test_missing_root_modules_fail_instead_of_reporting_market_success(self):
        from desktop import _market_smoke_ui
        for name in ('desktop_market', 'desktop_charts', 'desktop_forms'):
            with self.subTest(module=name), patch.dict(sys.modules, {name: None}):
                with self.assertRaises(ImportError):
                    _market_smoke_ui(self.app)

    def test_invalid_typed_module_contract_fails(self):
        from desktop import _market_smoke_ui
        with patch('desktop_forms.StrategyForm.build_payload', return_value={}):
            with self.assertRaises((ValueError, KeyError)):
                _market_smoke_ui(self.app)

    @unittest.skipIf(sys.platform == 'win32', 'Use an isolated home for failure-report test; Windows profile must remain untouched')
    def test_missing_bundled_root_module_fails_overall_without_dialog_hang(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary, 'report.json')
            env = dict(os.environ, HOME=temporary, QT_QPA_PLATFORM='offscreen', XDG_CACHE_HOME=str(Path(temporary, 'cache')))
            code = "import sys; import desktop; sys.modules['desktop_forms'] = None; raise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))"
            result = subprocess.run([sys.executable, '-c', code, str(report)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 1, result.stderr[-1000:])
            value = json.loads(report.read_text())
            self.assertEqual(value['status'], 'failed')
            self.assertEqual(value['market_smoke']['status'], 'failed')
            self.assertIn(value['market_smoke']['error_type'], ('ImportError', 'ModuleNotFoundError'))

    @unittest.skipIf(sys.platform == 'win32', 'Windows frozen smoke is run by installer harness; do not touch test-runner real profile here')
    def test_source_smoke_runs_worker_manual_exchange_and_preserves_seven_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            report = home / 'report.json'
            env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM='offscreen', XDG_CACHE_HOME=str(home / 'cache'))
            result = subprocess.run([sys.executable, str(ROOT / 'desktop.py'), '--smoke-test', str(report)],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=150)
            self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-2000:])
            value = json.loads(report.read_text())
            self.assertEqual(value['status'], 'passed')
            self.assertEqual(len(value['steps']), 7)
            self.assertTrue(all(row['passed'] for row in value['steps']))
            market = value['market_smoke']
            self.assertEqual(market['status'], 'passed')
            self.assertEqual([row['operation'] for row in market['steps']], ['manual_export', 'manual_import'])
            self.assertTrue(all(row['passed'] for row in market['steps']))
            self.assertEqual(len(market['engine_source_hashes']), 5)
            self.assertEqual(market['real_model_status'], 'not_verified')
            self.assertEqual(market['source_type'], 'synthetic')


if __name__ == '__main__':
    unittest.main()
