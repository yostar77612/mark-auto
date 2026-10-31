"""Reference-only market settings; emits intents without SDK or credential IO."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit

from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.widgets import button
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


class MarketDataPanel(QGroupBox):
    save_requested = Signal(object)
    connect_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(ui_text('marketdata.title'), parent)
        self.setObjectName('market_data_panel')
        self.setAccessibleName(ui_text('marketdata.title'))
        self.dirty = False
        self._loading = False
        form = QFormLayout(self)
        self.environment = QComboBox()
        self.environment.setObjectName('market_data_environment')
        self.environment.setAccessibleName(ui_text('marketdata.environment'))
        self.environment.addItem(ui_text('v2.broker_sim'), Environment.BROKER_SIMULATION)
        self.environment.addItem(ui_text('v2.live'), Environment.LIVE)
        self.environment.currentIndexChanged.connect(self._edited)
        form.addRow(ui_text('marketdata.environment'), self.environment)
        self.secret_ref = QLineEdit('MarkAuto/v2/broker/sinopac')
        self.secret_ref.setObjectName('market_data_secret_ref')
        self.secret_ref.setAccessibleName(ui_text('marketdata.secret_ref'))
        self.secret_ref.setMaxLength(120)
        self.secret_ref.textEdited.connect(self._edited)
        form.addRow(ui_text('marketdata.secret_ref'), self.secret_ref)
        self.status = QLabel(ui_text('watch.disconnected'))
        self.status.setObjectName('market_data_status')
        self.status.setAccessibleName(ui_text('marketdata.title'))
        form.addRow(self.status)
        save = button('marketdata.save', 'market_data_save')
        connect = button('marketdata.test', 'market_data_connect')
        disconnect = button('marketdata.disconnect', 'market_data_disconnect')
        save.clicked.connect(self._save)
        connect.clicked.connect(self._connect)
        disconnect.clicked.connect(self.disconnect_requested)
        form.addRow(save, connect)
        form.addRow(disconnect)

    def _edited(self):
        if not self._loading:
            self.dirty = True

    def _save(self):
        try:
            settings = MarketDataSettings(self.environment.currentData(), self.secret_ref.text().strip(), True)
        except DomainError:
            self.status.setText(ui_text('marketdata.invalid'))
            return
        self.save_requested.emit(settings)
        self.dirty = False

    def _connect(self):
        if self.dirty:
            self.status.setText(ui_text('marketdata.save_first'))
            return
        self.connect_requested.emit()

    def apply(self, settings: MarketDataSettings, connection: str):
        if not self.dirty:
            self._loading = True
            self.environment.setCurrentIndex(self.environment.findData(settings.environment))
            self.secret_ref.setText(settings.secret_ref)
            self._loading = False
        key = {'CONNECTED': 'watch.connected', 'CONNECTING': 'watch.connecting', 'DISCONNECTED': 'watch.disconnected'}
        self.status.setText(ui_text(key.get(connection, 'watch.unknown')))
