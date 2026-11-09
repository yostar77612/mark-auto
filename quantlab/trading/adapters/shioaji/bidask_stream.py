"""Latest-only five-level quote delivery for the selected stock; never queues.

The SDK thread only translates and replaces one slot under a short lock.
Vendor exception text is never exposed.
"""

import logging
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

from quantlab.trading.domain.bidask import LEVELS, BidAskSnapshot
from .sdk import sdk_decimal, sdk_text, sdk_time, sdk_value

logger = logging.getLogger(__name__)
_TAIPEI = ZoneInfo('Asia/Taipei')


def normalise_bidask(raw: object, instrument_id: str) -> BidAskSnapshot:
    stamp = sdk_value(raw, 'datetime')
    if isinstance(stamp, datetime) and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_TAIPEI)
    stamp = sdk_time(stamp)
    bid_prices, ask_prices = sdk_value(raw, 'bid_price'), sdk_value(raw, 'ask_price')
    bid_volumes, ask_volumes = sdk_value(raw, 'bid_volume'), sdk_value(raw, 'ask_volume')
    if any(len(column) < LEVELS for column in (bid_prices, ask_prices, bid_volumes, ask_volumes)):
        raise ValueError('bidask levels')
    return BidAskSnapshot(
        instrument_id,
        stamp,
        tuple(sdk_decimal(value, 'bid price') for value in bid_prices[:LEVELS]),
        tuple(bid_volumes[:LEVELS]),
        tuple(sdk_decimal(value, 'ask price') for value in ask_prices[:LEVELS]),
        tuple(ask_volumes[:LEVELS]),
    )


class ShioajiBidAskStream:
    def __init__(self, by_code: dict[str, str]) -> None:
        self.by_code = by_code
        self._lock = Lock()
        self._active: frozenset[str] = frozenset()
        self._latest: dict[str, BidAskSnapshot] = {}

    def set_active(self, instrument_ids: set[str]) -> None:
        with self._lock:
            self._active = frozenset(instrument_ids)
            self._latest = {key: value for key, value in self._latest.items() if key in self._active}

    def on_bidask(self, exchange: object, raw: object) -> None:
        try:
            instrument_id = self.by_code[sdk_text(sdk_value(raw, 'code'))]
            with self._lock:
                if instrument_id not in self._active:
                    return
            snapshot = normalise_bidask(raw, instrument_id)
            with self._lock:
                if instrument_id in self._active:
                    self._latest[instrument_id] = snapshot
        except Exception:
            logger.error('Shioaji bidask callback rejected; delivery continues')

    def latest(self, instrument_id: str) -> BidAskSnapshot | None:
        with self._lock:
            return self._latest.get(instrument_id)
