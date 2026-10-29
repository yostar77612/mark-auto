"""Cheap synthetic/offscreen U2-C6 evidence; no desktop or broker claims."""

import ast
from decimal import Decimal as D
from pathlib import Path
import random
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QStyleOptionViewItem, QTabWidget, QVBoxLayout, QWidget
from shiboken6 import delete

import desktop_app.components.privacy as privacy
from desktop_app.features.paper.paper import PaperPage
from quantlab.paper_tab_data import account_counts
from desktop_app.features.paper.paper_tabs import BAR_ROLE, build_tabs, existing_journal, refresh_tables
from desktop_app.components.result_widgets import KpiCards, ResultTable, bind_tab_count, shown
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_feedback import stop_presentation

ROOT = Path(__file__).resolve().parents[1]
CID = 'TAIFEX:TMF:202601'


def generated(seed=6, size=34):
    rng = random.Random(seed)
    return {
        'account_id': 'private-account-987654321',
        'cash': '987654321',
        'positions': {CID: 3},
        'orders': {
            str(i): {
                'intent': {'contract_id': CID, 'quantity': rng.randint(1, 3), 'side': 'buy'},
                'status': 'accepted' if i == 0 else 'partial' if i == 1 else 'filled',
            }
            for i in range(size)
        },
        'fills': {'f': {'order_id': '0', 'price': '100', 'multiplier': '10', 'quantity': 3}},
        'lots': [{'entry_fill_id': 'f', 'quantity': 3, 'direction': 1, 'price': '100'}],
        'last_mark_price': '105',
        'verification': 'synthetic_paper_only',
    }


class PaperTabWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.addCleanup(delete, self.owner)
        self.page = SimpleNamespace()
        self.tabs = build_tabs(self.page, QVBoxLayout(self.owner))

    def refresh(self, account):
        account = account or {}
        orders = [{**value.get('intent', {}), **value, 'order_id': key} for key, value in (account.get('orders') or {}).items()]
        fills = list((account.get('fills') or {}).values())
        refresh_tables(self.page, account, orders, fills)

    def test_exact_order_title_and_counts_match_account_tables_kpis_chart(self):
        for seed in range(4):
            account = generated(seed)
            market = SimpleNamespace(chart=SimpleNamespace(trace=None, set_paper_snapshot=Mock()), set_account_tables=Mock(), set_trading_status=Mock())
            kpis = KpiCards(('cash', 'positions', 'orders', 'fills', 'reconciliation_required', 'stop'), self.owner)
            shell = SimpleNamespace(
                **vars(self.page),
                market=market,
                root=Path('__c6_missing__'),
                host=SimpleNamespace(callbacks={}),
                paper_card=SimpleNamespace(label=QLabel(self.owner), set_values=Mock()),
                kpis=kpis,
                _amend_order=Mock(),
            )
            PaperPage._show_account(shell, account, strategy='synthetic')
            self.assertEqual(self.tabs.tabText(1), ui_text('results.orders') + ' [2/34]')
            for index, key in enumerate(('positions', 'orders', 'fills')):
                expected = len(account[key])
                self.assertEqual(self.tabs.widget(index).rowCount(), expected)
                self.assertEqual(kpis.labels[key].text(), shown(expected, key))
                self.assertTrue(self.tabs.tabText(index).endswith('/34]' if key == 'orders' else f'[{expected}]'))
            supplied = market.chart.set_paper_snapshot.call_args.args[0]
            self.assertEqual(len(supplied['orders']), self.page.orders_table.rowCount())
            self.assertIs(market.chart.set_paper_snapshot.call_args.kwargs['request'], shell._amend_order)

    def test_none_missing_and_empty_refreshes(self):
        self.refresh(generated())
        for account in (None, {}, dict(positions=None, orders=None, fills=None)):
            self.refresh(account)
            self.assertTrue(self.tabs.tabText(1).endswith('[0/0]'))
            self.assertEqual(self.page.positions_table.rowCount(), 0)

    def test_show_account_none_safe_and_legacy_presentation_values_preserved(self):
        for account in (generated(), {}, dict(positions=None, orders=None, fills=None), None):
            market = SimpleNamespace(chart=SimpleNamespace(trace=None, set_paper_snapshot=Mock()), set_account_tables=Mock(), set_trading_status=Mock())
            card = SimpleNamespace(label=QLabel(self.owner), set_values=Mock())
            shell = SimpleNamespace(
                **vars(self.page),
                market=market,
                root=Path('__c6_missing__'),
                host=SimpleNamespace(callbacks={}),
                paper_card=card,
                kpis=Mock(),
                _amend_order=Mock(),
            )
            PaperPage._show_account(shell, account, strategy='synthetic')
            normalized = {**(account or {})}
            for key in ('positions', 'orders', 'fills'):
                if key in normalized and normalized[key] is None:
                    normalized[key] = {}
            stop, _ = stop_presentation(normalized, manual_lock_text=ui_text('paper.manual_locked'))
            counts = account_counts(normalized)
            expected = {
                'account_id': normalized.get('account_id'),
                'cash': normalized.get('cash') if normalized.get('account_id') else None,
                'reconciliation_required': normalized.get('reconciliation_required'),
                ui_text('ui.show_account.position_items'): counts['positions'],
                ui_text('ui.show_account.order_count'): counts['orders'],
                ui_text('ui.show_account.fill_count'): counts['fills'],
                ui_text('ui.show_account.position_quantity'): normalized.get('positions', {}),
                ui_text('ui.show_account.stopped'): stop,
            }
            card.set_values.assert_called_once_with(expected)
            self.assertEqual(market.set_trading_status.call_args.kwargs['risk'], stop)
            self.assertEqual(
                market.set_trading_status.call_args.kwargs['paper'],
                ui_text('ui.show_account.id').format(normalized['account_id']) if normalized.get('account_id') else ui_text('ui.show_account.needs_reconcile'),
            )

    def test_large_resets_notify_once_and_allocate_constant_widgets(self):
        table = self.page.orders_table
        table.order_counts = True
        before = len(self.owner.findChildren(QWidget))
        start = time.monotonic()
        for count in (34, 1000, 5000):
            rows = [{'order_id': str(i), 'quantity': i, 'status': 'accepted' if i < 2 else 'filled'} for i in range(count)]
            with patch.object(self.tabs, 'setTabText', wraps=self.tabs.setTabText) as changed:
                table.set_rows(rows, ('order_id', 'contract_id', 'side', 'quantity', 'status'))
            self.assertEqual(changed.call_count, 1)
            self.assertEqual(table.rowCount(), count)
        self.assertLessEqual(len(self.owner.findChildren(QWidget)), before + 2)
        self.assertLess(time.monotonic() - start, 10)

    def test_5000_pnl_cells_allocate_no_row_widgets(self):
        table = self.page.positions_table
        before = len(self.owner.findChildren(QWidget))
        with patch.object(self.tabs, 'setTabText', wraps=self.tabs.setTabText) as changed:
            table.set_rows([{'position': 1, 'pnl': D(i - 2500)} for i in range(5000)], ('contract_id', 'position', 'pnl'))
        self.assertEqual(changed.call_count, 1)
        self.assertEqual(table.rowCount(), 5000)
        self.assertLessEqual(len(self.owner.findChildren(QWidget)), before + 2)
        self.assertEqual(table.item(0, 2).data(BAR_ROLE), D(1))

    def test_existing_export_is_read_only_projected_and_bounded(self):
        self.page.root = ROOT
        journal = [{'operation': 'amend', 'payload': {'secret': 'SECRET-SENTINEL', 'oos': 'OOS-SENTINEL'}}]
        with patch('desktop_app.features.paper.paper_tabs.existing_journal', return_value=journal):
            self.refresh(generated())
        self.assertIn('amend', self.page.events_table.item(0, 1).text())
        self.assertNotIn('SENTINEL', self.page.events_table.copy_text())
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=4 * 1024 * 1024 + 1)), patch.object(Path, 'open') as opened:
            self.assertIsNone(existing_journal(self.page))
            opened.assert_not_called()

    def test_pnl_sort_roles_format_and_missing_quote(self):
        table = self.page.positions_table
        rows = [{'pnl': value} for value in (D(2), D(-4), D(0))]
        table.set_rows(rows, ('contract_id', 'position', 'pnl'))
        table.sortItems(2, Qt.SortOrder.AscendingOrder)
        self.assertEqual([table.item(row, 2).data(Qt.ItemDataRole.UserRole)[1] for row in range(3)], [D(-4), D(0), D(2)])
        self.assertEqual([table.item(row, 2).data(BAR_ROLE) for row in range(3)], [D(1), D(0), D('.5')])
        self.assertTrue(table.item(0, 2).textAlignment() & Qt.AlignmentFlag.AlignRight)
        self.assertTrue(table.item(0, 2).font().fixedPitch())
        account = generated()
        account.pop('last_mark_price')
        self.refresh(account)
        item = table.item(0, 2)
        self.assertEqual(item.text(), shown(None, 'pnl'))
        self.assertIsNone(item.data(BAR_ROLE))

    def test_privacy_masks_positions_pnl_roles_and_paint(self):
        account = generated()
        account['positions'][CID] = 987654321
        account['lots'][0]['quantity'] = 987654321
        self.owner.privacy = SimpleNamespace(enabled=True)
        self.refresh(account)
        table = self.page.positions_table
        for column in (1, 2):
            item = table.item(0, column)
            self.assertEqual(item.text(), privacy.mask_money(''))
            self.assertNotIn('987654321', str([item.toolTip(), item.data(Qt.ItemDataRole.AccessibleTextRole), table.accessibleName()]))
        self.assertNotIn('987654321', ''.join(self.tabs.tabText(i) for i in range(4)))
        image = QImage(180, 30, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        option = QStyleOptionViewItem()
        option.rect = image.rect()
        table.itemDelegateForColumn(2).paint(painter, option, table.model().index(0, 2))
        painter.end()

    def test_events_plain_text_read_only_and_new_elements_have_no_actions(self):
        self.refresh(generated())
        table = self.page.events_table
        table.set_rows([{'operation': '<b>x</b>'}], ('operation',))
        self.assertEqual(table.item(0, 0).text(), '<b>x</b>')
        self.assertEqual(table.editTriggers(), table.EditTrigger.NoEditTriggers)
        job = Mock()
        self.page.paper_job = job
        for index in range(4):
            self.tabs.setCurrentIndex(index)
            target = self.tabs.widget(index)
            QTest.keyClick(target, Qt.Key.Key_Return)
            QTest.keyClick(target, Qt.Key.Key_Delete)
            QTest.mouseDClick(target.viewport(), Qt.MouseButton.LeftButton)
            self.assertTrue(all(action.text() == ui_text('results.copy') for action in target.actions()))
        job.assert_not_called()

    def test_keyboard_names_elision_and_minimum_width(self):
        self.refresh(generated())
        self.assertEqual(self.tabs.tabBar().elideMode(), Qt.TextElideMode.ElideNone)
        self.assertTrue(self.tabs.accessibleName())
        self.assertTrue(self.tabs.tabBar().accessibleName())
        QTest.keyClick(self.tabs, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.tabs.currentIndex(), 1)
        QTest.keyClick(self.tabs.tabBar(), Qt.Key.Key_Right)
        self.assertEqual(self.tabs.currentIndex(), 2)
        QTest.keyClick(self.tabs, Qt.Key.Key_Tab)
        for index in range(4):
            table = self.tabs.widget(index)
            self.assertTrue(table.accessibleName())
            self.assertEqual(table.focusPolicy(), Qt.FocusPolicy.StrongFocus)
            QTest.keyClick(table, Qt.Key.Key_Down)
        legacy = QTabWidget(self.owner)
        for key in ('results.positions', 'results.orders', 'results.fills'):
            table = ResultTable()
            legacy.addTab(table, ui_text(key))
            bind_tab_count(legacy, table)
        self.assertLessEqual(self.tabs.minimumSizeHint().width(), legacy.minimumSizeHint().width())
        table = self.page.orders_table
        table.setCurrentCell(0, 0)
        QTest.keyClick(table, Qt.Key.Key_Down)
        self.assertEqual(table.currentRow(), 1)

    def test_no_timers_filters_row_widgets_or_mutation_entrypoints(self):
        sources = [path.read_text(encoding='utf-8') for path in (ROOT / 'desktop_app/features/paper/paper_tabs.py', ROOT / 'quantlab/paper_tab_data.py')]
        for source in sources:
            tree = ast.parse(source)
            calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
            self.assertFalse(
                calls & {'setCellWidget', 'setIndexWidget', 'deleteLater', 'installEventFilter', 'findChildren', 'paper_job', 'submit', 'cancel', 'amend'}
            )
            self.assertNotIn('QTimer', source)
            for forbidden in ('shioaji', 'LiveBroker', 'place_order', 'apiPost', 'sendOrder'):
                self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
