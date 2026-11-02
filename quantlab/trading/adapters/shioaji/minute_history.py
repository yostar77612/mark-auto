"""Read-only M1 history binding for explicitly resolved TMF delivery contracts.

No login, CA, order or continuous-contract substitution. The existing gateway
owns authenticated session lifetime and authoritative InstrumentBinding checks.
"""

from datetime import datetime, timedelta

from quantlab.trading.domain.calendar import TradingCalendar
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.minute_research import TAIPEI
from quantlab.trading.domain.minute_contract import is_tmf_contract
from quantlab.trading.domain.validation import DomainError, aware
from quantlab.trading.ports.history import HistoryTarget, HistoryUsage
from .market_data import MarketDataContext
from .market_session import history_time
from .sdk import sdk_decimal, sdk_value


class TMFMinuteHistorySession:
    def __init__(self, context: MarketDataContext, calendar: TradingCalendar):
        self.context, self.calendar = context, calendar

    @property
    def connected(self) -> bool:
        return self.context.connected

    def usage(self) -> HistoryUsage | None:
        if not self.connected:
            return None
        try:
            raw = self.context.client.usage()
            return HistoryUsage(sdk_value(raw, 'bytes'), sdk_value(raw, 'limit_bytes'))
        except Exception:
            return None  # history() independently refuses unknown quota.

    def history(self, instrument: HistoryTarget, start: datetime, end: datetime) -> tuple[LiveBar, ...]:
        aware(start)
        aware(end)
        if not self.connected or not start < end or end - start > timedelta(days=29):
            raise DomainError('capability_missing', 'connected bounded TMF history required')
        usage = self.usage()
        if usage is None or usage.used_bytes >= min(usage.limit_bytes, 500 * 1024 * 1024) * 9 // 10:
            raise DomainError('history_quota_low', 'known TMF history quota required')
        spec = self.context.resolve(instrument.instrument_id)
        if not is_tmf_contract(spec):
            raise DomainError('instrument_unresolved', 'actual TMF contract required')
        binding = self.context.bindings[spec.instrument_id]
        try:
            contract = self.context.client.contracts.get(binding.sdk_code)
            raw = self.context.client.kbars(contract=contract, start=start.astimezone(TAIPEI).date().isoformat(), end=end.astimezone(TAIPEI).date().isoformat())
            rows = self._bars(raw, spec.instrument_id, start, end)
        except Exception:
            raise DomainError('market_data_not_connected', 'TMF history failed') from None
        if not self.connected:
            raise DomainError('market_data_not_connected', 'TMF session ended during history query')
        return rows

    def _bars(self, raw, instrument_id, start, end):
        columns = [sdk_value(raw, key) for key in ('ts', 'Open', 'High', 'Low', 'Close', 'Volume')]
        if len({len(column) for column in columns}) != 1:
            raise DomainError('validation_failed', 'TMF history column lengths')
        bars, seen = [], set()
        for stamp, opening, high, low, close, volume in zip(*columns):
            finish = history_time(stamp)
            begin = finish - timedelta(minutes=1)
            if not start <= begin < end:
                continue
            session = next((s for s in self.calendar.sessions if s.kind == 'DAY' and s.opens_at <= begin < s.closes_at), None)
            if session is None:
                continue  # Never treat overnight or unverified sessions as DAY.
            if begin in seen:
                raise DomainError('validation_failed', 'duplicate TMF history minute')
            seen.add(begin)
            if finish > session.closes_at:
                raise DomainError('calendar_missing', 'TMF minute crosses session boundary')
            prices = tuple(sdk_decimal(value, 'TMF bar price') for value in (opening, high, low, close))
            bars.append(LiveBar(instrument_id, begin, finish, session.trade_date, 'DAY', *prices, volume, final=finish <= self.context.clock.now()))
        return tuple(sorted(bars, key=lambda bar: bar.start))
