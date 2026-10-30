"""Offscreen readability audit of every desktop page, tab and theme (developer QA only).

Builds the real MainWindow in a disposable workspace and bootstrap (never the
installed %LOCALAPPDATA% data), then for each Qt style, theme, page and tab:
saves a viewport PNG and measures rendered text contrast. Each visible text
widget is grabbed; the dominant pixel colour is taken as its background and
the pixel with the highest WCAG contrast against it as the text colour. This
is a heuristic: it finds unreadable text (like light-on-light tabs) but is not
an accessibility certification, and offscreen styles may differ from a real
Windows desktop.
"""

from __future__ import annotations

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

TEXT_TYPES = ('QLabel', 'QPushButton', 'QCheckBox', 'QRadioButton', 'QComboBox', 'QLineEdit', 'QToolButton', 'QGroupBox')


def _luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(first, second):
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def image_contrast(image):
    """(background rgb, text rgb, ratio) of a rendered QImage, or None when blank."""
    width, height = image.width(), image.height()
    if width < 2 or height < 2:
        return None
    step = max(1, (width * height) // 20000)
    pixels = []
    for index in range(0, width * height, step):
        colour = image.pixelColor(index % width, index // width)
        pixels.append((colour.red(), colour.green(), colour.blue()))
    background = Counter(pixels).most_common(1)[0][0]
    best = max(set(pixels), key=lambda rgb: contrast(rgb, background))
    return background, best, contrast(best, background)


def _text(widget):
    for name in ('text', 'currentText', 'title', 'placeholderText'):
        getter = getattr(widget, name, None)
        if callable(getter):
            try:
                value = getter()
            except TypeError:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


def _composited(widget, page=None):
    """The widget area as painted inside its page (or window), including parent backgrounds.

    Page grabs render off-viewport content too, so scrolled-away widgets are measured.
    """
    from PySide6.QtCore import QPoint, QRect

    host = page if page is not None and page.isAncestorOf(widget) else widget.window()
    return host.grab(QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())).toImage()


def audit_widget(widget, page, rows, context, threshold):
    image = _composited(widget, page)
    measured = image_contrast(image)
    if measured is None:
        return
    background, text, ratio = measured
    if ratio < threshold:
        rows.append(
            {
                **context,
                'widget': type(widget).__name__,
                'name': widget.objectName(),
                'text': _text(widget)[:60],
                'enabled': widget.isEnabled(),
                'contrast': round(ratio, 2),
                'background': '#%02x%02x%02x' % background,
                'foreground': '#%02x%02x%02x' % text,
            }
        )


def audit_tabbar(tabbar, page, rows, context, threshold):
    image = _composited(tabbar, page)
    for index in range(tabbar.count()):
        rect = tabbar.tabRect(index)
        measured = image_contrast(image.copy(rect))
        if measured and measured[2] < threshold:
            rows.append(
                {
                    **context,
                    'widget': 'QTabBar tab',
                    'name': tabbar.objectName(),
                    'text': tabbar.tabText(index)[:60],
                    'enabled': tabbar.isTabEnabled(index),
                    'contrast': round(measured[2], 2),
                    'background': '#%02x%02x%02x' % measured[0],
                    'foreground': '#%02x%02x%02x' % measured[1],
                }
            )


def run(out, styles, themes, threshold=4.5, size=(1366, 768)):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QScrollArea, QTabWidget, QWidget

    import desktop_app.shell.theme
    from desktop_app.shell.window import MainWindow
    from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    if sys.platform == 'win32':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setFont(QFont('Microsoft JhengHei UI', 10))
    findings, summary = [], []
    for style in styles:
        if app.setStyle(style) is None:
            summary.append({'style': style, 'available': False})
            continue
        for theme in themes:
            with tempfile.TemporaryDirectory(prefix='markauto-readability-') as temporary:
                paths = AppPaths(Path(temporary) / 'workspace', Path(temporary) / 'bootstrap').ensure()
                jobs = JobManager(paths)
                window = MainWindow(
                    paths,
                    jobs,
                    SettingsStore(paths.state / 'settings.json'),
                    BackupManager(paths, jobs),
                    services=_c_create_ui_services(_c_create_operation_ports()),
                )
                try:
                    for timer in window.findChildren(QTimer):
                        timer.stop()
                    window.setProperty('appearanceTheme', theme)
                    desktop_app.shell.theme.apply_theme(window)
                    window.setFixedSize(*size)
                    window.show()
                    app.processEvents()
                    for index in range(window.stack.count()):
                        window.navigation.setCurrentRow(index)
                        app.processEvents()
                        container = window.stack.widget(index)
                        scroll = container if isinstance(container, QScrollArea) else window.market.page_scroll
                        page = scroll.widget()
                        page_name = window.navigation.item(index).text()
                        tab_widgets = [t for t in page.findChildren(QTabWidget) if t.isVisibleTo(page)]
                        variants = [(None, None)] + [(t, i) for t in tab_widgets for i in range(t.count())]
                        for tabs, tab_index in variants:
                            if tabs is not None:
                                tabs.setCurrentIndex(tab_index)
                                app.processEvents()
                            label = page_name if tabs is None else f'{page_name} / {tabs.tabText(tab_index)}'
                            stem = f'{style}_{theme}_{index + 1:02d}' + ('' if tabs is None else f'_{tabs.objectName() or "tabs"}_{tab_index + 1}')
                            window.grab().save(str(out / (stem + '.png')))
                            context = {'style': style, 'theme': theme, 'page': label}
                            before = len(findings)
                            for widget in page.findChildren(QWidget):
                                if not widget.isVisibleTo(page) or type(widget).__name__ not in TEXT_TYPES or not _text(widget):
                                    continue
                                if widget.width() < 4 or widget.height() < 4:
                                    continue
                                audit_widget(widget, page, findings, context, threshold)
                            for tabs_widget in tab_widgets:
                                audit_tabbar(tabs_widget.tabBar(), page, findings, context, threshold)
                            summary.append({**context, 'screenshot': stem + '.png', 'low_contrast': len(findings) - before})
                finally:
                    jobs.close()
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    # Duplicate rows for the same widget across tab variants are collapsed.
    unique = {json.dumps({k: v for k, v in row.items() if k != 'page'}, sort_keys=True, ensure_ascii=False): row for row in findings}
    report = {'threshold': threshold, 'summary': summary, 'findings': list(unique.values())}
    (out / 'readability.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('ui_readability'))
    parser.add_argument('--styles', default='Fusion,windowsvista', help='comma-separated Qt styles')
    parser.add_argument('--themes', default='dark,light')
    parser.add_argument('--threshold', type=float, default=4.5, help='WCAG contrast ratio below which text is reported')
    args = parser.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['QT_SCALE_FACTOR'] = '1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    report = run(args.out, args.styles.split(','), args.themes.split(','), args.threshold)
    print(json.dumps({'pages': len(report['summary']), 'low_contrast': len(report['findings'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
