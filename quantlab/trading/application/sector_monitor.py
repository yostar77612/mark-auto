"""Automatic money-flow monitoring of the leading sector groups (alert B).

Lock order: this class never calls the sector service or the session while holding its own lock, and the
sector service may call back into it (board views) while holding the service lock.
"""

from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from quantlab.trading.domain.sector import SectorStat
from quantlab.trading.domain.sector_alerts import SectorAlert, SectorAlertParams, in_alert_window
from quantlab.trading.domain.sector_flow import BASELINE_MINUTES, WARMUP_MINUTES, FlowMinute, MonitorSelector, allocate, judge_flow, tick_amount
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument

_TAIPEI = ZoneInfo('Asia/Taipei')
_MINUTE = timedelta(minutes=1)


class TickSubscriptionsPort(Protocol):
    def free_slots(self) -> int: ...
    def is_subscribed(self, instrument_id: str) -> bool: ...
    def subscribe(self, instrument: WatchInstrument) -> None: ...
    def unsubscribe(self, instrument_id: str) -> None: ...


class SectorMonitor:
    def __init__(
        self,
        candidates: Callable[[str], tuple[tuple[WatchInstrument, int], ...]],
        subscriptions: TickSubscriptionsPort,
        params: Callable[[], SectorAlertParams],
        name_of: Callable[[str], str],
    ):
        self.candidates, self.subscriptions, self.params, self.name_of = candidates, subscriptions, params, name_of
        self.lock = RLock()
        self._selector = MonitorSelector()
        self._selected_minute: datetime | None = None
        self._added: dict[str, WatchInstrument] = {}  # subscriptions this monitor owns, by instrument id
        self._groups: tuple[str, ...] = ()
        self._counts: tuple[tuple[str, int, int], ...] = ()
        self._code_groups: dict[str, tuple[str, ...]] = {}
        self._buckets: dict[tuple[str, datetime], list[int]] = {}
        self._history: dict[str, deque[FlowMinute]] = {}
        self._finalized: dict[str, datetime] = {}
        self._since: dict[str, datetime] = {}
        self._sides: dict[str, list[int]] = {}
        self._last_alert: dict[tuple[str, str], datetime] = {}

    # --- views ---------------------------------------------------------------
    def info(self) -> tuple[tuple[str, ...], tuple[tuple[str, int, int], ...]]:
        with self.lock:
            return self._groups, self._counts

    def side_ratio(self, code: str) -> Decimal | None:
        with self.lock:
            buy, sell = self._sides.get(code, (0, 0))
        return Decimal(buy) / Decimal(buy + sell) if buy + sell else None

    # --- subscription ownership ---------------------------------------------------------
    def claim(self, instrument_id: str) -> None:
        """The terminal now wants this instrument itself; it becomes the terminal's, not ours to drop."""
        with self.lock:
            self._added.pop(instrument_id, None)

    def release_one(self) -> bool:
        """Give a slot back to a higher-priority user (index > selected > watchlist > monitoring)."""
        with self.lock:
            if not self._added:
                return False
            instrument_id = next(reversed(self._added))
            del self._added[instrument_id]
        try:
            self.subscriptions.unsubscribe(instrument_id)
        except DomainError:
            pass
        return True

    def disconnected(self) -> None:
        with self.lock:
            self._selector.reset()
            self._selected_minute = None
            self._added, self._groups, self._counts, self._code_groups = {}, (), (), {}
            self._buckets, self._history, self._finalized, self._since, self._sides = {}, {}, {}, {}, {}

    # --- ticks (engine thread) ---------------------------------------------------------------
    def on_ticks(self, ticks: tuple[Tick, ...]) -> None:
        params = self.params()
        with self.lock:
            if not self._code_groups:
                return
            for tick in ticks:
                if tick.side == 'NONE':
                    continue
                code = tick.instrument_id.rsplit(':', 1)[-1]
                groups = self._code_groups.get(code)
                if not groups:
                    continue
                amount = tick_amount(tick.price, tick.volume)
                minute = tick.source_at.astimezone(_TAIPEI).replace(second=0, microsecond=0)
                buy = tick.side == 'BUY'
                side = self._sides.setdefault(code, [0, 0])
                side[0 if buy else 1] += amount
                for group_id in groups:
                    bucket = self._buckets.setdefault((group_id, minute), [0, 0, 0, 0])
                    bucket[0 if buy else 1] += amount
                    if amount >= params.big_order:
                        bucket[2 if buy else 3] += amount

    # --- rounds (poller thread) -----------------------------------------------------------------
    def on_round(self, now: datetime, stats: tuple[SectorStat, ...]) -> tuple[SectorAlert, ...]:
        params = self.params()
        minute = now.astimezone(_TAIPEI).replace(second=0, microsecond=0)
        with self.lock:
            reselect = self._selected_minute != minute
            if reselect:
                self._selected_minute = minute
                groups = self._selector.update(stats, now, params)
        if reselect:
            self._apply_selection(groups, now, params)
        return self._finalize(minute, params)

    def _apply_selection(self, groups: tuple[str, ...], now: datetime, params: SectorAlertParams) -> None:
        # Outside our lock: candidate lookup takes the service lock, subscribing talks to the SDK.
        members = {group_id: self.candidates(group_id) for group_id in groups}
        budget = min(params.monitor_budget, self.subscriptions.free_slots() + len(self._added)) if groups else 0
        plan = allocate(tuple((group_id, tuple((item.code, amount) for item, amount in members[group_id])) for group_id in groups), budget)
        instruments = {item.code: item for pairs in members.values() for item, _ in pairs}
        wanted = {instruments[code].instrument_id: instruments[code] for code in plan.codes}
        with self.lock:
            stale = [instrument_id for instrument_id in self._added if instrument_id not in wanted]
            for instrument_id in stale:
                del self._added[instrument_id]
        for instrument_id in stale:
            try:
                self.subscriptions.unsubscribe(instrument_id)
            except DomainError:
                pass
        receiving = set()
        for instrument_id, instrument in wanted.items():
            if self.subscriptions.is_subscribed(instrument_id):
                receiving.add(instrument.code)
                continue
            try:
                self.subscriptions.subscribe(instrument)
            except DomainError:
                break  # budget exhausted or the broker refused: degrade, never fail the board
            with self.lock:
                self._added[instrument_id] = instrument
            receiving.add(instrument.code)
        with self.lock:
            for group_id in groups:
                if group_id not in self._since:
                    self._since[group_id] = now
            for group_id in tuple(self._since):
                if group_id not in groups:
                    del self._since[group_id]
                    self._history.pop(group_id, None)
                    self._finalized.pop(group_id, None)
            self._groups = groups
            self._counts = tuple((group_id, sum(1 for item, _ in members[group_id] if item.code in receiving), len(members[group_id])) for group_id in groups)
            code_groups: dict[str, list[str]] = {}
            for group_id in groups:
                for item, _ in members[group_id]:
                    if item.code in receiving:
                        code_groups.setdefault(item.code, []).append(group_id)
            self._code_groups = {code: tuple(ids) for code, ids in code_groups.items()}

    def _finalize(self, current: datetime, params: SectorAlertParams) -> tuple[SectorAlert, ...]:
        alerts = []
        with self.lock:
            for group_id in self._groups:
                since = self._since.get(group_id)
                if since is None:
                    continue
                first = since.astimezone(_TAIPEI).replace(second=0, microsecond=0) + _MINUTE
                minute = self._finalized.get(group_id, first - _MINUTE) + _MINUTE
                history = self._history.setdefault(group_id, deque(maxlen=BASELINE_MINUTES + 10))
                while minute < current:
                    buy, sell, big_buy, big_sell = self._buckets.pop((group_id, minute), (0, 0, 0, 0))
                    history.append(FlowMinute(minute, buy - sell, big_buy - big_sell))
                    self._finalized[group_id] = minute
                    alert = self._flow_alert(group_id, minute, since, tuple(history), params)
                    if alert is not None:
                        alerts.append(alert)
                    minute += _MINUTE
            for key in [key for key in self._buckets if key[1] < current - _MINUTE * 2]:
                del self._buckets[key]
        return tuple(alerts)

    def _flow_alert(self, group_id: str, minute: datetime, since: datetime, history: tuple[FlowMinute, ...], params: SectorAlertParams) -> SectorAlert | None:
        if not params.flow_enabled or not in_alert_window(minute, _TAIPEI, params):
            return None
        if minute + _MINUTE - since < timedelta(minutes=WARMUP_MINUTES):
            return None
        result = judge_flow(history, params)
        if result is None:
            return None
        direction, net, big, minutes = result
        last = self._last_alert.get((group_id, direction))
        if last is not None and minute - last < timedelta(minutes=params.cooldown_minutes):
            return None
        self._last_alert[(group_id, direction)] = minute
        counts = {gid: (monitored, total) for gid, monitored, total in self._counts}
        monitored, total = counts.get(group_id, (0, 0))
        return SectorAlert(minute, group_id, self.name_of(group_id), 'FLOW', direction, net, minutes, None, big, total, monitored)
