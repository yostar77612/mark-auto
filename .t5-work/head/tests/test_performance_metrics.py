"""Frozen hand calculations on synthetic engineering fixtures; not market evidence."""
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext, ROUND_UP, ROUND_DOWN, Context, ROUND_HALF_EVEN
import tempfile
from pathlib import Path
from fractions import Fraction
import unittest
from quantlab.backtest import _performance_metrics
from quantlab.core import CostSpec, content_hash
from quantlab.reporting import export_report, load_result
from tests.test_backtest import bar, dataset, config, spec, run, C

D = Decimal


def metric(pnls=(), values=('10100','10302','10198.98'), initial='10000'):
    equity = [{'trade_date': f'2026-10-{i+1:02}', 'equity': D(v) if v is not None else None}
              for i,v in enumerate(values)]
    return _performance_metrics([{'net_pnl': D(p)} for p in pnls], equity, D(initial))


class PerformanceMetricTests(unittest.TestCase):
    def test_profit_factor_hand_golden_net_fifo_lots(self):
        values = metric(('150', '-30', '0', '50', '-20'))
        self.assertEqual(values['profit_factor'], D('4'))
        self.assertIsNone(values['profit_factor_reason'])
        self.assertIn('net PnL',values['profit_factor_basis'])

    def test_profit_factor_undefined_and_all_losses(self):
        for pnls,reason in (((), 'no closed lots'), (('0',), 'no losing closed lots'), (('20','30'), 'no losing closed lots')):
            with self.subTest(pnls=pnls):
                result = metric(pnls)
                self.assertIsNone(result['profit_factor']); self.assertEqual(result['profit_factor_reason'],reason)
        self.assertEqual(metric(('-10','-20'))['profit_factor'],D(0))

    def test_gross_winners_can_be_net_losers_after_fees(self):
        data = dataset([bar(i,p) for i,p in enumerate((20000,20000,20010,20000,20020))])
        cfg = config(costs=CostSpec(D('60'),D('0'),0,'none','2020-01-01','fee-golden'))
        result = run(data,[(0,1),(1,0),(2,1),(3,0)],cfg)
        self.assertEqual([x['gross_pnl'] for x in result.ledger],[D('100'),D('200')])
        self.assertEqual([x['net_pnl'] for x in result.ledger],[D('-20'),D('80')])
        self.assertEqual(result.metrics['profit_factor'],D('4'))

    def test_fifo_partial_cost_allocation_excludes_unclosed_lot(self):
        data = dataset([bar(i,p) for i,p in enumerate((20000,20000,20010,19990,20100))])
        cfg = config(costs=CostSpec(D('5'),D('0'),0,'none','2020-01-01','fee-golden'))
        result = run(data,[(0,3),(1,2),(2,1)],cfg)
        self.assertEqual([x['net_pnl'] for x in result.ledger],[D('90'),D('-110')])
        self.assertEqual(result.metrics['open_position'],1)
        self.assertAlmostEqual(result.metrics['profit_factor'], D(9)/11,places=26)
        self.assertGreater(result.metrics['unrealized_pnl'],0)

    def test_daily_mtm_uses_full_trade_pnl_not_exit_cash_delta(self):
        data = dataset([bar(0,20000),bar(1,20000),bar(2,20010),bar(3,20000),bar(4,19990)])
        event = {'timestamp':data.bars[1].end,'known_at':data.bars[1].end,'contract_id':C,'price':D('20020'),'version':'golden'}
        cfg = config(settlement_mode='daily_mtm',settlement_events=(event,),costs=CostSpec(D('5'),D('0'),0,'none','2020-01-01','fee-golden'))
        result = run(data,[(0,1),(1,0),(2,1),(3,0)],cfg)
        self.assertEqual(result.ledger[0]['cash_pnl_on_exit'],D('-100'))
        self.assertEqual([x['net_pnl'] for x in result.ledger],[D('90'),D('-110')])
        self.assertAlmostEqual(result.metrics['profit_factor'],D(9)/11,places=26)

    def test_final_settlement_costs_count_exactly_once(self):
        data = dataset([bar(0,20000),bar(1,20000),bar(2,19990),bar(3,20000),bar(4,20020)])
        event = {'timestamp':data.bars[-1].end,'known_at':data.bars[-1].end,'contract_id':C,'price':D('20020'),
                 'version':'golden','kind':'final','settlement_fee_per_contract':D('5'),'settlement_tax_rate':D('0'),'tax_rounding':'none'}
        cfg = config(settlement_mode='daily_mtm',settlement_events=(event,),instrument_expiries={C:'2026-10-01'},
                     costs=CostSpec(D('5'),D('0'),0,'none','2020-01-01','fee-golden'))
        result = run(data,[(0,1),(1,0),(2,1)],cfg)
        self.assertEqual([x['net_pnl'] for x in result.ledger],[D('-110'),D('190')])
        self.assertAlmostEqual(result.metrics['profit_factor'],D(19)/11,places=26)
        self.assertEqual(result.metrics['net_pnl'],D('80'))

    def test_sharpe_independent_hand_golden_sample_variance(self):
        # r=(.01,.02,-.01), mean=1/150, sample variance=7/30000;
        # sqrt(252) * mean / sample SD = sqrt(48).
        result = metric()
        self.assertEqual([x['return'] for x in result['daily_returns']],[D('.01'),D('.02'),D('-.01')])
        self.assertLess(abs(result['sharpe']-D('6.928203230275509174109785366023489')),D('1e-30'))
        self.assertIsNone(result['sharpe_reason'])
        self.assertEqual(result['sharpe_observations'],3)
        self.assertEqual(result['sharpe_sample_count'],3)
        assumptions = result['annualization']
        self.assertEqual(assumptions['periods_per_year'],252)
        self.assertEqual(assumptions['annual_risk_free_rate'],D(0))
        self.assertEqual(assumptions['standard_deviation'],'sample (ddof=1)')
        self.assertEqual(assumptions['minimum_observations'],2)
        self.assertIn('not evidence of reliability',result['sharpe_note'])
        self.assertIn('not a validated annual trading calendar',result['sharpe_note'])

    def test_sharpe_undefined_zero_variance_or_short_samples(self):
        for values,reason in (((), 'at least 2'), (('10000',), 'at least 2'), (('10000','10000'),'zero daily'), (('11000','12100'),'zero daily')):
            with self.subTest(values=values):
                result = metric(values=values)
                self.assertIsNone(result['sharpe']); self.assertIn(reason,result['sharpe_reason'])
        self.assertIsNotNone(metric(values=('10100','10302'))['sharpe'])

    def test_missing_nonfinite_nonpositive_equity_is_not_dropped(self):
        for bad in (None,'0','-1','NaN','Infinity'):
            with self.subTest(bad=bad):
                result = metric(values=('10100',bad,'10302'))
                self.assertIsNone(result['sharpe'])
                self.assertIn('no observations discarded',result['sharpe_reason'])
                self.assertEqual(result['sharpe_observations'],3)
                self.assertEqual(result['sharpe_sample_count'],1)
                self.assertIsNone(result['daily_returns'][1]['return'])
                self.assertIsNone(result['daily_returns'][2]['return'])
                self.assertIsNotNone(result['daily_returns'][1]['reason'])
        self.assertIsNone(metric(initial='0')['sharpe'])

    def test_causal_observed_date_returns_and_no_gap_imputation(self):
        equity = [dict(trade_date='2026-10-01',equity=D('10050')),dict(trade_date='2026-10-01',equity=D('10100')),
                  dict(trade_date='2026-10-05',equity=D('10302')),dict(trade_date='2026-10-09',equity=D('10198.98'))]
        prefix = _performance_metrics([],equity[:-1],D('10000'))
        full = _performance_metrics([],equity,D('10000'))
        self.assertEqual(prefix['daily_returns'],full['daily_returns'][:2])
        self.assertEqual(len(full['daily_returns']),3)
        self.assertIn('gaps may span multiple days',full['annualization']['return_frequency'])

    def test_fixed_decimal_context_and_caller_traps(self):
        results=[]
        for precision,rounding in ((4,ROUND_UP),(8,ROUND_DOWN),(60,ROUND_UP)):
            with localcontext() as ctx:
                ctx.prec=precision; ctx.rounding=rounding; ctx.traps[Inexact]=True
                results.append(content_hash(metric(('150','-30','50','-20'))))
        self.assertEqual(len(set(results)),1)

    def test_added_metrics_roundtrip_with_honest_source_hash(self):
        from quantlab.reporting import synthetic_dataset, demo_config
        from quantlab.strategies import builtin_strategies
        from quantlab.backtest import run_backtest
        import hashlib
        result=run_backtest(synthetic_dataset(),builtin_strategies()[0],demo_config())
        source=Path(__file__).resolve().parents[1]/'quantlab/backtest.py'
        self.assertEqual(result.manifest['source_hashes']['backtest.py'],hashlib.sha256(source.read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            paths=export_report(result,tmp)
            loaded=load_result(paths['result'])
            self.assertEqual(content_hash(loaded),content_hash(result))
            self.assertIn('profit_factor',loaded.metrics)
            self.assertIn('sharpe_observations',loaded.metrics)

    def test_short_mtm_partial_fees_independent_hand_golden(self):
        # Open 3 short at 20000 with fee 7 each; settle at 19950; close 1 at
        # 20010 then 1 at 19980, keeping one open. Net full-entry PnLs: -114,186.
        data=dataset([bar(i,p) for i,p in enumerate((20000,20000,20010,19980,19970))])
        event=dict(timestamp=data.bars[1].end,known_at=data.bars[1].end,contract_id=C,price=D('19950'),version='independent')
        cfg=config(settlement_mode='daily_mtm',settlement_events=(event,),costs=CostSpec(D('7'),D('0'),0,'none','2020-01-01','independent'))
        result=run(data,[(0,-3),(1,-2),(2,-1)],cfg)
        self.assertEqual([r['net_pnl'] for r in result.ledger],[D('-114'),D('186')])
        self.assertEqual([r['cash_pnl_on_exit'] for r in result.ledger],[D('-600'),D('-300')])
        self.assertEqual(result.metrics['open_position'],-1)
        with localcontext(Context(prec=34,rounding=ROUND_HALF_EVEN)):
            self.assertEqual(result.metrics['profit_factor'],D(31)/D(19))

    def test_sharpe_four_mixed_returns_independent_fraction_oracle(self):
        fractions=[Fraction(1003,1000),Fraction(998,1000),Fraction(1011,1000),Fraction(1005,1000)]
        with localcontext(Context(prec=70)):
            initial=D('1000000'); value=initial; equity=[]
            for i,m in enumerate(fractions):
                value=value*D(m.numerator)/D(m.denominator)
                equity.append(dict(trade_date=f'2026-10-{i*3+1:02d}',equity=value))
            returns=[m-1 for m in fractions]; mean=sum(returns)/len(returns)
            variance=sum((r-mean)**2 for r in returns)/(len(returns)-1)
            expected=D(252).sqrt()*(D(mean.numerator)/D(mean.denominator))/(D(variance.numerator)/D(variance.denominator)).sqrt()
        result=_performance_metrics([],equity,initial)
        self.assertLess(abs(result['sharpe']-expected),D('1e-30'))
        self.assertEqual(result['sharpe_sample_count'],4)

    def test_long_short_adverse_lot_policy_execution(self):
        # Two original entries 20000 and 20100; low/high spans both stops.
        for side in (1,-1):
            stop_bar=bar(3,20050,20500,19600) if side>0 else bar(3,20050,20500,19600)
            data=dataset([bar(0,20000),bar(1,20000),bar(2,20100),stop_bar])
            result=run(data,[(0,side),(1,3*side)],st=spec(stop_ticks=300,target_ticks=1000))
            self.assertEqual(result.fills[-1].price,D('19700' if side>0 else '20400'))
            self.assertEqual(result.fills[-1].quantity,3)
            self.assertEqual(result.fills[-1].reason,'stop')
            self.assertEqual(result.metrics['open_position'],0)

    def test_long_short_adverse_target_lot_execution(self):
        for side in (1,-1):
            # Long targets 20500,20600; short targets 19500,19600.
            end=bar(3,20100,20700,20000) if side>0 else bar(3,20100,20200,19400)
            data=dataset([bar(0,20000),bar(1,20000),bar(2,20100),end])
            result=run(data,[(0,side),(1,3*side)],st=spec(stop_ticks=1000,target_ticks=500))
            self.assertEqual(result.fills[-1].price,D('20500' if side>0 else '19600'))
            self.assertEqual(result.fills[-1].quantity,3)
            self.assertEqual(result.fills[-1].reason,'target')


if __name__=='__main__': unittest.main()
