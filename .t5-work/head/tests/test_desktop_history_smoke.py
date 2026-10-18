"""Offline synthetic packaging proof, never real TAIFEX or Windows acceptance."""
import hashlib
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


class HistorySmokeFixtureTests(unittest.TestCase):
    def test_tiny_explicit_fixture_contract_and_dates(self):
        from desktop import _history_smoke_fixture
        from quantlab.market_history import COLUMNS, PRODUCT_SOURCES, session_from_dict
        import csv
        with tempfile.TemporaryDirectory() as temporary:
            report, payload = _history_smoke_fixture(Path(temporary))
            self.assertEqual(set(payload), {'history_import', 'local_path', 'sessions', 'dated_policy_confirmed'})
            self.assertIs(payload['history_import'], True)
            self.assertIs(payload['dated_policy_confirmed'], True)
            path = Path(payload['local_path'])
            self.assertEqual(path.parent, Path(temporary))
            self.assertIn('SYNTHETIC', path.name)
            self.assertLess(path.stat().st_size, 2048)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), report['fixture_sha256'])
            self.assertEqual(report['fixture_sha256'], '1f3a1db271101b8442be113f932854eb1382c26bc4a40802302d710fd5c636e7')
            with path.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(tuple(rows[0]), COLUMNS)
            self.assertEqual(len(rows[1:]), 30)
            self.assertEqual({row[1] for row in rows[1:]}, {'TX', 'MTX', 'TMF'})
            self.assertTrue(all(row[0] == '20261008' and row[2] == '202610' for row in rows[1:]))
            self.assertEqual(report['source_type'], 'synthetic')
            self.assertEqual(report['generator'], 'fixture')
            self.assertFalse(report['network_used'])
            for record in payload['sessions']:
                session = session_from_dict(record)
                self.assertEqual(session.trade_date, '2026-10-08')
                self.assertEqual(session.open.isoformat(), '2026-10-08T00:45:00+00:00')
                self.assertEqual(session.end.isoformat(), '2026-10-08T01:46:00+00:00')
                self.assertEqual(session.source, PRODUCT_SOURCES[record['contract_id'].split(':')[1]])
                self.assertFalse(session.include_end)

    def test_omitted_history_module_cannot_prepare_smoke(self):
        from desktop import _history_smoke_fixture
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {'quantlab.market_history': None}):
            with self.assertRaises(ImportError):
                _history_smoke_fixture(Path(temporary))


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for history UI worker')
class HistorySmokeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from desktop import _history_smoke_fixture
        from desktop_ui import execute_ui_operation
        from quantlab.desktop_runtime import AppPaths
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = AppPaths(Path(self.temporary.name)).ensure()
        self.report, self.payload = _history_smoke_fixture(self.paths.root)
        with patch('socket.socket', side_effect=AssertionError('unexpected network')), \
                patch('quantlab.market_providers.refresh_daily', side_effect=AssertionError('daily network dispatch')), \
                patch('quantlab.market_providers.import_daily', side_effect=AssertionError('daily import dispatch')):
            self.result = execute_ui_operation('ui_market_refresh', self.payload, self.paths)

    def check(self, result=None):
        from desktop import _check_history_worker_result
        return _check_history_worker_result(self.result if result is None else result,
            self.paths, self.payload, self.report['fixture_sha256'])

    def test_reloads_actual_cache_and_renders_all_three_products_eight_timeframes(self):
        from desktop import _history_smoke_ui
        series, evidence = self.check()
        self.assertTrue(evidence['cache_reloaded'])
        self.assertEqual(evidence['bars'], 27)
        self.assertEqual(evidence['counters']['missing_minutes'], 156)
        self.assertEqual({item.instrument.symbol for item in series}, {'TX', 'MXF', 'TMF'})
        with patch('socket.socket', side_effect=AssertionError('unexpected network')):
            rendered = _history_smoke_ui(self.app, series)
        self.assertEqual(rendered['chart_render_checks'], 24)
        self.assertEqual(rendered['chart_rendered_bars'], rendered['timeframe_bars'])
        for counts in rendered['timeframe_bars'].values():
            self.assertEqual(counts, {'1m': 9, '3m': 6, '5m': 6, '15m': 5,
                                      '30m': 3, '60m': 2, '1d': 1, '1w': 1})
        self.assertFalse((self.paths.state / 'dataset.json').exists())
        self.assertFalse(any(name == 'trader' or name.startswith('trader.') for name in sys.modules))

    def test_missing_or_forged_worker_result_rejected(self):
        values = [{}, {'status': 'completed'}, dict(self.result, contracts=2),
                  dict(self.result, bars=26), dict(self.result, mode='official_local_import'),
                  dict(self.result, source_hash='0' * 64), dict(self.result, policy_hash='0' * 64),
                  dict(self.result, counters={}), dict(self.result, warnings=[])]
        for value in values:
            with self.subTest(result=value), self.assertRaises((ValueError, KeyError)):
                self.check(value)

    def test_changed_source_rejected(self):
        source = Path(self.payload['local_path'])
        source.write_bytes(source.read_bytes().replace(b',100,2,', b',101,2,', 1))
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.check()

    def test_missing_corrupt_and_redigested_wrong_cache_rejected(self):
        path = self.paths.state / 'market_history' / (self.result['cache_id'] + '.json')
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError): self.check()
        path.write_bytes(b'{"payload":')
        with self.assertRaises(ValueError): self.check()
        envelope = json.loads(original)
        envelope['payload']['bars'][0]['high'] = '999'
        envelope['sha256'] = hashlib.sha256(json.dumps(envelope['payload'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
        path.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'tick normalization mismatch'):
            self.check()

    @unittest.skipIf(sys.platform == 'win32', 'Frozen installer harness owns isolated Windows profile smoke')
    def test_missing_module_bad_result_and_worker_failure_fail_overall(self):
        variants = {
            'missing_module': "sys.modules['quantlab.market_history'] = None\n",
            'bad_result': "original = desktop._check_history_worker_result\ndef bad(result, *args):\n return original(dict(result, contracts=2), *args)\ndesktop._check_history_worker_result = bad\n",
            'worker_failure': "original = desktop._history_smoke_fixture\ndef missing(root):\n report, payload = original(root)\n payload['local_path'] = str(root / 'missing.csv')\n return report, payload\ndesktop._history_smoke_fixture = missing\n",
        }
        for name, injected in variants.items():
            with self.subTest(failure=name), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                report = home / 'report.json'
                env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM='offscreen',
                           XDG_CACHE_HOME=str(home / 'cache'))
                code = 'import sys\nimport desktop\n' + injected + "raise SystemExit(desktop.main(['--smoke-test', sys.argv[1]]))\n"
                result = subprocess.run([sys.executable, '-c', code, str(report)], cwd=ROOT,
                                        env=env, capture_output=True, text=True, timeout=150)
                self.assertEqual(result.returncode, 1, result.stderr[-2000:])
                value = json.loads(report.read_text())
                self.assertEqual(value['status'], 'failed')
                history = value['history_smoke']
                self.assertEqual(history['status'], 'failed')
                if name == 'missing_module':
                    self.assertIn(history['error_type'], ('ImportError', 'ModuleNotFoundError'))
                else:
                    self.assertEqual(len(value['steps']), 7)
                    self.assertTrue(all(row['passed'] for row in value['steps']))
                    self.assertEqual(len(value['market_smoke']['steps']), 2)
                    self.assertTrue(all(row['passed'] for row in value['market_smoke']['steps']))
                    self.assertEqual(history['steps'][0]['operation'], 'history_import')
                    self.assertFalse(history['steps'][0]['passed'])


if __name__ == '__main__':
    unittest.main()
