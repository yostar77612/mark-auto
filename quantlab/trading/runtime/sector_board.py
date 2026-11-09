"""Compose the read-only sector board with the market connection and a background snapshot poller."""

from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic

from quantlab.trading.adapters.shioaji.snapshot_poller import ShioajiSnapshotSource
from quantlab.trading.adapters.storage.sector_store import SectorGroupStore
from quantlab.trading.application.sector_group_editor import SectorGroupEditor
from quantlab.trading.application.sector_service import SectorService
from quantlab.trading.domain.validation import DomainError


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
    poller = SectorPoller(service)
    old_connected, old_disconnected = connection.on_connected, connection.on_disconnected

    def connected(session):
        old_connected(session)
        poller.start()

    def disconnected():
        service.disconnected()
        old_disconnected()

    connection.on_connected, connection.on_disconnected = connected, disconnected
    bundle.sector, bundle.sector_poller = service, poller
    bundle.sector_groups = SectorGroupEditor(store, lambda: connection.directory.items, service.recompute)
