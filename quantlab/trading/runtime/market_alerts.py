"""Compose local alerts with the market session, tick stream and durable history."""

from datetime import datetime, timedelta
from threading import RLock

from quantlab.trading.adapters.shioaji.scanner_stream import ShioajiScannerStream
from quantlab.trading.adapters.storage.alert_store import JsonAlertStore
from quantlab.trading.application.alert_contracts import AlertCommand, AlertSnapshot
from quantlab.trading.application.alert_observer import AlertTickObserver
from quantlab.trading.application.alert_service import AlertService
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.ticks import Tick


class RuntimeAlerts:
    """Serialize alert mutations without acquiring the runtime's composition lock.

    Market callbacks already hold the market lock. This distinct lock prevents
    inversion with runtime snapshots, while SDK callbacks only enqueue events.
    Persistence and indicators belong to their existing adapter/application owners.
    """

    def __init__(self, bundle):
        self.market = bundle.market_terminal
        self.connection = bundle.market_connection
        self.lock = RLock()
        self.service = AlertService(JsonAlertStore(bundle.launch.root), now=self.market.now())
        self.service.watchlist = self.market.watchlist
        self.observer = AlertTickObserver(self.service, self._facts, self._history, self._backfilling)
        self._scanner: ShioajiScannerStream | None = None

    def _facts(self, instrument_id):
        return next(view for view in self.market.views() if view.instrument_id == instrument_id)

    def _history(self, instrument_id):
        now = self.market.now()
        return self.market.store.read(instrument_id, now - timedelta(days=self.market.history.settings.daily_lookback_days), now)

    def _backfilling(self, instrument_id):
        return self.market.history.is_backfilling(instrument_id)

    def execute(self, command: AlertCommand) -> AlertSnapshot:
        with self.lock:
            return self.service.execute(command)

    def poll_scanner(self):
        with self.lock:
            return self.service.poll_scanner()

    def save_watchlist(self, save, requested):
        save(requested)
        with self.lock:
            self.service.watchlist = requested

    def on_tick(self, tick: Tick, bars: tuple[LiveBar, ...]):
        with self.lock:
            if self._backfilling(tick.instrument_id):
                return ()
            return self.observer.on_tick(tick, bars)

    def history_completed(self, instrument_id: str):
        with self.lock:
            self.observer.reset(instrument_id)

    def on_bars(self, instrument_id: str, bars: tuple[LiveBar, ...], now: datetime, trade_date):
        with self.lock:
            if not self.market.session.connected or self._backfilling(instrument_id):
                return ()
            # Session-end final bars remain eligible after the clock closes.
            if self._facts(instrument_id).health.freshness not in ('LIVE', 'CLOSED'):
                return ()
            return self.observer.on_bars(instrument_id, bars, now, trade_date)

    def connected(self, session):
        with self.lock:
            self._detach_scanner()
            try:
                self._scanner = ShioajiScannerStream(session.facade, session.sdk_module)
            except (session.sdk_module.ShioajiError, OSError):
                from quantlab.trading.domain.validation import DomainError

                raise DomainError('market_data_not_connected', 'scanner callback registration') from None
            self.service.set_scanner(self._scanner)
            self.service.watchlist = self.market.watchlist

    def _detach_scanner(self):
        from quantlab.trading.domain.validation import DomainError

        scanner, self._scanner = self._scanner, None
        try:
            if scanner is not None:
                scanner.close()
        except DomainError:
            # Logout follows this callback and releases any rejected unsubscribe.
            self.service.warning = 'alert.scanner_gap'
        finally:
            self.service.scanner = None

    def disconnected(self):
        with self.lock:
            self._detach_scanner()
            self.observer = AlertTickObserver(self.service, self._facts, self._history, self._backfilling)


def attach_alerts(bundle):
    alerts = RuntimeAlerts(bundle)
    market, connection = bundle.market_terminal, bundle.market_connection
    old_tick, old_bars = market.on_tick, market.on_bars
    old_connected, old_disconnected = connection.on_connected, connection.on_disconnected
    old_save = market.save_watchlist
    old_complete = market.history.on_complete

    def on_tick(tick, bars):
        old_tick(tick, bars)
        alerts.on_tick(tick, bars)

    def on_bars(instrument_id, bars, now, trade_date):
        old_bars(instrument_id, bars, now, trade_date)
        alerts.on_bars(instrument_id, bars, now, trade_date)

    def connected(session):
        old_connected(session)
        alerts.connected(session)

    def disconnected():
        alerts.disconnected()
        old_disconnected()

    def history_completed(instrument_id):
        old_complete(instrument_id)
        alerts.history_completed(instrument_id)

    market.on_tick, market.on_bars = on_tick, on_bars
    market.save_watchlist = lambda requested: alerts.save_watchlist(old_save, requested)
    connection.on_connected, connection.on_disconnected = connected, disconnected
    market.history.on_complete = history_completed
    bundle.alerts = alerts
