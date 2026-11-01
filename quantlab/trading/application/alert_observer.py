"""Convert live ticks and completed cached series into eligible alert observations."""

from datetime import date, datetime, time
from typing import Callable
from zoneinfo import ZoneInfo

from quantlab.trading.domain.alerts import BAR_KINDS, AlertKind, AlertObservation
from quantlab.trading.domain.freshness import Freshness
from quantlab.trading.domain.live_bars import LiveBar, aggregate_bars
from quantlab.trading.domain.ticks import Tick
from .alert_service import AlertService
from .contracts import MarketWatchView


class AlertTickObserver:
    def __init__(
        self, service: AlertService, facts: Callable[[str], MarketWatchView], history: Callable[[str], tuple[LiveBar, ...]], backfilling: Callable[[str], bool]
    ):
        self.service, self.facts, self.history, self.backfilling = service, facts, history, backfilling
        self._previous = {}
        self._days = {}
        self._seeds = {}
        self._prior_range = {}
        self._ends = {}
        self._minute_ends = {}

    def reset(self, instrument_id: str):
        """Reseed after official history completes; retain service cooldown/edges."""
        self._days.pop(instrument_id, None)
        self._seeds.pop(instrument_id, None)
        self._previous.pop(instrument_id, None)
        self._prior_range.pop(instrument_id, None)
        self._minute_ends.pop(instrument_id, None)
        self._ends = {key: end for key, end in self._ends.items() if key[0] != instrument_id}

    def _new_day(self, tick: Tick):
        key, day = tick.instrument_id, tick.trade_date
        self._days[key] = day
        seed = tuple(bar for bar in self.history(key) if bar.end <= tick.source_at and bar.final)
        self._seeds[key] = seed
        before = tuple(bar for bar in seed if bar.trade_date < day)
        previous_day = before[-1].trade_date if before else None
        previous = tuple(bar for bar in before if bar.trade_date == previous_day)
        self._prior_range[key] = (max((bar.high for bar in previous), default=None), min((bar.low for bar in previous), default=None))
        today = tuple(bar for bar in seed if bar.trade_date == day)
        self._previous[key] = (None, max((bar.high for bar in today), default=None), min((bar.low for bar in today), default=None))
        self._ends = {pair: end for pair, end in self._ends.items() if pair[0] != key}
        self._minute_ends.pop(key, None)

    def on_tick(self, tick: Tick, memory: tuple[LiveBar, ...]):
        key = tick.instrument_id
        if self._days.get(key) != tick.trade_date:
            self._new_day(tick)
        price, high, low = self._previous[key]
        previous_high, previous_low = self._prior_range[key]
        facts = self.facts(key)
        now = tick.source_at.astimezone(ZoneInfo('Asia/Taipei'))
        observation = AlertObservation(
            key,
            tick.source_at,
            tick.price,
            price,
            facts.reference_price,
            previous_high,
            previous_low,
            high,
            low,
            (now.hour * 60 + now.minute) - 540,
            Freshness(facts.health.freshness),
            self.backfilling(key),
        )
        emitted = self.service.observe(observation)
        self._previous[key] = (tick.price, tick.price if high is None else max(high, tick.price), tick.price if low is None else min(low, tick.price))
        if observation.freshness == Freshness.LIVE and not observation.backfilling:
            emitted += self.on_bars(key, memory, tick.source_at, tick.trade_date)
        return emitted

    def on_bars(self, instrument_id: str, memory: tuple[LiveBar, ...], occurred_at: datetime, trade_date: date):
        """Evaluate newly closed periods; the caller supplies only live, non-backfill bars."""
        if instrument_id not in self._seeds:
            return ()
        closed = occurred_at.astimezone(ZoneInfo('Asia/Taipei')).time() >= time(13, 30)
        finals = tuple(bar for bar in memory if bar.final and bar.end <= occurred_at)
        if not finals or self._minute_ends.get(instrument_id) == finals[-1].end:
            return ()
        self._minute_ends[instrument_id] = finals[-1].end
        by_start = {bar.start: bar for bar in (*self._seeds[instrument_id], *memory) if bar.start <= occurred_at and (not bar.final or bar.end <= occurred_at)}
        bars = tuple(sorted(by_start.values(), key=lambda bar: bar.start))
        periods = {
            '1m' if rule.kind == AlertKind.FAST_MOVE else rule.params['period'] for rule in self.service.rules if rule.enabled and rule.kind in BAR_KINDS
        }
        emitted = ()
        for period in periods:
            series = bars if period == '1m' else aggregate_bars(bars, period, now=occurred_at, trade_date_closed=True)
            finals = tuple(bar for bar in series if bar.final and (period != '1d' or bar.trade_date < trade_date or closed))
            if not finals:
                continue
            key = instrument_id, period
            end = finals[-1].end
            previous = self._ends.get(key)
            self._ends[key] = end
            if previous is None or end <= previous:
                continue
            emitted += self.service.observe(AlertObservation(instrument_id, occurred_at, bars=finals, period=period))
        return emitted
