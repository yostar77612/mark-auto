"""Independent market connection lifecycle and workspace reference settings.

All SDK work runs in one owned daemon. Startup/settings reads do not import the
SDK or resolve any credentials; only CONNECT_MARKET_DATA constructs a session.
"""

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Callable

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.adapters.shioaji.market_session import MarketSession
from quantlab.trading.adapters.shioaji.sdk_loader import load_pinned_sdk
from quantlab.trading.adapters.shioaji.secrets import WindowsSecretResolver
from quantlab.trading.adapters.shioaji.symbol_directory import SymbolDirectory
from quantlab.trading.application.contracts import UiAction, UiCommand, UiReceipt
from quantlab.trading.application.market_settings import MarketDataSettings
from quantlab.trading.application.errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


class MarketClock:
    def now(self):
        return datetime.now(timezone.utc)


def create_market_session(settings, directory):
    return MarketSession(settings, WindowsSecretResolver(), load_pinned_sdk(), MarketClock(), directory)


class MarketConnection:
    def __init__(self, root: Path, factory: Callable = create_market_session):
        self.store = SettingsStore(root / 'settings.json')
        self.settings_lock = RLock()
        self.directory = SymbolDirectory(root / 'market' / 'symbol_directory.json')
        self.settings = self._load()
        self.factory = factory
        self.session: MarketSession | None = None
        self.status = 'DISCONNECTED'
        self.error = ''
        self.lock = RLock()
        self.worker: Thread | None = None
        self.closed = False
        self.on_connected: Callable[[MarketSession], None] = lambda session: None
        self.on_disconnected: Callable[[], None] = lambda: None

    def _load(self):
        body = self.store.load().get('market_data_v1')
        if body is None:
            return MarketDataSettings()
        try:
            return MarketDataSettings(Environment(body['environment']), body['secret_ref'], body['enabled'])
        except (KeyError, TypeError, ValueError, DomainError):
            return MarketDataSettings()

    def execute(self, command: UiCommand):
        with self.lock:
            if self.closed or self.worker is not None and self.worker.is_alive():
                return UiReceipt(False, 'state_conflict', '')
            if command.action is UiAction.SAVE_MARKET_DATA_SETTINGS:
                if command.market_data_settings is None:
                    return UiReceipt(False, 'validation_failed', '')
                settings = command.market_data_settings
                if self.session is not None and self.session.connected:
                    return UiReceipt(False, 'state_conflict', '')
                with self.settings_lock:
                    body = self.store.load()
                    body['market_data_v1'] = {'environment': settings.environment.value, 'secret_ref': settings.secret_ref, 'enabled': settings.enabled}
                    self.store.save(body)
                self.settings = settings
                return UiReceipt(True, 'completed', '')
            if command.action is UiAction.CONNECT_MARKET_DATA and not self.settings.enabled:
                text = ERROR_TABLE['market_data_not_configured']
                return UiReceipt(False, 'market_data_not_configured', text.explanation + ' ' + text.action)
            self.status = 'CONNECTING' if command.action is UiAction.CONNECT_MARKET_DATA else 'DISCONNECTED'
            self.worker = Thread(target=self._transition, args=(command.action,), name='markauto-market-connect', daemon=True)
            self.worker.start()
            return UiReceipt(True, 'connection_pending', '')

    def _transition(self, action: UiAction):
        candidate = None
        try:
            if self.session is not None:
                self.on_disconnected()
                self.session.disconnect()
            if action is UiAction.DISCONNECT_MARKET_DATA:
                self.session = None
                return
            candidate = self.factory(self.settings, self.directory)
            candidate.connect()
            with self.lock:
                if self.closed:
                    candidate.disconnect()
                    return
                self.session = candidate
                self.on_connected(candidate)
                self.status, self.error = 'CONNECTED', ''
        except DomainError as exc:
            if candidate is not None:
                candidate.disconnect()
            with self.lock:
                self.session = None
                self.status = 'DISCONNECTED'
                self.error = 'market_sdk_missing' if exc.code == 'capability_missing' else exc.code
        except (OSError, ValueError, RuntimeError):
            if candidate is not None:
                candidate.disconnect()
            with self.lock:
                self.session = None
                self.status, self.error = 'DISCONNECTED', 'market_data_login_failed'

    def connection_status(self):
        with self.lock:
            if self.status == 'CONNECTED' and (self.session is None or not self.session.connected):
                return 'DISCONNECTED'
            return self.status

    def close(self):
        with self.lock:
            self.closed = True
            self.status = 'DISCONNECTED'
            session = self.session
        if session is not None:

            def disconnect():
                self.on_disconnected()
                session.disconnect()

            worker = Thread(target=disconnect, name='markauto-market-disconnect', daemon=True)
            worker.start()
