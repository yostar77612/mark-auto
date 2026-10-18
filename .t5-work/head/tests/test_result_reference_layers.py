"""Actual host and native renderer checks using synthetic offline engineering data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from pathlib import Path
import unittest
from tests import test_desktop_ui as support
from tests.test_backtest import bar, dataset, config, spec, run, C, START
from quantlab.core import content_hash, to_dict, ValidationError
from quantlab.reporting import save_dataset, export_report, load_result
from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance

D=Decimal


def fixture(side=1,mtm=False):
    data=dataset([bar(i,p) for i,p in enumerate((20000,20000,20100,20110))])
    data=replace(data,manifest={**data.manifest,'manifest_hash':content_hash(data.manifest)})
    cfg=config()
    if mtm:
        event=dict(timestamp=data.bars[-1].end,known_at=data.bars[-1].end,contract_id=C,price=D('20120'),version='synthetic')
        cfg=config(settlement_mode='daily_mtm',settlement_events=(event,))
    result=run(data,[(0,side),(1,side*3)],cfg,spec(stop_ticks=300,target_ticks=500))
    instrument=InstrumentRef('TAIFEX','TMF',C,'202610')
    bars=tuple(MarketBar(instrument,b.trade_date,b.session,b.open,b.high,b.low,b.close,b.volume,interval='1m',
                        timestamp=b.timestamp,end=b.end,session_open=START,session_end=data.bars[-1].end,source_id='synthetic-engineering') for b in data.bars)
    provenance=SourceProvenance('https://example.org/synthetic','a'*64,'合成工程測試資料','https://example.org/license',START,
                                '2026-10-01','2026-10-01','2026-10-01',mode='history')
    return data,result,MarketSeries(instrument,bars,provenance)


@unittest.skipUnless(support.HAS_QT,'Pinned Qt needed')
class ResultReferenceHostTests(unittest.TestCase):
    setUpClass=support.NativeDesktopTests.__dict__['setUpClass']
    setUp=support.NativeDesktopTests.setUp
    cleanup_window=support.NativeDesktopTests.cleanup_window

    def install(self,side=1,mtm=False):
        data,result,series=fixture(side,mtm)
        save_dataset(data,self.paths.state/'dataset.json')
        exported=export_report(result,self.paths.state/'reports')
        w=self.window
        w.market.set_market_series(series)
        w._market_data_bindings={C:data.manifest['data_hash']}
        w._market_research_series={C:series}
        w.market.timeframe_combo.setCurrentIndex(w.market.timeframe_combo.findData('1m'))
        w.result_choice.blockSignals(True); w.result_choice.clear(); w.result_choice.addItem('Engineering fixture',str(exported['result']))
        w.result_choice.blockSignals(False); w.show_result(); self.app.processEvents()
        return data,result,series

    def test_actual_host_binds_loaded_snapshot_and_visible_report_labels(self):
        _,result,_=self.install(mtm=True)
        chart=self.window.market.chart
        lines=chart.reference_lines
        self.assertEqual(len(lines),6)
        self.assertIsNotNone(chart.trace)
        self.assertEqual({line.snapshot_index for line in lines},{3})
        self.assertEqual({line.as_of for line in lines},{result.equity[-1]['timestamp']})
        self.assertEqual([line.price for line in lines[1:]],[D('20120'),D('19700'),D('19800'),D('20500'),D('20600')])
        self.assertLess(abs(lines[0].price-D('20066.66666666666666666666666666667')),D('1e-26'))
        self.assertIn('未含費用',lines[0].label); self.assertIn('非保證金',lines[1].label)
        self.assertTrue(chart.markers)
        text=self.window.result_card.label.text()
        for term in ('獲利因子','獲利因子未定義原因','夏普值（描述性）','夏普值觀測期數','假設每年期數：252','假設年無風險利率：0','數學最低觀測期數：2'):
            self.assertIn(term,text)
        chart.repaint();self.app.processEvents();self.assertFalse(chart.grab().isNull())

    def test_short_ranges_use_actual_entries_not_average_or_signals(self):
        self.install(side=-1)
        lines=self.window.market.chart.reference_lines
        self.assertEqual([line.price for line in lines[2:]],[D('20300'),D('20400'),D('19500'),D('19600')])

    def test_exact_data_strategy_source_or_contract_mismatch_clears_layers(self):
        from quantlab.core import to_dict
        data,result,series=self.install()
        w=self.window
        w._market_data_bindings[C]='f'*64;w.bind_result_layers(result)
        self.assertFalse(w.market.chart.reference_lines); self.assertFalse(w.market.chart.markers)
        w._market_data_bindings[C]=data.manifest['data_hash']
        wrong=replace(result,manifest={**to_dict(result.manifest),'spec_hash':'e'*64})
        w.bind_result_layers(wrong); self.assertFalse(w.market.chart.reference_lines)
        w._market_research_series[C]=replace(series,provenance=replace(series.provenance,sha256='b'*64))
        w.bind_result_layers(result);self.assertFalse(w.market.chart.reference_lines)
        w._market_research_series[C]=series
        wrong_contract=replace(result,equity=tuple([*result.equity[:-1],{**result.equity[-1],'contract_id':'TAIFEX:TMF:202611'}]))
        w.bind_result_layers(wrong_contract);self.assertFalse(w.market.chart.reference_lines)

    def test_final_event_snapshot_not_carried_into_earlier_view(self):
        self.install()
        chart=self.window.market.chart
        self.assertEqual(len(chart.visible_reference_lines()),6)
        chart._start=0;chart._count=3;chart.repaint();self.app.processEvents()
        self.assertFalse(chart.visible_reference_lines())
        chart._start=2;chart._count=2;self.assertEqual(len(chart.visible_reference_lines()),6)

    def test_daily_aggregation_exact_end_event_and_no_nearest_guess(self):
        _,result,_=self.install()
        w=self.window
        w.market.timeframe_combo.setCurrentIndex(w.market.timeframe_combo.findData('1d'))
        self.assertEqual(len(w.market.chart.bars),1)
        self.assertEqual({line.snapshot_index for line in w.market.chart.reference_lines},{0})
        self.assertEqual({line.as_of for line in w.market.chart.reference_lines},{result.equity[-1]['timestamp']})
        wrong=replace(result,equity=tuple([*result.equity[:-1],{**result.equity[-1],'timestamp':result.equity[-1]['timestamp']-timedelta(seconds=1)}]))
        w.bind_result_layers(wrong);self.assertFalse(w.market.chart.reference_lines)

    def test_flat_signal_only_invalid_future_and_incomplete_lots_no_references(self):
        from desktop_ui import MainWindow
        _,result,series=self.install()
        method=MainWindow._result_snapshot_lines
        for edits in ({'open_position':0,'open_lots':()}, {'open_position':3,'open_lots':()},
                      {'open_lots':({**result.metrics['open_lots'][0],'timestamp':START+timedelta(days=1)},)},
                      {'open_lots':({**result.metrics['open_lots'][0],'fill_id':'absent'},)},
                      {'open_lots':({**result.metrics['open_lots'][0],'contract_id':'TAIFEX:TMF:202611'},)}):
            wrong=replace(result,metrics={**result.metrics,**edits})
            self.assertEqual(method(wrong,series.bars,C),())
        no_policy=replace(result,manifest={**result.manifest,'protective_scope':'unknown'})
        self.assertEqual(len(method(no_policy,series.bars,C)),2)
        with localcontext() as ctx:
            ctx.prec=4;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
            self.assertEqual(method(result,series.bars,C),self.window.market.chart.reference_lines)

    def test_stale_snapshot_clears_on_empty_or_failed_result_selection(self):
        self.install()
        w=self.window
        w.result_choice.clear();self.assertFalse(w.market.chart.reference_lines)
        self.install()
        corrupt=Path(self.tmp.name)/'broken.json';corrupt.write_text('{')
        w.result_choice.addItem('broken',str(corrupt));w.result_choice.setCurrentIndex(w.result_choice.count()-1)
        self.assertFalse(w.market.chart.reference_lines)

    def test_snapshot_widget_identity_range_limits_and_atomic_validation(self):
        from desktop_charts import ReferenceLine,ChartTrace
        _,result,_=self.install()
        chart=self.window.market.chart;before=chart.reference_lines
        with self.assertRaises(ValueError):chart.set_reference_lines(before,trace=ChartTrace(C,'e'*64,'a'*64,'回測'))
        with self.assertRaises(ValueError):chart.set_reference_lines(before*2,trace=chart.trace)
        with self.assertRaises(ValueError):chart.set_reference_lines((ReferenceLine('late',D(1),4,result.equity[-1]['timestamp']),),trace=chart.trace)
        with self.assertRaises(ValueError):chart.set_reference_lines((ReferenceLine('wrong time',D(1),3,START),),trace=chart.trace)
        self.assertEqual(chart.reference_lines,before)
        with self.assertRaises(ValueError):ReferenceLine('unpaired',D(1),3)
        with self.assertRaises(ValueError):ReferenceLine('naive',D(1),3,START.replace(tzinfo=None))

    def test_same_prices_different_dataset_provenance_fails_closed(self):
        data,result,series=self.install()
        manifest=to_dict(data.manifest)
        manifest['calendar_version']='different-calendar-version'
        manifest['manifest_hash']=content_hash({k:v for k,v in manifest.items() if k not in ('manifest_hash','imported_at')})
        new_data=replace(data,manifest=manifest)
        # Valid alternate source dataset with identical bar values, both hashes valid.
        save_dataset(new_data,self.paths.state/'dataset.json')
        with self.assertRaisesRegex(ValidationError,'Result does not belong'):
            load_result(self.window.result_choice.currentData(),dataset=new_data)
        new_series=replace(series,provenance=replace(series.provenance,sha256='b'*64))
        self.window._market_research_series[C]=new_series
        self.window.market.set_market_series(new_series)
        self.window.bind_result_layers(result)
        self.assertFalse(self.window.market.chart.reference_lines,'Snapshot bound across distinct dataset provenance')
        self.assertFalse(self.window.market.chart.markers)

    def test_changed_basis_without_settlement_is_not_actual_mtm(self):
        from desktop_ui import MainWindow
        _,result,series=self.install()
        lots=tuple({**lot,'basis_price':D('25000')} for lot in result.metrics['open_lots'])
        wrong=replace(result,metrics={**result.metrics,'open_lots':lots})
        self.assertFalse(MainWindow._result_snapshot_lines(wrong,series.bars,C),'Unauthenticated basis is presented as actual MTM')

    def test_duplicate_lot_fragments_cannot_exceed_original_fill(self):
        from desktop_ui import MainWindow
        _,result,series=self.install()
        original=result.metrics['open_lots'][1]
        # Duplicating a 2-contract opening fill as 3 one-contract lot fragments
        # individually passes quantity <= fill.quantity but collectively cannot.
        lots=tuple({**original,'quantity':1} for _ in range(3))
        wrong=replace(result,metrics={**result.metrics,'open_lots':lots})
        self.assertFalse(MainWindow._result_snapshot_lines(wrong,series.bars,C),'A duplicate fill exceeds its actual filled quantity')


    def test_legitimate_split_residual_lots_preserve_references(self):
        from desktop_ui import MainWindow
        for side in (1,-1):
            for mtm in (False,True):
                _,result,series=fixture(side,mtm)
                first,second=result.metrics['open_lots']
                split=replace(result,metrics={**result.metrics,'open_lots':(first,{**second,'quantity':1},{**second,'quantity':1})})
                expected=MainWindow._result_snapshot_lines(result,series.bars,C)
                self.assertEqual(len(expected),6)
                self.assertEqual(MainWindow._result_snapshot_lines(split,series.bars,C),expected)

    def test_partial_closed_lot_residual_and_daily_mtm_are_verified(self):
        from desktop_ui import MainWindow
        for side in (1,-1):
            data=dataset([bar(i,p) for i,p in enumerate((20000,20000,20100,20110,20115))])
            event=dict(timestamp=data.bars[2].end,known_at=data.bars[2].end,contract_id=C,price=D('20120'),version='synthetic')
            result=run(data,[(0,3*side),(1,side)],config(settlement_mode='daily_mtm',settlement_events=(event,)),spec(stop_ticks=300,target_ticks=500))
            self.assertEqual(result.ledger[0]['quantity'],2)
            lines=MainWindow._result_snapshot_lines(result,data.bars,C)
            self.assertEqual(len(lines),4)
            self.assertEqual([line.price for line in lines[:2]],[D('20000'),D('20120')])
            bad=replace(result,metrics={**result.metrics,'open_lots':({**result.metrics['open_lots'][0],'quantity':3},),'open_position':3*side},
                        equity=(*result.equity[:-1],{**result.equity[-1],'position':3*side}))
            self.assertFalse(MainWindow._result_snapshot_lines(bad,data.bars,C))

    def test_settlement_before_same_timestamp_next_open_does_not_change_basis(self):
        from desktop_ui import MainWindow
        data=dataset([bar(i,p) for i,p in enumerate((20000,20000,20100,20110))])
        event=dict(timestamp=data.bars[0].end,known_at=data.bars[0].end,contract_id=C,price=D('19000'),version='synthetic')
        result=run(data,[(0,1)],config(settlement_mode='daily_mtm',settlement_events=(event,)))
        lines=MainWindow._result_snapshot_lines(result,data.bars,C)
        self.assertEqual(len(lines),2)
        self.assertEqual([line.price for line in lines],[D('20000'),D('20000')])

    def test_unapplied_or_misbound_settlement_omits_snapshot(self):
        from desktop_ui import MainWindow
        _,result,series=fixture(mtm=True)
        actual=result.metrics['settlements'][0]
        for settlement_rows in ((),({**actual,'event_id':'0'*64},),({**actual,'event':{**actual['event'],'price':D('25000')}},)):
            wrong=replace(result,metrics={**result.metrics,'settlements':settlement_rows})
            self.assertFalse(MainWindow._result_snapshot_lines(wrong,series.bars,C))

    def test_forged_rehashed_basis_rejected_in_actual_persisted_host_path(self):
        from quantlab.reporting import read_json,write_json
        self.install()
        path=self.window.result_choice.currentData()
        envelope=read_json(path)
        payload=envelope['payload']
        for lot in payload['metrics']['open_lots']:lot['basis_price']='25000'
        unhashed={**payload,'manifest':{k:v for k,v in payload['manifest'].items() if k not in ('run_hash','reproducibility_hash')}}
        digest=content_hash(unhashed)
        payload['manifest'].update(run_hash=digest,reproducibility_hash=digest)
        envelope['sha256']=content_hash(payload)
        write_json(path,envelope)
        self.window.show_result()
        self.assertFalse(self.window.market.chart.reference_lines)


    def test_rolled_open_lot_keeps_new_contract_entry_and_mtm_basis(self):
        from desktop_ui import MainWindow
        new='TAIFEX:TMF:202611'
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20010),bar(2,20100,contract=new),
                      bar(3,20110,contract=new),bar(4,20120,contract=new)])
        roll=dict(known_at=START,effective_at=data.bars[2].timestamp,from_contract=C,to_contract=new)
        settlements=tuple(dict(timestamp=b.end,known_at=b.end,contract_id=b.contract_id,price=price,version='synthetic')
                          for b,price in ((data.bars[1],D('20020')),(data.bars[4],D('20200'))))
        result=run(data,[(0,1)],config(roll_events=(roll,),settlement_mode='daily_mtm',settlement_events=settlements),
                   spec(stop_ticks=300,target_ticks=500))
        lines=MainWindow._result_snapshot_lines(result,tuple(b for b in data.bars if b.contract_id==new),new)
        self.assertEqual(len(lines),4)
        self.assertEqual([line.price for line in lines[:2]],[D('20100'),D('20200')])


if __name__=='__main__':unittest.main()
