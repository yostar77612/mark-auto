"""Cross-source previous-close checks use explicit DAYs and preserve RAW prices."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D, localcontext
import unittest

from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.daily_signal_data import OfficialDailyHistory
from quantlab.trading.domain.stock_history import CorporateAction, DailyStockBar
from quantlab.trading.domain.validation import DomainError


class PreviousCloseValidationTests(unittest.TestCase):
    def setUp(self):
        self.days = (date(2025, 6, 11), date(2025, 6, 12), date(2025, 6, 16))
        self.calendar = TradingCalendar(
            'recorded-days',
            'v1',
            'EXPLICIT_TEST_DAYS',
            tuple(TradingSession(day, datetime.combine(day, time(1), timezone.utc), datetime.combine(day, time(5, 30), timezone.utc)) for day in self.days),
        )
        self.bars = tuple(DailyStockBar('TWSE:2330', day, D('100'), D('101'), D('99'), D('100'), 1000, 'a' * 64) for day in self.days)
        self.event = CorporateAction('TWSE:2330', self.days[1], D('100'), D('99'), 'b' * 64, 'https://www.twse.com.tw/test')
        self.history = OfficialDailyHistory('TWSE:2330', self.bars, (self.event,), datetime(2025, 6, 17, tzinfo=timezone.utc), 'c' * 64)

    def rejected(self, history, code):
        with self.assertRaises(DomainError) as caught:
            history.validate_previous_closes(self.calendar)
        self.assertEqual(caught.exception.code, code)

    def test_matching_raw_previous_day_is_accepted_without_changing_either_source(self):
        original = self.history
        self.history.validate_previous_closes(self.calendar)
        self.assertEqual(self.history, original)
        self.assertEqual(tuple(bar.close for bar in self.history.raw_completed(self.calendar)), (D('100'),) * 3)
        self.assertEqual(self.history.signal_history(self.calendar, self.days[1])[0].close, D('99'))

    def test_half_cent_inclusive_tolerance_is_context_independent(self):
        for previous in (D('99.995'), D('100.005')):
            history = replace(self.history, events=(replace(self.event, previous_close=previous),))
            with self.subTest(previous=previous), localcontext() as context:
                context.prec = 3
                history.validate_previous_closes(self.calendar)

    def test_above_half_cent_in_either_direction_is_rejected(self):
        for previous in (D('99.9949'), D('100.0051'), D('100.0050001')):
            with self.subTest(previous=previous), localcontext() as context:
                context.prec = 3
                self.rejected(replace(self.history, events=(replace(self.event, previous_close=previous),)), 'daily_signal_source_unverified')

    def test_calendar_previous_day_is_required_not_any_earlier_observed_row(self):
        event = replace(self.event, ex_date=self.days[2])
        missing = replace(self.history, bars=(self.bars[0], self.bars[2]), events=(event,))
        self.rejected(missing, 'daily_signal_not_available')

    def test_previous_verified_day_crosses_explicit_holiday_gap(self):
        history = replace(self.history, events=(replace(self.event, ex_date=self.days[2]),))
        history.validate_previous_closes(self.calendar)
        self.assertEqual(history.events[0].previous_close, self.bars[1].close)
        self.assertGreater((self.days[2] - self.days[1]).days, 1)

    def test_action_on_first_row_cannot_adjust_an_earlier_row_and_is_exempt(self):
        history = replace(self.history, events=(replace(self.event, ex_date=self.days[0], previous_close=D('999')),))
        history.validate_previous_closes(self.calendar)
        self.assertEqual(history.signal_history(self.calendar, self.days[-1]), history.raw_completed(self.calendar))

    def test_future_action_is_not_validated_or_used_before_its_ex_date(self):
        history = replace(self.history, events=(replace(self.event, ex_date=self.days[-1] + timedelta(days=1), previous_close=D('999')),))
        history.validate_previous_closes(self.calendar)
        self.assertEqual(history.signal_history(self.calendar, self.days[-1]), history.raw_completed(self.calendar))

    def test_night_session_does_not_supply_an_adjustment_predecessor(self):
        calendar = replace(self.calendar, sessions=(replace(self.calendar.sessions[0], kind='NIGHT'), *self.calendar.sessions[1:]))
        with self.assertRaises(DomainError) as caught:
            self.history.validate_previous_closes(calendar)
        self.assertEqual(caught.exception.code, 'daily_signal_not_available')

    def test_previous_close_authority_is_close_rather_than_previous_open(self):
        bars = (replace(self.bars[0], open=D('99')), *self.bars[1:])
        history = replace(self.history, bars=bars, events=(replace(self.event, previous_close=D('99')),))
        self.rejected(history, 'daily_signal_source_unverified')


if __name__ == '__main__':
    unittest.main()
