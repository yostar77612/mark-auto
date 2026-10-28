"""Host composition for local engines and explicit disconnected broker contexts."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import stat
from threading import RLock, Thread, current_thread
from time import monotonic
from typing import Protocol
from uuid import uuid4

from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.contracts import TradingFacade, UiAction, UiCommand, UiReceipt, UiState
from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.application.engine import TradingEngine
from quantlab.trading.application.facade import LocalFacade
from quantlab.trading.application.readiness_session import ReadinessSession
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.storage import Journal
from .broker import FilesystemReferenceInspector, connect_profile_engine
from .config import RuntimeLaunch, RuntimeResources, load_profile, load_resources
from .gateway_cache import ReadOnlyGatewayCache


class WallClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class EngineFactory(Protocol):
    """Trusted composition injection, never a module name from configuration.

    Called only by the explicit read-only connection action. It must return an
    already authenticated, read-only engine; any acquired resources on failure
    remain the factory's responsibility. Tests inject fault ports, not a broker.
    """

    def __call__(self, launch: RuntimeLaunch, resources: RuntimeResources) -> TradingEngine: ...


@dataclass(frozen=True)
class PublicVersionState:
    environment: Environment
    configuration_id: str
    account_refs: tuple[str, ...]
    high_water: int

    def __post_init__(self) -> None:
        if (
            self.environment is Environment.LOCAL
            or type(self.high_water) is not int
            or not 0 <= self.high_water <= 10**12
            or type(self.configuration_id) is not str
            or not self.configuration_id
            or type(self.account_refs) is not tuple
            or not self.account_refs
        ):
            raise DomainError('validation_failed', 'runtime public version checkpoint')


register(PublicVersionState)


@dataclass
class RuntimeBundle:
    launch: RuntimeLaunch
    facade: TradingFacade
    journals: tuple[Journal, ...]
    engine: TradingEngine | None = None
    resources: RuntimeResources | None = None
    engine_factory: EngineFactory | None = None
    version_journal: Journal | None = None
    connect_timeout: float = 8.0

    def __post_init__(self) -> None:
        if type(self.connect_timeout) not in (int, float) or not 0 < self.connect_timeout <= 8:
            raise DomainError('validation_failed', 'bounded readonly connection deadline required')
        from .watchlist_settings import WatchlistSettings

        self.watch_settings = WatchlistSettings(self.launch.root / 'settings.json')
        if self.engine is not None:
            self.watch_settings.restore(self.engine)
        self.lock = RLock()
        self.version_offset = 0
        self.transitioning = False
        self.closing = False
        self.resources_closed = False
        self.cleanup_unconfirmed = False
        self.control_failed = False
        self.connection_attempt = ''
        self.connection_deadline = 0.0
        self.connection_threads: set[Thread] = set()
        self.query_caches: tuple[ReadOnlyGatewayCache, ...] = ()
        self.query_instruments: tuple[str, ...] = ()
        self.quote_cursor = 0
        self.version_sequence = 0
        self.high_water = -1
        if self.version_journal is not None:
            for event in self.version_journal.replay():
                checkpoint = loads(event.payload)
                if (
                    not isinstance(checkpoint, PublicVersionState)
                    or checkpoint.environment is not self.launch.environment
                    or checkpoint.configuration_id != self.configuration_id
                    or checkpoint.account_refs != self.account_refs
                    or checkpoint.high_water < self.high_water
                ):
                    raise DomainError('startup_workspace_incompatible', 'runtime public version context changed')
                self.high_water = checkpoint.high_water
                self.version_sequence = event.sequence
            self.version_offset = max(0, self.high_water + 1 - self.facade.snapshot().version)

    @property
    def configuration_id(self) -> str:
        if self.resources is not None:
            return self.resources.profile.source_sha256
        if self.launch.environment is Environment.LOCAL:
            return ''
        return 'UNCONFIGURED:' + self.launch.environment.value + ':' + self.launch.account_ref

    def _checkpoint(self, version: int) -> None:
        if self.version_journal is None or version <= self.high_water:
            return
        value = PublicVersionState(self.launch.environment, self.configuration_id, self.account_refs, version)
        try:
            event = self.version_journal.append(
                'runtime_public_version_published', dumps(value), datetime.now(timezone.utc), expected_sequence=self.version_sequence
            )
            if event.sequence != self.version_sequence + 1:
                raise DomainError('journal_failed', 'public version journal sequence mismatch')
        except Exception as exc:
            self._control_failure()
            raise DomainError('journal_failed', 'public version cannot be durably published') from exc
        self.high_water, self.version_sequence = version, event.sequence

    def _control_failure(self) -> None:
        self.control_failed = True
        if self.engine is not None and not self.engine.storage_failed and (not self.engine.state.stopped or 'outcome_unknown' not in self.engine.state.issues):
            # A control-stamp failure is not a trade-journal failure. Stop new
            # exposure while preserving independently durable protective work.
            with self.engine.lock:
                self.engine._persist(
                    'runtime_control_unconfirmed',
                    replace(self.engine.state, stopped=True, issues=tuple(sorted(set((*self.engine.state.issues, 'outcome_unknown'))))),
                )

    @property
    def account_refs(self) -> tuple[str, ...]:
        if self.resources is not None:
            config = self.resources.profile.configuration
            return tuple(ref for ref in (config.stock_account_ref, config.futures_account_ref) if ref)
        if self.engine is not None:
            return tuple(self.engine.gateways)
        return (self.launch.account_ref,)

    def snapshot(self) -> UiState:
        with self.lock:
            self._expire_connection()
            if self.control_failed:
                raise DomainError('journal_failed', 'runtime control confirmation is unavailable')
            state = self.facade.snapshot()
            version = state.version + self.version_offset
            self._checkpoint(version)
            return replace(
                state,
                watchlist=tuple(view.instrument_id for view in state.market_watch) if self.watch_settings.watchlist is None else self.watch_settings.watchlist,
                market_connection='CONNECTING' if self.transitioning else 'CONNECTED' if self.engine is not None else 'DISCONNECTED',
                version=version,
                engine_state='CONNECTING' if self.transitioning else state.engine_state,
                configuration_id=self.configuration_id,
            )

    @property
    def closed(self) -> bool:
        return self.engine.state.engine_closed if self.engine is not None else self.facade.state.engine_closed

    def execute(self, command: UiCommand) -> UiReceipt:
        # Keep the composition lock short. A research command can release the
        # engine's writer lock while its owned worker runs; host quoting stays live.
        with self.lock:
            if not isinstance(command, UiCommand) or not isinstance(command.action, UiAction) or type(command.expected_version) is not int:
                return UiReceipt(False, 'validation_failed', '')
            if self.control_failed:
                return UiReceipt(False, 'journal_failed', '')
            if self.transitioning and command.action not in (UiAction.STOP_NEW, UiAction.SHUTDOWN_ENGINE):
                return UiReceipt(False, 'state_conflict', '')
            if command.action is UiAction.SAVE_SETTINGS and command.watchlist is not None:
                if self.closing or self.closed:
                    return UiReceipt(False, 'state_conflict', '')
                if command.expected_version != self.facade.snapshot().version + self.version_offset:
                    return UiReceipt(False, 'state_conflict', '')
                if command.settings is not None:
                    return UiReceipt(False, 'validation_failed', '')
                receipt = self.watch_settings.save(self.engine, command.watchlist)
                if receipt.accepted:
                    self.version_offset += 1
                return receipt
            facade, offset = self.facade, self.version_offset
            current = facade.snapshot().version + offset
            if command.expected_version != current:
                return UiReceipt(False, 'state_conflict', '')
            if self.transitioning and command.action in (UiAction.STOP_NEW, UiAction.SHUTDOWN_ENGINE):
                self.transitioning = False
                self.connection_attempt = ''  # A later completion cannot promote.
        return facade.execute(replace(command, expected_version=command.expected_version - offset))

    def connect_read_only(self, command: UiCommand) -> UiReceipt:
        with self.lock:
            if not isinstance(command, UiCommand) or command.action is not UiAction.CONNECT_READ_ONLY or type(command.expected_version) is not int:
                return UiReceipt(False, 'validation_failed', '')
            if self.control_failed:
                return UiReceipt(False, 'journal_failed', '')
            if (
                self.closing
                or self.closed
                or self.transitioning
                or self.connection_threads
                or command.expected_version != self.facade.snapshot().version + self.version_offset
            ):
                return UiReceipt(False, 'state_conflict', '')
            if self.launch.environment is Environment.LOCAL or self.engine is not None or self.engine_factory is None or self.resources is None:
                return UiReceipt(False, 'capability_missing', '')
            if isinstance(self.facade, ReadinessSession) and self.facade.state.settings != self.resources.profile.settings:
                return UiReceipt(False, 'state_conflict', '')
            attempt = uuid4().hex
            self.facade.begin_connection(attempt)
            self._checkpoint(self.facade.snapshot().version + self.version_offset)
            self.transitioning = True
            self.connection_attempt = attempt
            self.connection_deadline = monotonic() + self.connect_timeout
            worker = Thread(target=self._connect_worker, args=(attempt,), name='markauto-readonly-connect', daemon=True)
            self.connection_threads.add(worker)
            try:
                worker.start()
            except RuntimeError as exc:
                self.connection_threads.discard(worker)
                self.transitioning = False
                self.connection_attempt = ''
                self.facade.finish_connection(attempt, 'outcome_unknown')
                raise DomainError('outcome_unknown', 'owned connection worker did not start') from exc
            return UiReceipt(True, 'connection_pending', '')

    def _expire_connection(self) -> None:
        if self.transitioning and monotonic() >= self.connection_deadline:
            attempt = self.connection_attempt
            self.transitioning = False
            self.connection_attempt = ''
            if isinstance(self.facade, ReadinessSession):
                self.facade.finish_connection(attempt, 'outcome_unknown')

    @staticmethod
    def _discard_candidate(candidate: TradingEngine | None) -> None:
        if candidate is None:
            return
        try:
            if candidate.research_runner is not None:
                candidate.research_runner.close()
        finally:
            try:
                seen = set()
                for gateway in candidate.gateways.values():
                    if id(gateway) not in seen:
                        seen.add(id(gateway))
                        disconnect = getattr(gateway, 'disconnect', None)
                        if disconnect is not None:
                            try:
                                disconnect()
                            except Exception:
                                pass
            finally:
                candidate.journal.close()

    def _connect_worker(self, attempt: str) -> None:
        candidate = None
        adopted = False
        try:
            # Re-read every pinned byte immediately before the controlled entry.
            profile = load_profile(self.resources.profile.source_path, self.launch.environment)
            if profile.source_sha256 != self.resources.profile.source_sha256:
                raise DomainError('capability_missing', 'selected runtime profile changed')
            resources = load_resources(profile)
            candidate = self.engine_factory(self.launch, resources)
            if (
                candidate.configuration.environment is not self.launch.environment
                or set(candidate.gateways) != set(self.account_refs)
                or not candidate.configuration.read_only
                or candidate.configuration.broker_simulation_enabled
                or candidate.configuration.live_execution_enabled
            ):
                raise DomainError('capability_missing', 'connector must preserve readonly environment and explicit accounts')
            if candidate.simulation is not None:
                raise DomainError('capability_missing', 'broker contexts cannot adopt the local exchange controller')
            from .live_market import attach_market

            attach_market(candidate)
            self.watch_settings.restore(candidate)
            caches = {}
            for account, gateway in candidate.gateways.items():
                if id(gateway) not in caches:
                    scoped = tuple(ref for ref, port in candidate.gateways.items() if port is gateway)
                    caches[id(gateway)] = ReadOnlyGatewayCache(gateway, scoped, self.launch.environment, candidate.clock)
            candidate.gateways = {account: caches[id(gateway)] for account, gateway in candidate.gateways.items()}
            with self.lock:
                self._expire_connection()
                if self.closing or self.closed or self.control_failed or self.connection_attempt != attempt or not self.transitioning:
                    return
                old_version = self.facade.snapshot().version + self.version_offset
                self.facade.finish_connection(attempt)
                offset = max(0, old_version + 2 - candidate.state.version)
                self._checkpoint(candidate.state.version + offset)
                self.version_offset = offset
                self.engine, self.facade = candidate, LocalFacade(candidate)
                self.journals = (*self.journals, candidate.journal)
                self.resources = resources
                self.query_caches = tuple(caches.values())
                adopted = True
                self.transitioning = False
                self.connection_attempt = ''
        except DomainError as exc:
            with self.lock:
                if not self.closing and not self.closed and self.connection_attempt == attempt and isinstance(self.facade, ReadinessSession):
                    self.facade.finish_connection(attempt, exc.code)
                    self.transitioning = False
                    self.connection_attempt = ''
        except Exception:
            with self.lock:
                if not self.closing and not self.closed and self.connection_attempt == attempt and isinstance(self.facade, ReadinessSession):
                    self.facade.finish_connection(attempt, 'capability_missing')
                    self.transitioning = False
                    self.connection_attempt = ''
        finally:
            try:
                if not adopted:
                    self._discard_candidate(candidate)
            finally:
                with self.lock:
                    self.connection_threads.discard(current_thread())

    def heartbeat(self) -> None:
        with self.lock:
            journals = self.journals
        now = datetime.now(timezone.utc)
        for journal in journals:
            try:
                if self.engine is not None and journal is self.engine.journal:
                    with self.engine.lock:
                        self.engine.fence()
                else:
                    journal.heartbeat(now)
            except Exception:
                if self.engine is not None and journal is self.engine.journal:
                    self.engine.storage_failed = True
                elif self.launch.environment is Environment.LOCAL and self.engine is not None:
                    self.engine.storage_failed = True
                else:
                    self._control_failure()

    def pump(self) -> None:
        with self.lock:
            self._expire_connection()
            engine = self.engine
        if self.closing or engine is None or engine.state.engine_closed or engine.storage_failed:
            return
        if engine.configuration.environment is not Environment.LOCAL:
            from quantlab.trading.application.coordinator import run_cycle, run_readonly_cycle

            with engine.lock:
                # Only actual normalized quotes from the selected gateway enter the
                # core; missing/expired quotes never become synthetic zero prices.
                selected = self.query_instruments
                seen = set()
                for gateway in engine.gateways.values():
                    if id(gateway) in seen:
                        continue
                    seen.add(id(gateway))
                    latest = getattr(gateway, 'latest', None)
                    if latest is None:
                        continue
                    for instrument_id in selected:
                        if self.closing:
                            break
                        try:
                            quote = latest(instrument_id)
                            prior = engine.quotes.get(instrument_id)
                            if quote is not None and (prior is None or quote != prior):
                                engine.quote(quote)
                        except DomainError:
                            continue
            if engine.configuration.read_only:
                run_readonly_cycle(engine)
            else:
                run_cycle(engine, engine.history, allow_entries=not engine.state.stopped and not self.control_failed)
        from quantlab.trading.application.market_cycle import poll_market

        with engine.lock:
            poll_market(engine)

    def poll_ports(self) -> None:
        """SDK waits run here, never on the decision/control writer lock."""
        with self.lock:
            engine, caches = self.engine, self.query_caches
        if self.closing or engine is None or engine.state.engine_closed or engine.storage_failed or not caches:
            return
        with engine.lock:
            instruments = tuple(spec.instrument_id for spec in engine.catalog.instruments)
            priority = tuple(dict.fromkeys(lot.instrument_id for lot in engine.state.positions if lot.quantity))
            rotated = instruments[self.quote_cursor :] + instruments[: self.quote_cursor]
            selected = tuple(dict.fromkeys((*priority, *rotated)))[:8]
            self.quote_cursor = (self.quote_cursor + len(selected)) % max(1, len(instruments))
            self.query_instruments = selected
        for cache in caches:
            if self.closing or engine.state.engine_closed:
                return
            cache.poll(selected, cancelled=lambda: self.closing or engine.state.engine_closed)

    def cancel_owned_workers(self) -> None:
        with self.lock:
            self.closing = True
            self.transitioning = False
            self.connection_attempt = ''
        if self.engine is not None and self.engine.research_runner is not None:
            self.engine.research_runner.close()

    def close(self) -> None:
        with self.lock:
            if self.resources_closed:
                return
            self.resources_closed = True
        self.cancel_owned_workers()
        errors = []
        if self.engine is not None and self.launch.environment is not Environment.LOCAL:
            seen_gateways = set()
            for gateway in self.engine.gateways.values():
                if id(gateway) not in seen_gateways:
                    seen_gateways.add(id(gateway))
                    disconnect = getattr(gateway, 'disconnect', None)
                    if disconnect is not None:

                        def close_gateway(operation=disconnect):
                            try:
                                operation()
                            except Exception as exc:
                                errors.append(exc)

                        # SDK logout has no supported timeout argument. Keep
                        # that uncertainty separate from closing our journals;
                        # an owned daemon cannot prolong the engine lifetime.
                        cleanup = Thread(target=close_gateway, name='markauto-readonly-disconnect', daemon=True)
                        try:
                            cleanup.start()
                        except RuntimeError:
                            self.cleanup_unconfirmed = True
                            continue
                        cleanup.join(0.25)
                        self.cleanup_unconfirmed = self.cleanup_unconfirmed or cleanup.is_alive()
        seen = set()
        for journal in reversed(self.journals):
            if id(journal) not in seen:
                seen.add(id(journal))
                try:
                    journal.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise DomainError('operation_failed', 'owned runtime resource cleanup failed') from errors[0]


def build_runtime(launch: RuntimeLaunch, *, engine_factory: EngineFactory | None = None) -> RuntimeBundle:
    if not isinstance(launch, RuntimeLaunch):
        raise DomainError('validation_failed', 'typed runtime launch required')
    if str(launch.root).startswith(('\\\\', '//')):
        raise DomainError('validation_failed', 'runtime journals require a selected local directory')
    for ancestor in (launch.root, *launch.root.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise DomainError('validation_failed', 'redirected runtime journal root refused')
    launch.root.mkdir(parents=True, exist_ok=True)
    if launch.environment is Environment.LOCAL:
        from .build import create_engine

        engine = create_engine(launch.root)
        # The composition root owns the optional local-exchange resource; the
        # authenticated host itself knows only the Journal lifecycle contract.
        journals = (engine.journal, engine.simulation.ledger)
        return RuntimeBundle(launch, LocalFacade(engine), journals, engine)
    resources = None
    settings = None
    stock = futures = Decimal('0')
    refs = (launch.account_ref,)
    if launch.profile_path is not None:
        profile = load_profile(launch.profile_path, launch.environment)
        resources = load_resources(profile)
        refs = tuple(ref for ref in (profile.configuration.stock_account_ref, profile.configuration.futures_account_ref) if ref)
        if launch.account_ref not in refs:
            raise DomainError('capability_missing', 'selected account is outside the pinned profile')
        settings = profile.settings
        stock, futures = profile.stock_allocation, profile.futures_allocation
    journal = Ledger(launch.root / 'readiness-v2.sqlite', 'runtime-readiness-' + launch.environment.value, datetime.now(timezone.utc))
    versions = None
    try:
        inspector = FilesystemReferenceInspector((launch.profile_path.parent,)) if launch.profile_path is not None else FilesystemReferenceInspector(())
        session = ReadinessSession(
            journal, launch.environment, refs, launch.account_ref, WallClock(), inspector, settings=settings, stock_allocation=stock, futures_allocation=futures
        )
        versions = Ledger(launch.root / 'runtime-control-v2.sqlite', 'runtime-public-version-' + launch.environment.value, datetime.now(timezone.utc))
        return RuntimeBundle(
            launch, session, (journal, versions), resources=resources, engine_factory=engine_factory or connect_profile_engine, version_journal=versions
        )
    except BaseException:
        journal.close()
        if versions is not None:
            versions.close()
        raise
