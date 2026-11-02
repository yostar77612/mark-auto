"""Draft acceptance of separate automatic product sessions and ledger envelope."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import unittest

from test_trading_adapters import instrument
from quantlab.trading.domain.calendar import TradingCalendar, TradingSession
from quantlab.trading.domain.models import Market
from quantlab.trading.domain.validation import DomainError

from quantlab.trading.domain.automatic_calendar import TAIPEI, TMF_SOURCE, TWSE_SOURCE, automatic_day_calendar, calendar_for_instrument

DAY_DATES = (date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 19))


def verified_base(*, utc=False):
    sessions = [TradingSession(day, datetime.combine(day, time(9), TAIPEI), datetime.combine(day, time(13, 29), TAIPEI)) for day in DAY_DATES]
    sessions.extend(
        (
            TradingSession(DAY_DATES[0], datetime(2026, 11, 13, 15, tzinfo=TAIPEI), datetime(2026, 11, 14, 5, tzinfo=TAIPEI), 'NIGHT'),
            TradingSession(date(2026, 11, 20), datetime(2026, 11, 19, 15, tzinfo=TAIPEI), datetime(2026, 11, 20, 5, tzinfo=TAIPEI), 'NIGHT'),
        )
    )
    if utc:
        sessions = [replace(row, opens_at=row.opens_at.astimezone(timezone.utc), closes_at=row.closes_at.astimezone(timezone.utc)) for row in sessions]
    return TradingCalendar(
        'verified-manual-common', 'verified-day-set-v3', 'EXPLICIT_FIXTURE_NO_HOLIDAY_INFERENCE', tuple(sorted(sessions, key=lambda row: row.opens_at))
    )


class AutomaticCalendarTests(unittest.TestCase):
    def test_stock_hours_are_product_hours_and_do_not_mutate_legacy_manual_calendar(self):
        base = verified_base()
        original = base.sessions
        projected = calendar_for_instrument(base, instrument())
        self.assertEqual(projected.days, DAY_DATES)
        for session in projected.sessions:
            self.assertEqual((session.opens_at.time(), session.closes_at.time()), (time(9), time(13, 30)))
            self.assertEqual(session.kind, 'DAY')
        self.assertEqual(base.sessions, original)
        self.assertEqual(base.day_session(DAY_DATES[0]).closes_at.time(), time(13, 29))

    def test_tmf_regular_day_opens_0845_and_closes_1345(self):
        calendar = calendar_for_instrument(verified_base(), instrument(Market.INDEX_FUTURE))
        session = calendar.day_session(DAY_DATES[0])
        self.assertEqual((session.opens_at.time(), session.closes_at.time()), (time(8, 45), time(13, 45)))

    def test_actual_contract_expiry_day_closes_1330(self):
        calendar = calendar_for_instrument(verified_base(), instrument(Market.INDEX_FUTURE))
        session = calendar.day_session(date(2026, 11, 18))
        self.assertEqual((session.opens_at.time(), session.closes_at.time()), (time(8, 45), time(13, 30)))

    def test_expiry_uses_actual_spec_date_instead_of_third_wednesday_inference(self):
        spec = replace(instrument(Market.INDEX_FUTURE), expiry=date(2026, 11, 16))
        calendar = calendar_for_instrument(verified_base(), spec)
        self.assertEqual(calendar.day_session(date(2026, 11, 16)).closes_at.time(), time(13, 30))
        self.assertEqual(calendar.day_session(date(2026, 11, 18)).closes_at.time(), time(13, 45))

    def test_expiry_for_next_month_does_not_shorten_front_month_settlement_date(self):
        spec = replace(instrument(Market.INDEX_FUTURE), instrument_id='TAIFEX:TMF:202612', delivery_month='202612', expiry=date(2026, 12, 16))
        calendar = calendar_for_instrument(verified_base(), spec)
        self.assertEqual(calendar.day_session(date(2026, 11, 18)).closes_at.time(), time(13, 45))

    def test_utc_input_has_identical_taipei_instants_and_sessions(self):
        local = calendar_for_instrument(verified_base(), instrument(Market.INDEX_FUTURE))
        utc = calendar_for_instrument(verified_base(utc=True), instrument(Market.INDEX_FUTURE))
        self.assertEqual(utc, local)
        session = utc.day_session(DAY_DATES[0])
        self.assertEqual(session.opens_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(session.opens_at.astimezone(timezone.utc).time(), time(0, 45))
        self.assertEqual(session.closes_at.astimezone(timezone.utc).time(), time(5, 45))

    def test_omitted_holiday_and_night_only_trade_date_are_never_fabricated(self):
        calendar = calendar_for_instrument(verified_base(), instrument())
        self.assertEqual(calendar.days, DAY_DATES)
        for missing in (date(2026, 11, 17), date(2026, 11, 20)):
            with self.subTest(missing=missing), self.assertRaises(DomainError) as rejected:
                calendar.day_session(missing)
            self.assertEqual(rejected.exception.code, 'calendar_missing')
        self.assertEqual(calendar.advance(DAY_DATES[0], 1), DAY_DATES[1])

    def test_night_session_is_not_exposed_even_when_caller_allows_night(self):
        calendar = calendar_for_instrument(verified_base(), instrument(Market.INDEX_FUTURE))
        with self.assertRaises(DomainError) as rejected:
            calendar.session_at(datetime(2026, 11, 13, 16, tzinfo=TAIPEI), allow_night=True)
        self.assertEqual(rejected.exception.code, 'session_closed')

    def test_night_only_base_has_no_verified_day_coverage(self):
        base = verified_base()
        base = replace(base, sessions=tuple(row for row in base.sessions if row.kind == 'NIGHT'))
        with self.assertRaises(DomainError) as rejected:
            calendar_for_instrument(base, instrument())
        self.assertEqual(rejected.exception.code, 'calendar_missing')

    def test_calendar_identity_version_and_source_are_explicit_and_reproducible(self):
        base = verified_base()
        stock = calendar_for_instrument(base, instrument())
        future = calendar_for_instrument(base, instrument(Market.INDEX_FUTURE))
        self.assertNotEqual(stock.calendar_id, base.calendar_id)
        self.assertNotEqual(stock.version, base.version)
        self.assertIn(TWSE_SOURCE, stock.source)
        self.assertIn(TMF_SOURCE, future.source)
        self.assertNotEqual(stock.calendar_id, future.calendar_id)
        self.assertEqual(stock, calendar_for_instrument(base, instrument()))
        self.assertNotEqual(stock.version, calendar_for_instrument(replace(base, version='verified-day-set-v4'), instrument()).version)

    def test_only_stocks_and_actual_tmf_contracts_receive_automatic_calendars(self):
        base = verified_base()
        for spec in (instrument(Market.STOCK_FUTURE), replace(instrument(Market.INDEX_FUTURE), instrument_id='TAIFEX:MTX:202611')):
            with self.subTest(spec=spec), self.assertRaises(DomainError) as rejected:
                calendar_for_instrument(base, spec)
            self.assertEqual(rejected.exception.code, 'strategy_instrument_restricted')

    def test_mixed_day_envelope_uses_earliest_open_and_latest_close(self):
        base = verified_base()
        mixed = automatic_day_calendar(base, (instrument(), instrument(Market.INDEX_FUTURE)))
        self.assertEqual(mixed.days, DAY_DATES)
        ordinary = mixed.day_session(DAY_DATES[0])
        self.assertEqual((ordinary.opens_at.time(), ordinary.closes_at.time()), (time(8, 45), time(13, 45)))
        expiry = mixed.day_session(date(2026, 11, 18))
        self.assertEqual((expiry.opens_at.time(), expiry.closes_at.time()), (time(8, 45), time(13, 30)))

    def test_distinct_tmf_contracts_keep_day_envelope_open_after_front_contract_expiry_close(self):
        front = instrument(Market.INDEX_FUTURE)
        next_month = replace(front, instrument_id='TAIFEX:TMF:202612', delivery_month='202612', expiry=date(2026, 12, 16))
        calendar = automatic_day_calendar(verified_base(), (front, next_month))
        self.assertEqual(calendar.day_session(front.expiry).closes_at.time(), time(13, 45))

    def test_stock_only_envelope_does_not_expand_to_futures_hours(self):
        calendar = automatic_day_calendar(verified_base(), (instrument(),))
        session = calendar.day_session(DAY_DATES[0])
        self.assertEqual((session.opens_at.time(), session.closes_at.time()), (time(9), time(13, 30)))

    def test_ledger_envelope_never_substitutes_for_stock_order_calendar(self):
        base = verified_base()
        stock, future = instrument(), instrument(Market.INDEX_FUTURE)
        at = datetime(2026, 11, 16, 8, 50, tzinfo=TAIPEI)
        self.assertEqual(automatic_day_calendar(base, (stock, future)).session_at(at).kind, 'DAY')
        with self.assertRaises(DomainError) as rejected:
            calendar_for_instrument(base, stock).session_at(at)
        self.assertEqual(rejected.exception.code, 'session_closed')

    def test_mixed_selection_is_order_and_duplicate_independent(self):
        base = verified_base()
        stock, future = instrument(), instrument(Market.INDEX_FUTURE)
        self.assertEqual(automatic_day_calendar(base, (stock, future)), automatic_day_calendar(base, (future, stock, future)))

    def test_empty_or_unsupported_selection_does_not_fall_back_to_manual_calendar(self):
        for instruments in ((), (instrument(), instrument(Market.STOCK_FUTURE))):
            with self.subTest(instruments=instruments), self.assertRaises(DomainError):
                automatic_day_calendar(verified_base(), instruments)


if __name__ == '__main__':
    unittest.main()
