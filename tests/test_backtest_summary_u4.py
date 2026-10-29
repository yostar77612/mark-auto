"""Cheap unshown-widget evidence: the report summary is not broken."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from desktop_app.components.forms import BacktestSummaryCard, RESULT_LABELS
from desktop_app.features.backtest.backtest import BacktestPage
from desktop_app.features.backtest.backtest_summary_card import ReportSummaryCard
from desktop_app.strings.catalog import ZH_TW, ui_text
import desktop_app.components.privacy as privacy


ROOT = Path(__file__).resolve().parents[1]


class BacktestSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        def advanced(layout, *args):
            box = QGroupBox()
            layout.addWidget(box)
            box.hide()
            return QVBoxLayout(box)

        def text(layout, *args):
            editor = QPlainTextEdit()
            layout.addWidget(editor)
            return editor

        def button(layout, *args, **kwargs):
            widget = QPushButton()
            layout.addWidget(widget)
            return widget

        self.state = SimpleNamespace(
            market=SimpleNamespace(chart=SimpleNamespace(set_reference_lines=Mock())),
            select_button=QPushButton(),
            jobs=SimpleNamespace(active=False),
            status=QLabel(),
        )
        self.host = SimpleNamespace(
            state=self.state,
            mount_page=lambda page, title: QVBoxLayout(page),
            advanced=advanced,
            text=text,
            remember=Mock(),
            button=button,
            bind_result_layers=Mock(),
        )
        self.page = BacktestPage(self.host)
        self.addCleanup(self.page.close)

    def load(self, *, bars=30, trades=5):
        result = SimpleNamespace(
            metrics={'net_pnl': '1234.56', 'max_drawdown': '100.25', 'closed_lots': trades, 'trade_count': trades},
            equity=[{'equity': '10000'}] * bars,
            fills=(),
            manifest={},
            warnings=(),
            rejects=(),
        )
        self.page.result_choice.blockSignals(True)
        self.page.result_choice.clear()
        self.page.result_choice.addItem('fixture', 'result.json')
        self.page.result_choice.blockSignals(False)
        with patch('desktop_app.features.backtest.backtest.load_result', return_value=result):
            self.page.show_result()
        return result

    def test_topmost_single_card_outside_collapsed_sections(self):
        page = self.page
        card = page.summary_card
        self.assertIs(card.parentWidget(), page)
        self.assertTrue(card.isHidden())
        self.load()
        self.assertFalse(card.isHidden())
        self.assertTrue(page._setup_panel.isHidden())
        self.assertFalse(page.setup_toggle.isHidden())
        page.setup_toggle.setChecked(True)
        self.assertFalse(page._setup_panel.isHidden())
        page.setup_toggle.setChecked(False)
        layout = page.layout()
        for widget in (page.result_choice, page.plot):
            self.assertLess(layout.indexOf(card), layout.indexOf(widget))
        # Secondary statistics and fills remain mounted inside named disclosures.
        # The summary itself stays outside every collapsed section.
        for widget in (page.kpis, page.fills_table):
            self.assertTrue(page.isAncestorOf(widget))
            self.assertFalse(card.isAncestorOf(widget))
            self.assertFalse(widget.isVisibleTo(page))
        self.assertEqual(page.findChildren(ReportSummaryCard), [card])
        self.assertEqual(page.findChildren(BacktestSummaryCard), [page.result_card])
        for widget in (card, card.label, card.hint, card.warning):
            self.assertTrue(widget.accessibleName())
        self.assertEqual(card.hint.text(), ui_text('backtest.summary.hint'))
        self.assertTrue(card.hint.wordWrap())
        self.assertNotIn('\n', card.hint.text())

    def test_exact_three_metrics_match_existing_kpis_and_privacy_toggle(self):
        result = self.load()
        page = self.page
        for enabled in (False, True, False):
            page.privacy = SimpleNamespace(enabled=enabled)
            page.summary_card.label._privacy_render()
            for label in page.kpis.labels.values():
                label._privacy_render()
            self.assertEqual(
                page.summary_card.label.text().splitlines(),
                [
                    ui_text('forms.set_values.named_value').format(RESULT_LABELS[key], page.kpis.labels[key].text())
                    for key in ('net_pnl', 'max_drawdown', 'closed_lots')
                ],
            )
            if enabled:
                self.assertNotIn('1,234.56', page.summary_card.label.text())
                self.assertIn(privacy.mask_money(None), page.summary_card.label.text())
        self.assertEqual(result.metrics['net_pnl'], '1234.56')

    def test_short_zero_closed_and_long_fixture_warnings(self):
        self.load(bars=1, trades=0)
        self.assertEqual(
            self.page.summary_card.warning.text().splitlines(), [ui_text('backtest.summary.sample_short'), ui_text('backtest.summary.no_closed_trades')]
        )
        self.assertFalse(self.page.summary_card.warning.isHidden())
        self.load()
        self.assertEqual(self.page.summary_card.warning.text(), '')
        self.assertTrue(self.page.summary_card.warning.isHidden())

    def test_placeholder_then_empty_and_failed_load_clear_stale_values(self):
        card = self.page.summary_card
        self.assertTrue(card.isHidden())
        self.assertEqual(card.label.text(), ui_text('backtest.summary.empty'))
        self.load()
        with patch('desktop_app.features.backtest.backtest.load_result', side_effect=ValueError('untrusted failure')):
            self.page.show_result()
        self.assertTrue(card.isHidden())
        self.assertEqual(card.label.text(), ui_text('backtest.summary.empty'))
        self.assertEqual(card.warning.text(), '')
        self.assertNotIn('untrusted failure', self.state.status.text())
        self.assertFalse(self.state._selection_allowed)
        self.load()
        self.page.result_choice.clear()
        self.assertTrue(card.isHidden())
        self.assertEqual(card.label.text(), ui_text('backtest.summary.empty'))

    def test_failed_run_clears_summary_without_launching_job(self):
        self.load()
        with patch.object(self.page.backtest_form, 'build_payload', side_effect=ValueError):
            with self.assertRaises(ValueError):
                self.page.run_backtest()
        self.assertTrue(self.page.summary_card.isHidden())
        self.assertEqual(self.page.summary_card.label.text(), ui_text('backtest.summary.empty'))

    def test_late_render_failure_also_clears_summary(self):
        self.host.bind_result_layers.side_effect = ValueError('untrusted detail')
        self.load()
        self.assertTrue(self.page.summary_card.isHidden())
        self.assertEqual(self.page.summary_card.label.text(), ui_text('backtest.summary.empty'))
        self.assertEqual(self.page.summary_card.warning.text(), '')
        self.assertEqual(self.page.plot.values, [])
        self.assertEqual(self.page.fills_table.rowCount(), 0)
        self.assertFalse(self.state._selection_allowed)
        self.assertNotIn('untrusted detail', self.state.status.text())

    def test_card_reads_only_reported_summary_fields(self):
        allowed = {'net_pnl', 'max_drawdown', 'closed_lots', 'trade_count'}

        class ReportFields(dict):
            def get(self, key, default=None):
                if key not in allowed:
                    raise AssertionError(key)
                return super().get(key, default)

            def __getitem__(self, key):
                if key not in allowed:
                    raise AssertionError(key)
                return super().__getitem__(key)

        values = ReportFields(net_pnl='7', max_drawdown='2', closed_lots=5, trade_count=5, unrelated=object())
        self.page.summary_card.set_values(values, bar_count=30)
        self.assertEqual(len(self.page.summary_card.label.text().splitlines()), 3)
        self.assertEqual(self.page.summary_card.warning.text(), '')

    def test_catalog_is_neutral_and_widget_names_are_registered(self):
        forbidden = (
            'profitable',
            'good',
            'bad',
            'recommended',
            'guaranteed',
            'best',
            '\u7372\u5229',
            '\u826f\u597d',
            '\u597d',
            '\u58de',
            '\u63a8\u85a6',
            '\u4fdd\u8b49',
            '\u6700\u4f73',
            'oos',
            'holdout',
            '\u003f\u003f\u003f',
        )
        for key, value in ZH_TW.items():
            if key.startswith('backtest.summary.'):
                self.assertFalse(any(word in value.lower() for word in forbidden), key)
        names = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertEqual(names, sorted(set(names)))
        for widget in (self.page.summary_card, self.page.summary_card.hint, self.page.summary_card.warning):
            self.assertIn(widget.objectName(), names)
