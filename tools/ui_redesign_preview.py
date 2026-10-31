"""Launch or capture the real desktop with disposable synthetic data only."""

from __future__ import annotations

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def isolate(root):
    """Set every user-profile location before importing the desktop runtime."""
    for variable, folder in (('LOCALAPPDATA', 'local'), ('APPDATA', 'roaming'), ('TEMP', 'temp'), ('TMP', 'temp')):
        path = root / folder
        path.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(path)
    os.environ['PYTHONUTF8'] = '1'
    os.environ['MARKAUTO_WORKSPACE'] = str(root / 'workspace')


def build_window(root, *, populated=True):
    from PySide6.QtCore import QEvent, QObject, QTimer
    from quantlab.core import ValidationError
    from quantlab.research_core.adapters.workspace_store import AppPaths
    from quantlab.research_core.application.job_manager import JobManager
    from quantlab.research_core.adapters.settings_store import SettingsStore
    from quantlab.research_core.adapters.workspace_backup import BackupManager
    from desktop_app.strings.catalog import ui_text
    from desktop_app.shell.window import MainWindow
    from desktop_app.shell.main_window import execute_ui_operation

    class PreviewJobs(JobManager):
        def start(self, operation, payload, **kwargs):
            forbidden = operation.startswith('ui_chatgpt') or operation in ('ui_refresh', 'ui_analysis_run', 'ui_idea_research')
            forbidden |= operation == 'ui_campaign' and payload.get('provider', {}).get('mode') != 'fixture'
            forbidden |= operation == 'ui_market_refresh' and not payload.get('local_path')
            if forbidden:
                raise ValidationError(ui_text('redesign.preview.network_disabled'))
            return super().start(operation, payload, **kwargs)

    class OfflinePreviewAvailability(QObject):
        """Queued readiness refreshes cannot grant preview network capabilities."""

        def __init__(self, buttons, parent):
            super().__init__(parent)
            self.buttons = frozenset(buttons)
            self.reason = ui_text('redesign.preview.network_disabled')
            for button in self.buttons:
                button.installEventFilter(self)
                button.setEnabled(False)
                button.setToolTip(self.reason)

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.EnabledChange and watched in self.buttons and watched.isEnabled():
                watched.setEnabled(False)
            if event.type() == QEvent.Type.ToolTipChange and watched in self.buttons and watched.toolTip() != self.reason:
                watched.setToolTip(self.reason)
            return False

    paths = AppPaths(root / 'workspace').ensure()
    jobs = PreviewJobs(paths)
    if populated:
        from desktop_app.smoke.fixtures import _smoke_steps

        for operation, payload in _smoke_steps()[:2]:
            execute_ui_operation(operation, payload, paths)
    window = MainWindow(
        paths, jobs, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, jobs), services=_c_create_ui_services(_c_create_operation_ports())
    )
    window.setWindowTitle(ui_text('redesign.preview.title'))
    window.settings_page.setProperty('offlinePreview', True)
    window.settings_page.maintenance_panel.setProperty('offlinePreview', True)
    from PySide6.QtWidgets import QPushButton

    releases = window.findChild(QPushButton, 'open_releases')
    window._offline_preview_availability = OfflinePreviewAvailability((releases, window.settings_page.maintenance_panel.update_button), window)
    if populated:
        window.backtest_page.show_result()
    for timer in window.findChildren(QTimer):
        timer.stop()
    return window, jobs


def capture(window, out):
    import json
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QScrollArea
    from desktop_app.shell.theme import apply_theme, scale_window_fonts
    from desktop_app.shell.palette_commands import page_index
    from tools.ui_snapshot import _save_png, page_metrics
    from tests.test_scaled_layouts import layout_defects

    app = QApplication.instance()
    out.mkdir(parents=True, exist_ok=True)
    records = []
    original = QFont(window.font())
    for theme in ('dark', 'light'):
        for width, height, factor in ((1366, 768, 1), (1920, 1080, 1), (1366, 768, 1.5), (1366, 768, 2)):
            window.setFixedSize(width, height)
            window.app_header.theme.setCurrentIndex(window.app_header.theme.findData(theme))
            apply_theme(window)
            font = QFont(original)
            font.setPointSizeF(original.pointSizeF() * factor)
            window.setFont(font)
            scale_window_fonts(window, factor)
            window.show()

            def record(name):
                app.processEvents()
                container = window.stack.currentWidget()
                scroll = container if isinstance(container, QScrollArea) else window.market.page_scroll
                scroll.verticalScrollBar().setValue(0)
                app.processEvents()
                page = scroll.widget()
                defects = layout_defects(page)
                header_defects = layout_defects(window.app_header)
                stem = f'{theme}-{width}x{height}-{factor:g}-{name}'
                _save_png(window, out / (stem + '.png'), 1)
                records.append(
                    dict(
                        view=stem,
                        window_width=window.width(),
                        scroll_max=scroll.horizontalScrollBar().maximum(),
                        truncated=defects[0] + header_defects[0],
                        overlaps=defects[1] + header_defects[1],
                        metrics=page_metrics(page),
                    )
                )

            for name in ('data', 'strategy', 'backtest', 'compare', 'paper', 'market', 'settings'):
                window.navigation.setCurrentRow(page_index(window, name))
                record(name)
            window.navigation.setCurrentRow(page_index(window, 'data'))
            for source in range(window.data_page.sources.count()):
                window.data_page.sources.setCurrentIndex(source)
                record('data-source-' + str(source))
            window.data_page.sources.setCurrentIndex(0)
            window.navigation.setCurrentRow(page_index(window, 'strategy'))
            for mode in ('ideas', 'research', 'manual', 'walk_forward'):
                window.strategy_page.choose_mode(mode)
                record('strategy-' + mode)
            window.strategy_page.choose_mode('ideas')
            if width == 1366 and factor == 1:
                window.navigation.setCurrentRow(page_index(window, 'strategy'))
                for mode in ('ideas', 'research', 'manual', 'walk_forward'):
                    window.strategy_page.choose_mode(mode)
                    app.processEvents()
                    _save_png(window, out / f'{theme}-strategy-{mode}.png', 1)
                window.navigation.setCurrentRow(page_index(window, 'settings'))
                window.settings_page.connection_toggle.setChecked(True)
                app.processEvents()
                _save_png(window, out / f'{theme}-connection-expanded.png', 1)
                window.settings_page.connection_toggle.setChecked(False)
                window.strategy_page.choose_mode('ideas')
    (out / 'layout-audit.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(
        json.dumps(
            {
                'views': len(records),
                'truncated': sum(bool(r['truncated']) for r in records),
                'overlaps': sum(bool(r['overlaps']) for r in records),
                'horizontal_scroll': sum(bool(r['scroll_max']) for r in records),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--empty', action='store_true')
    args = parser.parse_args()
    if args.capture:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    scratch = ROOT / '.tmp-ui-preview'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=scratch) as folder:
        root = Path(folder)
        isolate(root)
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.setStyle('Fusion')
        if sys.platform == 'win32':
            for face in ('msjh.ttc', 'msjhbd.ttc'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / face))
        app.setFont(QFont('Microsoft JhengHei UI', 10))
        window, jobs = build_window(root, populated=not args.empty)
        try:
            if args.capture:
                capture(window, args.capture.resolve())
            else:
                window.timer.start(150)
                window.app_header.timer.start(1000)
                window.show()
                app.exec()
        finally:
            window.close()
            jobs.close()


if __name__ == '__main__':
    main()
