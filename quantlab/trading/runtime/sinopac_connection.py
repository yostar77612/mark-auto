"""Explicit, generation-bound unified broker connection; startup is inert."""

from dataclasses import replace
from functools import lru_cache
from threading import Event, RLock, Thread
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.application.contracts import UiAction, UiReceipt
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.application.sinopac_contracts import SinopacAccountView, SinopacConnectionView
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError
from .sinopac_settings import SinopacSettingsStore
from .sinopac_calendar import built_in_calendar
from .sinopac_transition import transition

SINOPAC_ACTIONS = frozenset((UiAction.SAVE_AND_CONNECT_SINOPAC, UiAction.SELECT_SINOPAC_ACCOUNTS, UiAction.ACTIVATE_SINOPAC_CA, UiAction.DISCONNECT_SINOPAC))


@lru_cache(maxsize=1)
def _maintenance_fallback_calendar(factory):
    """Memoize only immutable bundled sessions; replacement factories reverify."""
    return factory()


def default_factory(environment):
    from .broker import ShioajiClientFactory
    from quantlab.trading.adapters.shioaji.sdk_loader import load_pinned_sdk

    return ShioajiClientFactory(load_pinned_sdk()).create(environment)


class SinopacConnection:
    def __init__(self, root, *, factory=default_factory, secrets=None, clock=None, timeout=8.0, resource_factory=None, environment=None):
        from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver
        from .market_connection import MarketClock

        if type(timeout) not in (int, float) or not 0 < timeout <= 8:
            raise DomainError('validation_failed', 'bounded connection deadline required')
        self.root, self.factory = root, factory
        self.secrets, self.clock = secrets if secrets is not None else WindowsSecretResolver(), clock or MarketClock()
        from .stock_maintenance import StockMaintenanceStore

        self.maintenance = StockMaintenanceStore(root)
        self.preferences = SinopacSettingsStore(root)
        self.configuration, self.selected = self.preferences.load()
        costs = self.maintenance.load()
        self.configuration = replace(
            self.configuration,
            api_key_expires_on=self.maintenance.key_expiry(self.configuration.key_ref),
            minimum_fee=costs.minimum_fee,
            tmf_fee_per_contract=costs.tmf_fee_per_contract,
        )
        if environment is not None:
            self.configuration = replace(self.configuration, environment=environment)
        self.environment = environment
        self.settings_lock = self.preferences.lock
        self.directory = SymbolDirectory(root / 'market' / 'symbol_directory.json')
        self.lock, self.done = RLock(), Event()
        self.done.set()
        self.worker = None
        self.shared = self.session = None
        self.accounts = ()
        self.query_ready = False
        self.closed, self.cleanup_unconfirmed = False, False
        self.ticket, self.deadline, self.timeout = '', 0.0, timeout
        historical = tuple(
            SinopacAccountView(row['alias'], row['label'], Market(row['market']), None, row['alias'] in self.selected, False, 'not_connected')
            for row in self.preferences.known_accounts()
        )
        self._view = SinopacConnectionView(settings=self.configuration, revision=self.preferences.advance_revision(), accounts=historical)
        self.on_connected, self.on_disconnected = lambda session: None, lambda: None
        self.resource_factory, self._resources = resource_factory, {}

    @property
    def settings(self):
        return MarketDataSettings(environment=self.configuration.environment, secret_ref=self.configuration.key_ref, enabled=self._view.environment is not None)

    @property
    def status(self):
        return self.snapshot().phase

    @property
    def error(self):
        return self.snapshot().error_code

    def connection_status(self):
        return self.status

    def publish(self, **changes):
        proposed = replace(self._view, **changes)
        if proposed != self._view:
            self._view = replace(proposed, revision=self.preferences.advance_revision())

    def _publish_maintenance(self, maintenance):
        previous = self._view.pre_open
        changes = dict(api_key_remaining_days=maintenance.key.remaining_days, api_key_expiry_state=maintenance.key.state, pre_open=maintenance)
        if previous is not None:
            # Day countdown and the rolling display horizon are derived views,
            # not mutations of the authenticated owner/control context. Every
            # expiry date/state, coverage/version, issue and reminder still CASes.
            authority = replace(maintenance, key=replace(maintenance.key, remaining_days=previous.key.remaining_days), through=previous.through)
            if authority == previous:
                self._view = replace(self._view, **changes)
                return
        self.publish(**changes)

    def snapshot(self):
        with self.lock:
            today = self.clock.now().astimezone(ZoneInfo('Asia/Taipei')).date()
            futures_required = not self.selected or any(account.market is not Market.STOCK for account in self.accounts if account.alias in self.selected)
            maintenance = self.maintenance.pre_open(
                _maintenance_fallback_calendar(built_in_calendar), today, self.configuration.key_ref, futures_required=futures_required
            )
            self._publish_maintenance(maintenance)
            if not self.closed and self.worker is not None and self.worker.is_alive() and monotonic() >= self.deadline:
                from .sinopac_transition import readiness

                self.ticket = uuid4().hex
                self.deadline = float('inf')
                self.query_ready = False
                self.publish(
                    phase='DISCONNECTED' if self._view.phase == 'CONNECTING' else self._view.phase,
                    certificate_status='UNKNOWN' if self._view.certificate_status == 'ACTIVATING' else self._view.certificate_status,
                    error_code='connection_timeout',
                    readiness=readiness(self),
                )
            if self.session is not None and not self.session.connected and self._view.phase == 'CONNECTED':
                from .sinopac_transition import readiness

                self.query_ready = False
                self.publish(phase='DISCONNECTED', error_code='session_lost', readiness=readiness(self))
            if self.shared is not None and self.shared.callback_errors:
                from .sinopac_transition import readiness

                self.query_ready = False
                self.publish(error_code='callback_failed', readiness=readiness(self))
            return self._view

    def execute(self, command):
        wait = False
        with self.lock:
            view = self.snapshot()
            if self.closed or command.action not in SINOPAC_ACTIONS:
                return UiReceipt(False, 'state_conflict', '')
            if command.connection_revision != view.revision or command.connection_generation != view.generation:
                return UiReceipt(False, 'state_conflict', '')
            if command.action is UiAction.ACTIVATE_SINOPAC_CA and self.configuration.environment is Environment.LIVE:
                return UiReceipt(False, 'production_orders_disabled', '')
            if self.worker is not None and self.worker.is_alive() or self.cleanup_unconfirmed:
                return UiReceipt(False, 'outcome_unknown' if self.cleanup_unconfirmed else 'state_conflict', '')
            if command.action is UiAction.SAVE_AND_CONNECT_SINOPAC:
                if command.sinopac_settings is None:
                    return UiReceipt(False, 'validation_failed', '')
                settings = command.sinopac_settings
                if self.environment is not None and settings.environment is not self.environment:
                    return UiReceipt(False, 'state_conflict', '')
                selected = self.selected if settings.environment is self.configuration.environment else ()
                self.maintenance.set_key_expiry(settings.key_ref, settings.api_key_expires_on)
                self.maintenance.save(
                    replace(
                        self.maintenance.load(),
                        discount=settings.fee_discount,
                        minimum_fee=settings.minimum_fee,
                        tmf_fee_per_contract=settings.tmf_fee_per_contract,
                    )
                )
                self.preferences.save(settings, selected)
                self.configuration, self.selected = settings, selected
                self.publish(settings=settings, environment=settings.environment, generation=uuid4().hex, phase='CONNECTING', error_code='')
            elif command.action is UiAction.DISCONNECT_SINOPAC:
                self.publish(phase='DISCONNECTING', error_code='')
                wait = True
            elif view.phase != 'CONNECTED':
                return UiReceipt(False, 'state_conflict', '')
            self.ticket, self.deadline = uuid4().hex, monotonic() + self.timeout
            self.done.clear()
            self.worker = Thread(target=transition, args=(self, command, self.ticket), name='markauto-sinopac-owner', daemon=True)
            self.worker.start()
        if wait:
            if not self.done.wait(min(self.timeout, 7.5)) or self.cleanup_unconfirmed:
                return UiReceipt(False, 'outcome_unknown', '')
            return UiReceipt(True, 'completed', '')
        return UiReceipt(True, 'connection_pending', '')

    def resources(self, account_ref):
        with self.lock:
            if self._view.phase != 'CONNECTED' or account_ref not in self.selected or self.shared is None:
                raise DomainError('capability_missing', 'selected authenticated account required')
            generation, shared = self._view.generation, self.shared
            cached = self._resources.get(account_ref)
        if cached is not None and all(capability.expires_at > self.clock.now() for capability in cached.capabilities):
            return cached
        factory = self.resource_factory
        if factory is None:
            from .sinopac_resources import generated_resources

            factory = generated_resources
        resources = factory(self, account_ref)
        with self.lock:
            if generation != self._view.generation or shared is not self.shared:
                raise DomainError('state_conflict', 'resource session changed')
            self._resources[account_ref] = resources
            return resources

    def close(self):
        with self.lock:
            if self.closed:
                return
            if self.worker is None or not self.worker.is_alive():
                from quantlab.trading.application.contracts import UiCommand

                view = self.snapshot()
                command = UiCommand(UiAction.DISCONNECT_SINOPAC, 0, connection_revision=view.revision, connection_generation=view.generation)
                self.ticket = uuid4().hex
                self.worker = Thread(target=transition, args=(self, command, self.ticket), name='markauto-sinopac-close', daemon=True)
                self.worker.start()
            self.closed = True
            self.ticket = uuid4().hex
            worker = self.worker
        worker.join(0.25)
        if worker.is_alive():
            self.cleanup_unconfirmed = True
