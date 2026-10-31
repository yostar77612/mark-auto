"""Snapshot CLI, logical metrics, full content rendering, and workspace isolation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]


class UiSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def cli(self, *args):
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR='3')
        return subprocess.run(
            [sys.executable, str(ROOT / 'tools/ui_snapshot.py'), *map(str, args)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
        )

    def test_help_and_invalid_arguments_write_nothing(self):
        result = self.cli('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ('--size WxH', '1366x768', '--scale', '--out'):
            self.assertIn(text, result.stdout)
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'must-not-exist'
            for value in ('bad', '0x768', '-1x768', '1366X768', '1366x768x2', '1.5x768'):
                result = self.cli('--size=' + value, '--out', out)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('size must be WxH', result.stderr)
                self.assertFalse(out.exists())
            for value in ('0', '-1', 'nan', 'inf', 'bad'):
                result = self.cli('--scale=' + value, '--out', out)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('scale must be', result.stderr)
                self.assertFalse(out.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def check_output(self, out, size, scale):
        from PySide6.QtGui import QImage

        metrics = json.loads((out / 'metrics.json').read_text(encoding='utf-8'))
        self.assertEqual(metrics['size'], list(size))
        self.assertEqual(metrics['scale'], scale)
        self.assertEqual(len(metrics['pages']), 7)
        self.assertEqual(len(list(out.glob('*.json'))), 1)
        self.assertEqual(len(list(out.glob('*.png'))), 14)
        for page in metrics['pages'].values():
            for key in ('page_height', 'visible_input_count', 'button_count', 'label_char_count', 'primary_button_count', 'full_width'):
                self.assertIs(type(page[key]), int, key)
                self.assertGreaterEqual(page[key], 0)
            self.assertIsInstance(page['visible_text'], list)
            self.assertTrue(page['visible_text'])
            self.assertTrue(all(isinstance(text, str) and text.strip() for text in page['visible_text']))
            self.assertIsInstance(page['unlabeled_inputs'], list)
            self.assertTrue(all(isinstance(text, str) for text in page['unlabeled_inputs']))
            self.assertLessEqual(page['primary_button_count'], 1)
            viewport = QImage(str(out / page['viewport_png']))
            full = QImage(str(out / page['full_png']))
            self.assertFalse(viewport.isNull())
            self.assertFalse(full.isNull())
            self.assertEqual((viewport.width(), viewport.height()), tuple(round(n * scale) for n in size))
            self.assertEqual((full.width(), full.height()), (round(page['full_width'] * scale), round(page['page_height'] * scale)))
        strategy = metrics['pages']['AI 策略中心']
        # The default task now fits a desktop; long research and validation
        # content stays in its named scrollable workspace and is measured too.
        self.assertGreater(strategy['page_height'], 0)
        self.assertLessEqual(strategy['page_height'], 768)
        self.assertEqual(strategy['primary_button_count'], 1)
        self.assertEqual(set(strategy['subpages']), {'策略設定', 'AI 研究', 'Walk-forward 驗證'})
        for name, height in strategy['subpages'].items():
            self.assertGreater(height, 0, name)
            self.assertLessEqual(height, 1100, name)
        return metrics

    def test_cli_scale_size_and_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for name, size, scale in (('normal', (1366, 768), 1), ('double', (1366, 768), 2), ('smaller', (1200, 700), 1)):
                result = self.cli('--size', f'{size[0]}x{size[1]}', '--scale', scale, '--out', base / name)
                self.assertEqual(result.returncode, 0, result.stderr)
                metrics = self.check_output(base / name, size, scale)
                if name == 'normal':
                    normal = metrics
                elif name == 'double':
                    self.assertEqual(normal['pages'], metrics['pages'])

    def test_metrics_roles_labels_and_hidden_controls(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox
        from tools.ui_snapshot import page_metrics

        page = QWidget()
        self.addCleanup(page.deleteLater)
        layout = QVBoxLayout(page)
        label = QLabel('Quantity')
        layout.addWidget(label)
        spin = QSpinBox()
        label.setBuddy(spin)
        layout.addWidget(spin)
        field = QLineEdit()
        field.setObjectName('missing_label')
        layout.addWidget(field)
        hidden = QLineEdit()
        layout.addWidget(hidden)
        hidden.hide()
        readonly = QLineEdit()
        readonly.setReadOnly(True)
        layout.addWidget(readonly)
        for key, value in (('role', 'primary'), ('primary', True), ('role', 'secondary')):
            button = QPushButton('Action')
            button.setProperty(key, value)
            layout.addWidget(button)
        page.show()
        self.app.processEvents()
        metrics = page_metrics(page)
        self.assertEqual(metrics['visible_input_count'], 2)
        self.assertEqual(metrics['unlabeled_inputs'], ['missing_label'])
        self.assertEqual(metrics['primary_button_count'], 1)
        self.assertEqual(metrics['button_count'], 3)
        self.assertEqual(metrics['label_char_count'], len('Quantity'))
        page.close()

    def test_tab_heights_measure_content_and_restore_selection(self):
        from PySide6.QtWidgets import QScrollArea, QTabWidget, QVBoxLayout, QWidget
        from tools.ui_snapshot import tab_heights

        page = QWidget()
        self.addCleanup(page.deleteLater)
        layout = QVBoxLayout(page)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for label, height in (('Short', 120), ('Tall', 900)):
            scroll = QScrollArea()
            content = QWidget()
            content.setMinimumHeight(height)
            scroll.setWidget(content)
            scroll.setWidgetResizable(True)
            tabs.addTab(scroll, label)
        page.resize(600, 400)
        page.show()
        self.app.processEvents()
        tabs.setCurrentIndex(0)
        heights = tab_heights(page, self.app)
        self.assertGreaterEqual(heights['Tall'], 900)
        self.assertLess(heights['Short'], heights['Tall'])
        self.assertEqual(tabs.currentIndex(), 0)
        page.close()

    def test_workspace_isolation_cleanup_and_default_fallback_tripwire(self):
        # QApplication is process-global. Exercise the production CLI lifecycle
        # in a fresh process rather than dispatching timers left by other tests.
        if os.environ.get('MARKAUTO_UI_SNAPSHOT_ISOLATION_CHILD') != '1':
            result = subprocess.run(
                [sys.executable, '-m', 'unittest', 'tests.test_ui_snapshot.UiSnapshotTests.test_workspace_isolation_cleanup_and_default_fallback_tripwire'],
                cwd=ROOT,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', MARKAUTO_UI_SNAPSHOT_ISOLATION_CHILD='1'),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        from tools import ui_snapshot
        from quantlab.research_core.adapters.workspace_store import AppPaths, WorkspaceLocator
        import desktop_app.shell.main_window

        # Read-only evidence for the actual bootstrap and redirected workspace.
        # No ensure(), probes, locks, application startup, or byte reads here.
        bootstrap = AppPaths.discover().root
        roots = {bootstrap, WorkspaceLocator(bootstrap).load(probe=False).root}

        def listing():
            result = {}
            for root in roots:
                if not root.exists():
                    result[str(root)] = None
                    continue
                result[str(root)] = [
                    (str(path.relative_to(root)), path.is_dir(), path.stat().st_size, path.stat().st_mtime_ns) for path in [root, *sorted(root.rglob('*'))]
                ]
            return result

        before = listing()
        directories = []
        original_temp = tempfile.TemporaryDirectory
        original_ensure = AppPaths.ensure
        original_window = desktop_app.shell.main_window.MainWindow
        original_save = ui_snapshot._save_png
        windows = []
        full_captures = []

        def disposable(*args, **kwargs):
            directory = original_temp(*args, **kwargs)
            directories.append(Path(directory.name).resolve())
            return directory

        def ensure(paths):
            self.assertTrue(any(paths.root.resolve().is_relative_to(path) for path in directories))
            self.assertNotIn(paths.root, roots)
            return original_ensure(paths)

        def construct(paths, *args, **kwargs):
            self.assertEqual(paths.root.parent.resolve(), directories[-1])
            windows.append(paths.root)
            return original_window(paths, *args, **kwargs)

        def save(widget, path, scale):
            from PySide6.QtWidgets import QScrollArea

            if path.name.endswith('_full.png'):
                full_captures.append(path.name)
                for scroll in widget.findChildren(QScrollArea):
                    if scroll.isVisibleTo(widget) and scroll.widget() is not None:
                        self.assertGreaterEqual(scroll.viewport().height(), scroll.widget().height())
            return original_save(widget, path, scale)

        with original_temp() as temporary:
            with (
                patch.object(ui_snapshot.tempfile, 'TemporaryDirectory', side_effect=disposable),
                patch.object(AppPaths, 'ensure', ensure),
                patch.object(AppPaths, 'discover', side_effect=AssertionError('default workspace forbidden')),
                patch.object(WorkspaceLocator, 'load', side_effect=AssertionError('workspace lookup forbidden')),
                patch('desktop_app.shell.main_window.MainWindow', side_effect=construct),
                patch.object(ui_snapshot, '_save_png', side_effect=save),
            ):
                ui_snapshot.capture(Path(temporary) / 'out')
                self.assertEqual(len(windows), 1)
                self.assertEqual(len(full_captures), 7)
                AppPaths.discover.assert_not_called()
                WorkspaceLocator.load.assert_not_called()
                self.assertTrue(all(not path.exists() for path in directories))
                with patch.object(ui_snapshot, '_save_png', side_effect=OSError('injected render failure')):
                    with self.assertRaisesRegex(OSError, 'injected render failure'):
                        ui_snapshot.capture(Path(temporary) / 'failure')
                self.assertTrue(all(not path.exists() for path in directories))

                # Prove this guard would fail if construction fell back to defaults.
                def fallback(*args, **kwargs):
                    return original_window(AppPaths.discover(), *args[1:], **kwargs)

                with patch('desktop_app.shell.main_window.MainWindow', side_effect=fallback):
                    with self.assertRaisesRegex(AssertionError, 'default workspace forbidden'):
                        ui_snapshot.capture(Path(temporary) / 'fallback')
                self.assertTrue(all(not path.exists() for path in directories))
        self.assertEqual(before, listing())


if __name__ == '__main__':
    unittest.main()
