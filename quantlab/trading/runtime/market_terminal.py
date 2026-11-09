"""Compose independent watch history and subscriptions without an execution capability."""

from quantlab.trading.adapters.storage.kline_store import KlineStore
from .market_terminal_settings import MarketTerminalSettings
from quantlab.trading.application.history_sync import HistorySync
from quantlab.trading.application.market_terminal_service import MarketTerminalService
from quantlab.trading.domain.validation import DomainError


class SessionBridge:
    """Resolve the explicitly connected generation, never construct or log in to it."""

    def __init__(self, connection):
        self.connection = connection

    @property
    def connected(self):
        session = self.connection.session
        return session is not None and session.connected

    def _session(self):
        session = self.connection.session
        if session is None:
            raise DomainError('market_data_not_connected')
        return session

    def history(self, instrument, start, end):
        return self._session().history(instrument, start, end)

    def usage(self):
        return self._session().usage() if self.connected else None

    def subscribe(self, instrument):
        self._session().subscribe(instrument)

    def unsubscribe(self, instrument_id):
        self._session().unsubscribe(instrument_id)

    def drain_ticks(self, limit):
        return self._session().drain_ticks(limit)

    def drain_tick_losses(self):
        return self._session().drain_tick_losses()

    def subscribe_bidask(self, instrument):
        self._session().subscribe_bidask(instrument)

    def unsubscribe_bidask(self, instrument_id):
        self._session().unsubscribe_bidask(instrument_id)

    def bidask(self, instrument_id):
        return self._session().bidask(instrument_id) if self.connected else None

    def quote_details(self, instrument_id):
        if not self.connected:
            return {}
        details = self._session().quote_details(instrument_id)
        details['source'] = 'SHIOAJI_SIMULATION' if self.connection.settings.environment.value == 'BROKER_SIMULATION' else 'SHIOAJI_LIVE'
        return details


def attach_terminal(bundle):
    connection = bundle.market_connection
    preferences = MarketTerminalSettings(bundle.launch.root / 'settings.json', lock=connection.settings_lock)
    store = KlineStore(bundle.launch.root / 'market' / 'klines.sqlite3')
    history = HistorySync(store, SessionBridge(connection))
    service = MarketTerminalService(
        store,
        history,
        SessionBridge(connection),
        lambda: connection.directory.items,
        watchlist=preferences.watchlist,
        selected=preferences.selected,
        save_watchlist=preferences.save_watchlist,
        save_selected=preferences.save_selected,
        warning_code=lambda: connection.error or store.warning_code,
    )
    service.active = connection.settings.enabled
    connection.on_connected = lambda session: service.connected()
    connection.on_disconnected = service.disconnected
    bundle.market_terminal, bundle.kline_store, bundle.market_history = service, store, history
    from .market_alerts import attach_alerts

    attach_alerts(bundle)

    from .sector_board import attach_sector

    attach_sector(bundle)
