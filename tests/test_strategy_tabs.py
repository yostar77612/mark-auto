"""Strategy work areas, preserved widget ancestry and real offscreen heights."""

import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QCheckBox, QTabWidget, QWidget
from tests import test_desktop_pages


class StrategyTabsTests(unittest.TestCase):
    # Reuse the real window fixture without inheriting its test cases.
    setUpClass = classmethod(test_desktop_pages.PageInteractionTests.setUpClass.__func__)
    setUp = test_desktop_pages.PageInteractionTests.setUp
    tearDown = test_desktop_pages.PageInteractionTests.tearDown

    def test_strategy_tabs_and_candidate_analysis(self):
        w = self.window
        tabs = w.strategy_page.tabs
        self.assertIsInstance(tabs, QTabWidget)
        self.assertEqual(tabs.count(), 3)
        self.assertEqual([tabs.tabText(i) for i in range(3)], ['策略設定', 'AI 研究', 'Walk-forward 驗證'])
        self.assertEqual(tabs.currentIndex(), 0)
        self.assertEqual(len({tabs.widget(i) for i in range(3)}), 3)
        settings, research, walk_forward = [tabs.widget(i) for i in range(3)]
        self.assertTrue(settings.isAncestorOf(w.strategy_form))
        self.assertTrue(research.isAncestorOf(w.campaign_form))
        self.assertTrue(walk_forward.isAncestorOf(w.walk_forward_form))
        names = (
            'analysis_candidates',
            'analysis_original_dataset',
            'analysis_preview',
            'analysis_evidence',
            'analysis_one_call_consent',
            'analysis_saved',
            'analysis_checkpoint_notice',
            'analysis_recovery_notice',
            'analysis_findings',
            'pick_analysis_original',
            'preview_candidate_analysis',
            'preview_candidate_comparison',
            'run_candidate_analysis',
            'read_candidate_analysis',
            'reconcile_saved_analysis',
        )
        for name in names:
            widget = w.findChild(QWidget, name)
            with self.subTest(widget=name):
                self.assertIsNotNone(widget)
                self.assertTrue(research.isAncestorOf(widget))
                self.assertFalse(w.compare_page.isAncestorOf(widget))
        toggle = w.findChild(QCheckBox, 'candidate_analysis_toggle')
        tabs.setCurrentIndex(1)
        toggle.setChecked(True)
        self.assertTrue(w.analysis_candidates.isVisibleTo(research))
        toggle.setChecked(False)
        self.assertFalse(w.analysis_candidates.isVisibleTo(research))


class StrategyTabSnapshotTests(unittest.TestCase):
    def test_default_tab_heights_from_real_capture(self):
        from tests.snapshot_cache import default_metrics

        with tempfile.TemporaryDirectory(prefix='markauto-strategy-tabs-'):
            result = default_metrics()
            page = result['pages']['AI 策略中心']
            self.assertEqual(set(page['subpages']), {'策略設定', 'AI 研究', 'Walk-forward 驗證'})
            for name, height in page['subpages'].items():
                with self.subTest(tab=name):
                    self.assertGreater(height, 0)
                    self.assertLessEqual(height, 1100)
            self.assertIn('page_height', page)
            self.assertIn('visible_input_count', page)
            self.assertIn('找策略點子', page['visible_text'])
            self.assertIn('自行設定', page['visible_text'])
