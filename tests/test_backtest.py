import json
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal,localcontext,ROUND_UP,ROUND_DOWN,Inexact
from pathlib import Path
import unittest
from unittest.mock import patch
from quantlab.core import Bar,Dataset,CostSpec,BacktestConfig,StrategySpec,Signal,ValidationError,content_hash
from quantlab.backtest import run_backtest,calculate_costs

D=Decimal
C='TAIFEX:TMF:202610'
START=datetime(2026,10,1,1,tzinfo=timezone.utc)

def bar(i,op,hi=None,lo=None,cl=None,volume=10,trade_date='2026-10-01',session='day',contract=C):
    op=D(op); hi=op if hi is None else D(hi); lo=op if lo is None else D(lo); cl=op if cl is None else D(cl)
    return Bar(START+timedelta(minutes=i),START+timedelta(minutes=i+1),trade_date,session,contract,op,hi,lo,cl,volume)

def dataset(bars):
    bars=tuple(bars)
    return Dataset(bars,{'source_type':'synthetic','validation_status':'valid','data_hash':content_hash(bars),'calendar_version':'synthetic-v1','calendar_hash':'synthetic-calendar'}, {'valid':True,'errors':[],'missing_intervals':0})

def config(**kwargs):
    defaults={'initial_cash':D('100000'),'costs':CostSpec(D('0'),D('0'),0,'none','2020-01-01','fixture-v1'),'initial_margin_per_contract':D('10000'),'maintenance_margin_per_contract':D('8000'),'margin_version':'fixture-v1','max_position':3}
    defaults.update(kwargs)
    return BacktestConfig(**defaults)

def spec(**params):
    return StrategySpec('fixture','channel_breakout',{'lookback':2,**params},{})

def run(data,targets,cfg=None,st=None):
    signals=tuple(Signal(data.bars[i].end,C,target,'golden intent') for i,target in targets)
    with patch('quantlab.backtest.generate_signals',return_value=signals):
        return run_backtest(data,st or spec(),cfg or config())

class EngineTests(unittest.TestCase):
    def test_independent_golden_pnl(self):
        golden=json.loads((Path(__file__).parent/'fixtures/engine_golden.json').read_text())
        for case in golden['cases']:
            with self.subTest(case=case['name']):
                data=dataset([bar(0,'19000'),bar(1,case['entry']),bar(2,case['exit'])])
                cfg=config(costs=CostSpec(D(case['commission']),D(case['tax_rate']),0,'none','2020-01-01','golden'))
                r=run(data,[(0,case['side']*case['quantity']),(1,0)],cfg)
                self.assertEqual(r.metrics['realized_gross_pnl'],D(case['gross']))
                self.assertEqual(r.metrics['net_pnl'],D(case['net']))
                self.assertEqual(r.ledger[0]['net_pnl'],D(case['net']))
                self.assertEqual(r.equity[-1]['cash'],D('100000')+D(case['net']))
    def test_next_open_slippage_tax(self):
        data=dataset([bar(0,'19000'),bar(1,'20000'),bar(2,'20010')])
        cfg=config(costs=CostSpec(D('5'),D('0.00002'),1,'none','2020-01-01','v1'))
        r=run(data,[(0,1),(1,0)],cfg)
        self.assertEqual([f.price for f in r.fills],[D('20001'),D('20009')])
        self.assertEqual(r.metrics['net_pnl'],D('61.998'))
        self.assertEqual(r.metrics['slippage_cost'],D('20'))
        self.assertEqual(r.fills[0].timestamp,data.bars[1].timestamp)
        self.assertEqual(r.equity[-1]['cash'],D('100061.998'))
    def test_gap_stop(self):
        r=run(dataset([bar(0,20000),bar(1,20000),bar(2,19980,19985,19970)]),[(0,1)],st=spec(stop_ticks=5))
        self.assertEqual(r.fills[-1].price,D('19980')); self.assertEqual(r.fills[-1].reason,'gap_stop')
        self.assertEqual(r.metrics['net_pnl'],D('-200'))
    def test_conflict_conservative(self):
        r=run(dataset([bar(0,20000),bar(1,20000,20010,19990)]),[(0,1)],st=spec(stop_ticks=5,target_ticks=5))
        self.assertEqual(r.fills[-1].price,D('19995'))
        self.assertIn('ambiguous',r.rejects[0]['reason']); self.assertEqual(r.metrics['net_pnl'],D('-50'))
    def test_fifo_partial_and_flip(self):
        r=run(dataset([bar(0,20000),bar(1,20000),bar(2,20010),bar(3,20020)]),[(0,2),(1,1),(2,-1)])
        self.assertEqual([x['quantity'] for x in r.ledger],[1,1])
        self.assertEqual([x['gross_pnl'] for x in r.ledger],[D('100'),D('200')])
        self.assertEqual(r.metrics['open_position'],-1)
        self.assertEqual(len(r.fills),4)
    def test_margin_insufficient(self):
        r=run(dataset([bar(0,20000),bar(1,20000)]),[(0,1)],config(initial_cash=D('9999')))
        self.assertFalse(r.fills); self.assertIn('margin',r.rejects[0]['reason'])
        with self.assertRaises(ValidationError): run(dataset([bar(0,20000)]),[],config(initial_margin_per_contract=None))
    def test_maintenance_liquidation_next_open(self):
        data=dataset([bar(0,20000),bar(1,20000,20000,19900,19900),bar(2,19800)])
        r=run(data,[(0,1)],config(initial_cash=D('10000'),maintenance_margin_per_contract=D('9500')))
        self.assertEqual(r.fills[-1].reason,'maintenance_liquidation'); self.assertEqual(r.fills[-1].price,D('19800'))
        self.assertEqual(r.metrics['net_pnl'],D('-2000'))
    def test_no_volume_wait_and_overnight(self):
        data=dataset([bar(0,20000),bar(1,20100,volume=0),bar(900,20010,trade_date='2026-10-02',session='night'),bar(901,20020,trade_date='2026-10-02',session='night')])
        r=run(data,[(0,1),(2,0)])
        self.assertEqual(r.fills[0].price,D('20010')); self.assertEqual(r.metrics['net_pnl'],D('100'))
    def test_expiry_roll_settlement_blocked(self):
        data=dataset([bar(0,20000)])
        with self.assertRaises(ValidationError): config(settlement_mode='daily')
        for cfg in (config(roll_events=({'from':C},)),config(instrument_expiries={C:'2026-09-30'})):
            with self.assertRaises(ValidationError): run(data,[],cfg)
        with self.assertRaises(ValidationError): run(dataset([bar(0,20000),bar(1,20000,contract='TAIFEX:TMF:202611')]),[])
    def test_explicit_roll_two_real_prices_and_costs(self):
        new='TAIFEX:TMF:202611'
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20010),bar(2,20100,contract=new),bar(3,20110,contract=new),bar(4,20120,contract=new)])
        event={'known_at':START,'effective_at':data.bars[2].timestamp,'from_contract':C,'to_contract':new}
        cfg=config(roll_events=(event,),costs=CostSpec(D('5'),D('0'),1,'none','2020-01-01','v1'))
        signals=(Signal(data.bars[0].end,C,1,'enter'),Signal(data.bars[4].end,new,0,'exit'))
        with patch('quantlab.backtest.generate_signals',return_value=signals): r=run_backtest(data,spec(),cfg)
        self.assertEqual([f.price for f in r.fills],[D('20001'),D('20009'),D('20101'),D('20119')])
        self.assertEqual([f.reason for f in r.fills],['target_open','roll_close','roll_open','target_close'])
        self.assertEqual(r.metrics['realized_gross_pnl'],D('260'))
        self.assertEqual(r.metrics['net_pnl'],D('240'))
        self.assertEqual(r.metrics['rolls'][0]['status'],'complete')
    def test_roll_unknown_future_and_missing_leg_blocked(self):
        new='TAIFEX:TMF:202611'
        data=dataset([bar(0,20000),bar(1,20000),bar(1,20100,contract=new)])
        event={'known_at':START+timedelta(minutes=2),'effective_at':START+timedelta(minutes=1),'from_contract':C,'to_contract':new}
        with self.assertRaises(ValidationError): run(data,[],config(roll_events=(event,)))
        event={**event,'known_at':START}
        with self.assertRaises(ValidationError): run(dataset(data.bars[:-1]),[],config(roll_events=(event,)))
    def test_roll_new_leg_margin_rejection_is_flat_recorded(self):
        new='TAIFEX:TMF:202611'
        data=dataset([bar(0,20000),bar(1,20000),bar(2,19990),bar(2,20100,contract=new)])
        event={'known_at':START,'effective_at':data.bars[2].timestamp,'from_contract':C,'to_contract':new}
        r=run(data,[(0,1)],config(initial_cash=D('10000'),maintenance_margin_per_contract=None,roll_events=(event,)))
        self.assertEqual(r.metrics['open_position'],0)
        self.assertEqual(r.metrics['rolls'][0]['status'],'new_leg_rejected')
        self.assertEqual(len(r.fills),2)
    def test_daily_fractional_settlement_no_double_count(self):
        data=dataset([bar(0,20000),bar(1,20000,20010,20000,20010),bar(2,20020,trade_date='2026-10-02')])
        settlement={'timestamp':data.bars[1].end,'known_at':data.bars[1].end,'contract_id':C,'price':D('20012.5'),'version':'synthetic-settlement-v1'}
        r=run(data,[(0,1),(1,0)],config(settlement_mode='daily_mtm',settlement_events=(settlement,)))
        self.assertEqual(r.equity[1]['cash'],D('100125'))
        self.assertEqual(r.equity[1]['unrealized_pnl'],D('-25'))
        self.assertEqual(r.equity[1]['equity'],D('100100'))
        self.assertEqual(r.ledger[0]['gross_pnl'],D('200'))
        self.assertEqual(r.ledger[0]['cash_pnl_on_exit'],D('75'))
        self.assertEqual(r.metrics['net_pnl'],D('200'))
        self.assertEqual(r.metrics['realized_gross_pnl'],D('200'))
        self.assertEqual(len(r.fills),2)
    def test_daily_missing_settlement_blocked(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20020,trade_date='2026-10-02')])
        with self.assertRaises(ValidationError): run(data,[(0,1)],config(settlement_mode='daily_mtm'))
        settlement={'timestamp':data.bars[2].end,'known_at':data.bars[2].end,'contract_id':C,'price':D('20020'),'version':'fixture'}
        with self.assertRaises(ValidationError): run(data,[(0,1)],config(settlement_mode='daily_mtm',settlement_events=(settlement,)))
    def test_target_open_gap_precedes_later_low(self):
        r=run(dataset([bar(0,20000),bar(1,20000),bar(2,20010,20020,19900)]),[(0,1)],st=spec(stop_ticks=5,target_ticks=5))
        self.assertEqual(r.fills[-1].reason,'gap_target'); self.assertEqual(r.fills[-1].price,D('20010'))
    def test_final_settlement_fractional_costed_once_after_daily(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20020)])
        daily={'timestamp':data.bars[1].end,'known_at':data.bars[1].end,'contract_id':C,'price':D('20010.5'),'version':'synthetic-daily'}
        final={'timestamp':data.bars[2].end,'known_at':data.bars[2].end,'contract_id':C,'price':D('20020.25'),'version':'synthetic-final-cost-assumption','kind':'final','settlement_fee_per_contract':D('5'),'settlement_tax_rate':D('0.00002'),'tax_rounding':'none'}
        cfg=config(settlement_mode='daily_mtm',settlement_events=(daily,final),instrument_expiries={C:'2026-10-01'})
        r=run(data,[(0,1),(2,1)],cfg)
        self.assertEqual(len(r.fills),1)  # Cash settlement is not a fabricated tick-valid trade fill.
        self.assertEqual(r.metrics['open_position'],0)
        self.assertEqual(r.metrics['realized_gross_pnl'],D('202.5'))
        self.assertEqual(r.metrics['total_costs'],D('9.00405'))
        self.assertEqual(r.metrics['net_pnl'],D('193.49595'))
        self.assertEqual(r.equity[-1]['cash'],D('100193.49595'))
        self.assertEqual(r.ledger[0]['net_pnl'],D('193.49595'))
        self.assertEqual(r.ledger[0]['cash_pnl_on_exit'],D('97.5'))
        self.assertEqual(r.ledger[0]['exit_event_type'],'final_settlement')
        self.assertIsNone(r.ledger[0]['exit_fill_id'])
        self.assertIn('finally settled',r.rejects[-1]['reason'])
        with self.assertRaises(ValidationError): run(data,[(0,1)],replace(cfg,settlement_events=(daily,final,final)))
        with self.assertRaises(ValidationError): run(dataset((*data.bars,bar(3,20020))),[(0,1)],cfg)
    def test_final_settlement_missing_and_expiry_night_blocked(self):
        data=dataset([bar(0,20000),bar(1,20000)])
        with self.assertRaises(ValidationError): run(data,[(0,1)],config(instrument_expiries={C:'2026-10-01'}))
        night=dataset([replace(bar(360,20000),session='night')])  # UTC07:00 = Taipei15:00 expiry day.
        with self.assertRaises(ValidationError): run(night,[],config(instrument_expiries={C:'2026-10-01'}))
        prior_night=dataset([replace(bar(-720,20000),session='night')])  # Previous local night can belong to expiry trading date.
        run(prior_night,[],config(instrument_expiries={C:'2026-10-01'}))
    def test_caller_rounding_and_traps_do_not_change_hash(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20010)])
        hashes=[]
        for rounding in (ROUND_UP,ROUND_DOWN):
            with localcontext() as ctx:
                ctx.prec=4; ctx.rounding=rounding; ctx.traps[Inexact]=True
                hashes.append(run(data,[(0,1),(1,0)]).manifest['run_hash'])
        self.assertEqual(hashes[0],hashes[1])
    def test_negative_data(self):
        with self.assertRaises(ValidationError): bar(0,'20000.5')
        data=dataset([bar(0,20000)])
        for d in (replace(data,quality={'valid':False}),replace(data,quality={'valid':True,'missing_intervals':1}),replace(data,manifest={**data.manifest,'data_hash':'fake'})):
            with self.assertRaises(ValidationError): run(d,[])
    def test_cost_and_margin_effective_changes(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20010,trade_date='2026-10-02')])
        cfg=config(cost_schedule=(CostSpec(D('5'),D('0'),0,'none','2026-10-02','v2'),),margin_schedule=({'effective_from':'2026-10-02','initial_margin':D('12000'),'maintenance_margin':D('9000'),'version':'m2'},))
        r=run(data,[(0,1),(1,0)],cfg)
        self.assertEqual(r.metrics['net_pnl'],D('95')); self.assertEqual(r.equity[-1]['margin_version'],'m2')
    def test_reproducible_three_runs_context_independent(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20010)])
        hashes=[]
        for precision in (10,28,50):
            with localcontext() as ctx:
                ctx.prec=precision
                hashes.append(content_hash(run(data,[(0,1),(1,0)])))
        self.assertEqual(len(set(hashes)),1)
    def test_import_wallclock_excluded_from_hash(self):
        data=dataset([bar(0,20000),bar(1,20000)])
        one=replace(data,manifest={**data.manifest,'imported_at':'2026-01-01T00:00:00Z'})
        two=replace(data,manifest={**data.manifest,'imported_at':'2026-02-01T00:00:00Z'})
        self.assertEqual(run(one,[(0,1)]).manifest['run_hash'],run(two,[(0,1)]).manifest['run_hash'])
    def test_short_stop_gap_and_settlement_signs(self):
        data=dataset([bar(0,20000),bar(1,20000),bar(2,20020)])
        r=run(data,[(0,-1)],st=spec(stop_ticks=5))
        self.assertEqual(r.metrics['net_pnl'],D('-200'))
        self.assertEqual(r.fills[-1].price,D('20020'))
        event={'timestamp':data.bars[1].end,'known_at':data.bars[1].end,'contract_id':C,'price':D('19990.5'),'version':'fixture'}
        r=run(data,[(0,-1),(1,0)],config(settlement_mode='daily_mtm',settlement_events=(event,)))
        self.assertEqual(r.equity[1]['cash'],D('100095'))
        self.assertEqual(r.metrics['net_pnl'],D('-200'))
        self.assertEqual(r.ledger[0]['cash_pnl_on_exit'],D('-295'))
    def test_position_limit_and_rounding(self):
        r=run(dataset([bar(0,20000),bar(1,20000)]),[(0,2)],config(max_position=1))
        self.assertFalse(r.fills); self.assertEqual(r.rejects[0]['reason'],'max position exceeded')
        for rounding,expected in [('none','4.0002'),('floor_twd','4'),('half_up_twd','4'),('ceiling_twd','5')]:
            costs=CostSpec(D('0'),D('0.00002'),0,rounding,'2020-01-01','fixture')
            self.assertEqual(calculate_costs(D('20001'),1,costs)[1],D(expected))
    def test_equity_accounting_identity_every_bar(self):
        data=dataset([bar(i,p) for i,p in enumerate([20000,20000,20010,19990,20020,20030])])
        cfg=config(costs=CostSpec(D('5'),D('0.00002'),1,'none','2020-01-01','fixture'))
        r=run(data,[(0,2),(1,1),(2,-2),(3,-1),(4,0)],cfg)
        for row in r.equity: self.assertEqual(row['equity'],row['cash']+row['unrealized_pnl'])
        self.assertEqual(r.metrics['net_pnl'],sum((x['net_pnl'] for x in r.ledger),D('0')))
    def test_flat_metrics_no_infinity(self):
        r=run(dataset([bar(0,20000)]),[])
        self.assertEqual(r.metrics['max_drawdown'],0); self.assertIsNone(r.metrics['win_rate']); self.assertIsNone(r.metrics['sharpe'])
    def test_real_strategy_integration(self):
        data=dataset([bar(i,p) for i,p in enumerate([100,100,102,103,99,98])])
        result=run_backtest(data,spec(),config())
        self.assertGreater(len(result.fills),0)
        self.assertEqual(result.fills[0].timestamp,data.bars[3].timestamp)

if __name__=='__main__': unittest.main()
