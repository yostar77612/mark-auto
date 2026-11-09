"""Independent read-only stock/index session; no trading catalogue or accounts.

The caller explicitly loads the pinned SDK only for a connect intent. Native
exceptions are sanitized at this SDK boundary; credentials are never retained.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from threading import Lock
from zoneinfo import ZoneInfo

from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.domain.watch import WatchInstrument, WatchKind
from quantlab.trading.ports.history import HistoryUsage
from quantlab.trading.ports.market_settings import MarketSessionSettings
from quantlab.trading.ports.interfaces import Clock
from .sdk import SecretResolver, sdk_decimal, sdk_text, sdk_time, sdk_value
from .sdk_facade import ShioajiSDKFacade
from .symbol_directory import SymbolDirectory
from .bidask_stream import ShioajiBidAskStream
from .tick_stream import ShioajiTickStream, normalise_tick

TAIPEI = ZoneInfo('Asia/Taipei')


def history_time(value: object) -> datetime:
    """KBars numeric ns are Taipei wall-clock encoded, not UTC epoch time."""
    if type(value) in (int, float):
        wall_time = sdk_time(value).replace(tzinfo=None)
        return wall_time.replace(tzinfo=TAIPEI).astimezone(timezone.utc)
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI).astimezone(timezone.utc)
    return sdk_time(value)


class WatchSessionResolver:
    """Display-only sessions from a received stock/index timestamp, never risk evidence."""

    def session_at(self, instrument_id: str, timestamp: datetime):
        return timestamp.astimezone(TAIPEI).date(), 'DAY'


def watch_tick(raw, instrument_id, received_at, resolver):
    stamp = sdk_value(raw, 'datetime')
    if isinstance(stamp, datetime) and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TAIPEI)
    normalized = SimpleNamespace(datetime=stamp, close=sdk_value(raw, 'close'), volume=sdk_value(raw, 'volume'), tick_type=getattr(raw, 'tick_type', 0))
    return normalise_tick(normalized, instrument_id, received_at, resolver)


class IndexTick:
    """Index QUO has no share-volume field; do not invent turnover from it."""

    volume = 0

    def __init__(self, quote):
        self.quote = quote

    def __getattr__(self, name):
        return getattr(self.quote, name)


class MarketSession:
    def __init__(
        self,
        settings: MarketSessionSettings,
        secret_resolver: SecretResolver,
        sdk_module: object,
        clock: Clock,
        directory: SymbolDirectory,
        live_settings: LiveMarketSettings = LiveMarketSettings(),
    ):
        self.settings, self.secret_resolver, self.sdk_module = settings, secret_resolver, sdk_module
        self.clock, self.directory, self.live_settings = clock, directory, live_settings
        self.connected = False
        self.facade: ShioajiSDKFacade | None = None
        self.tick_stream: ShioajiTickStream | None = None
        self.bidask_stream: ShioajiBidAskStream | None = None
        self.bidask_subscriptions: dict[str, object] = {}
        self.subscriptions: dict[str, object] = {}
        self._quote_lock = Lock()
        self._details: dict[str, dict[str, object]] = {}

    def connect(self) -> None:
        if self.facade is not None:
            self.disconnect()
        if not self.settings.enabled:
            raise DomainError('market_data_not_configured')
        authenticated = False
        try:
            client = self.sdk_module.Shioaji(simulation=self.settings.environment is Environment.BROKER_SIMULATION)
            self.facade = ShioajiSDKFacade(client, self.sdk_module, environment=self.settings.environment)
            credentials = self.secret_resolver.broker_credentials(self.settings.secret_ref)
            self.facade.login(api_key=credentials.api_key, secret_key=credentials.secret_key, subscribe_trade=False)
            authenticated = True
            del credentials
            self._start_quotes()
        except Exception:
            self.connected = False
            if self.facade is not None:
                try:
                    self.facade.logout()
                except Exception:
                    pass
            self.facade = None
            raise DomainError('broker_initialization_failed' if authenticated else 'market_data_login_failed') from None

    def attach_authenticated(self, facade: ShioajiSDKFacade) -> None:
        """Adopt a shared consumer; its logout releases only this consumer."""
        if self.facade is not None or not self.settings.enabled or facade.environment is not self.settings.environment:
            raise DomainError('market_data_not_configured')
        self.facade = facade
        try:
            self._start_quotes()
        except Exception:
            self.connected = False
            self.facade = None
            try:
                facade.logout()
            finally:
                raise DomainError('broker_initialization_failed') from None

    def _start_quotes(self) -> None:
        self.directory.refresh(self.facade, self.clock.now())
        self.connected = True
        self.tick_stream = ShioajiTickStream(
            self.facade,
            self.clock,
            (),
            WatchSessionResolver(),
            lambda: self.connected,
            self.live_settings,
            self._session_down,
            watch_instruments=self.directory.items,
            tick_normalizer=self._watch_tick,
        )
        self.tick_stream.start()
        self.bidask_stream = ShioajiBidAskStream(self.tick_stream.by_code)
        self.facade.set_on_bidask_stk_v1_callback(self.bidask_stream.on_bidask)
        self.facade.set_on_quote_idx_v1_callback(self._index_quote)

    def _session_down(self, *args) -> None:
        self.connected = False

    def _index_quote(self, raw: object) -> None:
        # Index QuoteIdxV1 carries the same datetime/close/code fields. Volume
        # is not share volume; omit it rather than mislabel index turnover.
        self.tick_stream.on_tick(None, IndexTick(raw))

    def _watch_tick(self, raw, instrument_id, received_at, resolver):
        tick = watch_tick(raw, instrument_id, received_at, resolver)
        details = {}
        for name, source in (('bid', 'bid_price'), ('ask', 'ask_price'), ('open', 'open'), ('high', 'high'), ('low', 'low')):
            value = getattr(raw, source, None)
            if value is not None:
                parsed = sdk_decimal(value, name)
                if parsed > 0:
                    details[name] = parsed
        total = getattr(raw, 'total_volume', None)
        if type(total) is int and total >= 0 and not instrument_id.startswith('INDEX:'):
            details['total_volume'] = total
        with self._quote_lock:
            self._details.setdefault(instrument_id, {}).update(details)
        return tick

    def quote_details(self, instrument_id: str) -> dict[str, object]:
        with self._quote_lock:
            return dict(self._details.get(instrument_id, {}))

    def _contract(self, instrument: WatchInstrument) -> object:
        if not self.connected:
            raise DomainError('market_data_not_connected')
        contract = self.facade.market_contract(instrument.code)
        expected_exchange = ('TSE', 'OTC') if instrument.kind is WatchKind.INDEX else (instrument.exchange,)
        security = 'IND' if instrument.kind is WatchKind.INDEX else 'STK'
        if (
            contract is None
            or sdk_text(sdk_value(contract, 'code')) != instrument.code
            or sdk_text(sdk_value(contract, 'security_type')) != security
            or sdk_text(sdk_value(contract, 'exchange')) not in expected_exchange
        ):
            raise DomainError('symbol_not_found')
        return contract

    def subscribe(self, instrument: WatchInstrument) -> None:
        if instrument.instrument_id in self.subscriptions:
            return
        if len(self.subscriptions) + len(self.bidask_subscriptions) >= self.live_settings.subscription_limit:
            raise DomainError('subscription_limit_reached')
        try:
            contract = self._contract(instrument)
            info = self.facade.market_contract_info(contract)
            reference = getattr(info, 'reference', None)
            if reference is not None:
                reference = sdk_decimal(reference, 'reference')
                if reference > 0:
                    with self._quote_lock:
                        self._details.setdefault(instrument.instrument_id, {})['reference_price'] = reference
            self.tick_stream.by_code[instrument.code] = instrument.instrument_id
            self.tick_stream.set_active(set(self.subscriptions) | {instrument.instrument_id})
            self.facade.market_subscribe(contract)
            self.subscriptions[instrument.instrument_id] = contract
        except Exception:
            self.tick_stream.set_active(set(self.subscriptions))
            raise DomainError('market_data_subscription_failed' if self.connected else 'market_data_not_connected') from None

    def subscribe_bidask(self, instrument: WatchInstrument) -> None:
        """Five levels cost one subscription slot, counted with the tick subscriptions."""
        if instrument.instrument_id in self.bidask_subscriptions:
            return
        if instrument.kind is not WatchKind.STOCK:
            raise DomainError('validation_failed', 'bidask supports stocks only')
        if len(self.subscriptions) + len(self.bidask_subscriptions) >= self.live_settings.subscription_limit:
            raise DomainError('subscription_limit_reached')
        try:
            contract = self._contract(instrument)
            self.bidask_stream.by_code[instrument.code] = instrument.instrument_id
            self.bidask_stream.set_active(set(self.bidask_subscriptions) | {instrument.instrument_id})
            self.facade.market_subscribe_bidask(contract)
            self.bidask_subscriptions[instrument.instrument_id] = contract
        except Exception:
            self.bidask_stream.set_active(set(self.bidask_subscriptions))
            raise DomainError('market_data_subscription_failed' if self.connected else 'market_data_not_connected') from None

    def unsubscribe_bidask(self, instrument_id: str) -> None:
        contract = self.bidask_subscriptions.get(instrument_id)
        if contract is None:
            return
        try:
            self.facade.market_subscribe_bidask(contract, remove=True)
        except Exception:
            raise DomainError('market_data_not_connected') from None
        finally:
            del self.bidask_subscriptions[instrument_id]
            self.bidask_stream.set_active(set(self.bidask_subscriptions))

    def bidask(self, instrument_id: str):
        return self.bidask_stream.latest(instrument_id) if self.connected and self.bidask_stream is not None else None

    def unsubscribe(self, instrument_id: str) -> None:
        contract = self.subscriptions.get(instrument_id)
        if contract is None:
            return
        try:
            self.facade.market_subscribe(contract, remove=True)
        except Exception:
            raise DomainError('market_data_not_connected') from None
        del self.subscriptions[instrument_id]
        self.tick_stream.set_active(set(self.subscriptions))

    def disconnect(self) -> None:
        self.connected = False
        facade, self.facade = self.facade, None
        if self.tick_stream is not None:
            self.tick_stream.set_active(set())
        subscriptions, self.subscriptions = self.subscriptions, {}
        bidasks, self.bidask_subscriptions = self.bidask_subscriptions, {}
        if self.bidask_stream is not None:
            self.bidask_stream.set_active(set())
        with self._quote_lock:
            self._details.clear()
        if facade is None:
            return
        try:
            for contract in subscriptions.values():
                facade.market_subscribe(contract, remove=True)
            for contract in bidasks.values():
                facade.market_subscribe_bidask(contract, remove=True)
        except Exception:
            raise DomainError('market_data_not_connected') from None
        finally:
            try:
                if facade.logout() is False:
                    raise DomainError('market_data_not_connected', 'native logout unconfirmed')
            except Exception:
                raise DomainError('market_data_not_connected') from None

    def history(self, instrument: WatchInstrument, start: datetime, end: datetime) -> tuple[LiveBar, ...]:
        aware(start)
        aware(end)
        if not start < end or end - start > timedelta(days=29):
            raise DomainError('validation_failed', 'history query range')
        try:
            raw = self.facade.market_kbars(self._contract(instrument), start.astimezone(TAIPEI).date().isoformat(), end.astimezone(TAIPEI).date().isoformat())
            columns = [sdk_value(raw, key) for key in ('ts', 'Open', 'High', 'Low', 'Close', 'Volume')]
            if len({len(column) for column in columns}) != 1:
                raise DomainError('validation_failed', 'history column lengths')
            bars = []
            for stamp, opening, high, low, close, volume in zip(*columns):
                finish = history_time(stamp)
                begin = finish - timedelta(minutes=1)
                if not start <= begin < end:
                    continue
                prices = tuple(sdk_decimal(value, 'bar price') for value in (opening, high, low, close))
                if type(volume) is not int or volume < 0 or min(prices) <= 0 or prices[1] < max(prices) or prices[2] > min(prices):
                    raise DomainError('validation_failed', 'history OHLCV')
                bars.append(
                    LiveBar(instrument.instrument_id, begin, finish, finish.astimezone(TAIPEI).date(), 'DAY', *prices, volume, final=finish <= self.clock.now())
                )
            if not bars:
                self.usage()
            return tuple(sorted(bars, key=lambda bar: bar.start))
        except Exception:
            raise DomainError('market_data_not_connected') from None

    def usage(self) -> HistoryUsage | None:
        if not self.connected:
            return None
        try:
            raw = self.facade.usage()
            return HistoryUsage(sdk_value(raw, 'bytes'), sdk_value(raw, 'limit_bytes'))
        except Exception:
            return None

    def drain_ticks(self, max_items: int):
        return self.tick_stream.drain_ticks(max_items) if self.connected else ()

    def drain_tick_losses(self):
        return self.tick_stream.drain_tick_losses() if self.connected else ()
