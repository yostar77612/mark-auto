"""Recorded public prices expose daily-source boundaries; no live account or SDK.

Exchange JSON files are unchanged HTTP responses. The separate SDK example is
explicitly documentation data, not an independently recorded exchange tick tape.
Synthetic minute positions below are labelled counterfactual bounds only.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from quantlab.trading.adapters.official.stock_data import parse_daily
from quantlab.trading.application.automatic import _history
from quantlab.trading.application.contracts import StrategyForm
from quantlab.trading.application.state import StrategyRecord
from quantlab.trading.application.stock_research import StockTaxTreatment, validate_request
from quantlab.trading.domain.auto_cycle import complete_buckets
from quantlab.trading.domain.calendar import TradingSession
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.live_bars import LiveBar, compose_minute, finalize_minute
from quantlab.trading.domain.models import Environment, HoldingKind, HoldingPolicy, Market, Side
from quantlab.trading.domain.stock_history import CorporateAction, price_series
from quantlab.trading.domain.strategy import CompletedBar, StrategyParameters
from quantlab.trading.domain.ticks import Tick
from quantlab.trading.domain.validation import DomainError
from test_trading_domain import instrument

D = Decimal
TAIPEI = ZoneInfo('Asia/Taipei')
FIXTURES = Path(__file__).parent / 'fixtures' / 'm2_daily_review'


def document(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8-sig'))


def session(day):
    return TradingSession(day, datetime.combine(day, time(9), TAIPEI), datetime.combine(day, time(13, 30), TAIPEI))


def dividend_inputs():
    raw = (FIXTURES / 'twse_2330_202506.json').read_bytes()
    bars = tuple(row for row in parse_daily(raw, 'TWSE:2330', date(2025, 6, 1)) if row.trade_date in (date(2025, 6, 11), date(2025, 6, 12)))
    action_raw = (FIXTURES / 'twse_ex_right_20250612.json').read_bytes()
    body = json.loads(action_raw)
    row = next(dict(zip(body['fields'], values)) for values in body['data'] if values[1] == '2330')
    manifest = document('manifest.json')
    source = next(item['url'] for item in manifest['documents'] if item['file'] == 'twse_ex_right_20250612.json')
    event = CorporateAction(
        'TWSE:2330',
        date(2025, 6, 12),
        D(row['除權息前收盤價'].replace(',', '')),
        D(row['除權息參考價'].replace(',', '')),
        sha256(action_raw).hexdigest(),
        source,
    )
    return bars, event


class DailyPriceBasisTests(unittest.TestCase):
    def test_public_response_bytes_match_their_recording_manifest(self):
        manifest = document('manifest.json')
        self.assertEqual(len(manifest['documents']), 4)
        for record in manifest['documents']:
            with self.subTest(file=record['file']):
                raw = (FIXTURES / record['file']).read_bytes()
                self.assertEqual(sha256(raw).hexdigest(), record['sha256'])
                self.assertTrue(record['url'].startswith(('https://www.twse.com.tw/', 'https://sinotrade.github.io/')))
        self.assertEqual(document('shioaji_closing_tick_example.json')['kind'], 'OFFICIAL_SDK_DOCUMENTATION_EXAMPLE_NOT_EXCHANGE_TAPE')

    def test_real_thin_stock_trade_count_cannot_cover_a_full_day_of_trade_minutes(self):
        body = document('twse_6225_202506.json')
        row = next(dict(zip(body['fields'], values)) for values in body['data'] if values[0] == '114/06/27')
        count = int(row['成交筆數'].replace(',', ''))
        observed = next(
            bar for bar in parse_daily((FIXTURES / 'twse_6225_202506.json').read_bytes(), 'TWSE:6225', date(2025, 6, 1)) if bar.trade_date == date(2025, 6, 27)
        )
        self.assertEqual((count, observed.close, observed.volume), (7, D('11.40'), 11000))
        day = session(observed.trade_date)
        required = (day.closes_at - day.opens_at) // timedelta(minutes=1)
        self.assertEqual(required, 270)
        self.assertLess(count, required)
        # Counterfactual upper bound, not reconstructed trades: even assigning
        # every recorded trade a different minute cannot supply 270 minutes.
        upper_bound = tuple(
            LiveBar(
                observed.instrument_id,
                start,
                start + timedelta(minutes=1),
                observed.trade_date,
                'DAY',
                observed.close,
                observed.close,
                observed.close,
                observed.close,
                1,
                final=True,
            )
            for index in range(count)
            for start in (day.opens_at + timedelta(minutes=index),)
        )
        self.assertEqual(complete_buckets(upper_bound, '1d', day, day.closes_at), ())

    def test_official_closing_tick_is_a_1330_to_1331_minute_outside_current_day_bucket(self):
        example = document('shioaji_closing_tick_example.json')
        state = None
        for row in example['rows'][:3]:
            at = datetime.fromisoformat(row['timestamp']).replace(tzinfo=TAIPEI)
            tick = Tick(example['instrument_id'], D(row['close']), row['volume'], at, at, at.date(), source='SHIOAJI')
            update = compose_minute(state, tick)
            state = update.state
        closing = finalize_minute(state, now=state.bar.end).bar
        self.assertEqual((closing.start.time(), closing.end.time(), closing.close, closing.volume), (time(13, 30), time(13, 31), D('2240.0'), 4606))
        self.assertTrue(closing.incomplete)  # No trades during the closing call accumulate a natural gap.
        # Isolate the end-bound guard from that independent gap guard. This is
        # a controlled boundary probe, not padding or repairing market data.
        independently_complete = replace(closing, incomplete=False)
        self.assertEqual(complete_buckets((independently_complete,), '1m', session(closing.trade_date), closing.end), ())

    def test_recorded_official_daily_prices_are_raw_and_adjustment_preserves_originals(self):
        bars, event = dividend_inputs()
        original = bars
        self.assertEqual((bars[0].close, bars[1].close, event.previous_close, event.reference_price), (D('1065.00'), D('1045.00'), D('1065.00'), D('1060.49')))
        adjusted = price_series(bars, (event,))
        raw = price_series(bars, (event,), adjusted=False)
        self.assertEqual(raw.mode, 'RAW')
        self.assertEqual(adjusted.mode, 'ADJUSTED')
        self.assertEqual(raw.bars, original)
        self.assertEqual(bars, original)
        self.assertEqual(adjusted.bars[0].close, D('1060.49'))
        self.assertEqual(adjusted.bars[1].close, D('1045.00'))
        self.assertEqual(adjusted.raw_digest, raw.raw_digest)

    def test_ex_date_requires_rebasing_the_historical_window_not_just_appending_raw_today(self):
        bars, event = dividend_inputs()
        before = price_series(bars, (event,), as_of=bars[0].trade_date)
        through_ex_date = price_series(bars, (event,), as_of=bars[1].trade_date)
        self.assertEqual(before.bars[0].close, D('1065.00'))
        self.assertEqual(through_ex_date.bars[0].close, D('1060.49'))
        self.assertEqual(before.bars[0].close - bars[1].close, D('20.00'))
        self.assertEqual(through_ex_date.bars[0].close - bars[1].close, D('15.49'))

    def test_current_completed_bar_history_has_no_implicit_official_rebase(self):
        bars, event = dividend_inputs()
        previous, today = bars
        old_day, new_day = session(previous.trade_date), session(today.trade_date)
        historic = CompletedBar(old_day.opens_at, old_day.closes_at, old_day.closes_at, previous.open, previous.close, previous.volume)
        # This audits a potential caller-supplied history. It does not assert
        # that ManualRuntime already installs official or adjusted stock bars.
        engine = SimpleNamespace(history={'TWSE:2330': (historic,)})
        live = LiveBar(
            'TWSE:2330', new_day.opens_at, new_day.closes_at, today.trade_date, 'DAY', today.open, today.high, today.low, today.close, today.volume, final=True
        )
        stitched = _history(engine, 'TWSE:2330', '1d', (live,))['TWSE:2330']
        self.assertEqual(tuple(row.close for row in stitched), (D('1065.00'), D('1045.00')))
        self.assertNotEqual(stitched[0].close, price_series(bars, (event,)).bars[0].close)

    def test_official_adjusted_research_does_not_implicitly_authorize_a_typed_strategy(self):
        spec = instrument()
        form = StrategyForm(
            'basis-audit', Market.STOCK, HoldingKind.CUSTOM, 0, 10, Side.BUY, spec.instrument_id, 'audit-stock', Environment.LOCAL, D('60000'), D('.02')
        )
        record = StrategyRecord(
            'basis-audit', 1, form, HoldingPolicy(HoldingKind.CUSTOM, 0, 10), state='RULE_VALID', parameters=StrategyParameters('1d', D('.02'), D('25000'))
        )
        with self.assertRaises(DomainError) as caught:
            validate_request(record, spec, StockTaxTreatment('STOCK'), FeeSchedule.taiwan(), 'TRAINING')
        self.assertEqual(caught.exception.code, 'validation_failed')


if __name__ == '__main__':
    unittest.main()
