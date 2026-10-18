"""Offline theme tokens, Qt property refresh, and application integration."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from desktop_theme import (COLORS, FONT_SIZES, SPACING, STATUS_COLORS,
                           apply_theme, build_app_stylesheet, set_status)
from test_no_inline_stylesheet import WIDGET_STYLESHEET_ALLOWLIST


class DesktopThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        old = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, old)
        apply_theme(self.app)

    def test_tokens_and_complete_selectors(self):
        self.assertTrue({'background', 'text', 'primary', 'success', 'warning',
                         'danger', 'neutral'} <= COLORS.keys())
        for color in COLORS.values():
            self.assertRegex(color, r'^#[0-9a-fA-F]{6}$')
        self.assertTrue(all(isinstance(value, int) and value > 0
                            for value in (*FONT_SIZES.values(), *SPACING.values())))
        qss = build_app_stylesheet()
        self.assertNotIn('@', qss)
        for role in ('primary', 'secondary', 'danger'):
            self.assertIn(f'QPushButton[role="{role}"]', qss)
        for state in ('success', 'warning', 'danger', 'neutral'):
            self.assertIn(f'[status="{state}"]', qss)

    def test_apply_and_status_refresh_offscreen(self):
        self.assertEqual(self.app.styleSheet(), build_app_stylesheet())
        label = QLabel('status')
        self.addCleanup(label.deleteLater)
        label.show()
        for state, color in STATUS_COLORS.items():
            set_status(label, state)
            self.app.processEvents()
            self.assertEqual(label.property('status'), state)
            self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).name(), color)
            self.assertEqual(label.styleSheet(), '')
        with self.assertRaises(ValueError):
            set_status(label, 'invalid')
        self.assertEqual(label.property('status'), 'neutral')
        label.close()

    def test_window_roles_and_empty_widget_stylesheets(self):
        from desktop_ui import MainWindow
        from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore
        root = Path(tempfile.gettempdir()) / ('markauto-theme-' + uuid.uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        paths = AppPaths(root).ensure()
        jobs = JobManager(paths)
        self.addCleanup(jobs.close)
        window = MainWindow(paths, jobs, SettingsStore(paths.state/'settings.json'),
                            BackupManager(paths, jobs))
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        for timer in window.findChildren(QTimer):
            timer.stop()
        window.show()
        self.app.processEvents()
        buttons = window.findChildren(QPushButton)
        self.assertTrue(buttons)
        for button in buttons:
            self.assertIn(button.property('role'), ('primary', 'secondary', 'danger'),
                          button.objectName())
        previous = window.strategy_form.property('feedback')
        with patch('desktop_ui.QTimer.singleShot') as single_shot:
            window.form_feedback(window.strategy_form, 'synthetic')
        self.assertTrue(window.strategy_form.property('feedback'))
        self.assertEqual(single_shot.call_args.args[:2], (1800, window.strategy_form))
        single_shot.call_args.args[2]()
        self.assertEqual(window.strategy_form.property('feedback'), previous)
        window.notify_local('synthetic', error=True)
        window._show_account({'kill_switch': False})
        for widget in [window, *window.findChildren(QWidget)]:
            if widget.objectName() not in WIDGET_STYLESHEET_ALLOWLIST:
                self.assertEqual(widget.styleSheet(), '', widget.objectName())

    def test_snapshot_diff_boundaries_and_metrics_guard(self):
        import json
        from PySide6.QtGui import QColor, QImage
        from tools.ui_theme_diff import compare
        root = Path(tempfile.gettempdir()) / ('markauto-theme-diff-' + uuid.uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        before, after = root/'before', root/'after'
        before.mkdir()
        after.mkdir()
        for directory in (before, after):
            (directory/'metrics.json').write_text(json.dumps({'pages': {'test': {
                'page_height': 10, 'visible_text': ['synthetic']}}}), encoding='utf-8')
        image = QImage(100, 10, QImage.Format.Format_RGB32)
        image.fill(QColor('#000000'))
        self.assertTrue(image.save(str(before/'01.png')))
        # One changed pixel out of 1000 is exactly the permitted 0.1%.
        image.setPixelColor(0, 0, QColor(9, 0, 0))
        self.assertTrue(image.save(str(after/'01.png')))
        self.assertTrue(compare(before, after)['passed'])
        image.setPixelColor(1, 0, QColor(0, 8, 0))
        self.assertTrue(image.save(str(after/'01.png')))
        self.assertTrue(compare(before, after)['passed'])
        image.setPixelColor(1, 0, QColor(0, 9, 0))
        self.assertTrue(image.save(str(after/'01.png')))
        self.assertFalse(compare(before, after)['passed'])
        (after/'metrics.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            compare(before, after)
