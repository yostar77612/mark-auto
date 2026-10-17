"""Display-only T3-B contracts, using isolated workspaces and native widgets."""
from decimal import Decimal
from pathlib import Path
import copy
import json
import os
import re
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel
from desktop_presentation import display_number, display_status, result_name
from desktop_forms import SummaryCard, ResultTable, backtest_summary_text
from desktop_ui import MainWindow
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, BackupManager
from tools.ui_snapshot import capture


class disposable_directory:
    """TemporaryDirectory interface with inherited workspace ACLs."""
    def __init__(self, *args, **kwargs):
        self.root = Path(__file__).resolve().parents[1] / ('.tmp-t3b-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.name = str(self.root)

    def __enter__(self): return self.name

    def cleanup(self):
        if self.root.exists(): shutil.rmtree(self.root)

    def __exit__(self, *args): self.cleanup()


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_formatting_never_changes_source_or_decimal_context(self):
        values = {'cash': '1000000.123456789', 'return': '-0.000706', 'sharpe': Decimal('7.98249664979112245085')}
        before = copy.deepcopy(values)
        card = SummaryCard(); table = ResultTable()
        card.set_values(values); table.set_rows([values])
        self.assertIn('1,000,000.12 TWD', card.label.text())
        self.assertIn('-0.07%', card.label.text()); self.assertIn('7.9825', card.label.text())
        self.assertEqual(values, before)
        self.assertFalse(re.search(r'\d+\.\d{5,}', card.label.text()))
        self.assertEqual(table.item(0, 0).toolTip(), values['cash'])
        self.assertEqual(display_number('0.25', 'win_rate'), '25.00%')
        card.close(); table.close()

    def test_one_status_mapping_and_unknown_fallback(self):
        for code, expected in (('SYNTHETIC', '合成示範資料'), ('DISABLED', '已停用'), ('NOT_VERIFIED', '尚未驗證')):
            self.assertEqual(display_status(code), expected)
            table = ResultTable(); table.set_rows([{'status': code}])
            self.assertEqual(table.item(0, 0).text(), expected); table.close()
        self.assertNotIn('NEW_INTERNAL_CODE', display_status('NEW_INTERNAL_CODE'))

    def test_snapshot_height_and_default_disclosures(self):
        with disposable_directory() as root, patch('tempfile.TemporaryDirectory', disposable_directory):
            metrics = capture(Path(root) / 'snapshots')
            for name in ('AI 策略中心', '紙上交易與復原'):
                self.assertLessEqual(metrics['pages'][name]['page_height'], 1600, name)
            for name, page in metrics['pages'].items():
                text = '\n'.join(page['visible_text'])
                self.assertLessEqual(len(re.findall('實盤|實單|唯讀', text)), 1, (name, text))
                self.assertNotRegex(text, r'\d+\.\d{5,}')
                self.assertNotRegex(text, r'\b(?:SYNTHETIC|DISABLED|NOT_VERIFIED)\b')
            print('T3-B heights:', {name: metrics['pages'][name]['page_height'] for name in ('AI 策略中心', '紙上交易與復原')})

    def test_collapsed_state_saved_and_top_explanation_expands(self):
        with disposable_directory() as root:
            paths = AppPaths(Path(root) / 'workspace', Path(root) / 'bootstrap').ensure()
            settings = SettingsStore(paths.state / 'settings.json'); jobs = JobManager(paths)
            window = MainWindow(paths, jobs, settings, BackupManager(paths, jobs))
            try:
                for timer in window.findChildren(QTimer): timer.stop()
                window.show(); self.app.processEvents()
                self.assertTrue(all(not toggle.isChecked() for toggle in window._section_toggles.values()))
                toggle = next(iter(window._section_toggles.values())); toggle.setChecked(True)
                self.assertTrue(next(iter(settings.load()['advanced_sections'].values())))
                marker = window.findChild(QCheckBox, 'research_mode_status')
                explanation = window.findChild(QLabel, 'research_mode_explanation')
                self.assertTrue(explanation.isHidden()); marker.setChecked(True); self.assertFalse(explanation.isHidden())
                toggle.setChecked(False); window.load_settings(); self.assertFalse(toggle.isChecked())
                saved = settings.load(); saved['advanced_sections'][next(iter(window._section_toggles))] = True; settings.save(saved)
                window.load_settings(); self.assertTrue(toggle.isChecked())
            finally:
                jobs.close(); window.close(); window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_result_selector_names_collision_ids_and_tooltips(self):
        from types import SimpleNamespace
        result = SimpleNamespace(manifest={'strategy': {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}}},
                                 equity=[{'timestamp': '2026-01-01T00:00:00Z'}, {'timestamp': '2026-01-31T00:00:00Z'}])
        name = result_name(result, 0)
        self.assertIn('趨勢・fast=5、slow=20・2026-01-01～2026-01-31・1970-01-01 08:00:00（台北）', name)
        with disposable_directory() as root:
            paths = AppPaths(Path(root)/'workspace', Path(root)/'bootstrap').ensure(); jobs = JobManager(paths)
            window = MainWindow(paths, jobs)
            try:
                for timer in window.findChildren(QTimer): timer.stop()
                reports = []
                for digest in ('a'*64, 'b'*64):
                    path = paths.state/'reports'/digest/'result.json'; path.parent.mkdir(parents=True); path.write_text('{}')
                    reports.append(path)
                # Selector metadata comes from verified report loader; keep detail rendering separate.
                with patch('desktop_ui.load_result', return_value=result), patch.object(window, 'show_result'), patch('desktop_ui.result_name', return_value=name):
                    window.refresh_views()
                self.assertEqual(window.result_choice.itemText(1), name + '（2）')
                for index, path in enumerate(reports):
                    self.assertEqual(window.result_choice.itemData(index), str(path))
                    self.assertEqual(window.comparison_list.item(index).data(Qt.ItemDataRole.UserRole), str(path))
                    self.assertNotRegex(window.result_choice.itemText(index), r'[a-f0-9]{8,}')
                    self.assertEqual(window.result_choice.itemData(index, Qt.ItemDataRole.ToolTipRole), path.parent.name)
            finally:
                jobs.close(); window.close(); window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
