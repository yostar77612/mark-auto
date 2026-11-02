"""Explicit official-history refresh; all-or-nothing daily/event publication."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json

from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.stock_history import StockPriceSeries, price_series
from quantlab.trading.domain.validation import DomainError, trading_date
from quantlab.trading.ports.stock_history import DailyStockStore, OfficialStockBatch, OfficialStockSource


def months_between(start: date, end: date) -> tuple[date, ...]:
    trading_date(start)
    trading_date(end)
    if start >= end or end.year - start.year > 20:
        raise DomainError('validation_failed', 'bounded nonempty history range required')
    result = []
    current = start.replace(day=1)
    while current < end:
        result.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return tuple(result)


class StockHistorySync:
    def __init__(self, store: DailyStockStore, source: OfficialStockSource):
        self.store, self.source = store, source

    def refresh(self, instrument_id: str, start: date, end: date, *, today: date, consent: bool = False) -> OfficialStockBatch:
        """End is exclusive; today's not-yet-final official bar is never accepted.

        Consent is per invocation and is never persisted. Even a late event or
        month failure leaves the entire previous interval untouched.
        """
        if consent is not True:
            raise DomainError('official_stock_consent_required')
        trading_date(today)
        if end > today:
            raise DomainError('official_stock_invalid', 'only already closed dates may be imported')
        bars, payloads, total_bytes = [], [], 0
        for month in months_between(start, end):
            observations, payload = self.source.month(instrument_id, month)
            bars.extend(b for b in observations if start <= b.trade_date < end)
            total_bytes += len(payload.raw)
            if total_bytes > 64 * 1024 * 1024:
                raise DomainError('official_stock_invalid', 'complete refresh byte limit')
            payloads.append(payload)
        events, payload = self.source.events(instrument_id, start, end)
        if total_bytes + len(payload.raw) > 64 * 1024 * 1024:
            raise DomainError('official_stock_invalid', 'complete refresh byte limit')
        payloads.append(payload)
        batch = OfficialStockBatch(instrument_id, start, end, tuple(bars), events, tuple(payloads))
        self.store.import_daily(batch)
        return batch

    def chart_prices(self, instrument_id: str, start: date, end: date, *, adjusted: bool = True) -> StockPriceSeries:
        """Minimal raw/adjusted data switch; never changes stored observations."""
        batch = self.store.daily_history(instrument_id, start, end)
        return price_series(batch.bars, batch.events, adjusted=adjusted)

    def research_inputs(self, instrument_id: str, start: date, end: date, calendar: TradingCalendar, fees: FeeSchedule) -> 'StockResearchInputs':
        batch = self._research_batch(instrument_id, start, end, calendar)
        return StockResearchInputs(batch, fees, calendar.version)

    def research_prices(self, instrument_id: str, start: date, end: date, calendar: TradingCalendar, *, adjusted: bool = True) -> StockPriceSeries:
        batch = self._research_batch(instrument_id, start, end, calendar)
        return price_series(batch.bars, batch.events, adjusted=adjusted)

    def _research_batch(self, instrument_id: str, start: date, end: date, calendar: TradingCalendar) -> OfficialStockBatch:
        """Require five calendar years and every explicitly expected trading day.

        Successful monthly queries alone do not certify complete observations.
        A suspension/young listing with absent bars remains insufficient rather
        than fabricating zero-volume days or issuing partial research evidence.
        """
        try:
            five_years_ago = end.replace(year=end.year - 5)
        except ValueError:
            five_years_ago = end.replace(year=end.year - 5, day=28)
        if start > five_years_ago or not self.store.daily_coverage(instrument_id, start, end):
            raise DomainError('official_stock_coverage_missing', 'at least five years of explicit daily coverage required')
        expected = tuple(day for day in calendar.days if start <= day < end)
        if not expected or calendar.days[0] > start or calendar.days[-1] < end:
            raise DomainError('calendar_missing', 'calendar must cover the complete research range')
        batch = self.store.daily_history(instrument_id, start, end)
        if tuple(b.trade_date for b in batch.bars) != expected:
            raise DomainError('official_stock_coverage_missing', 'daily observations do not match the verified calendar')
        return batch


@dataclass(frozen=True)
class StockResearchInputs:
    """Explicit training-only input bundle, not a completed backtest claim.

    Signals request point-in-time adjusted history. Fills/accounting consume
    batch.bars (raw) and the same immutable fees used by simulation/risk.
    The metadata includes empty event responses as well as observed events.
    """

    batch: OfficialStockBatch
    fees: FeeSchedule
    calendar_version: str

    def signals_at(self, closed_date: date) -> StockPriceSeries:
        return price_series(self.batch.bars, self.batch.events, as_of=closed_date)

    def evidence(self) -> tuple[tuple[str, str], ...]:
        series = price_series(self.batch.bars, self.batch.events)
        sources = json.dumps(sorted((p.source_url, p.digest) for p in self.batch.payloads), separators=(',', ':'))
        return (
            *series.evidence(),
            ('partition', 'TRAINING'),
            ('cost_version', self.fees.version),
            ('calendar_version', self.calendar_version),
            ('official_sources', sources),
            ('sources_digest', sha256(sources.encode()).hexdigest()),
            ('signal_prices', 'point-in-time-adjusted'),
            ('execution_and_pnl_prices', 'RAW'),
        )
