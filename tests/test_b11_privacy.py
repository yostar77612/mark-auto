"""Cheap offscreen display-only privacy contracts; no jobs, paints or network."""

import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QTableWidget, QWidget
import desktop_privacy as privacy
from desktop_accessibility import INTERACTIVE, semantic_name, visual_focus_order
from desktop_forms import ResultTable as LegacyTable
from desktop_forms import backtest_summary_text
from desktop_pages.result_widgets import ResultTable, TaipeiFillsTable
from desktop_strings import ui_text
from desktop_ui import MainWindow
from quantlab.backtest import run_backtest
from quantlab.core import content_hash
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
from quantlab.reporting import demo_config, export_report, synthetic_dataset, write_json
from quantlab.strategies import builtin_strategies
from tests.test_t9_onboarding import sandbox_ui

ROOT = Path(__file__).resolve().parents[1]


def cells(table):
    return [table.item(r, c) for r in range(table.rowCount()) for c in range(table.columnCount()) if table.item(r, c) is not None]


def capture(tables):
    return [[(item.text(), item.toolTip(), item.data(Qt.ItemDataRole.UserRole)) for item in cells(table)] for table in tables]


class MaskTests(unittest.TestCase):
    def test_money_constant_for_all_inputs_and_account_suffix_bound(self):
        for value in (None, '', 0, -1, Decimal('-123.45'), Decimal('NaN'), float('nan'), float('inf'), 10**500, '1234567890'):
            with self.subTest(value=str(value)[:30]):
                self.assertEqual(privacy.mask_money(value), '••••')
                self.assertFalse(any(ch.isdigit() for ch in privacy.mask_money(value)))
        for length in range(40):
            for prefix in ('1234567890', 'account-', '１２３４５６７８９０'):
                value = (prefix * 40)[:length]
                masked = privacy.mask_account_id(value)
                self.assertEqual(masked, '••••' + (value[-4:] if len(value) > 4 else ''))
                self.assertFalse(any(ch.isdigit() for ch in masked[:-4]))
        self.assertEqual(privacy.mask_account_id(None), '••••')

    def test_preview_redacts_nested_values_without_mutating_input(self):
        fixture = {'account_id': 'ACCOUNT-987654321', 'cash': '-98765.43', 'fills': [{'price': '12345.67', 'symbol': 'TMF'}]}
        raw = json.dumps(fixture)
        masked = privacy.preview_text(raw, True)
        for value in ('ACCOUNT-987654321', '-98765.43', '12345.67'):
            self.assertNotIn(value, masked)
        self.assertIn('TMF', masked)
        self.assertEqual(privacy.preview_text(raw, False), raw)
        self.assertEqual(fixture['cash'], '-98765.43')
        self.assertEqual(privacy.preview_text('unknown raw 12345', True), '••••')

    def test_summary_money_builder_preserves_other_metrics(self):
        fixture = {'net_pnl': '12345.67', 'return': '0.25', 'initial_cash': '987654.32'}
        raw = backtest_summary_text(fixture)
        masked = backtest_summary_text(fixture, private=True)
        self.assertIn('12,345.67', raw)
        self.assertNotIn('12,345.67', masked)
        self.assertNotIn('987,654.32', masked)
        self.assertIn('25.00%', masked)


class PrivacyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.temp = tempfile.TemporaryDirectory(prefix='b11-privacy-')
        cls.paths = AppPaths(Path(cls.temp.name) / 'workspace').ensure()
        cls.jobs = JobManager(cls.paths)
        cls.store = SettingsStore(cls.paths.state / 'settings.json')
        cls.window = MainWindow(cls.paths, cls.jobs, cls.store)
        for timer in cls.window.findChildren(QTimer):
            timer.stop()

    @classmethod
    def tearDownClass(cls):
        cls.jobs.close()
        cls.window.close()
        cls.window.deleteLater()
        cls.temp.cleanup()
        cls.context.__exit__(None, None, None)

    def setUp(self):
        self.window.privacy.toggle.setChecked(False)

    def tearDown(self):
        self.window.privacy.toggle.setChecked(False)

    def test_all_page_tables_immediate_roundtrip_roles_and_storage(self):
        w = self.window
        pages = [w.market_page, w.data_page, w.strategy_page, w.backtest_page, w.compare_page, w.paper_page, w.settings_page]
        row = {
            'account_id': 'ACCOUNT-987654321',
            'cash': '-98765.43',
            'net_pnl': '54321.76',
            'price': '12345.67',
            'contract_id': 'TAIFEX:TMF:202601',
            'timestamp': '2026-01-05T01:00:00Z',
            'status': 'filled',
        }
        tables = []
        for page in pages:
            for table in page.findChildren(QTableWidget):
                if type(table) in (ResultTable, LegacyTable):
                    table.set_rows([dict(row)], list(row))
                    tables.append(table)
                elif isinstance(table, TaipeiFillsTable):
                    table.set_rows([row])
                    tables.append(table)
        self.assertGreater(len(tables), 5)
        w.market.set_account_tables(
            positions=[{'contract_id': 'TAIFEX:TMF:202601', 'quantity': 1, 'average_price': '12345.67'}],
            orders=[{'order_id': 'order-1', 'contract_id': 'TAIFEX:TMF:202601', 'side': 'buy', 'quantity': 1, 'status': 'filled'}],
            fills=[{'fill_id': 'fill-1', 'contract_id': 'TAIFEX:TMF:202601', 'side': 'buy', 'quantity': 1, 'price': '12345.67'}],
        )
        tables.extend([w.market.positions_table, w.market.orders_table, w.market.fills_table])
        before = capture(tables)
        write_json(self.paths.state / 'b11-source.json', row)
        source = self.paths.state / 'b11-source.json'
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        model_hash = content_hash(row)
        with (
            patch.object(w, 'refresh_views', side_effect=AssertionError('toggle must not query')),
            patch.object(w.jobs, 'start', side_effect=AssertionError('no jobs')),
        ):
            w.privacy.toggle.click()
            self.assertTrue(w.privacy.enabled)
            for table, old_cells in zip(tables, before):
                for item, (old_text, old_tip, old_role) in zip(cells(table), old_cells):
                    key = item._privacy_key
                    self.assertEqual(item.data(Qt.ItemDataRole.UserRole), old_role)
                    if key in privacy.MONEY_FIELDS | privacy.ACCOUNT_FIELDS:
                        expected = privacy.mask_account_id(old_text) if key in privacy.ACCOUNT_FIELDS else privacy.mask_money(old_text)
                        self.assertEqual(item.text(), expected)
                        for role in privacy.ACCESS_ROLES:
                            self.assertEqual(item.data(role), expected)
                    else:
                        self.assertEqual((item.text(), item.toolTip()), (old_text, old_tip))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)
            self.assertEqual(content_hash(row), model_hash)
            # Re-population while already private must use the same state immediately.
            tables[0].set_rows([row], list(row))
            self.assertEqual(tables[0].item(0, 1).text(), '••••')
            w.privacy.toggle.click()
        self.assertEqual(capture(tables), before)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)

    def test_previews_charts_cards_and_exports(self):
        w = self.window
        fixture = {'account_id': 'ACCOUNT-987654321', 'cash': '-98765.43', 'fills': [{'price': '12345.67'}]}
        raw = json.dumps(fixture)
        w.paper_detail.setPlainText(raw)
        w.paper_card.set_values(fixture)
        w.paper_page.kpis.set_values({'cash': '-98765.43'})
        w.backtest_page.plot.set_values([{'equity': '98765.43', 'timestamp': '2026-01-05T01:00:00Z'}])
        axis_before = w.backtest_page.plot.axis_labels()
        card_before = w.paper_card.label.text()
        result = run_backtest(synthetic_dataset(30), builtin_strategies()[0], demo_config())
        exports = Path(self.temp.name) / 'exports'
        export_report(result, exports)
        before = {path.relative_to(exports).as_posix(): path.read_bytes() for path in exports.rglob('*') if path.is_file()}
        self.assertTrue(before)
        w.privacy.toggle.click()
        self.assertEqual(w.privacy.notice.text(), ui_text('privacy.exports_raw'))
        self.assertEqual(w.privacy.toggle.accessibleName(), ui_text('privacy.toggle'))
        for widget_text in (w.paper_detail.toPlainText(), w.paper_card.label.text(), w.paper_page.kpis.labels['cash'].text()):
            for value in ('ACCOUNT-987654321', '-98765.43', '12345.67'):
                self.assertNotIn(value, widget_text)
        self.assertEqual(w.backtest_page.plot.axis_labels()['value'], ['••••'] * 3)
        self.assertEqual(w.market.chart.price_text('12345.67'), '••••')
        export_report(result, exports)
        self.assertEqual({path.relative_to(exports).as_posix(): path.read_bytes() for path in exports.rglob('*') if path.is_file()}, before)
        w.privacy.toggle.click()
        self.assertEqual(w.paper_detail.toPlainText(), raw)
        self.assertEqual(w.paper_card.label.text(), card_before)
        self.assertEqual(w.backtest_page.plot.axis_labels(), axis_before)
        self.assertEqual(w.market.chart.price_text('12345.67'), '12345.67')

    def test_persistence_corrupt_value_and_accessibility_all_pages(self):
        w = self.window
        w.privacy.toggle.click()
        self.assertIs(self.store.load()['privacy_mode'], True)
        for index in range(w.stack.count()):
            page = w.stack.widget(index)
            for control in page.findChildren(QWidget):
                if isinstance(control, INTERACTIVE):
                    self.assertTrue(control.accessibleName() or semantic_name(control))
            visual_focus_order(page)
        self.assertEqual(w.stack.count(), 7)
        for corrupt in (None, 'true', '1', 1, [], {}):
            w.privacy.restore({'privacy_mode': corrupt})
            self.assertFalse(w.privacy.enabled)
        w.privacy.restore({'privacy_mode': True})
        self.assertTrue(w.privacy.enabled)
        w.privacy.toggle.click()
        self.assertIs(self.store.load()['privacy_mode'], False)

    def test_saved_and_transposed_comparison_roundtrip(self):
        w = self.window
        saved = w.comparison_list.table
        row = {'name': 'fixture', 'net_pnl': '12345.67', 'max_drawdown': '98765.43', 'trade_count': 4}
        saved.set_saved([('fixture-path', row)])
        w.comparison_table.set_rows([row])
        tables = [saved, w.comparison_table]
        before = capture(tables)
        w.privacy.toggle.click()
        for table in tables:
            for item in cells(table):
                if item._privacy_key in privacy.MONEY_FIELDS:
                    self.assertEqual(item.text(), '••••')
                    self.assertEqual(item.toolTip(), '••••')
        # Both special adapters must also work when populated after the toggle.
        saved.set_saved([('fixture-path', row)])
        w.comparison_table.set_rows([row])
        for table in tables:
            for item in cells(table):
                if item._privacy_key in privacy.MONEY_FIELDS:
                    self.assertEqual(item.text(), '••••')
        w.privacy.toggle.click()
        self.assertEqual(capture(tables), before)

    def test_public_oracle_and_class_limits(self):
        from tests.test_ui_operations_registry import RegistryTests
        from tests.test_no_inline_stylesheet import NoInlineStylesheetTests

        RegistryTests().test_public_names_unchanged()
        NoInlineStylesheetTests().test_desktop_and_tools_have_no_inline_stylesheet()
        tree = ast.parse((ROOT / 'desktop_ui.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
        self.assertLessEqual(node.end_lineno - node.lineno + 1, 400)
        expected = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted({v.objectName() for v in self.window.findChildren(QWidget) if v.objectName()}), expected)
