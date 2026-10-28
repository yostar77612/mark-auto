"""Pure tick/bar behavior contracts; no subscription, calendar lookup or UI tests."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from quantlab.trading.domain.live_bars import DataGap, aggregate_bars, compose_minute, finalize_minute, merge_history_live
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError

D = Decimal
START = datetime(2026, 10, 27, 15, tzinfo=timezone(timedelta(hours=8)))
TRADE_DATE = date(2026, 10, 28)


def tick(seconds=0, price='100', volume=1, sequence=None):
    at = START + timedelta(seconds=seconds)
    return Tick('TMF', D(price), volume, at, at + timedelta(minutes=2), TRADE_DATE, 'NIGHT', sequence)


def minute_bars(ticks):
    state, bars = None, []
    for item in ticks:
        update = compose_minute(state, item)
        state = update.state
        bars.extend(update.finalized)
    return (*bars, finalize_minute(state, now=state.bar.end).bar)


class LiveBarsTests(unittest.TestCase):
    def test_tick_boundary_validation(self):
        base = tick()
        for changes in (
            {'received_at': START - timedelta(seconds=1)},
            {'price': D('0')},
            {'price': D('-1')},
            {'price': D('NaN')},
            {'price': 100},
            {'session': 'OTHER'},
            {'volume': -1},
            {'sequence': -1},
            {'source_at': START.replace(tzinfo=None)},
            {'trade_date': None},
        ):
            with self.subTest(changes=changes), self.assertRaises(DomainError) as caught:
                replace(base, **changes)
            self.assertEqual(caught.exception.code, 'validation_failed')
        with self.assertRaises(FrozenInstanceError):
            base.volume = 2

    def test_source_buckets_minute_boundaries_and_resolved_night_date(self):
        for seconds, minute in ((0, 0), (59.999, 0), (60, 1), (120, 2)):
            with self.subTest(seconds=seconds):
                bar = compose_minute(None, tick(seconds)).state.bar
                self.assertEqual(bar.start, START + timedelta(minutes=minute))
                self.assertEqual((bar.trade_date, bar.session), (TRADE_DATE, 'NIGHT'))
                self.assertNotEqual(bar.start.date(), bar.trade_date)
                self.assertFalse(bar.final)

    def test_out_of_order_duplicate_and_finalization(self):
        state = compose_minute(None, tick(30, '103', 2, 3)).state
        state = compose_minute(state, tick(10, '101', 3, 1)).state
        state = compose_minute(state, tick(20, '99', 4, 2)).state
        self.assertEqual((state.bar.open, state.bar.high, state.bar.low, state.bar.close, state.bar.volume), (D('101'), D('103'), D('99'), D('103'), 9))
        for duplicate in (tick(30, '103', 2, 3), tick(40, '900', 50, 1)):
            with self.subTest(sequence=duplicate.sequence):
                update = compose_minute(state, duplicate)
                self.assertFalse(update.accepted)
                self.assertEqual(update.state, state)
        self.assertFalse(finalize_minute(state, now=START + timedelta(seconds=59)).bar.final)
        final = finalize_minute(state, now=START + timedelta(minutes=1))
        self.assertTrue(final.bar.final)
        late = compose_minute(final, tick(45, '200', 1, 4))
        self.assertFalse(late.accepted)
        self.assertEqual(late.state.bar.close, D('103'))
        self.assertTrue(late.state.bar.incomplete)
        update = compose_minute(state, tick(60, '105', 5, 4))
        self.assertTrue(update.finalized[0].final)
        self.assertFalse(update.state.bar.final)
        self.assertFalse(compose_minute(update.state, tick(65, sequence=2)).accepted)
        late = compose_minute(update.state, tick(50, sequence=5))
        self.assertFalse(late.accepted)
        self.assertTrue(late.state.bar.incomplete)

    def test_loss_sequence_scope_and_no_sequence(self):
        state = compose_minute(None, tick(sequence=10)).state
        for item, explicit_loss in ((tick(120, sequence=11), False), (tick(60, sequence=11), True)):
            with self.subTest(explicit_loss=explicit_loss):
                update = compose_minute(state, item, incomplete=explicit_loss)
                self.assertTrue(update.state.bar.incomplete)
                self.assertEqual(len(update.finalized), 1)
        for changes in ({'trade_date': date(2026, 10, 29)}, {'source': 'NEW_SOURCE'}, {'session': 'DAY'}):
            with self.subTest(changes=changes):
                self.assertTrue(compose_minute(state, replace(tick(60, sequence=1), **changes)).accepted)
        state = compose_minute(None, tick()).state
        self.assertEqual(compose_minute(state, tick()).state.bar.volume, 2)

    def test_periods_match_direct_tick_ohlcv(self):
        ticks = tuple(tick(i * 60 + second, str(100 + i + offset), i + 1, i * 2 + j) for i in range(60) for j, (second, offset) in enumerate(((1, 0), (50, 2))))
        bars = minute_bars(ticks)
        for period, width in (('3m', 3), ('5m', 5), ('15m', 15), ('30m', 30), ('60m', 60), ('1d', 60)):
            with self.subTest(period=period):
                result = aggregate_bars(bars, period, now=START + timedelta(hours=1), trade_date_closed=True)
                self.assertEqual(len(result), 60 // width)
                for index, bar in enumerate(result):
                    direct = ticks[index * width * 2 : (index + 1) * width * 2]
                    self.assertEqual(
                        (bar.open, bar.high, bar.low, bar.close, bar.volume),
                        (direct[0].price, max(t.price for t in direct), min(t.price for t in direct), direct[-1].price, sum(t.volume for t in direct)),
                    )
                    self.assertTrue(bar.final)
        with self.assertRaises(DomainError):
            aggregate_bars(bars, '2m', now=START)

    def test_aggregate_forming_incomplete_and_trade_date_sessions(self):
        night = minute_bars((tick(),))[0]
        day = replace(
            night,
            start=START + timedelta(hours=18),
            end=START + timedelta(hours=18, minutes=1),
            session='DAY',
            open=D('110'),
            close=D('111'),
            high=D('112'),
            incomplete=True,
        )
        for closed, expected in ((False, False), (True, True)):
            with self.subTest(closed=closed):
                daily = aggregate_bars((day, night), '1d', now=day.end, trade_date_closed=closed)[0]
                self.assertEqual((daily.open, daily.close, daily.volume, daily.final, daily.incomplete), (D('100'), D('111'), 2, expected, True))
        for final, now, expected in ((False, START + timedelta(minutes=5), False), (True, START, False), (True, START + timedelta(minutes=5), True)):
            with self.subTest(final=final, now=now):
                bar = aggregate_bars((replace(night, final=final),), '5m', now=now)[0]
                self.assertEqual(bar.final, expected)
        next_day = replace(day, trade_date=date(2026, 10, 29))
        self.assertEqual(len(aggregate_bars((night, next_day), '1d', now=next_day.end)), 2)

    def test_history_merge_suffix_ownership_and_explicit_gap(self):
        base = minute_bars((tick(),))[0]
        live = replace(base, start=START + timedelta(minutes=3), end=START + timedelta(minutes=4))
        for history, incoming, expected_bars, gaps in (
            ((base, replace(live, close=D('900')), replace(live, start=live.end)), (live,), (base, live), (DataGap(base.end, live.start),)),
            ((replace(base, end=live.start),), (live,), (replace(base, end=live.start), live), ()),
            ((live,), (live,), (live,), ()),
            ((base,), (), (base,), ()),
            ((), (live,), (live,), ()),
        ):
            with self.subTest(history=history, incoming=incoming):
                merged = merge_history_live(history, incoming)
                self.assertEqual((merged.bars, merged.gaps), (expected_bars, gaps))


if __name__ == '__main__':
    unittest.main()
