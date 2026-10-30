"""desktop_app components chart_interaction responsibilities."""

from PySide6.QtCore import Qt


class ChartInteraction:
    """Viewport interactions; the Qt view retains data and painting."""

    def __init__(self, view):
        self.view = view

    def _pan(self, bars):
        self.view._start = max(0, min(max(0, len(self.view.bars) - self.view._count), self.view._start + bars))
        self.view.view_changed.emit()
        self.view.update()

    def _zoom(self, factor, anchor=0.5):
        old = self.view._count
        new = max(10, min(self.view.MAX_VISIBLE, len(self.view.bars) or 10, round(old * factor)))
        self.view._start = max(0, min(max(0, len(self.view.bars) - new), round(self.view._start + (old - new) * anchor)))
        self.view._count = new
        self.view.view_changed.emit()
        self.view.update()

    def wheelEvent(self, event):
        r = self.view.price_rect
        anchor = max(0, min(1, (event.position().x() - r.left()) / r.width()))
        self._zoom(0.8 if event.angleDelta().y() > 0 else 1.25, anchor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.view.setFocus()
            if self.view.paper_orders.press(event.position(), self.view.price_rect):
                event.accept()
                return
            self.view._drag = (event.position().x(), self.view._start)
            event.accept()

    def mouseMoveEvent(self, event):
        r = self.view.price_rect
        start, end = self.view.visible_range
        if self.view._drag is not None:
            x, origin = self.view._drag
            self.view._start = max(
                0, min(max(0, len(self.view.bars) - self.view._count), origin - round((event.position().x() - x) / r.width() * max(1, end - start)))
            )
            self.view.view_changed.emit()
        if self.view.bars and r.contains(event.position()):
            self.view.crosshair_index = min(end - 1, max(start, start + int((event.position().x() - r.left()) / r.width() * max(1, end - start))))
            self.view.crosshair_changed.emit(self.view.bar_details(self.view.crosshair_index))
        else:
            self.view.crosshair_index = None
        self.view.update()

    def leaveEvent(self, event):
        self.view.crosshair_index = None
        self.view.crosshair_changed.emit(None)
        self.view.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.view.paper_orders.drag = None
            self.view._drag = None
        elif key == Qt.Key.Key_Left:
            self._pan(-max(1, self.view._count // 10))
        elif key == Qt.Key.Key_Right:
            self._pan(max(1, self.view._count // 10))
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom(0.8)
        elif key == Qt.Key.Key_Minus:
            self._zoom(1.25)
        elif key == Qt.Key.Key_Home:
            self.view.reset_view()
        else:
            return False
        return True
