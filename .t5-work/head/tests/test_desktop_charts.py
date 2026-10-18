"""Frozen preimplementation acceptance: synthetic engineering fixtures only.
Golden: index50 O150 H153 L148 C152 V50; delta +2; no fabricated times.
Viewport renders <=600/10,000; wheel zoom, drag pan, hover payload exact.
Trace mismatch rejects atomically; signal never presented as price/fill;
None gaps remain gaps; daily labels use explicit trade_date; no bars empty.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
HAS_QT=importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from quantlab.market import InstrumentRef, MarketBar
    from desktop_charts import CandlestickChart, ChartTrace, ChartMarker, ReferenceLine


def fixture(n=100):
    instrument=InstrumentRef('TAIFEX','TMF','TAIFEX:TMF:202610','202610')
    return tuple(MarketBar(instrument,(datetime(2000,1,1)+timedelta(days=i)).date().isoformat(),'day',Decimal(100+i),Decimal(103+i),Decimal(98+i),Decimal(102+i),i,interval='1d') for i in range(n))


@unittest.skipUnless(HAS_QT, 'Install pinned desktop requirements to test Qt widgets')
class ChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.widget=CandlestickChart(); self.widget.resize(1000,640); self.widget.show()
        self.trace=ChartTrace('TAIFEX:TMF:202610','a'*64,'b'*64,'回測')
        self.widget.set_series(fixture(),trace=self.trace,source_label='測試資料',status_label='歷史')
        self.app.processEvents(); self.addCleanup(self.widget.close)
    def test_golden_crosshair_daily(self):
        data=self.widget.bar_details(50)
        self.assertEqual((data['open'],data['high'],data['low'],data['close'],data['volume']),(Decimal(150),Decimal(153),Decimal(148),Decimal(152),50))
        self.assertEqual(data['change_text'],'+2'); self.assertEqual(data['time'],'2000-02-20')
        point=self.widget.bar_point(50)
        QTest.mouseMove(self.widget,point); self.app.processEvents()
        self.assertEqual(self.widget.crosshair_index,50)
    def test_taipei_cross_midnight_display_preserves_utc(self):
        from dataclasses import replace
        from desktop_charts import _display_time
        utc=datetime(2026,10,8,16,5,tzinfo=timezone.utc)
        bar=replace(fixture(1)[0],trade_date='2026-10-09',interval='1m',
                    timestamp=utc,end=utc+timedelta(minutes=1),
                    session_open=utc-timedelta(hours=8),session_end=utc+timedelta(hours=5))
        self.widget.set_series((bar,),trace=self.trace)
        self.assertEqual(self.widget.bar_details(0)['time'],'2026/10/09 00:05 台北時間')
        self.assertEqual(bar.timestamp,utc)
        self.assertEqual(bar.timestamp.utcoffset(),timedelta(0))
        self.assertEqual(_display_time(utc.isoformat()),'2026/10/09 00:05 台北時間')
        self.assertEqual(_display_time(None,'2026-10-09'),'2026-10-09')
        self.assertEqual(_display_time(datetime(2026,10,9)),'時間未提供／未驗證')

    def test_unavailable_legend_does_not_hide_zero(self):
        self.widget.set_overlays({'MA60':(None,)*100,'零值':(Decimal(0),)*100},panes={'RSI14':(None,)*100})
        self.assertEqual(self.widget._legend_label('MA60'),'MA60 · 資料不足')
        self.assertEqual(self.widget._legend_label('零值'),'零值')
        self.assertEqual(self.widget._legend_label('RSI14',pane=True),'RSI14 · 資料不足')
        self.widget.repaint(); self.app.processEvents()

    def test_bounded_render_zoom_pan(self):
        self.widget.set_series(fixture(10000),trace=self.trace)
        self.app.processEvents(); self.assertLessEqual(self.widget.last_rendered_bar_count,600)
        before=self.widget.visible_range
        p=self.widget.price_rect.center()
        event=QWheelEvent(p,p,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(self.widget,event); self.app.processEvents()
        self.assertLess(self.widget.visible_range[1]-self.widget.visible_range[0],before[1]-before[0])
        start=self.widget.visible_range
        QTest.mousePress(self.widget,Qt.MouseButton.LeftButton,pos=p.toPoint())
        QTest.mouseMove(self.widget,(p+QPointF(130,0)).toPoint())
        QTest.mouseRelease(self.widget,Qt.MouseButton.LeftButton,pos=(p+QPointF(130,0)).toPoint())
        self.assertLess(self.widget.visible_range[0],start[0])
    def test_trace_layers_and_reference(self):
        signal=ChartMarker(50,'signal','買進目標 1',reason='交叉')
        fill=ChartMarker(51,'fill','買進成交',price=Decimal(154),quantity=1,cost=Decimal(20))
        self.widget.set_markers((signal,fill),trace=self.trace)
        self.widget.set_reference_lines((ReferenceLine('停損',Decimal(140)),))
        self.assertEqual(len(self.widget.markers),2)
        with self.assertRaises(ValueError): self.widget.set_markers((fill,),trace=ChartTrace(self.trace.contract_id,'c'*64,self.trace.strategy_hash,'回測'))
        self.assertEqual(len(self.widget.markers),2)
        with self.assertRaises(ValueError): ChartMarker(1,'fill','成交')
    def test_series_change_clears_all_trace_layers(self):
        self.widget.set_markers((ChartMarker(50,'signal','目標1',target_position=1),),trace=self.trace)
        self.widget.set_series(fixture(20),trace=self.trace)
        self.assertEqual(self.widget.markers,())
        self.assertEqual(self.widget.bar_details(10)['markers'],())
        self.widget.repaint(); self.app.processEvents()

    def test_overlays_gaps_and_atomic_validation(self):
        values=(None,)*20+tuple(Decimal(100+i) for i in range(80))
        self.widget.set_overlays({'MA20（20根）':values})
        self.assertIsNone(self.widget.overlays['MA20（20根）'][0])
        with self.assertRaises(ValueError): self.widget.set_overlays({'壞':(Decimal('NaN'),)*100})
        self.assertIn('MA20（20根）',self.widget.overlays)
    def test_histogram_pane_keeps_missing_values(self):
        values=(None,)*50+tuple(Decimal(i-25) for i in range(50))
        self.widget.set_overlays({},panes={'MACD 柱（1倍）':values},pane_styles={'MACD 柱（1倍）':'histogram'})
        self.widget.repaint(); self.app.processEvents()
        self.assertIsNone(self.widget.panes['MACD 柱（1倍）'][0])
        with self.assertRaises(ValueError): self.widget.set_overlays({},panes={'指標':values},pane_styles={'指標':'invalid'})

    def test_empty_error_resize_and_host_timeframes(self):
        self.assertEqual(self.widget.timeframes,('1m','3m','5m','15m','30m','60m','1d','1w'))
        changes=[]; self.widget.timeframe_changed.connect(changes.append)
        self.widget.set_timeframe('5m'); self.assertEqual(changes,['5m'])
        self.widget.set_series((),source_label='無資料'); self.widget.set_error('來源不可用')
        for size in ((640,400),(1366,768),(1920,1080)):
            self.widget.resize(*size); self.app.processEvents(); self.assertFalse(self.widget.grab().isNull())
        self.assertEqual(self.widget.last_rendered_bar_count,0)

if __name__=='__main__': unittest.main()
