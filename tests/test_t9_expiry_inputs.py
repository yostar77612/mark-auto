"""T9 A: offline provenance, unchanged payload/hash gates and synthetic summary."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from quantlab.taifex_expiries import load_expiries, lookup_expiry, validate_data
from quantlab.core import content_hash

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / 'tests/fixtures/t9_manual_payloads.json').read_text(encoding='utf-8'))


class ExpiryDataTests(unittest.TestCase):
    def test_exact_coverage_and_provenance(self):
        data = load_expiries()
        expected = [
            ('202510', '2025-10-15'),
            ('202511', '2025-11-19'),
            ('202512', '2025-12-17'),
            ('202601', '2026-01-21'),
            ('202602', '2026-02-23'),
            ('202603', '2026-03-18'),
            ('202604', '2026-04-15'),
            ('202605', '2026-05-20'),
            ('202606', '2026-06-17'),
            ('202607', '2026-07-15'),
            ('202608', '2026-08-19'),
            ('202609', '2026-09-16'),
        ]
        self.assertEqual([(r['contract_month'], r['expiry_date']) for r in data['expiries']], expected)
        self.assertEqual(data['verified_date'], '2026-10-18')
        self.assertRegex(data['sources'][0]['sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(data['sources'][0]['sha256'], 'e9869a6cc927ec094201d04eee866ea0d3bc7f55fab7a7ea71c09900daa87656')
        self.assertEqual(data['sources'][0]['retrieval_date'], '2026-10-18')
        self.assertEqual(data['trading_calendar']['status'], 'not_bundled')
        for product in ('TX', 'MTX', 'TMF'):
            for month, expiry in expected:
                self.assertEqual(lookup_expiry(product, month)['expiry_date'], expiry)
            for month in ('202509', '202610', '202609W2'):
                self.assertIsNone(lookup_expiry(product, month))
        match = lookup_expiry('TMF', '202609', data=data)
        match['source']['url'] = 'changed'
        self.assertTrue(lookup_expiry('TMF', '202609', data=data)['source']['url'].startswith('https://'))

    def test_invalid_data_fails_closed(self):
        original = load_expiries()
        mutations = [
            lambda d: d.pop('sources'),
            lambda d: d.pop('data_version'),
            lambda d: d.update(status='unverified'),
            lambda d: d['expiries'][0].update(status='unverified'),
            lambda d: d['sources'][0].update(url='https://taifex.com.tw.evil.test/a'),
            lambda d: d['sources'][0].update(url='http://www.taifex.com.tw/a'),
            lambda d: d['sources'][0].pop('sha256'),
            lambda d: d['sources'][0].pop('retrieval_method'),
            lambda d: d['sources'][0].update(sha256='a' * 63),
            lambda d: d['sources'][0].update(sha256='a' * 65),
            lambda d: d['sources'][0].update(sha256='A' * 64),
            lambda d: d['sources'][0].update(sha256='g' * 64),
            lambda d: d['sources'][0].update(sha256='0' * 63 + '\n'),
            lambda d: d['sources'][0].update(url='https://user@www.taifex.com.tw/a'),
            lambda d: d['sources'][0].update(url='https://www.taifex.com.tw:444/a'),
            lambda d: d['sources'][0].update(retrieval_method=' '),
            lambda d: d.update(verified_date='2026-02-30'),
            lambda d: d.update(products=['TMF']),
            lambda d: d.update(expiries=[]),
            lambda d: d['trading_calendar'].update(status='inferred'),
            lambda d: d['expiries'][0].update(source_index=1),
            lambda d: d['sources'][0].update(retrieval_date='2026-1-18'),
            lambda d: d['expiries'].append(deepcopy(d['expiries'][0])),
            lambda d: d['expiries'][0].update(expiry_date='2026-02-30'),
            lambda d: d['expiries'][0].update(contract_month='202613'),
            lambda d: d['expiries'][0].update(source_index=True),
        ]
        for mutate in mutations:
            data = deepcopy(original)
            mutate(data)
            with self.assertRaises(ValueError):
                validate_data(data)

    def test_raw_html_parser_filters_numeric_product_column(self):
        from tools.update_taifex_expiries import parse_expiries

        html = (ROOT / 'tests/fixtures/taifex_expiries_sample.html').read_text(encoding='utf-8')
        rows = parse_expiries(html)
        self.assertEqual([(r['contract_month'], r['expiry_date']) for r in rows], [('202602', '2026-02-23'), ('202609', '2026-09-16')])
        with self.assertRaises(ValueError):
            parse_expiries('<table><tr><td>2026/10/21</td><td>202610</td><td>100</td></tr></table>')
        with self.assertRaises(ValueError):
            parse_expiries(html.replace('</table>', '<tr><td>2026/09/16</td><td>202609</td><td>1</td></tr></table>', 1))

    def test_loader_rejects_missing_malformed_and_unverified_files(self):
        with self.assertRaises(OSError):
            load_expiries(ROOT / 'tests/fixtures/nonexistent-t9-expiries.json')
        for text in ('{', 'null', '[]', '{}', json.dumps({**load_expiries(), 'status': 'unverified'})):
            with self.subTest(text=text), patch('pathlib.Path.read_text', return_value=text):
                with self.assertRaises(ValueError):
                    load_expiries()

    def test_validated_data_is_detached_and_unknown_product_not_inferred(self):
        data = load_expiries()
        validated = validate_data(data)
        validated['expiries'][0]['expiry_date'] = '2025-10-01'
        self.assertEqual(data['expiries'][0]['expiry_date'], '2025-10-15')
        self.assertIsNone(lookup_expiry('TXF', '202510'))

    def test_packaged_data_and_manifest(self):
        # Reuse the real freezer harness; do not download/build an installer.
        import runpy
        import sys
        import types

        captured = {}
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_data_files = lambda name: []
        hooks.copy_metadata = lambda name: []

        def analysis(*args, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

        with (
            patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks}),
            patch('quantlab.sqlite_runtime.verify'),
            patch('quantlab.sqlite_runtime.verify_binaries'),
        ):
            runpy.run_path(
                str(ROOT / 'packaging/markauto.spec'),
                init_globals={
                    'SPECPATH': str(ROOT / 'packaging'),
                    'Analysis': analysis,
                    'PYZ': lambda *a, **kw: None,
                    'EXE': lambda *a, **kw: None,
                    'COLLECT': lambda *a, **kw: None,
                },
            )
        self.assertIn((str(ROOT / 'quantlab/data_files/taifex_expiries.json'), 'quantlab/data_files'), captured['datas'])
        manifest = runpy.run_path(str(ROOT / 'packaging/build_manifest.py'))
        outputs = {}
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == ROOT / 'dist/validation/sqlite-runtime.json':
                return '{}'
            return read_text(path, *args, **kwargs)

        def write(path, text, *args, **kwargs):
            outputs[path.name] = text
            return len(text)

        with (
            patch.object(Path, 'read_text', autospec=True, side_effect=read),
            patch.object(Path, 'write_text', autospec=True, side_effect=write),
            patch.dict(manifest['main'].__globals__, distributions=lambda: []),
            patch('subprocess.check_output', return_value=GOLDEN['head_archive']),
        ):
            manifest['main']()
        inputs = json.loads(outputs['build-manifest.json'])['inputs_sha256']
        import hashlib

        self.assertEqual(
            inputs['quantlab/data_files/taifex_expiries.json'], hashlib.sha256((ROOT / 'quantlab/data_files/taifex_expiries.json').read_bytes()).hexdigest()
        )


class ExpiryInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def assert_same_request(self, old, new):
        self.assertEqual(old, new)
        self.assertEqual(json.dumps(old, ensure_ascii=False).encode(), json.dumps(new, ensure_ascii=False).encode())
        self.assertEqual(content_hash(old), content_hash(new))

    def assert_golden_request(self, expected, actual):
        self.assert_same_request(expected['payload'], actual)
        self.assertEqual(expected['json_utf8'].encode('utf-8'), json.dumps(actual, ensure_ascii=False).encode('utf-8'))
        self.assertEqual(expected['content_hash'], content_hash(actual))

    def test_manual_payload_bytes_and_hash_match_head_archive(self):
        from desktop_app.features.backtest.forms import BacktestForm
        from PySide6.QtWidgets import QTableWidgetItem

        self.assertEqual(GOLDEN['head_archive'], 'db44477ac24573c752484ed357c11689b29deddf')
        for month, expected in GOLDEN['backtest'].items():
            with self.subTest(month=month):
                form = BacktestForm()
                self.addCleanup(form.close)
                form.expiries.add_row()
                contract = 'TAIFEX:TMF:' + month
                expiry = expected['payload']['config']['instrument_expiries'][contract]
                for column, value in enumerate((contract, expiry)):
                    form.expiries.table.setItem(0, column, QTableWidgetItem(value))
                self.assert_golden_request(expected, form.build_payload())

    def test_run_payload_identical_to_manual_for_every_product_and_boundaries(self):
        from desktop_app.features.backtest.forms import BacktestForm
        from PySide6.QtWidgets import QTableWidgetItem

        for product in ('TX', 'MTX', 'TMF'):
            for month in ('202510', '202602', '202609'):
                with self.subTest(product=product, month=month):
                    manual, selected = BacktestForm(), BacktestForm()
                    self.addCleanup(manual.close)
                    self.addCleanup(selected.close)
                    expiry = lookup_expiry(product, month)['expiry_date']
                    manual.expiries.add_row()
                    for column, value in enumerate(('TAIFEX:{}:{}'.format(product, month), expiry)):
                        manual.expiries.table.setItem(0, column, QTableWidgetItem(value))
                    picker = selected.expiry_picker
                    picker.product.setCurrentText(product)
                    picker.month.setCurrentText(month)
                    if product == 'TMF':
                        self.assert_same_request(manual.build_payload(), selected.build_payload())
                        self.assert_golden_request(GOLDEN['backtest'][month], selected.build_payload())
                    else:
                        # The locked research engine admits TMF only. Selection
                        # must preserve the same rejection for TX/MTX.
                        from quantlab.core import ValidationError

                        with self.assertRaises(ValidationError) as old_error:
                            manual.build_payload()
                        with self.assertRaises(ValidationError) as new_error:
                            selected.build_payload()
                        self.assertEqual(str(old_error.exception), str(new_error.exception))
                        self.assert_same_request(manual.expiries.values(), selected.expiries.values())
                    picker.source_button.click()
                    self.assertFalse(picker.source.isHidden())
                    for text in ('https://www.taifex.com.tw/cht/5/futIndxFSP', '2026-10-18', load_expiries()['data_version']):
                        self.assertIn(text, picker.source.text())
                    selected.expiries.table.item(0, 1).setText('2026-10-20')
                    picker._changed()
                    self.assertEqual(selected.expiries.table.item(0, 1).text(), '2026-10-20')

    def test_uncovered_does_not_fill_or_bypass_missing_expiry_guard(self):
        from desktop_app.features.backtest.forms import BacktestForm
        from quantlab.reporting import synthetic_dataset
        from quantlab.backtest import run_backtest
        from quantlab.__main__ import config_from_json
        from quantlab.strategies import builtin_strategies
        from quantlab.core import ValidationError

        form = BacktestForm()
        self.addCleanup(form.close)
        for month in ('202509', '202610'):
            form.expiry_picker.month.setEditText(month)
            self.assertEqual(form.build_payload()['config']['instrument_expiries'], {})
            self.assertIn('手動提供', form.expiry_picker.summary.text())
            data = synthetic_dataset(160)
            data = replace(
                data, bars=tuple(replace(b, contract_id='TAIFEX:TMF:' + month) for b in data.bars), manifest={**data.manifest, 'source_type': 'proxy'}
            )
            data = replace(data, manifest={**data.manifest, 'data_hash': content_hash(data.bars)})
            with self.assertRaisesRegex(ValidationError, 'explicit instrument expiry required'):
                run_backtest(data, builtin_strategies()[0], config_from_json(form.build_payload()['config']))

    def test_picker_uncovered_selection_preserves_manual_history_and_requires_calendar(self):
        from desktop_app.features.market.history_dialog import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        for month in ('202509', '202610', '202609W2'):
            with self.subTest(month=month):
                dialog = MarketHistoryDialog()
                self.addCleanup(dialog.close)
                fill(dialog, 'TMF')
                before = dialog.session_payload()
                dialog.expiry_picker.month.setEditText(month)
                self.assert_same_request(before, dialog.session_payload())
                self.assertIn('手動提供', dialog.expiry_picker.summary.text())
                self.assertIsNone(lookup_expiry('TMF', month))
                dialog.trade_date.clear()
                dialog.confirm.setChecked(True)
                with self.assertRaisesRegex(ValueError, 'history_session_invalid'):
                    dialog.session_payload()

    def test_picker_selection_invalidates_history_confirmation(self):
        from desktop_app.features.market.history_dialog import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        dialog = MarketHistoryDialog()
        self.addCleanup(dialog.close)
        fill(dialog, 'TMF')
        dialog.expiry_picker.product.setCurrentText('TMF')
        dialog.expiry_picker.month.setCurrentText('202510')
        self.assertFalse(dialog.confirm.isChecked())
        with self.assertRaisesRegex(ValueError, 'history_confirmation_required'):
            dialog.session_payload()

    def test_invalid_provenance_preserves_manual_expiry_payload(self):
        from desktop_app.features.backtest.forms import BacktestForm
        from PySide6.QtWidgets import QTableWidgetItem

        with patch('desktop_app.components.expiry_inputs.load_expiries', side_effect=ValueError('invalid source digest')):
            form = BacktestForm()
        self.addCleanup(form.close)
        self.assertIn('未通過來源驗證', form.expiry_picker.summary.text())
        form.expiries.add_row()
        for column, value in enumerate(('TAIFEX:TMF:202609', '2026-09-16')):
            form.expiries.table.setItem(0, column, QTableWidgetItem(value))
        self.assertEqual(form.build_payload()['config']['instrument_expiries'], {'TAIFEX:TMF:202609': '2026-09-16'})

    def test_import_request_identical_and_calendar_still_explicit(self):
        from desktop_app.features.market.history_dialog import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        for product in ('TX', 'MTX', 'TMF'):
            manual, selected = MarketHistoryDialog(), MarketHistoryDialog()
            self.addCleanup(manual.close)
            self.addCleanup(selected.close)
            for dialog in (manual, selected):
                fill(dialog, product)
                dialog.path.setText('synthetic-fixture.csv')
            manual.month.setText('202609')
            selected.expiry_picker.product.setCurrentText(product)
            selected.expiry_picker.month.setCurrentText('202609')
            for dialog in (manual, selected):
                dialog.confirm.setChecked(True)
                dialog.add_session()
            self.assert_same_request(manual.request_payload(), selected.request_payload())
            selected.trade_date.clear()
            selected.confirm.setChecked(True)
            with self.assertRaises(ValueError):
                selected.session_payload()

    def test_history_manual_and_picker_requests_match_head_bytes_for_day_and_night(self):
        from desktop_app.features.market.history_dialog import MarketHistoryDialog
        from tests.test_market_history_ui import fill

        for key, expected in GOLDEN['history'].items():
            product, month, session = key.split('-')
            for automatic in (False, True):
                with self.subTest(key=key, automatic=automatic):
                    dialog = MarketHistoryDialog()
                    self.addCleanup(dialog.close)
                    fill(dialog, product, night=session == 'night')
                    dialog.path.setText('synthetic-fixture.csv')
                    if automatic:
                        dialog.expiry_picker.product.setCurrentText(product)
                        dialog.expiry_picker.month.setCurrentText(month)
                    else:
                        dialog.month.setText(month)
                    dialog.confirm.setChecked(True)
                    dialog.add_session()
                    self.assert_golden_request(expected, dialog.request_payload())

    def test_market_page_demo_visible_without_calendar_and_clears_for_real_or_missing(self):
        from desktop_app.features.market.market import MarketPage
        from desktop_app.shell.host import PageState
        from quantlab.reporting import synthetic_dataset, save_dataset

        mkdir = os.mkdir

        def inherited(path, mode=0o777, *args, **kwargs):
            return mkdir(path, 0o777 if os.name == 'nt' else mode, *args, **kwargs)

        with patch('os.mkdir', side_effect=inherited), tempfile.TemporaryDirectory(prefix='t9-market-') as folder:
            host = Mock()
            host.state = PageState(root=Path(folder), _market_outcomes={}, _section_toggles={})
            host.latest_market_observations.return_value = ()
            host.dataset_market_series.return_value = ()
            page = MarketPage(host)
            self.addCleanup(page.close)
            page.show()
            page.load_market_cache()
            self.assertTrue(page.research_summary.isHidden())
            quotes = dict(page._quote_series)
            dataset = synthetic_dataset(160)
            save_dataset(dataset, Path(folder) / 'dataset.json')
            page.load_market_cache()
            self.app.processEvents()
            self.assertTrue(page.research_summary.isVisible())
            for text in ('合成示範資料，非真實行情', 'TAIFEX:TMF:202601', '160', '2026-01-05'):
                self.assertIn(text, page.research_summary.text())
            self.assertEqual(page._quote_series, quotes)
            real = replace(dataset, manifest={**dataset.manifest, 'source_type': 'proxy'})
            with patch('desktop_app.features.market.market.load_dataset', return_value=real):
                page.load_market_cache()
            self.assertTrue(page.research_summary.isHidden())
            self.assertEqual(page.research_summary.text(), '')
            with patch('desktop_app.features.market.market.load_dataset', return_value=replace(dataset, bars=())):
                page.load_market_cache()
            self.assertTrue(page.research_summary.isHidden())
            (Path(folder) / 'dataset.json').write_text('{invalid', encoding='utf-8')
            page.load_market_cache()
            self.assertTrue(page.research_summary.isHidden())
            self.assertEqual(page.research_summary.text(), '')
            (Path(folder) / 'dataset.json').unlink()
            page.load_market_cache()
            self.assertTrue(page.research_summary.isHidden())

    def test_widget_inventory_matches_fixture_with_verified_picker_enabled(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QWidget
        from desktop_app.shell.window import MainWindow
        from quantlab.research_core.adapters.workspace_store import AppPaths
        from desktop_app.research_bootstrap import create_job_manager

        mkdir = os.mkdir

        def inherited(path, mode=0o777, *args, **kwargs):
            return mkdir(path, 0o777 if os.name == 'nt' else mode, *args, **kwargs)

        with (
            patch('os.mkdir', side_effect=inherited),
            patch('quantlab.assistant.adapters.chatgpt.vault.DPAPIVault._prepare'),
            tempfile.TemporaryDirectory(prefix='t9-widgets-') as folder,
        ):
            paths = AppPaths(Path(folder) / 'workspace').ensure()
            jobs = create_job_manager(paths)
            window = MainWindow(paths, jobs, services=_c_create_ui_services(_c_create_operation_ports()))
            try:
                for timer in window.findChildren(QTimer):
                    timer.stop()
                actual = sorted({w.objectName() for w in [window, *window.findChildren(QWidget)] if w.objectName()})
                expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
                self.assertEqual(actual, expected)
                for name in ('expiry_product', 'expiry_month', 'expiry_view_source', 'expiry_summary', 'expiry_provenance'):
                    self.assertIn(name, actual)
            finally:
                jobs.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
