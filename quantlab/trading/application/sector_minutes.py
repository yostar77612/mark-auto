"""Minute roll-up of snapshot rounds and burst alerts (A); the last round of a minute is that minute's state."""

from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from quantlab.trading.domain.sector import SectorStat
from quantlab.trading.domain.sector_alerts import SESSION_OPEN, MinuteStat, SectorAlert, SectorAlertParams, in_alert_window, judge_burst, minute_direction
from quantlab.trading.domain.validation import DomainError

_TAIPEI = ZoneInfo('Asia/Taipei')
_MINUTE = timedelta(minutes=1)


def _bps(value: Decimal | None) -> int:
    return 0 if value is None else int((value * 100).to_integral_value())


class MinuteAggregator:
    """Feed rounds in time order; finished minutes are stored and judged exactly once."""

    def __init__(self, store, params: Callable[[], SectorAlertParams], name_of: Callable[[str], str]):
        self.store, self.params, self.name_of = store, params, name_of
        self._day: date | None = None
        self._pending_minute: datetime | None = None
        self._pending: dict[str, SectorStat] = {}
        self._previous_minute: datetime | None = None
        self._previous: dict[str, tuple[int, int, int]] = {}  # group -> (cumulative amount, equal pct bps, valid members)
        self._history: dict[str, deque[int]] = {}
        self._last_alert: dict[tuple[str, str], datetime] = {}
        self.warning = ''

    def _reset(self, day: date) -> None:
        self._day, self._pending_minute, self._pending = day, None, {}
        self._previous_minute, self._previous, self._history, self._last_alert = None, {}, {}, {}
        try:
            self.store.purge(day)
            for item in self.store.load_day(day):
                if item.complete and item.minute.astimezone(_TAIPEI).time() >= SESSION_OPEN:
                    self._history.setdefault(item.group_id, deque(maxlen=60)).append(item.amount)
            self._last_alert = self.store.alert_marks(day, 'BURST')
        except DomainError:
            self.warning = 'sector_minutes_unavailable'

    def on_round(self, now: datetime, stats: tuple[SectorStat, ...]) -> tuple[SectorAlert, ...]:
        local = now.astimezone(_TAIPEI)
        minute = local.replace(second=0, microsecond=0)
        if self._day != local.date():
            self._reset(local.date())
        alerts: tuple[SectorAlert, ...] = ()
        if self._pending_minute is not None and minute > self._pending_minute:
            alerts = self._finish()
        if self._pending_minute is None or minute > self._pending_minute:
            self._pending_minute = minute
        self._pending = {item.group_id: item for item in stats}
        return alerts

    def _finish(self) -> tuple[SectorAlert, ...]:
        minute = self._pending_minute
        continuous = self._previous_minute is not None and minute - self._previous_minute == _MINUTE
        params, rows, alerts = self.params(), [], []
        for group_id, stat in self._pending.items():
            previous = self._previous.get(group_id)
            delta = stat.amount - previous[0] if previous is not None else None
            # A changed member count (a quote dropping out or returning, a group edit) moves the cumulative
            # amount without any trading, so that minute is not comparable with the previous one.
            complete = continuous and delta is not None and delta >= 0 and previous[2] == stat.valid_count
            pct = _bps(stat.equal_pct)
            share = int((stat.share * 10000).to_integral_value()) if stat.share is not None else 0
            breadth = int((stat.breadth * 10000).to_integral_value()) if stat.breadth is not None else 0
            rows.append(
                MinuteStat(
                    minute.astimezone(timezone.utc),
                    group_id,
                    delta if complete else 0,
                    stat.amount,
                    share,
                    pct,
                    breadth,
                    stat.limit_up,
                    stat.limit_down,
                    stat.valid_count,
                    complete,
                )
            )
            if complete:
                history = self._history.setdefault(group_id, deque(maxlen=60))
                alert = self._burst(minute, group_id, stat, delta, pct - previous[1], tuple(history), params)
                if minute.time() >= SESSION_OPEN:
                    history.append(delta)  # pre-open minutes carry no turnover and would dilute the baseline
                if alert is not None:
                    alerts.append(alert)
        try:
            self.store.append(tuple(rows), minute.date())
        except DomainError:
            self.warning = 'sector_minutes_unavailable'
        self._previous = {group_id: (stat.amount, _bps(stat.equal_pct), stat.valid_count) for group_id, stat in self._pending.items()}
        self._previous_minute = minute
        return tuple(alerts)

    def _burst(self, minute, group_id, stat, delta, pct_change, history, params) -> SectorAlert | None:
        if not params.burst_enabled or not in_alert_window(minute, _TAIPEI, params):
            return None
        fired, baseline = judge_burst(delta, history, params)
        if not fired:
            return None
        direction = minute_direction(pct_change, params.direction_pct)
        last = self._last_alert.get((group_id, direction))
        if last is not None and minute - last < timedelta(minutes=params.cooldown_minutes):
            return None
        self._last_alert[(group_id, direction)] = minute
        try:
            self.store.mark_alert(minute.date(), 'BURST', group_id, direction, minute)
        except DomainError:
            self.warning = 'sector_minutes_unavailable'
        return SectorAlert(
            minute,
            group_id,
            self.name_of(group_id),
            'BURST',
            direction,
            delta,
            baseline,
            Decimal(delta) / Decimal(baseline),
            members=stat.valid_count,
        )
