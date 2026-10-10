"""Typed expiry inputs preserve explicit metadata and existing research gates.

All embedded market-like bars are synthetic test fixtures. Actual-data smoke
evidence is produced separately; these tests never run a campaign or a model.
"""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None
CONTRACT = 'TAIFEX:TMF:202610'
EXPIRY = '2026-10-21'


@unittest.skipUnless(HAS_QT, 'Install desktop requirements for Qt expiry tests')
class DesktopExpiryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def form(self):
        from desktop_forms import BacktestForm
        form = BacktestForm()
        self.addCleanup(form.close)
        return form

    def add(self, form, contract=CONTRACT, expiry=EXPIRY):
        from PySide6.QtWidgets import QPushButton, QTableWidgetItem
        form.expiries.findChild(QPushButton, 'instrument_expiries_add').click()
        row = form.expiries.table.rowCount() - 1
        for column, value in enumerate((contract, expiry)):
            form.expiries.table.setItem(row, column, QTableWidgetItem(value))

    def test_empty_defaults_do_not_infer_or_claim_verified_expiry(self):
        form = self.form()
        self.assertEqual(form.expiries.table.rowCount(), 0)
        self.assertEqual(form.build_payload()['config']['instrument_expiries'], {})
        self.assertIn('https://www.taifex.com.tw/cht/2/tMF', form.expiry_note.text())
        self.assertIn('不會驗證來源', form.expiry_note.text())
        self.assertIn('該年度交易行事曆及異動公告', form.expiry_note.text())
        self.assertTrue(form.expiries.table.accessibleName())

    def test_add_and_type_cells_without_json(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLineEdit, QPushButton
        form = self.form(); form.show(); self.app.processEvents()
        QTest.mouseClick(form.expiries.findChild(QPushButton, 'instrument_expiries_add'), Qt.MouseButton.LeftButton)
        table = form.expiries.table
        for column, value in enumerate((CONTRACT, EXPIRY)):
            table.setCurrentCell(0, column)
            table.edit(table.model().index(0, column))
            self.app.processEvents()
            editor = self.app.focusWidget()
            self.assertIsInstance(editor, QLineEdit)
            QTest.keyClicks(editor, value)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            self.app.processEvents()
        self.assertEqual(form.build_payload()['config']['instrument_expiries'], {CONTRACT: EXPIRY})

    def test_rejects_empty_malformed_contracts_and_invalid_dates(self):
        from quantlab.core import ValidationError
        for contract, expiry in (
            ('', EXPIRY), ('TMF202610', EXPIRY), ('TAIFEX:TMF:202613', EXPIRY),
            ('TAIFEX:TMF:000010', EXPIRY), ('TAIFEX:TXF:202610', EXPIRY),
            (CONTRACT, ''), (CONTRACT, '2026-02-30'), (CONTRACT, '2026-1-21'),
            (CONTRACT, '20261021'), (CONTRACT, '2026-10-21T00:00:00Z'),
            (CONTRACT, '2026-10-21\n2026-10-22')):
            with self.subTest(contract=contract, expiry=expiry):
                form = self.form(); self.add(form, contract, expiry)
                with self.assertRaises(ValidationError): form.build_payload()

    def test_rejects_duplicate_contract_instead_of_overwriting(self):
        from quantlab.core import ValidationError
        for second in (EXPIRY, '2026-10-20'):
            form = self.form(); self.add(form); self.add(form, ' ' + CONTRACT + ' ', second)
            with self.assertRaisesRegex(ValidationError, '合約重複'):
                form.build_payload()

    def test_add_remove_and_repeated_loads_clear_stale_rows(self):
        from PySide6.QtWidgets import QPushButton
        form = self.form(); original = form.build_payload()
        self.add(form); self.add(form, 'TAIFEX:TMF:202611', '2026-11-18')
        table = form.expiries.table; table.setCurrentCell(0, 0)
        form.expiries.findChild(QPushButton, 'instrument_expiries_remove').click()
        self.assertEqual(form.build_payload()['config']['instrument_expiries'], {'TAIFEX:TMF:202611':'2026-11-18'})
        for _ in range(2):
            form.from_payload(original)
            self.assertEqual(table.rowCount(), 0)
            self.assertEqual(form.build_payload(), original)
            self.add(form)
        form.from_payload({'config': {'initial_cash':'1', 'costs':original['config']['costs']}})
        self.assertEqual(form.build_payload()['config']['instrument_expiries'], {})

    def test_preserves_loaded_mapping_and_advanced_policy_fields(self):
        from quantlab.core import to_dict
        from quantlab.reporting import demo_config
        config = to_dict(demo_config())
        config.update(instrument_expiries={CONTRACT:EXPIRY, 'TAIFEX:TMF:202611':'2026-11-18'},
            source_commit='preserve-source', settlement_mode='daily_mtm',
            margin_schedule=[{'effective_from':'2026-01-01','initial_margin':'120000','maintenance_margin':'90000','version':'test-margin'}],
            roll_events=[{'known_at':'2026-10-19T00:00:00Z','effective_at':'2026-10-20T00:45:00Z','from_contract':CONTRACT,'to_contract':'TAIFEX:TMF:202611'}],
            settlement_events=[{'timestamp':'2026-10-19T05:45:00Z','known_at':'2026-10-19T05:45:00Z','contract_id':CONTRACT,'price':'20000','version':'test-settlement'}])
        config['cost_schedule'] = [{**config['costs'], 'effective_from':'2026-10-01', 'version':'test-cost'}]
        payload = {'config':config, 'start_date':'2026-10-01', 'end_date':'2026-10-20'}
        expected = deepcopy(payload)
        form = self.form().from_payload(payload)
        payload['config']['instrument_expiries'].clear()
        self.assertEqual(form.build_payload(), expected)
        edited = form.build_payload(); edited['config']['margin_schedule'].clear()
        self.assertEqual(form.build_payload(), expected)
        form.expiries.table.item(0, 1).setText('2026-10-20')
        expected['config']['instrument_expiries'][CONTRACT] = '2026-10-20'
        self.assertEqual(form.build_payload(), expected)

    def test_dates_are_explicit_inputs_not_guessed_from_month(self):
        form = self.form(); self.add(form, CONTRACT, '2026-10-20')
        self.assertEqual(form.build_payload()['config']['instrument_expiries'][CONTRACT], '2026-10-20')

    def test_engine_missing_expiry_guard_remains_for_non_synthetic_data(self):
        from dataclasses import replace
        from quantlab.__main__ import config_from_json
        from quantlab.backtest import run_backtest
        from quantlab.core import ValidationError
        from quantlab.reporting import synthetic_dataset
        from quantlab.strategies import builtin_strategies
        synthetic = synthetic_dataset(160)
        fixture = replace(synthetic, manifest={**synthetic.manifest, 'source_type':'proxy'})
        form = self.form()
        with self.assertRaisesRegex(ValidationError, 'explicit instrument expiry required'):
            run_backtest(fixture, builtin_strategies()[0], config_from_json(form.build_payload()['config']))
        self.add(form, fixture.bars[0].contract_id, '2026-01-21')
        result = run_backtest(fixture, builtin_strategies()[0], config_from_json(form.build_payload()['config']))
        self.assertEqual(result.manifest['source_type'], 'proxy')

    def test_normal_window_sends_same_expiries_to_backtest_and_campaign(self):
        from desktop_ui import MainWindow
        from quantlab.core import to_dict, ValidationError
        from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
        from quantlab.reporting import demo_config, synthetic_dataset
        from quantlab.research import demo_campaign_config
        with tempfile.TemporaryDirectory() as temporary:
            paths = AppPaths(Path(temporary) / 'workspace').ensure()
            jobs = JobManager(paths)
            window = MainWindow(paths, jobs, SettingsStore(paths.state/'settings.json'), BackupManager(paths, jobs))
            try:
                window.campaign_form.from_payload(to_dict(demo_campaign_config(synthetic_dataset(160), demo_config())))
                self.add(window.backtest_form)
                with patch.object(window, 'start_job') as launch:
                    window.run_backtest()
                    operation, backtest = launch.call_args.args
                    self.assertEqual(operation, 'ui_backtest')
                    window.run_campaign()
                    operation, campaign = launch.call_args.args
                    self.assertEqual(operation, 'ui_campaign')
                    self.assertEqual(backtest['config']['instrument_expiries'], {CONTRACT:EXPIRY})
                    self.assertEqual(backtest['config'], campaign['config']['backtest_config'])
                    launch.reset_mock()
                    self.add(window.backtest_form)
                    with self.assertRaises(ValidationError): window.run_backtest()
                    with self.assertRaises(ValidationError): window.run_campaign()
                    launch.assert_not_called()
            finally:
                jobs.close(); window.close(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
