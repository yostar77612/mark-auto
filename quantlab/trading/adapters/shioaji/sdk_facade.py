"""Explicit boundary for the pinned Shioaji 1.7.9 Python surface.

Evidence: the hash-verified 1.7.9 wheel's _core.pyi and __init__.py, and
https://sinotrade.github.io/tutor/contract/ (Contract V2 get/info).
The wheel exports Unit/QuoteType/QuoteVersion at the module top level. Its
quote proxy is deprecated; subscriptions use the documented top-level API.

Construction performs no SDK import, client construction, login, credential
lookup, query or callback registration. Inject an already explicitly created
client and the same pinned module. SDK objects stay within this adapter.

Only methods with a documented timeout parameter receive one. These are SDK
request budgets, not a promise of hard cancellation. Contracts get/info are
lazy and have no documented timeout argument; neither do login/logout, account
listing, subscriptions, CA activation and callback registration.
"""

from typing import Callable, cast

from .sdk import SDK_VERSION, sdk_decimal, sdk_text, sdk_value
from quantlab.trading.domain.models import PriceBand, validate_price_bands
from quantlab.trading.domain.validation import DomainError, identity


def _budget(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 30000:
        raise DomainError('validation_failed', 'explicit SDK timeout must be 1..30000 milliseconds')
    return value


def _callable(owner: object, name: str) -> Callable[..., object]:
    method = getattr(owner, name, None)
    if not callable(method):
        raise DomainError('capability_missing', 'pinned SDK method unavailable')
    return cast(Callable[..., object], method)


def _rows(value: object) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise DomainError('reconciliation_required', 'SDK collection result is not a sequence')
    return list(value)


def _contract_identity(contract: object) -> tuple[str, str, str]:
    code = sdk_text(sdk_value(contract, 'code'))
    identity(code)
    security = sdk_text(sdk_value(contract, 'security_type'))
    exchange = sdk_text(sdk_value(contract, 'exchange'))
    region = sdk_text(sdk_value(contract, 'region'))
    if security not in ('STK', 'FUT') or region != 'TW':
        raise DomainError('instrument_unresolved', 'only explicit Taiwan stock/futures contracts are enabled')
    if security == 'STK' and exchange not in ('TSE', 'OTC') or security == 'FUT' and exchange != 'TAIFEX':
        raise DomainError('instrument_unresolved', 'contract exchange does not match its type')
    target = getattr(contract, 'target_code', None)
    if code.endswith(('R1', 'R2')) or target not in (None, '', code):
        raise DomainError('instrument_unresolved', 'continuous or redirected contract is not executable')
    return code, security, exchange


class ShioajiContractStore:
    """Delegate to authoritative Contract V2; never guess a delivery month.

    Info remains the original SDK StockInfo/FuturesInfo object. Required unit,
    suspension, expiry, multiplier and tick evidence is checked by the existing
    gateway resolver against the explicit InstrumentBinding; no missing field
    is fabricated or replaced with a default specification here.
    """

    def __init__(self, client: object):
        self._client = client

    def _store(self) -> object:
        # Access stays lazy: api.contracts itself may initialize a remote view.
        store = getattr(self._client, 'contracts', None)
        if store is None:
            raise DomainError('capability_missing', 'pinned Contract V2 API unavailable')
        return store

    def get(self, code: str) -> object:
        identity(code)
        if code.endswith(('R1', 'R2')):
            raise DomainError('instrument_unresolved', 'explicit real contract code required')
        contract = _callable(self._store(), 'get')(code)
        if _contract_identity(contract)[0] != code:
            raise DomainError('instrument_unresolved', 'SDK returned another contract code')
        return contract

    def info(self, contract: object) -> object:
        expected = _contract_identity(contract)
        info = _callable(self._store(), 'info')(contract)
        if _contract_identity(info) != expected:
            raise DomainError('instrument_unresolved', 'SDK info identity does not match the requested contract')
        return info

    def tick_bands(self, info: object) -> tuple[PriceBand, ...]:
        """Normalize the documented Contract V2 min/max/tick table only."""
        _contract_identity(info)
        raw = _rows(_callable(self._store(), 'tick_bands')(info))
        if not 1 <= len(raw) <= 64:
            raise DomainError('instrument_unresolved', 'bounded complete SDK tick bands required')
        bands = []
        for row in raw:
            if type(row) is not dict or set(row) != {'min', 'max', 'tick'}:
                raise DomainError('instrument_unresolved', 'SDK tick-band shape changed')
            bands.append(
                PriceBand(
                    sdk_decimal(row['min'], 'band min'),
                    None if row['max'] is None else sdk_decimal(row['max'], 'band max'),
                    sdk_decimal(row['tick'], 'band tick'),
                )
            )
        result = tuple(bands)
        validate_price_bands(result)
        return result


class ShioajiSDKFacade:
    """Small typed delegation layer; execution authorization remains in gateway.

    Query/order budgets are injectable. Defaults divide a 10-second control
    request into useful queries without turning 100ms into a broker SLA. A
    timeout on a trading command does not prove rejection or cancellation; the
    gateway/application must retain UNKNOWN exposure and reconcile it.
    """

    def __init__(self, client: object, sdk_module: object, *, query_timeout_ms: int = 2500, order_timeout_ms: int = 10000):
        if getattr(sdk_module, '__version__', None) != SDK_VERSION:
            raise DomainError('capability_missing', 'pinned SDK version required')
        self._client = client
        self._module = sdk_module
        self.query_timeout_ms = _budget(query_timeout_ms)
        self.order_timeout_ms = _budget(order_timeout_ms)
        self.contracts = ShioajiContractStore(client)

    def _enum(self, name: str, value: object, permitted: tuple[str, ...]) -> object:
        text = sdk_text(value)
        if text not in permitted:
            raise DomainError('validation_failed', 'unsupported SDK enum value')
        try:
            return _callable(self._module, name)(text)
        except (TypeError, ValueError):
            raise DomainError('capability_missing', 'pinned SDK enum unavailable') from None

    def _account_query(self, name: str, account: object, **kwargs: object) -> object:
        if account is None:
            raise DomainError('capability_missing', 'explicit SDK account required')
        return _callable(self._client, name)(account=account, timeout=self.query_timeout_ms, **kwargs)

    def login(self, *, api_key: str, secret_key: str, subscribe_trade: bool) -> list[object]:
        if not isinstance(api_key, str) or not api_key or not isinstance(secret_key, str) or not secret_key or type(subscribe_trade) is not bool:
            raise DomainError('capability_missing', 'explicit broker credentials and subscription choice required')
        return _rows(_callable(self._client, 'login')(api_key=api_key, secret_key=secret_key, subscribe_trade=subscribe_trade))

    def logout(self) -> object:
        return _callable(self._client, 'logout')()

    def activate_ca(self, *, ca_path: str, ca_passwd: str, person_id: str) -> bool:
        result = _callable(self._client, 'activate_ca')(ca_path=ca_path, ca_passwd=ca_passwd, person_id=person_id)
        if type(result) is not bool:
            raise DomainError('capability_missing', 'SDK certificate activation result is not confirmed')
        return result

    def list_accounts(self) -> list[object]:
        return _rows(_callable(self._client, 'list_accounts')())

    def account_balance(self, *, account: object) -> object:
        return self._account_query('account_balance', account)

    def trading_limits(self, *, account: object) -> object:
        return self._account_query('trading_limits', account)

    def margin(self, *, account: object) -> object:
        return self._account_query('margin', account)

    def settlements(self, *, account: object) -> list[object]:
        return _rows(self._account_query('settlements', account))

    def list_positions(self, *, account: object, unit: object) -> list[object]:
        actual_unit = self._enum('Unit', unit, ('Common', 'Share'))
        return _rows(self._account_query('list_positions', account, unit=actual_unit))

    def kbars(self, *, contract: object, start: str, end: str) -> object:
        _contract_identity(contract)
        return _callable(self._client, 'kbars')(contract=contract, start=start, end=end, timeout=self.query_timeout_ms)

    def snapshots(self, contracts: list[object]) -> list[object]:
        if not contracts:
            raise DomainError('validation_failed', 'explicit nonempty contract snapshot request required')
        for contract in contracts:
            _contract_identity(contract)
        return _rows(_callable(self._client, 'snapshots')(contracts, timeout=self.query_timeout_ms))

    def subscribe(self, contract: object, *, quote_type: str, version: object) -> None:
        _contract_identity(contract)
        kind = self._enum('QuoteType', quote_type, ('tick', 'bid_ask', 'quote'))
        actual_version = self._enum('QuoteVersion', version, ('v1',))
        _callable(self._client, 'subscribe')(contract, quote_type=kind, version=actual_version)

    def unsubscribe(self, contract: object, *, quote_type: str, version: object) -> None:
        _contract_identity(contract)
        kind = self._enum('QuoteType', quote_type, ('tick', 'bid_ask', 'quote'))
        actual_version = self._enum('QuoteVersion', version, ('v1',))
        _callable(self._client, 'unsubscribe')(contract, quote_type=kind, version=actual_version)

    def Order(self, **kwargs: object) -> object:
        # SDK 1.7.9 exports Order and attaches the same constructor as api.Order.
        return _callable(self._module, 'Order')(**kwargs)

    def place_order(self, contract: object, order: object) -> object:
        _contract_identity(contract)
        return _callable(self._client, 'place_order')(contract, order, timeout=self.order_timeout_ms)

    def update_order(self, trade: object, *, price: float, qty: int) -> object:
        return _callable(self._client, 'update_order')(trade, price=price, qty=qty, timeout=self.order_timeout_ms)

    def cancel_order(self, trade: object) -> object:
        return _callable(self._client, 'cancel_order')(trade, timeout=self.order_timeout_ms)

    def update_status(self, *, account: object) -> object:
        return self._account_query('update_status', account)

    def list_trades(self) -> list[object]:
        # Official list_trades is a local snapshot API without timeout argument.
        return _rows(_callable(self._client, 'list_trades')())

    def _callback(self, name: str, callback: Callable[..., None], *, bind: bool | None = None) -> None:
        if not callable(callback) or bind is not None and type(bind) is not bool:
            raise DomainError('validation_failed', 'explicit trusted callback required')
        kwargs = {} if bind is None else {'bind': bind}
        _callable(self._client, name)(callback, **kwargs)

    def set_on_tick_stk_v1_callback(self, callback: Callable[..., None], bind: bool = False) -> None:
        self._callback('set_on_tick_stk_v1_callback', callback, bind=bind)

    def set_on_bidask_stk_v1_callback(self, callback: Callable[..., None], bind: bool = False) -> None:
        self._callback('set_on_bidask_stk_v1_callback', callback, bind=bind)

    def set_on_tick_fop_v1_callback(self, callback: Callable[..., None], bind: bool = False) -> None:
        self._callback('set_on_tick_fop_v1_callback', callback, bind=bind)

    def set_on_bidask_fop_v1_callback(self, callback: Callable[..., None], bind: bool = False) -> None:
        self._callback('set_on_bidask_fop_v1_callback', callback, bind=bind)

    def set_order_callback(self, callback: Callable[..., None]) -> None:
        self._callback('set_order_callback', callback)

    def set_event_callback(self, callback: Callable[..., None]) -> None:
        self._callback('set_event_callback', callback)

    def set_session_down_callback(self, callback: Callable[..., None]) -> None:
        self._callback('set_session_down_callback', callback)
