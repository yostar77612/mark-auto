"""Base literals for ordering, late dispatch, rendering and refresh behavior."""

import json
from collections import Counter
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
import shiboken6

import desktop_app.components.charts as charts
from desktop_app.components.chart_annotations import ReferenceLine as _c_charts_ReferenceLine
from desktop_app.components.chart_paint import _paint_chart_references as _c_charts__paint_chart_references
import desktop_app.features.market.dashboard as market
from desktop_app.shell import mount
from desktop_app.components import result_layers
from desktop_app.shell.host import PageHost
from desktop_app.shell.bindings import SharedStateBindings
from desktop_app.shell.views import ViewCoordinator
from tests.r7_characterization import ROOT, capture, mount_capture, snapshot_cases, public_names

BASE = json.loads((ROOT / 'tests/fixtures/r7_base.json').read_text(encoding='utf-8'))
REDESIGN = json.loads((ROOT / 'tests/fixtures/ui_redesign_characterization_delta.json').read_text(encoding='utf-8'))
AUTO_IMPORT = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))


def semantic_rows(rows):
    """Retain exact row values and multiplicity independent of layout order."""
    return Counter(json.dumps(row, ensure_ascii=False) for row in rows)


def reviewed_ui_rows(rows, *deltas):
    expected = semantic_rows(rows)
    for changes in deltas:
        for change in changes['removed']:
            key = json.dumps(change['row'], ensure_ascii=False)
            if expected[key] < change['count']:
                raise AssertionError('Reviewed UI delta removes a row absent from the historical fixture')
            expected[key] -= change['count']
            if not expected[key]:
                del expected[key]
        for change in changes['added']:
            expected[json.dumps(change['row'], ensure_ascii=False)] += change['count']
    return expected


class CharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.actual = capture()

    def test_mount_effect_order_and_values(self):
        self.assertEqual(self.actual['mount'], MOUNT_EVENTS)
        self.assertEqual(self.actual['stub_callbacks'], STUB_CALLBACKS)

    def test_main_window_attribute_and_callback_sets(self):
        self.assertEqual(self.actual['window']['attributes'], sorted(WINDOW_ATTRIBUTES + REDESIGN['added_window_attributes']))
        self.assertEqual(self.actual['window']['callbacks'], WINDOW_CALLBACKS)

    def test_mount_callbacks_dispatch_to_patched_shell(self):
        _, _, shell = mount_capture()
        for name in ('_busy', '_safe'):
            patched = Mock(return_value='patched')
            setattr(shell, name, patched)
            self.assertEqual(shell.page_host.callbacks[name](), 'patched')
            patched.assert_called_once_with()

    def test_public_names_are_identical(self):
        expected = json.loads(json.dumps(BASE['public']))
        chart = expected['desktop_app/components/charts.py']
        moved_imports = {'ChartMarker', 'ChartTrace', 'ReferenceLine', 'Decimal', 'QPolygonF', 'ZoneInfo', 'dataclass', 'datetime', 're', 'timedelta'}
        chart[0] = sorted((set(chart[0]) - moved_imports) | {'ChartInteraction'})
        annotation_classes = {name: value for name, value in chart[1].items() if name != 'CandlestickChart'}
        chart[1] = {'CandlestickChart': chart[1]['CandlestickChart']}
        self.assertEqual(self.actual['public'], expected)
        annotations = public_names((ROOT / 'desktop_app/components/chart_annotations.py').read_text(encoding='utf-8'))
        self.assertEqual(annotations[1], annotation_classes)

    def test_three_chart_pixels_and_painter_stack_counts(self):
        self.assertEqual([x[1] for x in self.actual['charts']], [x[1] for x in BASE['charts']])
        # Native glyph rasterization is platform-specific; Linux still checks
        # paint ordering, state and stack counts with the same synthetic cases.
        if sys.platform == 'win32':
            self.assertEqual(self.actual['charts'], BASE['charts'])

    def test_eight_result_snapshots_equal_base_literals(self):
        self.assertEqual(len(self.actual['snapshots']), 8)
        self.assertEqual(self.actual['snapshots'], BASE['snapshots'])
        self.assertTrue(self.actual['snapshots'][2])

    def test_refresh_four_states_call_order_and_error_boundaries(self):
        # The coordinator's execution order and propagated errors remain exact.
        for name in ('calls', 'errors'):
            self.assertEqual(self.actual['window'][name], BASE['window'][name], name)
        self.assertEqual(len(self.actual['window']['states']), len(BASE['window']['states']))
        for index, (actual, historical) in enumerate(zip(self.actual['window']['states'], BASE['window']['states'])):
            self.assertEqual(semantic_rows(actual), reviewed_ui_rows(historical, REDESIGN['refresh_states'], AUTO_IMPORT['refresh_states']), index)

    def test_accessible_names_descriptions_and_focus_chain(self):
        # Controls moved across task panels and into a guide dialog. Preserve
        # every historical semantic row except the explicit UI-only delta;
        # test_accessibility_walk checks the new real keyboard traversal order.
        self.assertEqual(semantic_rows(self.actual['window']['focus']), reviewed_ui_rows(BASE['window']['focus'], REDESIGN['focus'], AUTO_IMPORT['focus']))

    def test_reviewed_refresh_delta_changes_only_layout_controls_and_captions(self):
        changes = REDESIGN['refresh_states']
        captions = {'idea_research_entry', 'use_candidate', 'strategy_page_hint'}
        legacy_sections = {'advanced_1', 'advanced_7', 'advanced_8', 'advanced_9', 'advanced_10', 'advanced_11', 'advanced_12', 'advanced_13'}
        self.assertEqual({change['row'][0] for change in changes['removed']}, captions | legacy_sections)
        for change in changes['removed']:
            if change['row'][0] not in captions:
                continue
            replacements = [item for item in changes['added'] if item['row'][0] == change['row'][0]]
            self.assertEqual(len(replacements), 1)
            self.assertEqual(replacements[0]['row'][2:], change['row'][2:])
            self.assertEqual(replacements[0]['count'], change['count'])

    def test_mount_widget_tools_stage_in_isolation(self):
        events, _, shell = mount_capture(mount._mount_widget_tools)
        self.assertEqual(events, MOUNT_EVENTS[MOUNT_EVENTS.index(['construct', 'WidgetTools']) : MOUNT_EVENTS.index(['construct', 'MarketPage'])])
        self.assertEqual(shell._button.name, 'WidgetTools._button')

    def test_market_header_stage_in_isolation(self):
        parent = QWidget()
        shell = SimpleNamespace(refresh_requested=SimpleNamespace(emit=Mock()))
        try:
            root = QVBoxLayout(parent)
            header = market._build_market_header(shell, root)
            self.assertEqual(header.count(), 4)
            self.assertEqual(shell.refresh_button.objectName(), 'market_refresh')
            shell.refresh_button.click()
            shell.refresh_requested.emit.assert_called_once_with()
        finally:
            shiboken6.delete(parent)

    def test_chart_reference_stage_on_image_painter(self):
        chart = charts.CandlestickChart()
        image = QImage(800, 480, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            text = lambda x, y, value: painter.drawText(QPointF(x, y), str(value))
            result = _c_charts__paint_chart_references(
                chart, painter, painter.fontMetrics(), text, (), chart.price_rect, lambda i: i, lambda price: float(price), 1
            )
            self.assertEqual(result, ([], []))
        finally:
            painter.end()
            shiboken6.delete(chart)

    def test_snapshot_line_stage_in_isolation(self):
        result, bars, _ = snapshot_cases()[2]
        actual = result_layers._build_snapshot_lines(result, [20000], [20000], [1], 1, 1, len(bars) - 1, bars[-1].end, _c_charts_ReferenceLine)
        self.assertEqual([line.price for line in actual], [20000, 20000, 19700, 20500])

    def test_refresh_restore_stage_in_isolation(self):
        fake = SimpleNamespace(
            root=Path('/nonexistent-r7-synthetic'),
            active_candidate=None,
            _refresh_recovery_controls=Mock(),
            state=SimpleNamespace(onboarding=SimpleNamespace(refresh=Mock())),
        )
        ViewCoordinator._restore_active_candidate(fake)
        fake._refresh_recovery_controls.assert_called_once_with(force=True)
        fake.state.onboarding.refresh.assert_called_once_with()

    def test_snapshot_aliases_remain_patchable(self):
        self.assertIn('result_snapshot_lines', PageHost.__annotations__)
        binding = SharedStateBindings()
        binding.page_state = SimpleNamespace(_result_snapshot_lines=result_layers.result_snapshot_lines)
        with patch('desktop_app.components.result_layers.result_snapshot_lines', return_value=('module',)) as patched:
            self.assertEqual(result_layers.result_snapshot_lines(None, (), None), ('module',))
            patched.assert_called_once()
        with patch.object(binding, '_result_snapshot_lines', return_value=('binding',)):
            self.assertEqual(binding._result_snapshot_lines(None, (), None), ('binding',))


MOUNT_EVENTS = [
    ['callbacks', '_advanced'],
    ['callbacks', '_analysis_event'],
    ['callbacks', '_analysis_request'],
    ['callbacks', '_analysis_saved_changed'],
    ['callbacks', '_analysis_section'],
    ['callbacks', '_browse'],
    ['callbacks', '_busy'],
    ['callbacks', '_button'],
    ['callbacks', '_chatgpt_cancel'],
    ['callbacks', '_chatgpt_dispatch'],
    ['callbacks', '_chatgpt_event'],
    ['callbacks', '_chatgpt_open_browser'],
    ['callbacks', '_chatgpt_quiesce'],
    ['callbacks', '_compare_page'],
    ['callbacks', '_confirm_button'],
    ['callbacks', '_current_plan_binding'],
    ['callbacks', '_invalidate_analysis_preview'],
    ['callbacks', '_mount_market'],
    ['callbacks', '_mount_page'],
    ['callbacks', '_navigate_selected_page'],
    ['callbacks', '_notification_link'],
    ['callbacks', '_page'],
    ['callbacks', '_paper_page'],
    ['callbacks', '_payload'],
    ['callbacks', '_plan_usage_request'],
    ['callbacks', '_quiesce_and_recover'],
    ['callbacks', '_record_connection_error'],
    ['callbacks', '_recovery_display_fingerprint'],
    ['callbacks', '_refresh_analysis_saved'],
    ['callbacks', '_refresh_recovery_controls'],
    ['callbacks', '_remember'],
    ['callbacks', '_remember_stop'],
    ['callbacks', '_safe'],
    ['callbacks', '_save_section_preferences'],
    ['callbacks', '_selected_recovery_launch'],
    ['callbacks', '_settings_page'],
    ['callbacks', '_show_account'],
    ['callbacks', '_text'],
    ['callbacks', 'auto_restore_chatgpt'],
    ['callbacks', 'backup'],
    ['callbacks', 'cancel_job'],
    ['callbacks', 'closeEvent'],
    ['callbacks', 'configure_workspace'],
    ['callbacks', 'demo_paper_policy'],
    ['callbacks', 'form_feedback'],
    ['callbacks', 'freeze_paper'],
    ['callbacks', 'inspect_plan_usage'],
    ['callbacks', 'kill_paper'],
    ['callbacks', 'load_form_file'],
    ['callbacks', 'load_settings'],
    ['callbacks', 'notify_local'],
    ['callbacks', 'open_releases'],
    ['callbacks', 'paper_job'],
    ['callbacks', 'pick_analysis_original'],
    ['callbacks', 'poll_jobs'],
    ['callbacks', 'preview_analysis'],
    ['callbacks', 'read_analysis'],
    ['callbacks', 'read_logs'],
    ['callbacks', 'reconcile_saved_analysis'],
    ['callbacks', 'record_event'],
    ['callbacks', 'refresh_views'],
    ['callbacks', 'run_analysis'],
    ['callbacks', 'save_settings'],
    ['callbacks', 'select_strategy'],
    ['callbacks', 'show_chatgpt_sign_in'],
    ['callbacks', 'start_job'],
    ['callbacks', 'update'],
    ['callbacks', 'service'],
    ['construct', 'WidgetTools'],
    ['shell', 'widgets_page', 'WidgetTools'],
    ['shell', '_button', 'WidgetTools._button'],
    ['shell', '_confirm_button', 'WidgetTools._confirm_button'],
    ['shell', '_text', 'WidgetTools._text'],
    ['shell', '_advanced', 'WidgetTools._advanced'],
    ['shell', '_save_section_preferences', 'WidgetTools._save_section_preferences'],
    ['shell', '_payload', 'WidgetTools._payload'],
    ['shell', '_remember', 'WidgetTools._remember'],
    ['shell', '_browse', 'WidgetTools._browse'],
    ['construct', 'MarketPage'],
    ['shell', 'market_page', 'MarketPage'],
    ['shell', 'refresh_market', 'MarketPage.refresh_market'],
    ['shell', 'save_market_preferences', 'MarketPage.save_market_preferences'],
    ['shell', 'load_market_cache', 'MarketPage.load_market_cache'],
    ['shell', 'bind_result_layers', 'MarketPage.bind_result_layers'],
    ['shell', 'market', 'MarketPage'],
    ['state', 'market', 'MarketPage'],
    ['state', 'refresh_market', 'MarketPage.refresh_market'],
    ['state', 'save_market_preferences', 'MarketPage.save_market_preferences'],
    ['state', 'load_market_cache', 'MarketPage.load_market_cache'],
    ['state', 'bind_result_layers', 'MarketPage.bind_result_layers'],
    ['construct', 'DataPage'],
    ['shell', 'data_page', 'DataPage'],
    ['shell', 'bars', 'DataPage.bars'],
    ['shell', 'calendar_path', 'DataPage.calendar_path'],
    ['shell', 'contract', 'DataPage.contract'],
    ['shell', 'data_card', 'DataPage.data_card'],
    ['shell', 'data_detail', 'DataPage.data_detail'],
    ['shell', 'days', 'DataPage.days'],
    ['shell', 'import_kind', 'DataPage.import_kind'],
    ['shell', 'import_path', 'DataPage.import_path'],
    ['shell', 'market_provider', 'DataPage.market_provider'],
    ['shell', 'network_data', 'DataPage.network_data'],
    ['shell', 'overview', 'DataPage.overview'],
    ['shell', 'summary', 'DataPage.summary'],
    ['shell', 'import_market_file', 'DataPage.import_market_file'],
    ['shell', 'import_market_history', 'DataPage.import_market_history'],
    ['shell', 'import_data', 'DataPage.import_data'],
    ['shell', 'download_data', 'DataPage.download_data'],
    ['state', 'bars', 'DataPage.bars'],
    ['state', 'calendar_path', 'DataPage.calendar_path'],
    ['state', 'contract', 'DataPage.contract'],
    ['state', 'data_card', 'DataPage.data_card'],
    ['state', 'data_detail', 'DataPage.data_detail'],
    ['state', 'days', 'DataPage.days'],
    ['state', 'import_kind', 'DataPage.import_kind'],
    ['state', 'import_path', 'DataPage.import_path'],
    ['state', 'market_provider', 'DataPage.market_provider'],
    ['state', 'network_data', 'DataPage.network_data'],
    ['state', 'overview', 'DataPage.overview'],
    ['state', 'summary', 'DataPage.summary'],
    ['state', 'import_market_file', 'DataPage.import_market_file'],
    ['state', 'import_market_history', 'DataPage.import_market_history'],
    ['state', 'import_data', 'DataPage.import_data'],
    ['state', 'download_data', 'DataPage.download_data'],
    ['construct', 'StrategyPage'],
    ['shell', 'strategy_page', 'StrategyPage'],
    ['shell', 'campaign_config', 'StrategyPage.campaign_config'],
    ['shell', 'campaign_form', 'StrategyPage.campaign_form'],
    ['shell', 'candidate_card', 'StrategyPage.candidate_card'],
    ['shell', 'candidate_choice', 'StrategyPage.candidate_choice'],
    ['shell', 'candidate_detail', 'StrategyPage.candidate_detail'],
    ['shell', 'chatgpt_sign_in_entry', 'StrategyPage.chatgpt_sign_in_entry'],
    ['shell', 'evaluation_table', 'StrategyPage.evaluation_table'],
    ['shell', 'family', 'StrategyPage.family'],
    ['shell', 'history', 'StrategyPage.history'],
    ['shell', 'history_table', 'StrategyPage.history_table'],
    ['shell', 'manual_path', 'StrategyPage.manual_path'],
    ['shell', 'manual_response', 'StrategyPage.manual_response'],
    ['shell', 'parameters', 'StrategyPage.parameters'],
    ['shell', 'provider_mode', 'StrategyPage.provider_mode'],
    ['shell', 'strategy_detail', 'StrategyPage.strategy_detail'],
    ['shell', 'strategy_form', 'StrategyPage.strategy_form'],
    ['shell', 'use_candidate_button', 'StrategyPage.use_candidate_button'],
    ['shell', 'walk_forward_advanced', 'StrategyPage.walk_forward_advanced'],
    ['shell', 'walk_forward_advanced_group', 'StrategyPage.walk_forward_advanced_group'],
    ['shell', 'walk_forward_campaign', 'StrategyPage.walk_forward_campaign'],
    ['shell', 'walk_forward_choice', 'StrategyPage.walk_forward_choice'],
    ['shell', 'walk_forward_consent', 'StrategyPage.walk_forward_consent'],
    ['shell', 'walk_forward_form', 'StrategyPage.walk_forward_form'],
    ['shell', 'walk_forward_original', 'StrategyPage.walk_forward_original'],
    ['shell', 'walk_forward_preview', 'StrategyPage.walk_forward_preview'],
    ['shell', 'walk_forward_results', 'StrategyPage.walk_forward_results'],
    ['shell', 'walk_forward_saved_controls', 'StrategyPage.walk_forward_saved_controls'],
    ['shell', 'walk_forward_start', 'StrategyPage.walk_forward_start'],
    ['shell', 'walk_forward_status', 'StrategyPage.walk_forward_status'],
    ['shell', '_walk_forward_section', 'StrategyPage._walk_forward_section'],
    ['shell', '_connect_walk_forward_inputs', 'StrategyPage._connect_walk_forward_inputs'],
    ['shell', '_walk_forward_origin_changed', 'StrategyPage._walk_forward_origin_changed'],
    ['shell', 'pick_walk_forward_original', 'StrategyPage.pick_walk_forward_original'],
    ['shell', '_walk_forward_saved_source', 'StrategyPage._walk_forward_saved_source'],
    ['shell', '_invalidate_walk_forward_preview', 'StrategyPage._invalidate_walk_forward_preview'],
    ['shell', '_walk_forward_input_key', 'StrategyPage._walk_forward_input_key'],
    ['shell', 'preview_walk_forward', 'StrategyPage.preview_walk_forward'],
    ['shell', 'run_walk_forward', 'StrategyPage.run_walk_forward'],
    ['shell', 'read_walk_forward', 'StrategyPage.read_walk_forward'],
    ['shell', '_refresh_walk_forward_references', 'StrategyPage._refresh_walk_forward_references'],
    ['shell', '_walk_forward_event', 'StrategyPage._walk_forward_event'],
    ['shell', '_family_changed', 'StrategyPage._family_changed'],
    ['shell', 'run_campaign', 'StrategyPage.run_campaign'],
    ['shell', 'export_manual_request', 'StrategyPage.export_manual_request'],
    ['shell', 'inspect_candidate', 'StrategyPage.inspect_candidate'],
    ['shell', 'use_candidate', 'StrategyPage.use_candidate'],
    ['shell', 'use_builtin', 'StrategyPage.use_builtin'],
    ['state', 'campaign_config', 'StrategyPage.campaign_config'],
    ['state', 'campaign_form', 'StrategyPage.campaign_form'],
    ['state', 'candidate_card', 'StrategyPage.candidate_card'],
    ['state', 'candidate_choice', 'StrategyPage.candidate_choice'],
    ['state', 'candidate_detail', 'StrategyPage.candidate_detail'],
    ['state', 'chatgpt_sign_in_entry', 'StrategyPage.chatgpt_sign_in_entry'],
    ['state', 'evaluation_table', 'StrategyPage.evaluation_table'],
    ['state', 'family', 'StrategyPage.family'],
    ['state', 'history', 'StrategyPage.history'],
    ['state', 'history_table', 'StrategyPage.history_table'],
    ['state', 'manual_path', 'StrategyPage.manual_path'],
    ['state', 'manual_response', 'StrategyPage.manual_response'],
    ['state', 'parameters', 'StrategyPage.parameters'],
    ['state', 'provider_mode', 'StrategyPage.provider_mode'],
    ['state', 'strategy_detail', 'StrategyPage.strategy_detail'],
    ['state', 'strategy_form', 'StrategyPage.strategy_form'],
    ['state', 'use_candidate_button', 'StrategyPage.use_candidate_button'],
    ['state', 'walk_forward_advanced', 'StrategyPage.walk_forward_advanced'],
    ['state', 'walk_forward_advanced_group', 'StrategyPage.walk_forward_advanced_group'],
    ['state', 'walk_forward_campaign', 'StrategyPage.walk_forward_campaign'],
    ['state', 'walk_forward_choice', 'StrategyPage.walk_forward_choice'],
    ['state', 'walk_forward_consent', 'StrategyPage.walk_forward_consent'],
    ['state', 'walk_forward_form', 'StrategyPage.walk_forward_form'],
    ['state', 'walk_forward_original', 'StrategyPage.walk_forward_original'],
    ['state', 'walk_forward_preview', 'StrategyPage.walk_forward_preview'],
    ['state', 'walk_forward_results', 'StrategyPage.walk_forward_results'],
    ['state', 'walk_forward_saved_controls', 'StrategyPage.walk_forward_saved_controls'],
    ['state', 'walk_forward_start', 'StrategyPage.walk_forward_start'],
    ['state', 'walk_forward_status', 'StrategyPage.walk_forward_status'],
    ['state', '_walk_forward_section', 'StrategyPage._walk_forward_section'],
    ['state', '_connect_walk_forward_inputs', 'StrategyPage._connect_walk_forward_inputs'],
    ['state', '_walk_forward_origin_changed', 'StrategyPage._walk_forward_origin_changed'],
    ['state', 'pick_walk_forward_original', 'StrategyPage.pick_walk_forward_original'],
    ['state', '_walk_forward_saved_source', 'StrategyPage._walk_forward_saved_source'],
    ['state', '_invalidate_walk_forward_preview', 'StrategyPage._invalidate_walk_forward_preview'],
    ['state', '_walk_forward_input_key', 'StrategyPage._walk_forward_input_key'],
    ['state', 'preview_walk_forward', 'StrategyPage.preview_walk_forward'],
    ['state', 'run_walk_forward', 'StrategyPage.run_walk_forward'],
    ['state', 'read_walk_forward', 'StrategyPage.read_walk_forward'],
    ['state', '_refresh_walk_forward_references', 'StrategyPage._refresh_walk_forward_references'],
    ['state', '_walk_forward_event', 'StrategyPage._walk_forward_event'],
    ['state', '_family_changed', 'StrategyPage._family_changed'],
    ['state', 'run_campaign', 'StrategyPage.run_campaign'],
    ['state', 'export_manual_request', 'StrategyPage.export_manual_request'],
    ['state', 'inspect_candidate', 'StrategyPage.inspect_candidate'],
    ['state', 'use_candidate', 'StrategyPage.use_candidate'],
    ['state', 'use_builtin', 'StrategyPage.use_builtin'],
    ['construct', 'BacktestPage'],
    ['shell', 'backtest_page', 'BacktestPage'],
    ['shell', 'backtest_form', 'BacktestPage.backtest_form'],
    ['shell', 'batch', 'BacktestPage.batch'],
    ['shell', 'config', 'BacktestPage.config'],
    ['shell', 'end_date', 'BacktestPage.end_date'],
    ['shell', 'fills_table', 'BacktestPage.fills_table'],
    ['shell', 'plot', 'BacktestPage.plot'],
    ['shell', 'result_card', 'BacktestPage.result_card'],
    ['shell', 'result_choice', 'BacktestPage.result_choice'],
    ['shell', 'result_detail', 'BacktestPage.result_detail'],
    ['shell', 'run_button', 'BacktestPage.run_button'],
    ['shell', 'start_date', 'BacktestPage.start_date'],
    ['shell', 'run_backtest', 'BacktestPage.run_backtest'],
    ['shell', 'show_result', 'BacktestPage.show_result'],
    ['state', 'backtest_form', 'BacktestPage.backtest_form'],
    ['state', 'batch', 'BacktestPage.batch'],
    ['state', 'config', 'BacktestPage.config'],
    ['state', 'end_date', 'BacktestPage.end_date'],
    ['state', 'fills_table', 'BacktestPage.fills_table'],
    ['state', 'plot', 'BacktestPage.plot'],
    ['state', 'result_card', 'BacktestPage.result_card'],
    ['state', 'result_choice', 'BacktestPage.result_choice'],
    ['state', 'result_detail', 'BacktestPage.result_detail'],
    ['state', 'run_button', 'BacktestPage.run_button'],
    ['state', 'start_date', 'BacktestPage.start_date'],
    ['state', 'run_backtest', 'BacktestPage.run_backtest'],
    ['state', 'show_result', 'BacktestPage.show_result'],
    ['construct', 'ComparePage'],
    ['shell', 'compare_page', 'ComparePage'],
    ['shell', '_analysis_section', 'ComparePage._analysis_section'],
    ['shell', '_invalidate_analysis_preview', 'ComparePage._invalidate_analysis_preview'],
    ['shell', 'pick_analysis_original', 'ComparePage.pick_analysis_original'],
    ['shell', '_analysis_request', 'ComparePage._analysis_request'],
    ['shell', 'preview_analysis', 'ComparePage.preview_analysis'],
    ['shell', 'run_analysis', 'ComparePage.run_analysis'],
    ['shell', 'read_analysis', 'ComparePage.read_analysis'],
    ['shell', '_analysis_saved_changed', 'ComparePage._analysis_saved_changed'],
    ['shell', '_selected_recovery_launch', 'ComparePage._selected_recovery_launch'],
    ['shell', 'reconcile_saved_analysis', 'ComparePage.reconcile_saved_analysis'],
    ['shell', '_recovery_display_fingerprint', 'ComparePage._recovery_display_fingerprint'],
    ['shell', '_refresh_recovery_controls', 'ComparePage._refresh_recovery_controls'],
    ['shell', '_analysis_event', 'ComparePage._analysis_event'],
    ['shell', '_refresh_analysis_saved', 'ComparePage._refresh_analysis_saved'],
    ['shell', 'select_strategy', 'ComparePage.select_strategy'],
    ['construct', 'PaperPage'],
    ['shell', 'paper_page', 'PaperPage'],
    ['shell', 'load_form_file', 'PaperPage.load_form_file'],
    ['shell', 'demo_paper_policy', 'PaperPage.demo_paper_policy'],
    ['shell', 'paper_job', 'PaperPage.paper_job'],
    ['shell', 'kill_paper', 'PaperPage.kill_paper'],
    ['shell', '_show_account', 'PaperPage._show_account'],
    ['shell', '_remember_stop', 'PaperPage._remember_stop'],
    ['shell', 'freeze_paper', 'PaperPage.freeze_paper'],
    ['construct', 'SettingsPage'],
    ['shell', 'settings_page', 'SettingsPage'],
    ['shell', 'auto_restore_chatgpt', 'SettingsPage.auto_restore_chatgpt'],
    ['shell', 'show_chatgpt_sign_in', 'SettingsPage.show_chatgpt_sign_in'],
    ['shell', '_chatgpt_quiesce', 'SettingsPage._chatgpt_quiesce'],
    ['shell', '_chatgpt_dispatch', 'SettingsPage._chatgpt_dispatch'],
    ['shell', '_chatgpt_cancel', 'SettingsPage._chatgpt_cancel'],
    ['shell', '_chatgpt_open_browser', 'SettingsPage._chatgpt_open_browser'],
    ['shell', '_plan_usage_request', 'SettingsPage._plan_usage_request'],
    ['shell', '_current_plan_binding', 'SettingsPage._current_plan_binding'],
    ['shell', 'inspect_plan_usage', 'SettingsPage.inspect_plan_usage'],
    ['shell', '_record_connection_error', 'SettingsPage._record_connection_error'],
    ['shell', '_chatgpt_event', 'SettingsPage._chatgpt_event'],
    ['shell', 'save_settings', 'SettingsPage.save_settings'],
    ['shell', 'load_settings', 'SettingsPage.load_settings'],
    ['shell', 'configure_workspace', 'SettingsPage.configure_workspace'],
    ['shell', 'open_releases', 'SettingsPage.open_releases'],
    ['shell', 'record_event', 'SettingsPage.record_event'],
    ['shell', 'read_logs', 'SettingsPage.read_logs'],
    ['shell', 'backup', 'SettingsPage.backup'],
    ['state', 'chatgpt_panel', 'shell.chatgpt_panel'],
    ['state', 'chatgpt_controller', 'shell.chatgpt_controller'],
    ['construct', 'ViewCoordinator'],
    ['shell', 'views_page', 'ViewCoordinator'],
    ['shell', 'refresh_views', 'ViewCoordinator.refresh_views'],
    ['state', 'select_button', 'shell.select_button'],
    ['call', 'shell.chatgpt_panel.model.currentIndexChanged.connect'],
    ['call', 'shell.chatgpt_panel.timeout.valueChanged.connect'],
    ['call', 'shell.chatgpt_panel.account.currentIndexChanged.connect'],
    ['call', 'StrategyPage._connect_walk_forward_inputs'],
]

STUB_CALLBACKS = [
    '_advanced',
    '_analysis_event',
    '_analysis_request',
    '_analysis_saved_changed',
    '_analysis_section',
    '_browse',
    '_busy',
    '_button',
    '_chatgpt_cancel',
    '_chatgpt_dispatch',
    '_chatgpt_event',
    '_chatgpt_open_browser',
    '_chatgpt_quiesce',
    '_compare_page',
    '_confirm_button',
    '_current_plan_binding',
    '_invalidate_analysis_preview',
    '_mount_market',
    '_mount_page',
    '_navigate_selected_page',
    '_notification_link',
    '_page',
    '_paper_page',
    '_payload',
    '_plan_usage_request',
    '_quiesce_and_recover',
    '_record_connection_error',
    '_recovery_display_fingerprint',
    '_refresh_analysis_saved',
    '_refresh_recovery_controls',
    '_remember',
    '_remember_stop',
    '_safe',
    '_save_section_preferences',
    '_selected_recovery_launch',
    '_settings_page',
    '_show_account',
    '_text',
    'auto_restore_chatgpt',
    'backup',
    'cancel_job',
    'closeEvent',
    'configure_workspace',
    'demo_paper_policy',
    'form_feedback',
    'freeze_paper',
    'inspect_plan_usage',
    'kill_paper',
    'load_form_file',
    'load_settings',
    'notify_local',
    'open_releases',
    'paper_job',
    'pick_analysis_original',
    'poll_jobs',
    'preview_analysis',
    'read_analysis',
    'read_logs',
    'reconcile_saved_analysis',
    'record_event',
    'refresh_views',
    'run_analysis',
    'save_settings',
    'select_strategy',
    'show_chatgpt_sign_in',
    'start_job',
    'service',
]

WINDOW_ATTRIBUTES = [
    '__METAOBJECT__',
    '_advanced',
    '_analysis_event',
    '_analysis_request',
    '_analysis_saved_changed',
    '_analysis_section',
    '_browse',
    '_button',
    '_chatgpt_cancel',
    '_chatgpt_dispatch',
    '_chatgpt_event',
    '_chatgpt_open_browser',
    '_chatgpt_quiesce',
    '_confirm_button',
    '_current_plan_binding',
    '_disabled_hints',
    '_invalidate_analysis_preview',
    '_page_widgets',
    '_payload',
    '_plan_usage_request',
    '_record_connection_error',
    '_recovery_display_fingerprint',
    '_refresh_analysis_saved',
    '_refresh_recovery_controls',
    '_remember',
    '_remember_stop',
    '_save_section_preferences',
    '_selected_recovery_launch',
    '_show_account',
    '_text',
    'accessible_layout',
    'app_header',
    'auto_restore_chatgpt',
    'backup',
    'cancel_shortcut',
    'command_palette',
    'compare_page',
    'configure_workspace',
    'customContextMenuRequested',
    'demo_paper_policy',
    'destroyed',
    'freeze_paper',
    'help_relocations',
    'iconSizeChanged',
    'inspect_plan_usage',
    'job_feedback',
    'job_progress',
    'kill_paper',
    'load_form_file',
    'load_settings',
    'notification_center',
    'objectNameChanged',
    'onboarding',
    'open_releases',
    'page_host',
    'page_shortcuts',
    'page_state',
    'palette_shortcut',
    'paper_job',
    'paper_page',
    'pick_analysis_original',
    'preview_analysis',
    'privacy',
    'quick_start',
    'read_analysis',
    'read_logs',
    'reconcile_saved_analysis',
    'record_event',
    'refresh_shortcut',
    'refresh_views',
    'run_analysis',
    'save_settings',
    'select_strategy',
    'settings_page',
    'show_chatgpt_sign_in',
    'tabifiedDockWidgetActivated',
    'toolButtonStyleChanged',
    'views_page',
    'widgets_page',
    'windowIconChanged',
    'windowIconTextChanged',
    'windowTitleChanged',
]

WINDOW_CALLBACKS = [
    '_advanced',
    '_analysis_event',
    '_analysis_request',
    '_analysis_saved_changed',
    '_analysis_section',
    '_browse',
    '_busy',
    '_button',
    '_chatgpt_cancel',
    '_chatgpt_dispatch',
    '_chatgpt_event',
    '_chatgpt_open_browser',
    '_chatgpt_quiesce',
    '_compare_page',
    '_confirm_button',
    '_current_plan_binding',
    '_invalidate_analysis_preview',
    '_mount_market',
    '_mount_page',
    '_navigate_selected_page',
    '_notification_link',
    '_page',
    '_paper_page',
    '_payload',
    '_plan_usage_request',
    '_quiesce_and_recover',
    '_record_connection_error',
    '_recovery_display_fingerprint',
    '_refresh_analysis_saved',
    '_refresh_recovery_controls',
    '_remember',
    '_remember_stop',
    '_safe',
    '_save_section_preferences',
    '_selected_recovery_launch',
    '_settings_page',
    '_show_account',
    '_text',
    'auto_restore_chatgpt',
    'backup',
    'cancel_job',
    'closeEvent',
    'configure_workspace',
    'demo_paper_policy',
    'form_feedback',
    'freeze_paper',
    'inspect_plan_usage',
    'kill_paper',
    'load_form_file',
    'load_settings',
    'notify_local',
    'open_releases',
    'paper_job',
    'pick_analysis_original',
    'poll_jobs',
    'preview_analysis',
    'read_analysis',
    'read_logs',
    'reconcile_saved_analysis',
    'record_event',
    'refresh_views',
    'run_analysis',
    'save_settings',
    'select_strategy',
    'show_chatgpt_sign_in',
    'start_job',
    'ui_operations',
    'paper_risk_limits',
    '_paper',
    '_dataset',
    'plan_provider',
    'connection_event_from_payload',
    'analysis_preview_text',
    'analysis_record_text',
    'saved_analysis_entries',
    'load_result',
    'result_name',
    'write_json',
    'read_json',
    'load_dataset',
]
