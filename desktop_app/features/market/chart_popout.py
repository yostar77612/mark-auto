"""One display-only chart follower; no provider, polling or trading capabilities."""

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton
from desktop_app.components.charts import CandlestickChart
from desktop_app.strings.catalog import ui_text
from quantlab.desktop_errors import error_message


def save_position(window, store, market=None):
    """Merge frame coordinates into the existing atomic settings store."""
    value = store.load()
    value['market_popout'] = {'x': window.x(), 'y': window.y(), 'width': window.width(), 'height': window.height()}
    if market is not None:
        value['market'] = market
    store.save(value)


def restore_position(window, saved, screens, fallback):
    """Accept secondary-monitor coordinates; reject coercion and invalid scalars."""
    saved = saved if isinstance(saved, dict) else {}
    rects = [screen.availableGeometry() for screen in screens]
    default = fallback.availableGeometry() if fallback is not None else (rects[0] if rects else QRect(0, 0, 1280, 720))
    x, y = saved.get('x'), saved.get('y')
    valid = type(x) is int and type(y) is int and abs(x) < 2**30 and abs(y) < 2**30
    area = next((r for r in rects if valid and r.contains(x, y)), default)
    width, height = saved.get('width', 900), saved.get('height', 650)
    width = width if type(width) is int else 900
    height = height if type(height) is int else 650
    width = min(area.width(), max(360, width))
    height = min(area.height(), max(280, height))
    x = x if valid else area.x() + 30
    y = y if valid else area.y() + 30
    window.resize(width, height)
    window.move(max(area.x(), min(x, area.right() - width + 1)), max(area.y(), min(y, area.bottom() - height + 1)))


class ChartPopout(QDialog):
    def __init__(self, controller):
        super().__init__(controller.dashboard.window(), Qt.WindowType.Window)
        self.controller = controller
        self.closed = False
        self.setObjectName('market_chart_popout')
        self.setWindowTitle(ui_text('popout.title'))
        self.setAccessibleName(ui_text('popout.title'))
        self.setMinimumSize(360, 280)
        layout = QVBoxLayout(self)
        self.safety = QLabel(ui_text('market.init.research_paper'))
        self.safety.setWordWrap(True)
        layout.addWidget(self.safety)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.chart = CandlestickChart()
        self.chart.setObjectName('market_popout_candles')
        layout.addWidget(self.chart)
        button = QPushButton(ui_text('popout.close'))
        button.setObjectName('market_popout_close')
        button.setAccessibleName(ui_text('popout.close'))
        button.setToolTip(ui_text('popout.close'))
        button.clicked.connect(self.close)
        layout.addWidget(button)
        QShortcut(QKeySequence('Escape'), self, activated=self.close)
        self.sync()

    @property
    def series_store(self):
        return self.controller.dashboard._series

    def sync(self, *args):
        if self.closed:
            return
        dashboard = self.controller.dashboard
        source, target = dashboard.chart, self.chart
        # All sequences/mappings are validated by the authoritative main setters.
        # Immutable bars, overlays and annotation records are shared by identity.
        for field in (
            'bars',
            'trace',
            'overlays',
            'panes',
            'pane_styles',
            'markers',
            'reference_lines',
            'drawings',
            'source_label',
            'status_label',
            'error',
            'timeframe',
            '_marker_index',
            '_unavailable_overlays',
            '_unavailable_panes',
        ):
            if hasattr(source, field):
                setattr(target, field, getattr(source, field))
        target.layer_visibility = dict(source.layer_visibility)
        # Snapshot projection only: never forward the main chart's order callback.
        target.paper_orders.snapshot = source.paper_orders.snapshot
        target.paper_orders.mode = source.paper_orders.mode
        target.paper_orders.tick = source.paper_orders.tick
        target._start, target._count = source._start, source._count
        self.status.setText(' · '.join((source.source_label, source.status_label, dashboard.source_status.text(), dashboard.message.text())))
        self.status.setToolTip(dashboard.message.toolTip())
        target.update()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if not self.closed:
            controller = self.controller
            if self.isVisible() and not self.isMinimized():
                controller.save(self)
            self.closed = True
            controller.detach(self)
            self.controller = None
            self.setParent(None)
        event.accept()


class PopoutController:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.window = None
        self.destroying = False
        menu = dashboard.workspace.panels['chart'].handle.menu()
        self.action = menu.addAction(ui_text('popout.open'))
        self.action.setObjectName('market_popout_action')
        self.action.setToolTip(ui_text('popout.hint'))
        self.action.triggered.connect(self.open)
        dashboard.destroyed.connect(self.owner_destroyed)

    def store(self):
        return getattr(getattr(self.dashboard, 'state', None), 'settings', None)

    def open(self, checked=False, *, visible=True):
        if self.window is None:
            window = ChartPopout(self)
            self.window = window
            store = self.store()
            try:
                saved = store.load().get('market_popout', {}) if store is not None else {}
                host = getattr(self.dashboard, 'host', None)
                screen = getattr(host, 'window_screen', lambda: self.dashboard.screen())()
                restore_position(window, saved, QApplication.screens(), screen)
            except (OSError, ValueError, RuntimeError, TypeError):
                self.dashboard.message.setText(error_message('operation_failed_local'))
            self.dashboard.chart.display_changed.connect(window.sync)
            self.dashboard.chart.view_changed.connect(window.sync)
            window.chart.view_changed.connect(self.follow_view)
            self.dashboard.series_rendered.connect(window.sync)
        window = self.window
        if visible:
            window.showNormal()
            window.raise_()
            window.activateWindow()
        return window

    def save(self, window):
        store = self.store()
        if store is not None:
            try:
                save_position(window, store, self.dashboard.preferences())
            except (OSError, ValueError, RuntimeError, TypeError):
                self.dashboard.message.setText(error_message('operation_failed_local'))

    def detach(self, window):
        self.dashboard.chart.display_changed.disconnect(window.sync)
        self.dashboard.chart.view_changed.disconnect(window.sync)
        window.chart.view_changed.disconnect(self.follow_view)
        if not self.destroying:
            self.dashboard.series_rendered.disconnect(window.sync)
        self.window = None

    def follow_view(self):
        if self.window is not None:
            source, target = self.window.chart, self.dashboard.chart
            target._start, target._count = source._start, source._count
            target.update()

    def close(self):
        if self.window is not None:
            self.window.close()

    def owner_destroyed(self, *args):
        # QObject destroys children after emitting destroyed; disconnect first.
        self.destroying = True
        self.close()
