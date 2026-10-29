"""Facade callback registration, SDK normalization and bounded tick delivery.

No bars, calendar guesses, aggregation or freshness calculations belong here.
The SDK thread only translates and appends under a short lock; the consumer
drains independently. Loss envelopes coalesce by instrument, bounding metadata
by the active subscription count rather than by the number of lost ticks.
"""

from collections import deque
from datetime import datetime
import logging
from threading import Lock
from typing import Callable

from quantlab.trading.domain.freshness import LiveMarketSettings
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError, integer
from quantlab.trading.ports.interfaces import Clock
from quantlab.trading.ports.tick_stream import TickLoss
from .sdk import InstrumentBinding, TradeDateResolver, sdk_decimal, sdk_text, sdk_time, sdk_value
from .sdk_facade import ShioajiSDKFacade

logger = logging.getLogger(__name__)


def normalise_tick(raw: object, instrument_id: str, received_at: datetime, resolver: TradeDateResolver | None) -> Tick:
    """Validate SDK input once, including Domain Tick's ordering/session rules."""
    if resolver is None:
        raise DomainError('calendar_missing', 'explicit trade-date/session mapping required')
    source_at = sdk_time(sdk_value(raw, 'datetime'))
    trade_date, session = resolver.session_at(instrument_id, source_at)
    return Tick(
        instrument_id,
        sdk_decimal(sdk_value(raw, 'close'), 'tick price'),
        sdk_value(raw, 'volume'),
        source_at,
        received_at,
        trade_date,
        session,
        source='SHIOAJI',
    )


class ShioajiTickStream:
    def __init__(
        self,
        facade: ShioajiSDKFacade,
        clock: Clock,
        bindings: tuple[InstrumentBinding, ...],
        resolver: TradeDateResolver | None,
        connected: Callable[[], bool],
        settings: LiveMarketSettings,
        session_down: Callable[..., None],
    ) -> None:
        self.facade, self.clock, self.resolver, self.connected = facade, clock, resolver, connected
        self.by_code = {binding.sdk_code: binding.spec.instrument_id for binding in bindings}
        self.limit = settings.queue_limit
        self._lock = Lock()
        self._ticks: deque[Tick] = deque()
        self._losses: dict[str, TickLoss] = {}
        self._active: frozenset[str] = frozenset()
        self._registered = False
        self.session_down = session_down

    def start(self) -> None:
        if not self._registered:
            self.facade.set_on_tick_stk_v1_callback(self.on_tick)
            self.facade.set_on_tick_fop_v1_callback(self.on_tick)
            self.facade.set_session_down_callback(self.session_down)
            self._registered = True

    def set_active(self, instrument_ids: set[str]) -> None:
        with self._lock:
            self._active = frozenset(instrument_ids)
            self._ticks = deque(tick for tick in self._ticks if tick.instrument_id in self._active)
            self._losses = {key: loss for key, loss in self._losses.items() if key in self._active}

    def on_tick(self, exchange: object, raw: object) -> None:
        """The single callback guard; never expose vendor exception text."""
        try:
            if not self.connected():
                return
            instrument_id = self.by_code[sdk_text(sdk_value(raw, 'code'))]
            with self._lock:
                if instrument_id not in self._active:
                    return
            tick = normalise_tick(raw, instrument_id, self.clock.now(), self.resolver)
            with self._lock:
                if instrument_id not in self._active:
                    return
                if len(self._ticks) < self.limit:
                    self._ticks.append(tick)
                else:
                    previous = self._losses.get(instrument_id)
                    self._losses[instrument_id] = TickLoss(
                        instrument_id,
                        min(previous.first_source_at, tick.source_at) if previous else tick.source_at,
                        max(previous.last_source_at, tick.source_at) if previous else tick.source_at,
                        previous.count + 1 if previous else 1,
                    )
        except Exception:
            logger.error('Shioaji tick callback rejected; delivery continues')

    def drain_ticks(self, max_items: int) -> tuple[Tick, ...]:
        integer(max_items, 'tick drain budget')
        with self._lock:
            return tuple(self._ticks.popleft() for _ in range(min(max_items, len(self._ticks))))

    def drain_tick_losses(self) -> tuple[TickLoss, ...]:
        with self._lock:
            result = tuple(self._losses.values())
            self._losses.clear()
            return result
