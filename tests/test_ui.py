"""Run with optional Streamlit dependency. Core-only runs explicitly skip UI."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None


@unittest.skipUnless(HAS_STREAMLIT, 'Optional Streamlit is not installed; UI verification not run')
class UITests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.AppTest = AppTest
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.environment = patch.dict(os.environ, {'QUANTLAB_WORKSPACE': str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'research_app.py')).run(timeout=30)
        self.assertFalse(self.app.exception)

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run(timeout=60)
        self.assertFalse(self.app.exception)

    def field(self, kind, label):
        return next(item for item in getattr(self.app, kind) if item.label == label)

    def test_empty_error_and_import(self):
        self.assertTrue(self.field('button', 'Run backtest').disabled)
        self.click('Import local data')
        self.assertTrue(self.app.error)
        self.field('text_input', 'Local CSV / RPT path').set_value('examples/synthetic_bars.csv')
        self.field('text_input', 'Session calendar JSON path').set_value('examples/synthetic_calendar.json')
        self.field('selectbox', 'Import kind').set_value('synthetic_bars')
        self.click('Import local data')
        self.assertFalse(self.app.error)
        self.assertTrue((self.root / 'dataset.json').exists())
        self.click('Run backtest')
        self.assertEqual(len(list((self.root / 'reports').glob('*/result.json'))), 1)
        self.field('text_area', 'Backtest configuration JSON').set_value('{broken')
        self.click('Run backtest')
        self.assertTrue(self.app.error)

    def test_repeated_run_selection_and_restart(self):
        self.click('Create synthetic dataset')
        self.click('Run backtest')
        self.click('Run backtest')
        self.assertEqual(len(list((self.root / 'reports').glob('*/result.json'))), 1)
        self.click('Select immutable strategy')
        selection = json.loads((self.root / 'selection.json').read_text())
        self.assertEqual(len(selection['strategy_hash']), 64)
        self.app = self.AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'research_app.py')).run(timeout=30)
        self.assertFalse(self.app.exception)
        self.assertTrue(any(selection['strategy_hash'] in item.value for item in self.app.json))
        self.assertTrue(any('Selected result SHA-256' in item.value for item in self.app.caption))

    def test_campaign_repeat_and_path_error(self):
        self.click('Create synthetic dataset')
        self.click('Run / reopen campaign')
        path = self.root / 'campaigns' / 'fixture-demo' / 'campaign.json'
        initial = json.loads(path.read_text())
        self.assertEqual(initial['status'], 'completed')
        self.assertEqual(len(initial['attempts']), 15)
        self.click('Run / reopen campaign')
        self.assertEqual(json.loads(path.read_text()), initial)
        self.field('text_input', 'Campaign directory name').set_value('../escape').run()
        self.assertTrue(self.field('button', 'Run / reopen campaign').disabled)
        self.assertFalse((self.root / 'escape').exists())

    def test_paper_repeated_intent_stop_and_reconciliation_error(self):
        self.click('Create synthetic dataset')
        self.click('Run backtest')
        self.click('Select immutable strategy')
        self.click('Reconcile paper state')
        self.click('Start paper / remove kill switch')
        self.click('Submit paper intent')
        self.click('Submit paper intent')
        snapshots = [json.loads(item.value) for item in self.app.json]
        account = next(item for item in reversed(snapshots) if isinstance(item, dict) and 'orders' in item)
        self.assertEqual(len(account['orders']), 1)
        self.click('Stop paper / enable kill switch')
        snapshots = [json.loads(item.value) for item in self.app.json]
        account = next(item for item in reversed(snapshots) if isinstance(item, dict) and 'orders' in item)
        self.assertTrue(account['kill_switch'])
        bad = dict(account, cash='123')
        self.field('text_area', 'External paper snapshot for reconciliation JSON').set_value(json.dumps(bad))
        self.click('Reconcile paper state')
        self.assertTrue(self.app.error)

    def test_selected_strategy_paper_replay(self):
        self.click('Create synthetic dataset')
        self.click('Run backtest')
        self.click('Select immutable strategy')
        self.click('Reconcile paper state')
        self.click('Start selected strategy replay')
        self.click('Advance replay batch')
        snapshots = [json.loads(item.value) for item in self.app.json]
        account = next(item for item in reversed(snapshots) if isinstance(item, dict) and 'orders' in item)
        self.assertTrue(account['fills'])
        replay = next(item for item in reversed(snapshots) if isinstance(item, dict) and 'cursor' in item)
        self.assertEqual(replay['cursor'], 100)
        self.click('Stop selected strategy replay')
        self.click('Advance replay batch')
        snapshots = [json.loads(item.value) for item in self.app.json]
        replay = next(item for item in reversed(snapshots) if isinstance(item, dict) and 'cursor' in item)
        self.assertEqual(replay['cursor'], 100)
        self.assertFalse(replay['active'])
