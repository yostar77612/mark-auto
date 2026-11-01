"""One authenticated native owner with detachable consumers.

Native callback setters are installed once; subscribing to the same quote from
the terminal and a trading view retains one remote subscription. A consumer's
logout only releases its leases. Only the owner can log out the native client.
"""

from threading import Lock, RLock
from typing import Callable

from quantlab.trading.domain.validation import DomainError, identity
from .sdk import sdk_text, sdk_value
from .sdk_facade import ShioajiSDKFacade


class SharedSDKSession:
    def __init__(self, facade: ShioajiSDKFacade):
        self.facade = facade
        self._lock, self._operations = RLock(), Lock()
        self._consumers: dict[str, SharedFacadeView] = {}
        self._callbacks: dict[str, dict[str, Callable]] = {}
        self._installed: set[str] = set()
        self._leases: dict[tuple, tuple[set[str], Callable]] = {}
        self._authenticated = False
        self._closed = False
        self.logout_confirmed = False
        self.callback_errors = 0

    def login(self, *, api_key: str, secret_key: str) -> list[object]:
        with self._operations:
            if self._authenticated or self._closed:
                raise DomainError('capability_missing', 'session owner cannot log in twice')
            accounts = self.facade.login(api_key=api_key, secret_key=secret_key, subscribe_trade=True)
            self._authenticated = True
            return accounts

    def consumer(self, name: str) -> 'SharedFacadeView':
        identity(name)
        with self._lock:
            if self._closed or not self._authenticated or name in self._consumers:
                raise DomainError('capability_missing', 'authenticated unique session consumer required')
            view = SharedFacadeView(self, name)
            self._consumers[name] = view
            return view

    def callback(self, name: str, consumer: str, callback: Callable, bind: bool | None) -> None:
        if not callable(callback) or bind not in (None, False):
            raise DomainError('validation_failed', 'unbound shared callback required')
        with self._operations:
            with self._lock:
                self._active(consumer)
                install = name not in self._installed
            if install:
                self.facade._callback(name, lambda *args: self._dispatch(name, args), bind=bind)
            with self._lock:
                self._installed.add(name)
                self._callbacks.setdefault(name, {})[consumer] = callback

    def _dispatch(self, name: str, args: tuple) -> None:
        with self._lock:
            callbacks = tuple(self._callbacks.get(name, {}).values())
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:
                # Do not leak native payloads or stop another consumer's delivery.
                with self._lock:
                    self.callback_errors += 1

    def _active(self, consumer: str) -> None:
        if self._closed or consumer not in self._consumers:
            raise DomainError('market_data_not_connected')

    def lease(self, consumer: str, key: tuple, acquire: Callable, release: Callable, remove: bool) -> None:
        # SDK calls never hold the callback/state lock. The separate operation
        # lock serializes remote subscription changes and detach/close.
        with self._operations:
            with self._lock:
                self._active(consumer)
                holders, remote_release = self._leases.get(key, (set(), release))
                present = consumer in holders
            if remove and not present or not remove and present:
                return
            if remove and len(holders) == 1:
                remote_release()
            elif not remove and not holders:
                acquire()
            with self._lock:
                if remove:
                    holders.remove(consumer)
                    if not holders:
                        self._leases.pop(key, None)
                else:
                    holders.add(consumer)
                    self._leases[key] = holders, remote_release

    def detach(self, consumer: str) -> None:
        with self._operations:
            with self._lock:
                if consumer not in self._consumers:
                    return
                self._consumers.pop(consumer)
                for callbacks in self._callbacks.values():
                    callbacks.pop(consumer, None)
                releases = []
                for key, (holders, release) in tuple(self._leases.items()):
                    holders.discard(consumer)
                    if not holders:
                        self._leases.pop(key)
                        releases.append(release)
            failed = False
            for release in releases:
                try:
                    release()
                except Exception:
                    failed = True
            if failed:
                raise DomainError('market_data_not_connected', 'subscription release unconfirmed')

    def close(self) -> None:
        with self._operations:
            with self._lock:
                if self._closed:
                    if not self.logout_confirmed:
                        raise DomainError('outcome_unknown', 'session logout remains unconfirmed')
                    return
                self._closed = True
                self._callbacks.clear()
                self._consumers.clear()
                releases = [release for _, release in self._leases.values()]
                self._leases.clear()
            try:
                for release in releases:
                    try:
                        release()
                    except Exception:
                        pass  # Native logout remains mandatory after release failure.
            finally:
                if self.facade.logout() is False:
                    raise DomainError('market_data_not_connected', 'session logout unconfirmed')
                self.logout_confirmed = True


class SharedFacadeView(ShioajiSDKFacade):
    """Typed SDK facade preserving the native environment and execution guards."""

    def __init__(self, owner: SharedSDKSession, name: str):
        parent = owner.facade
        super().__init__(
            parent._client, parent._module, environment=parent.environment, query_timeout_ms=parent.query_timeout_ms, order_timeout_ms=parent.order_timeout_ms
        )
        self._owner, self._name = owner, name

    def login(self, **kwargs) -> list[object]:
        raise DomainError('capability_missing', 'only the shared owner can log in')

    def logout(self) -> None:
        self._owner.detach(self._name)

    def place_order(self, contract: object, order: object) -> object:
        with self._owner._operations:
            with self._owner._lock:
                self._owner._active(self._name)
            return super().place_order(contract, order)

    def update_order(self, trade: object, *, price: float | None = None, qty: int | None = None) -> object:
        with self._owner._operations:
            with self._owner._lock:
                self._owner._active(self._name)
            return super().update_order(trade, price=price, qty=qty)

    def cancel_order(self, trade: object) -> object:
        with self._owner._operations:
            with self._owner._lock:
                self._owner._active(self._name)
            return super().cancel_order(trade)

    def _callback(self, name, callback, *, bind=None) -> None:
        self._owner.callback(name, self._name, callback, bind)

    def subscribe(self, contract, *, quote_type, version) -> None:
        self._quote(contract, quote_type, version, False)

    def unsubscribe(self, contract, *, quote_type, version) -> None:
        self._quote(contract, quote_type, version, True)

    def _quote(self, contract, quote_type, version, remove, *, market=False) -> None:
        key = ('quote', *(sdk_text(sdk_value(contract, field)) for field in ('security_type', 'exchange', 'code')), sdk_text(quote_type), sdk_text(version))
        parent = self._owner.facade
        if market:
            acquire = lambda: parent.market_subscribe(contract)
            release = lambda: parent.market_subscribe(contract, remove=True)
        else:
            acquire = lambda: parent.subscribe(contract, quote_type=quote_type, version=version)
            release = lambda: parent.unsubscribe(contract, quote_type=quote_type, version=version)
        self._owner.lease(self._name, key, acquire, release, remove)

    def market_subscribe(self, contract, *, remove=False) -> None:
        kind = 'quote' if sdk_text(sdk_value(contract, 'security_type')) == 'IND' else 'tick'
        self._quote(contract, kind, 'v1', remove, market=True)

    def subscribe_scanner(self, scanner, *, region, security_type, exchange) -> None:
        self._scanner(scanner, region, security_type, exchange, False)

    def unsubscribe_scanner(self, scanner, *, region, security_type, exchange) -> None:
        self._scanner(scanner, region, security_type, exchange, True)

    def _scanner(self, scanner, region, security_type, exchange, remove) -> None:
        parent = self._owner.facade
        key = ('scanner', sdk_text(sdk_value(scanner, 'id')), *(sdk_text(item) for item in (region, security_type, exchange)))
        self._owner.lease(
            self._name,
            key,
            lambda: parent.subscribe_scanner(scanner, region=region, security_type=security_type, exchange=exchange),
            lambda: parent.unsubscribe_scanner(scanner, region=region, security_type=security_type, exchange=exchange),
            remove,
        )
