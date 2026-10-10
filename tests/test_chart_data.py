"""Frozen aggregation goldens (before implementation).
Session opens 23:59 UTC, 1m prices [1,3,2]: 3m O1 H3 L1 C2 V3,
end00:02, same exchange trade_date. Gap middle: V2, partial, never fill.
Daily night1/day3 => O1 H3 L1 C3 V2; contracts never mingle.
"""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from quantlab.market import InstrumentRef, MarketBar
from quantlab.chart_data import aggregate_bars
from quantlab.data import SessionCalendar

START=datetime(2026,10,8,23,59,tzinfo=timezone.utc)
INSTRUMENT=InstrumentRef('TAIFEX','TMF','TAIFEX:TMF:202610','202610')


def bar(i, price, **kwargs):
    return MarketBar(instrument=INSTRUMENT,trade_date='2026-10-09',session='night',
        open=D(price),high=D(price),low=D(price),close=D(price),volume=1,
        interval='1m',timestamp=START+timedelta(minutes=i),end=START+timedelta(minutes=i+1),
        session_open=START,session_end=kwargs.pop('session_end',START+timedelta(minutes=6)),source_id='synthetic',**kwargs)


class ChartDataTests(unittest.TestCase):
    def test_cross_midnight_frozen_gold(self):
        out=aggregate_bars([bar(0,1),bar(1,3),bar(2,2)],timeframe='3m')
        b=out.bars[0]
        self.assertEqual((b.open,b.high,b.low,b.close,b.volume),(D(1),D(3),D(1),D(2),3))
        self.assertEqual((b.timestamp,b.end,b.trade_date),(START,START+timedelta(minutes=3),'2026-10-09'))
        self.assertFalse(b.partial)

    def test_all_periods_and_partial_short_session(self):
        for period in (1,3,5,15,30,60):
            bs=[bar(i,i+1,session_end=START+timedelta(minutes=60)) for i in range(60)]
            result=aggregate_bars(bs,timeframe=f'{period}m')
            self.assertEqual(len(result.bars),60//period)
            self.assertTrue(all(not b.partial for b in result.bars))
        short=[replace(bar(i,2),session_end=START+timedelta(minutes=2)) for i in range(2)]
        self.assertFalse(aggregate_bars(short,timeframe='3m').bars[0].partial)

    def test_missing_partial_and_asof(self):
        result=aggregate_bars([bar(0,1),bar(2,2)],timeframe='3m')
        self.assertTrue(result.bars[0].partial)
        self.assertEqual(result.bars[0].volume,2)
        self.assertTrue(result.warnings)
        self.assertTrue(aggregate_bars([bar(0,1,partial=True)],timeframe='1m').bars[0].partial)
        with self.assertRaises(ValueError):
            aggregate_bars([bar(0,1)],timeframe='1m',as_of=START)

    def test_out_of_order_duplicate_conflict(self):
        result=aggregate_bars([bar(1,2),bar(0,1),bar(0,1)],timeframe='3m')
        self.assertEqual(result.duplicate_count,1)
        self.assertEqual(result.bars[0].open,D(1))
        with self.assertRaises(ValueError): aggregate_bars([bar(0,1),bar(0,2)],timeframe='3m')

    def test_contract_isolation(self):
        other=replace(bar(0,9),instrument=InstrumentRef('TAIFEX','TMF','TAIFEX:TMF:202611','202611'))
        result=aggregate_bars([bar(0,1),other],timeframe='3m')
        self.assertEqual(len(result.bars),2)
        self.assertEqual({b.open for b in result.bars},{D(1),D(9)})

    def test_date_only_daily_weekly_and_no_fake_intraday(self):
        night=replace(bar(0,1),timestamp=None,end=None,session_open=None,session_end=None,interval='session')
        day=replace(night,session='day',open=D(3),high=D(3),low=D(3),close=D(3))
        result=aggregate_bars([day,night],timeframe='1d')
        self.assertEqual((result.bars[0].open,result.bars[0].close,result.bars[0].volume),(D(1),D(3),2))
        self.assertIsNone(result.bars[0].timestamp)
        self.assertTrue(result.bars[0].partial)  # no independently known coverage
        self.assertEqual(len(aggregate_bars([day,night],timeframe='1w').bars),1)
        with self.assertRaises(ValueError): aggregate_bars([day],timeframe='1m')

    def test_calendar_validation_and_missing_session(self):
        calendar=SessionCalendar([dict(open=START,end=START+timedelta(minutes=6),trade_date='2026-10-09',session='night',source='synthetic')],version='fixture')
        bs=[bar(i,1) for i in range(6)]
        self.assertFalse(aggregate_bars(bs,timeframe='1d',calendar=calendar).bars[0].partial)
        with self.assertRaises(ValueError):
            aggregate_bars([replace(bar(0,1),trade_date='2026-10-08')],timeframe='1m',calendar=calendar)

    def test_no_upsampling_or_straddled_buckets(self):
        source=replace(bar(0,1),interval='5m',end=START+timedelta(minutes=5))
        with self.assertRaises(ValueError): aggregate_bars([source],timeframe='3m')
        with self.assertRaises(ValueError): aggregate_bars([source],timeframe='1m')

    def test_whole_empty_bucket_and_sources_preserved(self):
        bs=[bar(0,1),bar(1,2),bar(2,3),bar(6,7,session_end=START+timedelta(minutes=9))]
        bs=[replace(b,session_end=START+timedelta(minutes=9)) for b in bs]
        result=aggregate_bars(bs,timeframe='3m')
        self.assertEqual(len(result.bars),2)  # no manufactured 00:02 bucket
        self.assertTrue(any('missing source interval' in x for x in result.warnings))
        long=[replace(bar(0,1),source_id='a'*128),replace(bar(1,2),source_id='b'*128)]
        out=aggregate_bars(long,timeframe='3m')
        self.assertEqual(out.source_ids,('a'*128,'b'*128))
        self.assertTrue(out.bars[0].source_id.startswith('aggregate:'))

    def test_daily_missing_session_and_week_holiday(self):
        records=[dict(open=START,end=START+timedelta(minutes=6),trade_date='2026-10-09',session='night',source='fixture'),
                 dict(open=START+timedelta(hours=1),end=START+timedelta(hours=1,minutes=2),trade_date='2026-10-09',session='day',source='fixture')]
        calendar=SessionCalendar(records,version='holiday-no-other-sessions')
        night=[bar(i,1) for i in range(6)]
        self.assertTrue(aggregate_bars(night,timeframe='1d',calendar=calendar).bars[0].partial)
        day=[replace(bar(i,3),session='day',timestamp=START+timedelta(hours=1,minutes=i),
                     end=START+timedelta(hours=1,minutes=i+1),session_open=START+timedelta(hours=1),
                     session_end=START+timedelta(hours=1,minutes=2)) for i in range(2)]
        complete=aggregate_bars(night+day,timeframe='1d',calendar=calendar).bars[0]
        self.assertFalse(complete.partial)
        self.assertEqual((complete.open,complete.close,complete.volume),(D(1),D(3),8))
        week=aggregate_bars(night+day,timeframe='1w',calendar=calendar,
                            as_of=datetime(2026,10,12,tzinfo=timezone.utc)).bars[0]
        self.assertFalse(week.partial)
        self.assertTrue(aggregate_bars(night+day,timeframe='1w',calendar=calendar).bars[0].partial)

    def test_closed_prefix_determinism_unknown_volume(self):
        bs=[bar(i,i+1) for i in range(6)]
        first=aggregate_bars(bs[:3],timeframe='3m')
        full=aggregate_bars(bs,timeframe='3m')
        self.assertEqual(first.bars,full.bars[:1])
        self.assertEqual(full.bars,aggregate_bars(tuple(reversed(bs)),timeframe='3m').bars)
        unknown=aggregate_bars([replace(bar(0,1),volume=None),bar(1,2)],timeframe='3m')
        self.assertIsNone(unknown.bars[0].volume)

    def test_live_partial_duration_and_display_contract(self):
        partial=replace(bar(0,2),partial=True,end=START+timedelta(seconds=30))
        result=aggregate_bars([partial],timeframe='3m',as_of=START+timedelta(seconds=30))
        self.assertTrue(result.bars[0].partial)
        tx=replace(bar(0,5),instrument=InstrumentRef('TAIFEX','TX','TAIFEX:TX:202610','202610'))
        self.assertEqual(aggregate_bars([tx],timeframe='1m').bars[0].symbol,'TX')

    def test_aggregation_decimal_context_independent(self):
        from decimal import localcontext, ROUND_UP, Inexact
        bs=[bar(0,'1.123456789'),bar(1,'2.123456789'),bar(2,'1.987654321')]
        expected=repr(aggregate_bars(bs,timeframe='3m'))
        with localcontext() as ctx:
            ctx.prec=6
            ctx.rounding=ROUND_UP
            ctx.traps[Inexact]=True
            before=(ctx.prec,ctx.rounding,dict(ctx.traps),dict(ctx.flags))
            self.assertEqual(repr(aggregate_bars(bs,timeframe='3m')),expected)
            self.assertEqual((ctx.prec,ctx.rounding,dict(ctx.traps),dict(ctx.flags)),before)
