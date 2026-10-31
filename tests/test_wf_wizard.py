"""Five-step navigation, unchanged preview boundary and display-only presets."""

import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QStackedWidget
from tests import test_desktop_pages
from desktop_app.features.walk_forward.wf_wizard import preset_values
from desktop_app.components.formatting import display_number
from quantlab.core import ValidationError


class WizardTests(unittest.TestCase):
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp

    def tearDown(self):
        from PySide6.QtCore import QCoreApplication, QEvent

        test_desktop_pages.PageInteractionTests.tearDown(self)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wizard(self, bars=960):
        from desktop_app.connection_composition import execute_ui_operation

        execute_ui_operation('ui_demo', {'bars': bars}, self.paths)
        self.window.refresh_views()
        return self.window.strategy_page.wf_wizard

    def preview(self):
        from desktop_app.connection_composition import execute_ui_operation

        page = self.window.strategy_page
        with patch.object(page.host, 'start_job', return_value='preview-job'):
            page.preview_walk_forward()
        self.window.last_operation = 'ui_walk_forward_preview'
        result = execute_ui_operation('ui_walk_forward_preview', {'plan': page._walk_forward_input_key()[1]}, self.paths)
        page._walk_forward_event({'type': 'result', 'result': result})
        return result

    def test_invalid_data_and_pool_block_progress_with_message(self):
        wizard = self.window.strategy_page.wf_wizard
        self.assertTrue(wizard.go_to(1))
        self.assertFalse(wizard.go_to(2))
        self.assertIn('資料', wizard.message.text())
        wizard.go_to(0)
        self.window.walk_forward_form.fields['pool_origin'].setCurrentIndex(1)
        self.assertFalse(wizard.go_to(1))
        self.assertIn('候選池', wizard.message.text())

    def test_default_preview_takes_three_control_operations(self):
        wizard = self.wizard()
        operations = 0
        with patch.object(wizard.page.host, 'start_job', return_value='preview-job') as start:
            for expected in (1, 2, 3):
                wizard.next.click()
                operations += 1
                self.assertEqual(wizard.position, expected, wizard.message.text())
            self.assertEqual(start.call_args.args[0], 'ui_walk_forward_preview')
        self.assertLessEqual(operations, 5)
        self.assertEqual(self.window.walk_forward_form.fields['train_bars'].text(), '240')

    def test_presets_drive_same_fields_and_core_validation(self):
        wizard = self.wizard()
        for preset, folds, train, width, holdout in (('quick', 2, 240, 120, 600), ('standard', 3, 240, 120, 720), ('strict', 4, 240, 60, 540)):
            wizard.preset.setCurrentIndex(wizard.preset.findData(preset))
            wizard.apply_preset()
            self.assertEqual(
                preset_values(960, preset),
                dict(
                    start=0,
                    train_bars=train,
                    validation_bars=width,
                    oos_bars=width,
                    step_bars=width,
                    gap_bars=0,
                    fold_count=folds,
                    final_holdout_start=holdout,
                    final_holdout_end=960,
                    max_evaluations=folds * 11,
                ),
            )
            self.assertEqual(wizard.validate_step(2), '')
            self.assertEqual(int(self.window.walk_forward_form.fields['fold_count'].text()), folds)
        for count in (8, 240, 961):
            for preset in ('quick', 'standard', 'strict'):
                values = preset_values(count, preset)
                self.assertLess(values['final_holdout_start'], count)
        with self.assertRaises(ValueError):
            preset_values(7, 'standard')

    def test_custom_fields_only_visible_and_enabled_for_custom(self):
        wizard = self.wizard()
        wizard.go_to(1)
        wizard.go_to(2)
        form = self.window.walk_forward_form
        self.assertTrue(form.isHidden())
        self.assertFalse(form.isEnabled())
        wizard.preset.setCurrentIndex(wizard.preset.findData('custom'))
        self.assertFalse(form.isHidden())
        self.assertTrue(form.isEnabled())
        form.fields['train_bars'].setText('invalid')
        self.assertFalse(wizard.go_to(3))
        self.assertIn('窗口', wizard.message.text())
        form.fields['train_bars'].setText('99999')
        self.assertFalse(wizard.go_to(3))

    def test_skip_ahead_refused_even_through_stack_base_api(self):
        wizard = self.wizard()
        self.assertFalse(wizard.go_to(3))
        wizard.stack.setCurrentIndex(4)
        self.assertEqual(wizard.stack.currentIndex(), 0)
        self.assertFalse(wizard.stack.accept(4))
        QStackedWidget.setCurrentIndex(wizard.stack, 4)
        self.assertEqual(wizard.stack.currentIndex(), 0)
        self.assertIn('跳過', wizard.message.text())

    def test_preview_timeline_labels_order_and_width_ratios(self):
        wizard = self.wizard()
        self.preview()
        self.assertEqual(wizard.timeline.lengths, (240, 120, 120, 240))
        segments = wizard.timeline.segments(720)
        self.assertEqual([s[0] for s in segments], ['train', 'validation', 'oos', 'holdout'])
        self.assertEqual([s[1] for s in segments], ['訓練', '驗證', '前推', '保留集'])
        self.assertEqual([s[3] for s in segments], [240, 120, 120, 240])
        self.assertEqual(wizard.summary.rowCount(), 10)
        self.assertEqual(wizard.summary.horizontalHeaderItem(0).text(), '輪次')
        wizard.timeline.resize(720, 110)
        self.assertFalse(wizard.timeline.grab().isNull())

    def test_consent_preview_and_busy_gating_remain_fail_closed(self):
        wizard = self.wizard()
        page = wizard.page
        with self.assertRaises(ValidationError):
            page.run_walk_forward()
        self.preview()
        self.assertFalse(page.walk_forward_start.isEnabled())
        self.window._busy(False)
        self.assertFalse(page.walk_forward_start.isEnabled())
        with self.assertRaises(ValidationError):
            page.run_walk_forward()
        page.walk_forward_consent.setChecked(True)
        self.assertTrue(page.walk_forward_start.isEnabled())
        page.walk_forward_form.fields['min_trades'].setText('2')
        self.assertIsNone(page.state._wf_preview)
        self.assertFalse(page.walk_forward_consent.isChecked())
        self.assertFalse(page.walk_forward_start.isEnabled())
        self.assertFalse(wizard.validate_step(3) == '')

    def test_numbers_are_formatted_and_missing_is_not_zero(self):
        wizard = self.wizard()
        result = self.preview()
        for row in range(wizard.summary.rowCount()):
            for col in range(wizard.summary.columnCount()):
                self.assertIsNone(re.search(r'\d+\.\d{5}', wizard.summary.item(row, col).text()))
        self.assertNotEqual(wizard.summary.item(9, 0).text(), '0')
        self.assertEqual(display_number('0.123456789'), '0.1235')
        self.assertNotIn('已評估 第', wizard.preview_summary.text())
        self.assertNotIn('[0,', wizard.preview_summary.text())
        self.assertTrue(wizard.page.walk_forward_preview.isHidden())
        self.assertIn(result['source_identity'], wizard.page.walk_forward_advanced.toPlainText())

    def test_saved_read_remains_available_without_new_preview(self):
        from PySide6.QtWidgets import QPushButton

        wizard = self.window.strategy_page.wf_wizard
        read = wizard.findChild(QPushButton, 'read_walk_forward')
        self.assertFalse(wizard.stack.isAncestorOf(read))
        self.window.walk_forward_choice.addItem('Saved evidence', 'a' * 64)
        with patch.object(wizard.page.host, 'start_job') as start:
            wizard.page.read_walk_forward()
        start.assert_called_once_with('ui_walk_forward_read', {'reference': 'a' * 64})

    def test_result_winner_wording_changes_only_display_projection(self):
        from desktop_app.features.walk_forward.wf_wizard import display_result_rows

        rows = [{'贏家': '第 4 個', '最大回撤': None}]
        result = {'folds': [{'winner_pool_index': 3}]}
        with patch('desktop_app.features.walk_forward.rows.result_rows', return_value=rows):
            displayed = display_result_rows(result)
        self.assertEqual(displayed[0]['贏家'], '候選 4')
        self.assertIsNone(displayed[0]['最大回撤'])

    def test_reopening_consumed_plan_never_retries_oos(self):
        from desktop_app.connection_composition import execute_ui_operation
        from tests.test_desktop_walk_forward import fake_worker

        wizard = self.wizard(240)
        preview = self.preview()
        wizard.page.walk_forward_consent.setChecked(True)
        with patch.object(wizard.page.host, 'start_job', return_value='run-job') as start:
            wizard.page.run_walk_forward()
        operation, payload = start.call_args.args
        wizard.page.state._wf_launch = None
        self.assertEqual(operation, 'ui_walk_forward_run')
        self.assertFalse(wizard.page.walk_forward_consent.isChecked())
        with patch('quantlab.walk_forward._run_bounded', side_effect=fake_worker) as worker:
            first = execute_ui_operation(operation, payload, self.paths)
            calls = worker.call_count
            reopened = execute_ui_operation(operation, payload, self.paths)
            self.assertEqual(worker.call_count, calls)
        self.assertEqual(calls, 33)
        self.assertEqual(first['reference'], preview['preview_identity'])
        self.assertEqual(first['summary'], reopened['summary'])
