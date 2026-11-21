"""OPT-1 P11: the shared tail reader against the engine every chart read reaches, round by round.

The reader must hand back exactly the bars a whole-series read would, through new minutes, updates of the forming
minute, tick-loss marks, day and night sessions across trade dates, history backfills that shift every index,
period switches and the retry button; and it must fall back to the whole read whenever the tail does not line up.
"""

import tempfile
import unittest
from unittest.mock import patch

from desktop_app.features.trading import series_reader
from desktop_app.features.trading.series_reader import SERIES_TAIL_BARS, read_series
from quantlab.trading.application.contracts import MarketSeriesQuery
from quantlab.trading.domain.validation import DomainError
from tests import test_m5_sector as sector_tests
from tests.series_read_simulator import OTHER, STOCK, TerminalFeed, whole_round, without_window_check

KEY = STOCK.instrument_id


class TerminalEngineReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.feed = TerminalFeed(self.temp.name)
        self.addCleanup(self.feed.close)
        self.facade = self.feed.facade

    def assertSameSeries(self, result, period, key=KEY):
        page, bars, whole = result
        oracle = self.feed.whole(key, period)
        self.assertEqual(repr(bars), repr(oracle.bars))  # repr keeps Decimal exponents and every flag
        self.assertEqual((page.instrument_id, page.period, page.total, page.gaps), (oracle.instrument_id, oracle.period, oracle.total, oracle.gaps))

    def play(self, rounds=90):
        """The mismatching rounds and the rounds that read the whole series, over a script of every kind of change."""
        cache, mismatches, wholes = {}, [], []
        for number in range(rounds):
            period = '1m' if number < 50 else '5m' if number < 65 else '1d' if number < 75 else '1m'
            self.feed.tick()
            if number % 17 == 5:
                self.feed.backfill_older()
            if number % 11 == 3:
                self.feed.tick(lost=True)
            if number == 30:
                self.feed.tick(6 * 3600)  # the day session closes and the night session opens under the next trade date
            if number == 40:
                for _ in range(4):
                    self.feed.tick(lost=True)
            if number == 45:
                self.feed.tick(14 * 3600)  # the next morning: the day session of that trade date
            del self.facade.queries[:]
            result = read_series(self.facade, KEY, period, cache.get(period), pinned_tail=True)
            oracle = self.feed.whole(KEY, period)
            if repr(result[1]) != repr(oracle.bars) or result[0].total != oracle.total:
                mismatches.append(number)
            cache[period] = result[:2]
            if result[2]:
                wholes.append(number)
        return mismatches, wholes

    def test_the_terminal_engine_serves_a_page_past_the_first_only_from_a_named_snapshot(self):
        total = self.feed.whole(KEY, '1m').total
        with self.assertRaises(DomainError) as caught:
            self.facade.market_series(MarketSeriesQuery(KEY, '1m', offset=total - SERIES_TAIL_BARS))
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_cached_reads_equal_whole_reads_through_every_kind_of_change(self):
        mismatches, wholes = self.play()
        self.assertEqual(mismatches, [])
        # The first read of each period and every backfill that shifted the indexes of a long series read the whole series.
        self.assertLessEqual({0, 50, 65, 5, 22, 39, 56}, set(wholes))
        self.assertGreater(90 - len(wholes), 55)  # every other round only re-read the tail

    def test_removing_the_window_comparison_is_caught(self):
        with patch.object(series_reader, '_read_tail', without_window_check):
            mismatches, _ = self.play()
        self.assertTrue(mismatches)

    def test_a_steady_read_is_one_bar_then_the_tail_of_that_snapshot(self):
        first = read_series(self.facade, KEY, '1m', None, pinned_tail=True)
        self.assertTrue(first[2])
        self.feed.tick()
        del self.facade.queries[:]
        result = read_series(self.facade, KEY, '1m', first[:2], pinned_tail=True)
        self.assertFalse(result[2])
        head, tail = self.facade.queries
        self.assertEqual((head.offset, head.limit, head.market_revision), (0, 1, None))
        self.assertEqual((tail.offset, tail.limit), (len(first[1]) - SERIES_TAIL_BARS, MarketSeriesQuery(KEY).limit))
        self.assertIsNotNone(tail.market_revision)
        self.assertSameSeries(result, '1m')

    def test_the_retry_read_is_always_whole_and_its_first_page_asks_for_the_history_again(self):
        first = read_series(self.facade, KEY, '1m', None, pinned_tail=True)
        del self.facade.queries[:]
        result = read_series(self.facade, KEY, '1m', first[:2], retry_history=True, pinned_tail=True)
        self.assertTrue(result[2])
        self.assertTrue(self.facade.queries[0].retry_history)
        self.assertEqual(self.facade.queries[0].offset, 0)
        self.assertTrue(all(query.offset == 0 or query.market_revision is not None for query in self.facade.queries))
        self.assertFalse(any(query.retry_history for query in self.facade.queries[1:]))
        self.assertSameSeries(result, '1m')

    def test_a_snapshot_replaced_between_the_two_reads_falls_back_to_the_whole_series(self):
        first = read_series(self.facade, KEY, '1m', None, pinned_tail=True)
        feed, service = self.feed, self.feed.service

        class Racing:
            """Another reader takes a newer snapshot of the same series right after this one's first-page read."""

            def __init__(self):
                self.queries = []

            def market_series(self, query):
                self.queries.append(query)
                page = service.series(query)
                if query.limit == 1:
                    feed.tick()
                    service.series(MarketSeriesQuery(KEY, '1m', limit=1))
                return page

        racing = Racing()
        feed.tick()
        result = read_series(racing, KEY, '1m', first[:2], pinned_tail=True)
        self.assertTrue(result[2])
        self.assertEqual([(query.offset > 0, query.limit == 1) for query in racing.queries[:2]], [(False, True), (True, False)])  # head, refused tail
        self.assertSameSeries(result, '1m')

    def test_other_errors_and_an_unpinned_refusal_are_not_swallowed(self):
        first = read_series(self.facade, KEY, '1m', None, pinned_tail=True)

        class Refusing:
            def __init__(self, code):
                self.code = code

            def market_series(self, query):
                raise DomainError(self.code)

        with self.assertRaises(DomainError) as caught:
            read_series(Refusing('capability_missing'), KEY, '1m', first[:2], pinned_tail=True)
        self.assertEqual(caught.exception.code, 'capability_missing')
        with self.assertRaises(DomainError) as caught:
            read_series(Refusing('state_conflict'), KEY, '1m', first[:2])  # the sector board's own unpinned read
        self.assertEqual(caught.exception.code, 'state_conflict')

    def test_a_short_series_is_read_from_its_first_page_without_pinning(self):
        first = read_series(self.facade, OTHER.instrument_id, '1d', None, pinned_tail=True)
        self.assertLess(len(first[1]), SERIES_TAIL_BARS)
        self.feed.tick(6 * 3600)
        del self.facade.queries[:]
        result = read_series(self.facade, OTHER.instrument_id, '1d', first[:2], pinned_tail=True)
        self.assertFalse(result[2])
        self.assertEqual([(query.offset, query.market_revision) for query in self.facade.queries], [(0, None)])
        self.assertSameSeries(result, '1d', OTHER.instrument_id)

    def test_a_rewrite_of_older_bars_is_shown_after_the_next_whole_read(self):
        cached = read_series(self.facade, KEY, '1m', None, pinned_tail=True)[:2]
        self.feed.tick()
        self.feed.rewrite_old()  # same size, same tail, different closes for bars older than the tail window
        page, bars, whole = read_series(self.facade, KEY, '1m', cached, pinned_tail=True)
        full = self.feed.whole(KEY, '1m').bars
        self.assertFalse(whole)
        self.assertNotEqual(repr(bars[:-SERIES_TAIL_BARS]), repr(full[:-SERIES_TAIL_BARS]))  # the documented bound
        self.assertEqual(repr(bars[-SERIES_TAIL_BARS:]), repr(full[-SERIES_TAIL_BARS:]))
        self.assertSameSeries(read_series(self.facade, KEY, '1m', None, pinned_tail=True), '1m')  # the resync read

    def test_whole_round_tells_whole_reads_from_tail_reads(self):
        first = read_series(self.facade, KEY, '1m', None, pinned_tail=True)
        self.assertTrue(whole_round(self.facade.queries, KEY))
        self.assertFalse(whole_round(self.facade.queries, OTHER.instrument_id))
        self.feed.tick()
        del self.facade.queries[:]
        read_series(self.facade, KEY, '1m', first[:2], pinned_tail=True)
        self.assertFalse(whole_round(self.facade.queries, KEY))


class LiveEnginePinnedTailTests(unittest.TestCase):
    """The legacy live path (LiveMarketService) has no snapshots: the pinned tail only needs the market not to move between its two reads."""

    # The sector board's OPT-1 P8 fixture (a real LiveMarketService over the simulated tick feed), borrowed method by method.
    KEY = sector_tests.DetailSeriesEquivalenceTests.KEY
    setUp = sector_tests.DetailSeriesEquivalenceTests.setUp
    backfill = sector_tests.DetailSeriesEquivalenceTests.backfill
    step = sector_tests.DetailSeriesEquivalenceTests.step
    lose_recent = sector_tests.DetailSeriesEquivalenceTests.lose_recent
    assertSameSeries = sector_tests.DetailSeriesEquivalenceTests.assertSameSeries

    def test_pinned_reads_equal_whole_reads_when_the_market_holds_still_between_the_two_reads(self):
        cache = {}
        for number in range(40):
            period = '1m' if number < 30 else '5m'
            self.step()
            if number % 13 == 4:
                self.depth += 45
                self.backfill()
            if number % 7 == 2:
                self.lose_recent(2)
            result = read_series(self.facade, self.KEY, period, cache.get(period), pinned_tail=True)
            with self.subTest(round=number):
                self.assertSameSeries(result, period)
            cache[period] = result[:2]

    def test_a_tick_between_the_two_reads_falls_back_to_the_whole_series(self):
        cached = read_series(self.facade, self.KEY, '1m', None, pinned_tail=True)[:2]
        test, facade = self, self.facade

        class Racing:
            def __init__(self):
                self.reads = []

            def market_series(self, query):
                page = facade.market_series(query)
                self.reads.append((query.offset, query.limit))
                if query.limit == 1:
                    test.step()  # the market moves between the first-page read and the tail read
                return page

        racing = Racing()
        result = read_series(racing, self.KEY, '1m', cached, pinned_tail=True)
        self.assertTrue(result[2])
        # The first-page read, then the whole read; the refused tail read is not recorded (it raised).
        self.assertEqual(racing.reads, [(0, 1), (0, MarketSeriesQuery(self.KEY).limit)])
        self.assertSameSeries(result, '1m')


if __name__ == '__main__':
    unittest.main()
