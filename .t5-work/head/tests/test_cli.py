import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from quantlab.__main__ import main


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def call(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_demo_backtest_compare_persist(self):
        args = ('demo', '--output', str(self.root), '--bars', '240')
        status, out, error = self.call(*args)
        self.assertEqual(status, 0, error)
        demo = json.loads(out)
        self.assertEqual(len(demo['reports']), 5)
        status, again, error = self.call(*args)
        self.assertEqual(json.loads(again), demo)
        result = demo['reports'][0]['result']
        status, out, error = self.call('compare', result)
        self.assertEqual(status, 0, error)
        self.assertEqual(len(json.loads(out)), 1)
        status, out, error = self.call('backtest', demo['dataset'], '--family', 'trend', '--output', str(self.root / 'again'))
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(out)['result_hash'], demo['reports'][0]['result_hash'])

    def test_missing_and_bad_input(self):
        status, _, error = self.call('compare', str(self.root / 'missing'))
        self.assertEqual(status, 2)
        self.assertTrue(error.startswith('quantlab:'))
        status, _, error = self.call('demo', '--output', str(self.root), '--bars', '0')
        self.assertEqual(status, 2)

    def test_import_backtest_and_campaign_reopen(self):
        status, out, error = self.call('import', 'examples/synthetic_bars.csv', '--kind', 'synthetic_bars',
                                      '--calendar', 'examples/synthetic_calendar.json', '--output', str(self.root / 'dataset.json'))
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(out)['manifest']['source_type'], 'synthetic')
        status, out, error = self.call('backtest', str(self.root / 'dataset.json'), '--config', 'examples/synthetic_config.json', '--output', str(self.root / 'reports'))
        self.assertEqual(status, 0, error)
        args = ('campaign', str(self.root / 'dataset.json'), '--output', str(self.root / 'campaign'))
        status, out, error = self.call(*args)
        self.assertEqual(status, 0, error)
        result = json.loads(out)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['attempts']), 15)
        status, again, error = self.call(*args)
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(again), result)
