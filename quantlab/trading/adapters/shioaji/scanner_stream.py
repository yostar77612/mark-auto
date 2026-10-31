"""SDK scanner presets and bounded, typed delivery across the callback thread."""

from collections import deque
from dataclasses import replace
import logging
from threading import Lock

from quantlab.trading.domain.alerts import AlertKind, AlertObservation
from quantlab.trading.domain.validation import DomainError, decimal_value, identity
from .sdk import sdk_decimal, sdk_text, sdk_time, sdk_value
from .sdk_facade import ShioajiSDKFacade

logger = logging.getLogger(__name__)


class ShioajiScannerStream:
    """Only enabled scanner kinds receive both Taiwan stock-exchange streams.

    Vendor signals are events, so drain emits a false/true pulse for each event.
    This re-arms edge state while the per-rule/per-instrument cooldown still
    suppresses repeated vendor signals. No account or trading capability exists.
    """

    def __init__(self, facade: ShioajiSDKFacade, sdk_module):
        self.facade, self.sdk = facade, sdk_module
        limit, move, volume = sdk_module.LimitScanner, sdk_module.PriceMoveScanner, sdk_module.VolumeScanner
        self.presets = (
            (AlertKind.LIMIT_UP, 'NEAR', 'UP', limit.bid_near_limit_up()),
            (AlertKind.LIMIT_UP, 'TOUCH', 'UP', limit.bid_touch_limit_up()),
            (AlertKind.LIMIT_UP, 'OPEN', 'DOWN', limit.limit_up_unlocked()),
            (AlertKind.LIMIT_DOWN, 'NEAR', 'DOWN', limit.ask_near_limit_down()),
            (AlertKind.LIMIT_DOWN, 'TOUCH', 'DOWN', limit.ask_touch_limit_down()),
            (AlertKind.LIMIT_DOWN, 'OPEN', 'UP', limit.limit_down_unlocked()),
            (AlertKind.PRICE_JUMP, '', 'UP', move.trade_surge()),
            (AlertKind.PRICE_JUMP, '', 'DOWN', move.trade_drop()),
            (AlertKind.VOLUME_BURST, '', 'ANY', volume.burst()),
        )
        self.by_id = {preset.id: (kind, subtype, direction) for kind, subtype, direction, preset in self.presets}
        self.kinds: frozenset[AlertKind] = frozenset()
        self._subscriptions = {}
        self._lock = Lock()
        self._queue: deque[AlertObservation] = deque(maxlen=1000)
        self.warning = ''
        self.facade.set_on_scanner_callback(self.on_event)

    def set_kinds(self, kinds: frozenset[AlertKind]) -> None:
        """Reconcile enabled kinds without subscribing twice on unchanged rules."""
        desired = {
            (preset.id, sdk_text(exchange)): (preset, exchange)
            for kind, _, _, preset in self.presets
            if kind in kinds
            for exchange in (self.sdk.Exchange.TSE, self.sdk.Exchange.OTC)
        }
        self.kinds = kinds
        for key in tuple(self._subscriptions):
            if key not in desired:
                self._subscription(self.facade.unsubscribe_scanner, *self._subscriptions[key])
                del self._subscriptions[key]
        for key, values in desired.items():
            if key not in self._subscriptions:
                self._subscription(self.facade.subscribe_scanner, *values)
                self._subscriptions[key] = values

    def _subscription(self, operation, preset, exchange):
        try:
            operation(preset, region=self.sdk.Region.TW, security_type=self.sdk.SecurityType.Stock, exchange=exchange)
        except (self.sdk.ShioajiError, OSError):
            raise DomainError('market_data_not_connected', 'scanner subscription') from None

    def on_event(self, raw: object) -> None:
        """Normalize only SDK boundary fields; never log raw vendor messages."""
        try:
            # Quote-scanner and gap events share this callback with signal events.
            if not hasattr(raw, 'scanner'):
                if hasattr(raw, 'dropped_count'):
                    self.warning = 'alert.scanner_gap'
                return
            kind, subtype, direction = self.by_id[sdk_value(raw, 'scanner').id]
            if kind not in self.kinds:
                return
            exchange = sdk_text(sdk_value(raw, 'exchange'))
            if exchange not in ('TSE', 'OTC'):
                return
            quote = sdk_value(raw, 'quote')
            code = sdk_text(sdk_value(quote, 'code'))
            instrument_id = ('TWSE:' if exchange == 'TSE' else 'TPEX:') + code
            identity(instrument_id)
            price = decimal_value(sdk_decimal(sdk_value(quote, 'close'), 'scanner price'), 'scanner price', positive=True)
            observation = AlertObservation(
                instrument_id,
                sdk_time(sdk_value(quote, 'datetime')),
                price=price,
                scanner_kind=kind,
                scanner_subtype=subtype,
                scanner_direction=direction,
            )
            with self._lock:
                if len(self._queue) == self._queue.maxlen:
                    self.warning = 'alert.scanner_gap'
                self._queue.append(observation)
        except (DomainError, KeyError, AttributeError, TypeError, ValueError):
            logger.error('Shioaji scanner callback rejected; delivery continues')

    def drain(self) -> tuple[AlertObservation, ...]:
        with self._lock:
            pending = tuple(self._queue)
            self._queue.clear()
        return tuple(item for event in pending for item in (replace(event, scanner_active=False), event))

    def close(self) -> None:
        self.set_kinds(frozenset())
        with self._lock:
            self._queue.clear()
