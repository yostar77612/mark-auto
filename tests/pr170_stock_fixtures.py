"""Deterministic synthetic official-style stock history for PR #170 characterization tests."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.stock_history import CashDividendAction, CorporateAction, DailyStockBar

D = Decimal
INSTRUMENT = 'TWSE:2330'


def weekdays(first, count):
    day, result = first, []
    while len(result) < count:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def synthetic_history(count, *, events=(), first=date(2010, 1, 4), instrument=INSTRUMENT):
    """`events` are (bar_index, ratio_numerator, ratio_denominator, cash_only) tuples; ex-date is that bar's date."""
    days = weekdays(first, count)
    bars, price, state = [], D('100.25'), 12345
    for day in days:
        state = (state * 1103515245 + 12345) % 2**31
        move = D((state % 401) - 200) / D(100)  # -2.00 .. +2.00
        close = max(D('5.05'), price + move)
        open_ = max(D('5.05'), price + D((state // 7 % 201) - 100) / D(200))
        high = max(open_, close) + D(state // 11 % 100) / D(100)
        low = min(open_, close) - min(D(state // 13 % 100) / D(100), min(open_, close) - D('0.05'))
        volume = 0 if state % 97 == 0 else 1000 + state % 5000
        bars.append(DailyStockBar(instrument, day, open_, high, low, close, volume, 'a' * 64))
        price = close
    actions = []
    for position, (index, numerator, denominator, cash_only) in enumerate(events):
        ex = days[index]
        previous = bars[index - 1].close
        reference = (previous * D(numerator) / D(denominator)).quantize(D('0.01'))
        digest = format(position + 1, 'x').rjust(64, 'c')
        url = 'https://www.twse.com.tw/test'
        if cash_only:
            actions.append(CashDividendAction(instrument, ex, previous, reference, digest, url, previous - reference, ex + timedelta(days=20)))
        else:
            actions.append(CorporateAction(instrument, ex, previous, reference, digest, url))
    history = OfficialDailyHistory(instrument, tuple(bars), tuple(actions), datetime(2099, 1, 1, tzinfo=timezone.utc), 'b' * 64)
    # The request window must span five calendar years; one calendar-only trailing day provides that.
    through = max(days[-1], first.replace(year=first.year + 5)) + timedelta(days=1)
    while through.weekday() >= 5:
        through += timedelta(days=1)
    sessions = tuple(
        TradingSession(
            day, datetime(day.year, day.month, day.day, 1, 0, tzinfo=timezone.utc), datetime(day.year, day.month, day.day, 5, 30, tzinfo=timezone.utc)
        )
        for day in (*days, through)
    )
    return history, TradingCalendar('synthetic', 'v1', 'synthetic', sessions), through
