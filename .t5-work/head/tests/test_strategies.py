import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from quantlab.core import Bar,StrategySpec,ValidationError
from quantlab.strategies import builtin_strategies,generate_signals,validate_strategy

C='TAIFEX:TMF:202610'
def bars(prices):
    start=datetime(2026,10,1,1,tzinfo=timezone.utc)
    return tuple(Bar(start+timedelta(minutes=i),start+timedelta(minutes=i+1),'2026-10-01','day',C,Decimal(p),Decimal(p),Decimal(p),Decimal(p),10) for i,p in enumerate(prices))

class StrategyTests(unittest.TestCase):
    def test_five_distinct_triggers(self):
        fixtures=[
            ('trend',{'fast':1,'slow':2},[100,100,110],1),
            ('mean_reversion',{'lookback':2,'entry_bps':'50'},[100,100,90],1),
            ('channel_breakout',{'lookback':2},[100,101,102],1),
            ('momentum',{'lookback':2,'threshold_bps':'50','max_holding_bars':1},[100,100,101,102],0),
            ('volatility_compression',{'lookback':2,'max_range_bps':'100'},[100,100,102],1),
        ]
        self.assertEqual(len(builtin_strategies()),5)
        for family,p,prices,target in fixtures:
            with self.subTest(family=family):
                signals=generate_signals(bars(prices),StrategySpec('x',family,p,{}))
                self.assertEqual(signals[-1].target_position,target)
                self.assertEqual(signals[0].timestamp,bars(prices)[2].end)
        # Same breakout after wide prior range is specifically NOT compression.
        self.assertFalse(generate_signals(bars([90,110,120]),StrategySpec('x','volatility_compression',{'lookback':2,'max_range_bps':'100'},{})))
    def test_all_prefixes_identical(self):
        data=bars([100+i%7*(1 if i%9<5 else -1) for i in range(60)])
        for spec in builtin_strategies():
            full=generate_signals(data,spec)
            for n in range(1,len(data)):
                self.assertEqual(generate_signals(data[:n],spec),tuple(s for s in full if s.timestamp<=data[n-1].end))
    def test_validation(self):
        for p in ({'fast':True,'slow':2},{'fast':2,'slow':2},{'fast':1,'slow':2,'bogus':3}):
            with self.assertRaises(ValidationError): validate_strategy(StrategySpec('x','trend',p,{}))
        with self.assertRaises(ValidationError): generate_signals(tuple(reversed(bars([1,2]))),builtin_strategies()[0])
    def test_warmup_not_zero_filled(self):
        for spec in builtin_strategies(): self.assertEqual(generate_signals(bars([100]),spec),())
    def test_ast_causality_and_warmup(self):
        rules={'long':{'op':'gt','left':{'op':'field','name':'close'},'right':{'op':'sma','field':'close','period':3,'lag':1}},'short':{'op':'lt','left':{'op':'field','name':'close'},'right':{'op':'const','value':'0'}}}
        spec=StrategySpec('ast','trend',{'fast':1,'slow':2},rules)
        data=bars([100,100,101,102,99])
        self.assertEqual(generate_signals(data[:3],spec),())
        self.assertEqual(generate_signals(data,spec)[0].timestamp,data[3].end)
        for n in range(1,6): self.assertEqual(generate_signals(data[:n],spec),tuple(s for s in generate_signals(data,spec) if s.timestamp<=data[n-1].end))
    def test_reject_ast_attack_and_negative_lag(self):
        for node in ({'op':'eval','value':'__import__'},{'op':'field','name':'close','lag':-1}):
            with self.assertRaises(ValidationError): validate_strategy(StrategySpec('x','trend',{'fast':1,'slow':2},{'long':node,'short':node}))

if __name__=='__main__': unittest.main()
