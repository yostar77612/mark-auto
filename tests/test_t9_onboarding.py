"""T9 C: real workspace progress, navigation, persistence and wording capture."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QComboBox
from desktop_strings import GLOSSARY, FORBIDDEN_DEFAULT_TERMS
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore


@contextmanager
def sandbox_ui():
    """Confined empty profiles use inherited ACLs; no real credentials are read."""
    mkdir = os.mkdir

    def inherited(path, mode=0o777, *args, **kwargs):
        return mkdir(path, 0o777 if os.name == 'nt' else mode, *args, **kwargs)

    with patch('os.mkdir', side_effect=inherited), patch('desktop_chatgpt_auth.DPAPIVault._prepare'):
        yield


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import faulthandler  # a hang prints every thread's stack to the CI log instead of silently timing out

        faulthandler.dump_traceback_later(240)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.context = sandbox_ui()
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory(prefix='t9-onboarding-')
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name) / 'workspace').ensure()
        self.jobs = JobManager(self.paths)
        self.addCleanup(self.jobs.close)
        self.settings = SettingsStore(self.paths.state / 'settings.json')
        self.open_window()

    def open_window(self):
        from desktop_ui import MainWindow

        self.window = MainWindow(self.paths, self.jobs, self.settings)
        for timer in self.window.findChildren(QTimer):
            timer.stop()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def test_fresh_navigation_empty_actions_and_dismiss_reopen_persistence(self):
        w = self.window
        self.assertFalse(w.onboarding.isHidden())
        self.assertEqual(w.onboarding.completed, (False,) * 5)
        for index, button in enumerate(w.onboarding.buttons):
            button.click()
            self.assertEqual(w.stack.currentIndex(), index)
        for key, expected in (('market', 0), ('strategy', 1), ('backtest', 0), ('compare', 2), ('paper', 0)):
            w.navigation.setCurrentRow({'market': 5, 'strategy': 1, 'backtest': 2, 'compare': 3, 'paper': 4}[key])
            if key == 'strategy':
                w.strategy_page.tabs.setCurrentIndex(1)
            button = w.findChild(QPushButton, 'empty_' + key + '_action')
            self.assertEqual(button.property('role'), 'primary')
            self.assertTrue(button.isVisible())
            button.click()
            self.assertEqual(w.navigation.currentRow(), expected)
        for index in range(7):
            self.assertTrue(w.navigation.item(index).toolTip())
            w.navigation.setCurrentRow(index)
            self.assertEqual(w.stack.currentIndex(), index)
        w.findChild(QPushButton, 'onboarding_dismiss').click()
        self.assertTrue(w.onboarding.isHidden())
        self.assertTrue(self.settings.load()['onboarding_dismissed'])
        w.close()
        self.open_window()
        w = self.window
        self.assertTrue(w.onboarding.isHidden())
        w.findChild(QPushButton, 'onboarding_help').click()
        self.assertFalse(w.onboarding.isHidden())
        self.assertFalse(self.settings.load()['onboarding_dismissed'])

    def test_progress_from_real_worker_outputs_and_selection(self):
        from desktop_ui import execute_ui_operation

        w = self.window
        execute_ui_operation('ui_demo', {'bars': 100}, self.paths)
        w.refresh_views()
        self.assertEqual(w.onboarding.completed, (True, False, False, False, False))
        payload = {'family': 'trend', 'parameters': w.strategy_form.build_payload()['parameters']}
        # Exercise the actual existing worker request, without launching a child process.
        from quantlab.reporting import demo_config
        from quantlab.core import to_dict

        payload['config'] = to_dict(demo_config())
        execute_ui_operation('ui_backtest', payload, self.paths)
        w.refresh_views()
        self.assertTrue(w.onboarding.completed[2])
        w.comparison_list.item(0).setSelected(True)
        self.assertTrue(w.onboarding.completed[3])
        execute_ui_operation('ui_select', {'result': w.result_choice.currentData()}, self.paths)
        w.refresh_views()
        self.assertTrue(w.onboarding.completed[1])
        w.demo_paper_policy()
        execute_ui_operation('ui_paper_snapshot', {'policy': w.policy_form.build_payload()}, self.paths)
        w.onboarding.refresh()
        self.assertFalse(w.onboarding.completed[4])
        execute_ui_operation('ui_paper_reconcile', {'policy': w.policy_form.build_payload(), 'snapshot': w.snapshot_form.build_payload()}, self.paths)
        w.onboarding.refresh()
        self.assertEqual(w.onboarding.completed, (True,) * 5)
        self.assertTrue(all(box.isHidden() for box in w.onboarding.empty_states[2:]))
        w.close()
        self.open_window()
        self.assertTrue(self.window.onboarding.isHidden())

    def test_glossary_and_default_snapshot_all_pages(self):
        from PySide6.QtWidgets import QScrollArea
        from tools.ui_snapshot import page_metrics

        self.assertEqual(GLOSSARY['bar'], 'K棒')
        self.assertEqual(GLOSSARY['OOS'], '樣本外')
        self.assertEqual(GLOSSARY['fixture'], '離線示範')
        self.assertEqual(GLOSSARY['validated_dataset'], '已驗證資料')
        # Measure the already-open window: re-running the full PNG snapshot capture here created a second
        # MainWindow and hung on Linux CI; tests.test_desktop_pages already covers capture() end to end.
        w = self.window
        w.show()
        metrics = {'pages': {}}
        for index in range(w.stack.count()):
            w.navigation.setCurrentRow(index)
            self.app.processEvents()
            container = w.stack.widget(index)
            scroll = container if isinstance(container, QScrollArea) else w.market.page_scroll
            metrics['pages']['page ' + str(index)] = page_metrics(scroll.widget())
        self.assertEqual(len(metrics['pages']), 7)
        for index in range(w.strategy_page.tabs.count()):
            w.strategy_page.tabs.setCurrentIndex(index)
            self.app.processEvents()
            metrics['pages']['strategy tab ' + str(index)] = page_metrics(w.strategy_page)
        for page, values in metrics['pages'].items():
            texts = values['visible_text'] + values['combo_items'] + values['table_headers']
            for text in texts:
                for term in FORBIDDEN_DEFAULT_TERMS:
                    pattern = r'(?i)\b' + re.escape(term) + r'\b' if term.isascii() and not term.endswith(':') else re.escape(term)
                    self.assertIsNone(re.search(pattern, text), (page, term, text))
        # Display names never replace the worker identities in itemData.
        w = self.window
        self.assertEqual([w.provider_mode.itemData(i) for i in range(w.provider_mode.count())], ['chatgpt_plan', 'fixture', 'manual'])
        self.assertIn('離線示範', w.provider_mode.itemText(1))
        self.assertIn('synthetic-assumption-v1', w.config.toPlainText())
        self.assertTrue(w.config.isHidden() or not w.config.isVisibleTo(w))
        self.assertIn('SHA-256', w.findChild(QPushButton, 'onboarding_help').toolTip())

    def test_import_display_names_preserve_old_requests_and_hashes(self):
        from quantlab.core import content_hash, canonical_json

        w = self.window
        w.import_path.setText('input.json')
        w.calendar_path.setText('calendar.json')
        # The old request included an explicitly selected contract. The new
        # optional filter must be enabled before comparing those same bytes.
        w.contract.setText('TAIFEX:TMF:202601')
        w.data_page.contract_filter.setChecked(True)
        legacy = QComboBox()
        legacy.addItems(
            ['validated_dataset', 'ticks', 'ticks_rpt', 'daily_json', 'synthetic_daily_json', 'synthetic_bars', 'synthetic_ticks', 'proxy_bars', 'proxy_ticks']
        )
        self.assertEqual(w.import_kind.count(), legacy.count())
        for index in range(legacy.count()):
            legacy.setCurrentIndex(index)
            w.import_kind.setCurrentIndex(index)
            kind = legacy.currentText()
            self.assertEqual(w.import_kind.currentData(), kind)
            old = {'path': w.import_path.text(), 'calendar': w.calendar_path.text(), 'kind': kind, 'contract': w.contract.text()}
            with patch.object(w.page_host, 'start_job') as start:
                w.import_data()
            new = start.call_args.args[1]
            self.assertEqual(start.call_args.args[0], 'ui_import')
            self.assertEqual(old, new)
            self.assertEqual(canonical_json(old), canonical_json(new))
            self.assertEqual(content_hash(old), content_hash(new))
            self.assertEqual(w.import_kind.itemData(index, 3), kind)

    def test_import_blank_contract_never_infers_a_default(self):
        from quantlab.core import canonical_json, content_hash

        w = self.window
        w.import_path.setText('input.json')
        w.calendar_path.setText('calendar.json')
        w.contract.clear()
        w.data_page.contract_filter.setChecked(False)
        for index in range(w.import_kind.count()):
            w.import_kind.setCurrentIndex(index)
            expected = {'path': 'input.json', 'calendar': 'calendar.json', 'kind': w.import_kind.currentData(), 'contract': ''}
            with self.subTest(kind=expected['kind']), patch.object(w.page_host, 'start_job') as start:
                w.import_data()
                actual = start.call_args.args[1]
                self.assertEqual(actual, expected)
                self.assertEqual(canonical_json(actual), canonical_json(expected))
                self.assertEqual(content_hash(actual), content_hash(expected))
        # A remembered value is also ignored when normalized data is unfiltered.
        w.contract.setText('TAIFEX:TMF:202601')
        for kind in ('synthetic_bars', 'synthetic_ticks', 'proxy_bars', 'proxy_ticks'):
            w.import_kind.setCurrentIndex(w.import_kind.findData(kind))
            with self.subTest(unfiltered=kind), patch.object(w.page_host, 'start_job') as start:
                w.import_data()
                self.assertEqual(start.call_args.args[1]['contract'], '')


if __name__ == '__main__':
    unittest.main()
