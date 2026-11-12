"""Compose the read-only sector board with the market connection and a background snapshot poller."""

import logging
from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic

from quantlab.trading.adapters.shioaji.snapshot_poller import ShioajiSnapshotSource
from quantlab.trading.adapters.storage.sector_store import SectorGroupStore
from quantlab.trading.adapters.storage.sector_minute_store import SectorMinuteStore
from quantlab.trading.application.sector_group_editor import SectorGroupEditor
from quantlab.trading.application.sector_minutes import MinuteAggregator, sector_history
from quantlab.trading.application.sector_monitor import SectorMonitor
from quantlab.trading.application.sector_service import SectorService
from quantlab.trading.domain.validation import DomainError
from .sector_settings import SectorAlertSettings


logger = logging.getLogger(__name__)


class NullMinuteStore:
    """Stand-in when the minute database cannot be opened; nothing is persisted."""

    def append(self, stats, trade_date):
        return None

    def load_day(self, trade_date):
        return ()

    def purge(self, today):
        return 0

    def alert_marks(self, trade_date, kind):
        return {}

    def share_baseline(self, before, minute, days=5):
        return {}

    def trade_days(self):
        return ()

    def day_minutes(self, trade_date):
        return ()

    def load_minute(self, trade_date, minute):
        return ()

    def mark_alert(self, trade_date, kind, group_id, direction, minute):
        return None

    def close(self):
        return None


class SnapshotBridge:
    """Resolve the connected session per call; never construct or log in to one."""

    def __init__(self, connection):
        self.connection = connection
        self._session = None
        self._source = None

    @property
    def connected(self):
        session = self.connection.session
        return session is not None and session.connected

    def snapshots(self, instruments):
        session = self.connection.session
        if session is None or not session.connected:
            raise DomainError('market_data_not_connected')
        if session is not self._session:
            self._session, self._source = session, ShioajiSnapshotSource(session)
        return self._source.snapshots(instruments)


class MonitorSubscriptions:
    """Tick subscriptions on the connected session for the sector monitor."""

    def __init__(self, connection):
        self.connection = connection

    def _session(self):
        session = self.connection.session
        if session is None or not session.connected:
            raise DomainError('market_data_not_connected')
        return session

    def free_slots(self):
        return max(0, self._session().free_slots())

    def is_subscribed(self, instrument_id):
        return instrument_id in self._session().subscriptions

    def subscribe(self, instrument):
        self._session().subscribe(instrument)

    def unsubscribe(self, instrument_id):
        self._session().unsubscribe(instrument_id)


class SectorPoller:
    """One round at a time: a slow round delays the next one instead of overlapping it."""

    def __init__(self, service: SectorService):
        self.service = service
        self._stop = Event()
        self._kick = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._run, name='sector-snapshots', daemon=True)
            self._thread.start()
        self._kick.set()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = monotonic()
            if self.service.due():
                try:
                    self.service.refresh()
                except Exception:
                    pass
            self._kick.wait(max(0.5, self.service.interval_seconds - (monotonic() - started)))
            self._kick.clear()


def attach_sector(bundle):
    connection = bundle.market_connection
    store = SectorGroupStore(bundle.launch.root / 'market' / 'sector_groups.json')
    service = SectorService(lambda: connection.directory.items, SnapshotBridge(connection), lambda: datetime.now(timezone.utc), concepts=store.groups)
    settings = SectorAlertSettings(bundle.launch.root / 'settings.json', lock=connection.settings_lock)
    service.interval_seconds = settings.get().snapshot_seconds
    try:
        minute_store = SectorMinuteStore((bundle.launch.root / 'market' / 'sector_minutes.sqlite3').resolve())
    except DomainError:
        minute_store = NullMinuteStore()  # minute history is optional: the board and alerts keep working in memory
    minutes = MinuteAggregator(minute_store, settings.get, service.group_name)
    monitor = SectorMonitor(service.candidates, MonitorSubscriptions(connection), settings.get, service.group_name, minute_store)

    def on_round(now, stats):
        alerts = minutes.on_round(now, stats)
        try:
            return (*alerts, *monitor.on_round(now, stats))
        except Exception:
            logger.error('sector monitor round failed')
            return alerts

    service.on_round = on_round
    service.monitor_info, service.side_ratio = monitor.info, monitor.side_ratio
    service.share_baselines = lambda: minutes.baselines
    bundle.session_bridge.monitor = monitor
    service.on_alert = bundle.alerts.record_sector
    poller = SectorPoller(service)
    old_connected, old_disconnected = connection.on_connected, connection.on_disconnected

    def connected(session):
        old_connected(session)
        poller.start()

    def disconnected():
        monitor.disconnected()
        service.disconnected()
        old_disconnected()

    connection.on_connected, connection.on_disconnected = connected, disconnected
    bundle.sector, bundle.sector_poller = service, poller
    bundle.sector_settings, bundle.sector_minute_store = settings, minute_store
    bundle.sector_history = lambda query: sector_history(minute_store, query, service.group_name)
    bundle.sector_groups = SectorGroupEditor(store, lambda: connection.directory.items, service.recompute)
