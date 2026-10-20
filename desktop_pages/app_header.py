"""Compact, read-only application context; existing adapters own preferences."""

from datetime import datetime, timezone

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from desktop_privacy import PrivacyState, enabled
from desktop_strings import ui_text
from desktop_theme import load_appearance


# Set by tools/ui_snapshot.py so raster snapshots do not depend on the wall clock.
CLOCK_OVERRIDE = None


class _CloseWatcher(QObject):
    """Owned by the watched window (never by the header) so teardown order cannot leave a dangling filter."""

    def __init__(self, window, on_close):
        super().__init__(window)
        self._on_close = on_close
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close:
            try:
                self._on_close()
            except RuntimeError:  # the header was already destroyed
                pass
        return False


class AppHeader(QWidget):
    def __init__(self, host, *, clock=None, quote_age_seconds=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.clock = clock or CLOCK_OVERRIDE or (lambda: datetime.now(timezone.utc))
        self.quote_age_seconds = quote_age_seconds
        self.setObjectName('app_header')
        self.setMaximumHeight(48)
        self.setMinimumWidth(1)  # let narrow windows shrink the strip instead of forcing a wider window
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.badge = QLabel(ui_text('header.live_disabled'))
        self.badge.setObjectName('header_live_disabled')
        self.badge.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.badge.setToolTip(ui_text('ui.__init__.text_4'))
        self.source = QLabel()
        self.source.setObjectName('header_data_source')
        self.job = QLabel()
        self.job.setObjectName('header_job_state')
        self.time = QLabel()
        self.time.setObjectName('header_clock')
        self.disclosure = QCheckBox(ui_text('header.help'))
        self.disclosure.setObjectName('research_mode_status')
        self.disclosure.setAccessibleName(ui_text('ui.__init__.text_3'))
        self.disclosure.setToolTip(ui_text('ui.__init__.text_4'))
        self.explanation = QLabel(ui_text('ui.__init__.text_4'))
        self.explanation.setObjectName('research_mode_explanation')
        self.explanation.setWordWrap(True)
        self.explanation.hide()
        self.disclosure.toggled.connect(self.explanation.setVisible)
        if isinstance(host, QWidget):
            host.privacy = PrivacyState(host, row, self.badge, compact=True)
            self.privacy_toggle = host.privacy.toggle
        else:
            row.addWidget(self.badge)
            self.privacy_toggle = QCheckBox(ui_text('privacy.toggle'))
            self.privacy_toggle.setObjectName('privacy_toggle')
            row.addWidget(self.privacy_toggle)
            self.privacy_toggle.setEnabled(getattr(host, 'privacy', None) is not None)
            self.privacy_toggle.toggled.connect(self._privacy_changed)
        self.privacy_toggle.setAccessibleName(ui_text('privacy.toggle'))
        for label in (self.source, self.job, self.time):
            row.addWidget(label)
        row.addWidget(self.disclosure)
        self.theme = QComboBox()
        self.theme.setAccessibleName(ui_text('appearance.theme'))
        self.theme.addItem(ui_text('appearance.dark'), 'dark')
        self.theme.addItem(ui_text('appearance.light'), 'light')
        self.theme.setCurrentIndex(self.theme.findData(load_appearance(getattr(host, 'settings', None))[0]))
        self.theme.setEnabled(False)
        row.addWidget(self.theme)
        row.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        if isinstance(host, QWidget):
            self._close_watcher = _CloseWatcher(host, self.timer.stop)
        self.refresh()

    def _tick(self):
        # Hidden strips (and windows that were never shown) have nothing to repaint.
        if self.isVisible():
            self.refresh()

    def _privacy_changed(self, value):
        state = getattr(self.host, 'privacy', None)
        if state is not None:
            state.set_enabled(value)

    def bind_controls(self):
        """Move the actual B4 theme control, retaining its store and callback."""
        combo = self.host.findChild(QComboBox, 'appearance_theme')
        if combo is not None:
            self.layout().removeWidget(self.theme)
            self.theme.hide()
            self.theme.deleteLater()
            self.theme = combo
            combo.setParent(self)
            self.layout().insertWidget(self.layout().count() - 1, combo)
            combo.show()
        QWidget.setTabOrder(self.privacy_toggle, self.disclosure)
        QWidget.setTabOrder(self.disclosure, self.theme)

    def refresh(self):
        for label in self.findChildren(QLabel):
            label.setWordWrap(False)
        now = self.clock()
        self.time.setText(ui_text('header.clock').format(now.strftime('%H:%M:%S')))
        market = getattr(self.host, 'market', None)
        quotes = getattr(market, '_quote_series', None)
        series = quotes if quotes is not None else getattr(market, '_series', {})
        selected = getattr(market, '_selected', '')
        item = series.get(selected) or next(iter(series.values()), None) if series else None
        provenance = getattr(item, 'provenance', None)
        if provenance is None:
            self.source.setText(ui_text('header.dataset') if getattr(self.host, '_dataset_ready', False) else ui_text('header.no_data'))
        else:
            stamp = getattr(provenance, 'received_at', None)
            stale = getattr(market, '_quote_stale' if quotes is not None else '_stale', True)
            if stamp is None or stamp.tzinfo is None or self.quote_age_seconds is None:
                stale = True
            else:
                age = (now - stamp).total_seconds()
                stale = stale or age < 0 or age > self.quote_age_seconds
            marker = ui_text('header.stale') if stale else ui_text('header.snapshot')
            exchange = getattr(getattr(item, 'instrument', None), 'exchange', '')
            self.source.setText(ui_text('header.source').format(exchange, getattr(provenance, 'as_of', ''), marker))
            self.source.setToolTip(ui_text('header.provenance').format(getattr(provenance, 'attribution', ''), stamp))
        feedback = getattr(self.host, 'job_feedback', None)
        progress = getattr(self.host, 'job_progress', None)
        if getattr(progress, 'running', False):
            text = ui_text('header.running')
        elif getattr(feedback, 'terminal', False):
            notice = getattr(self.host, 'notification', None)
            failed = notice is not None and notice.property('status') == 'danger'
            text = ui_text('header.failed') if failed else ui_text('header.done')
        else:
            text = ui_text('header.idle')
        self.job.setText(text)
        private = enabled(self) if isinstance(self.host, QWidget) else getattr(getattr(self.host, 'privacy', None), 'enabled', False)
        self.privacy_toggle.blockSignals(True)
        self.privacy_toggle.setChecked(private)
        self.privacy_toggle.blockSignals(False)
        self.theme.setToolTip(ui_text('appearance.theme'))

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


def install_header(shell, layout, quote_age_seconds):
    shell.app_header = AppHeader(shell, quote_age_seconds=quote_age_seconds)
    layout.addWidget(shell.app_header)
    layout.addWidget(shell.app_header.explanation)
