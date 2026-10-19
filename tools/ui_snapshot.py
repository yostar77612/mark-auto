"""Capture all desktop pages in an empty, disposable workspace (no desktop startup).

See docs/analysis/baseline/ui_snapshot_1366x768/README.md for metric definitions.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import json


def parse_size(value):
    match = re.fullmatch(r'([1-9][0-9]*)x([1-9][0-9]*)', value)
    if match is None:
        raise argparse.ArgumentTypeError('size must be WxH with positive integer dimensions (e.g. 1366x768)')
    return tuple(map(int, match.groups()))


def parse_scale(value):
    try:
        scale = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('scale must be a finite positive number') from exc
    if not math.isfinite(scale) or scale <= 0:
        raise argparse.ArgumentTypeError('scale must be a finite positive number')
    return scale


def _input_widgets(page):
    from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QRadioButton, QTextEdit, QWidget

    kinds = (QAbstractSpinBox, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QRadioButton, QTextEdit)
    result = []
    for widget in page.findChildren(QWidget):
        if not isinstance(widget, kinds) or not widget.isVisibleTo(page):
            continue
        # Qt embeds line editors inside spin boxes/combos: count the control once.
        parent = widget.parentWidget()
        if isinstance(widget, QLineEdit) and isinstance(parent, (QAbstractSpinBox, QComboBox)):
            continue
        if hasattr(widget, 'isReadOnly') and widget.isReadOnly():
            continue
        result.append(widget)
    return result


def _has_label(widget, page):
    from PySide6.QtWidgets import QAbstractButton, QFormLayout, QLabel

    if widget.accessibleName().strip():
        return True
    if isinstance(widget, QAbstractButton) and widget.text().strip():
        return True
    if any(label.buddy() is widget and label.text().strip() for label in page.findChildren(QLabel) if label.isVisibleTo(page)):
        return True

    # Existing forms use QFormLayout, or a QLabel immediately before a field
    # in a box/grid layout. Do not mistake placeholder/value/tooltip for a label.
    def in_layout(layout):
        if isinstance(layout, QFormLayout):
            label = layout.labelForField(widget)
            if isinstance(label, QLabel) and label.text().strip() and label.isVisibleTo(page):
                return True
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.widget() is widget and index:
                previous = layout.itemAt(index - 1).widget()
                if isinstance(previous, QLabel) and previous.text().strip() and previous.isVisibleTo(page):
                    return True
            if item.layout() and in_layout(item.layout()):
                return True
        return False

    parent = widget.parentWidget()
    return bool(parent and parent.layout() and in_layout(parent.layout()))


def page_metrics(page):
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QTabBar, QTextEdit, QWidget

    widgets = [widget for widget in page.findChildren(QWidget) if widget.isVisibleTo(page)]
    inputs = _input_widgets(page)
    # Checkboxes and radio buttons are inputs; action/toggle buttons are buttons.
    buttons = [widget for widget in widgets if isinstance(widget, QAbstractButton) and widget not in inputs]
    text = []
    for widget in widgets:
        value = ''
        if isinstance(widget, (QLabel, QAbstractButton)):
            value = widget.text()
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            value = widget.toPlainText()
        elif isinstance(widget, QLineEdit):
            if widget.parentWidget() not in inputs:
                value = widget.displayText()
        elif isinstance(widget, QComboBox):
            value = widget.currentText()
        elif isinstance(widget, QAbstractSpinBox):
            value = widget.text()
        elif isinstance(widget, QGroupBox):
            value = widget.title()
        elif isinstance(widget, QTabBar):
            text.extend(widget.tabText(index) for index in range(widget.count()) if widget.isTabVisible(index) and widget.tabText(index).strip())
        if value.strip():
            text.append(value)
    from PySide6.QtWidgets import QTableWidget

    combo_items = [widget.itemText(index) for widget in widgets if isinstance(widget, QComboBox) for index in range(widget.count())]
    table_headers = [
        widget.horizontalHeaderItem(index).text()
        for widget in widgets
        if isinstance(widget, QTableWidget)
        for index in range(widget.columnCount())
        if widget.horizontalHeaderItem(index)
    ]
    return {
        'page_height': page.height(),
        'visible_input_count': len(inputs),
        'button_count': len(buttons),
        'label_char_count': sum(len(widget.text()) for widget in widgets if isinstance(widget, QLabel)),
        'visible_text': text,
        'combo_items': combo_items,
        'table_headers': table_headers,
        'unlabeled_inputs': [widget.objectName() or f'{type(widget).__name__}[{index}]' for index, widget in enumerate(inputs) if not _has_label(widget, page)],
        'disabled_buttons': [
            {'object_name': widget.objectName(), 'text': widget.text(), 'tooltip': widget.toolTip(), 'hint': widget.property('disabled_hint') or ''}
            for widget in buttons
            if not widget.isEnabled()
        ],
        'primary_button_count': sum(widget.property('role') == 'primary' for widget in buttons),
    }


def _save_png(widget, path, scale):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    image = QImage(round(widget.width() * scale), round(widget.height() * scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.scale(scale, scale)
        widget.render(painter, QPoint())
    finally:
        painter.end()
    if not image.save(str(path), 'PNG'):
        raise OSError(f'Could not save snapshot: {path}')


def tab_heights(page, app):
    """Measure every tab at its real viewport width, restoring selection afterward.

    Scroll tabs report natural content height, not the clipped viewport height.
    Existing top-level metrics continue to describe the selected/default tab.
    """
    from PySide6.QtWidgets import QScrollArea, QTabWidget

    result = {}
    for tabs in page.findChildren(QTabWidget):
        if not tabs.isVisibleTo(page):
            continue
        selected = tabs.currentIndex()
        try:
            for index in range(tabs.count()):
                tabs.setCurrentIndex(index)
                app.processEvents()
                widget = tabs.widget(index)
                if isinstance(widget, QScrollArea):
                    width = widget.viewport().width()
                    content = widget.widget()
                else:
                    width, content = widget.width(), widget
                if content is None:
                    continue
                layout = content.layout()
                if layout:
                    layout.activate()
                height = max(content.minimumHeight(), content.sizeHint().height(), content.minimumSizeHint().height())
                if layout and layout.hasHeightForWidth():
                    height = max(height, layout.heightForWidth(width))
                result[tabs.tabText(index)] = height
        finally:
            tabs.setCurrentIndex(selected)
            app.processEvents()
    return result


def capture(out, size=(1366, 768), scale=1.0, images=True, *, window=None):
    """Return logical metrics; all application state lives below TemporaryDirectory."""
    if window is not None:
        if images:
            raise ValueError('A supplied window supports metrics only')
        return capture_layout_metrics(window, out, size, scale)
    from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QScrollArea
    from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore
    from desktop_ui import MainWindow

    out = Path(out)
    app = QApplication.instance() or QApplication([])
    # Dispose closed windows from earlier callers before changing application
    # style; their deferred children and layout filters must not be repolished.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # Load the Windows CJK face directly: offscreen font discovery can list a
    # system family without making its glyph data available to the rasterizer.
    font_ids = []
    if sys.platform == 'win32':
        for name in ('msjh.ttc', 'msjhbd.ttc'):
            font_id = QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
            if font_id >= 0:
                font_ids.append(font_id)
    old_font, old_locale = app.font(), QLocale()
    old_style = app.style().objectName()
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft JhengHei UI', 10))
    QLocale.setDefault(QLocale('zh_TW'))
    result = {'schema_version': 1, 'size': list(size), 'scale': scale, 'pages': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='markauto-ui-snapshot-') as temporary:
            paths = AppPaths(Path(temporary) / 'workspace').ensure()
            jobs = JobManager(paths)
            window = None
            try:
                window = MainWindow(paths, jobs, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, jobs))
                # Stop polling before dispatching Qt events: snapshots never run jobs.
                for timer in window.findChildren(QTimer):
                    timer.stop()
                # Normalize only displayed paths; actual AppPaths remain disposable.
                for widget in window.findChildren(QLabel) + window.findChildren(QLineEdit):
                    widget.setText(widget.text().replace(str(paths.root), '<temporary workspace>'))
                window.setFixedSize(*size)
                window.show()
                app.processEvents()
                out.mkdir(parents=True, exist_ok=True)
                for index in range(window.stack.count()):
                    window.navigation.setCurrentRow(index)
                    app.processEvents()
                    container = window.stack.widget(index)
                    scroll = container if isinstance(container, QScrollArea) else window.market.page_scroll
                    scroll.verticalScrollBar().setValue(0)
                    scroll.horizontalScrollBar().setValue(0)
                    page = scroll.widget()
                    subpages = tab_heights(page, app)
                    stem = f'{index + 1:02d}'
                    if images:
                        _save_png(window, out / f'{stem}_viewport.png', scale)
                    # Render the actual scroll content at its natural height, even
                    # when it extends well beyond the screen. Never grab viewport().
                    width = scroll.viewport().width()
                    # The market page contains another scrolling panel. Expand
                    # nested content too, otherwise its indicators remain clipped
                    # even in a tall image of the outer content widget.
                    nested = []
                    for child in reversed(page.findChildren(QScrollArea)):
                        if child.isVisibleTo(page) and child.widget() is not None:
                            nested.append((child, child.minimumHeight()))
                            content = child.widget()
                            needed = max(content.sizeHint().height(), content.minimumSizeHint().height())
                            if content.layout() and content.layout().hasHeightForWidth():
                                needed = max(needed, content.layout().heightForWidth(child.viewport().width()))
                            child.setMinimumHeight(
                                max(child.minimumHeight(), needed + 2 * child.frameWidth() + child.horizontalScrollBar().sizeHint().height())
                            )
                    page.layout().activate()
                    app.processEvents()
                    scroll.setWidgetResizable(False)
                    height = max(page.sizeHint().height(), page.minimumSizeHint().height())
                    if page.layout().hasHeightForWidth():
                        height = max(height, page.layout().heightForWidth(width))
                    page.resize(width, height)
                    page.layout().activate()
                    app.processEvents()
                    if images:
                        _save_png(page, out / f'{stem}_full.png', scale)
                    metrics = page_metrics(page)
                    if subpages:
                        metrics['subpages'] = subpages
                    wizard = window.strategy_page.wf_wizard if scroll.widget() is window.strategy_page else None
                    if wizard is not None:
                        # Inspect natural layouts without bypassing navigation guards
                        # or launching preview/run operations during a snapshot.
                        metrics['wizard_steps'] = {
                            str(step + 1): max(wizard.stack.widget(step).sizeHint().height(), wizard.stack.widget(step).minimumSizeHint().height())
                            for step in range(wizard.stack.count())
                        }
                    metrics.update(viewport_png=f'{stem}_viewport.png', full_png=f'{stem}_full.png', full_width=page.width())
                    result['pages'][window.navigation.item(index).text()] = metrics
                    for child, minimum in nested:
                        child.setMinimumHeight(minimum)
                    scroll.setWidgetResizable(True)
                (out / 'metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            finally:
                jobs.close()
                if window is not None:
                    try:
                        if not window.close():
                            raise RuntimeError('Snapshot window refused to close')
                    finally:
                        window.deleteLater()
                        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    finally:
        app.setFont(old_font)
        app.setStyle(old_style)
        QLocale.setDefault(old_locale)
        for font_id in font_ids:
            QFontDatabase.removeApplicationFont(font_id)
    return result


def capture_layout_metrics(window, out, size, scale):
    """Cheap viewport metrics for an existing disposable test window.

    Does not change app font/style, expand content, render pixels or own the window.
    The caller restores its font when probing larger logical font sizes.
    """
    from PySide6.QtWidgets import QApplication, QScrollArea

    old_row, old_size = window.navigation.currentRow(), window.size()
    result = {'schema_version': 1, 'size': list(size), 'scale': parse_scale(scale), 'pages': {}}
    try:
        window.resize(*size)
        for index in range(window.stack.count()):
            window.navigation.setCurrentRow(index)
            for _ in range(3):
                QApplication.processEvents()
            container = window.stack.widget(index)
            scroll = container if isinstance(container, QScrollArea) else window.market.page_scroll
            result['pages'][window.navigation.item(index).text()] = page_metrics(scroll.widget())
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    finally:
        window.navigation.setCurrentRow(old_row)
        window.resize(old_size)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=parse_size, default=(1366, 768), metavar='WxH', help='logical viewport size WxH (default: 1366x768)')
    parser.add_argument('--scale', type=parse_scale, default=1.0, help='PNG pixel scale; logical metrics stay unchanged (default: 1)')
    parser.add_argument('--out', type=Path, default=Path('ui_snapshot'), help='output directory for 14 PNGs and metrics.json (default: ui_snapshot)')
    args = parser.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    # Raster scale is explicit, independent of the host monitor or Qt DPI env.
    os.environ['QT_SCALE_FACTOR'] = '1'
    os.environ['QT_SCREEN_SCALE_FACTORS'] = '1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    capture(args.out, args.size, args.scale)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
