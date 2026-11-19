"""Frozen independent formula cases, declared before implementation (2026-10-10).
SMA3 [1,2,3,4]=[None,None,2,3]; EMA3 next=2*.5+4*.5=3.
RSI3 [1,2,3,2] seed gains=2/3 losses=1/3 => 66 2/3.
BB3 [1,2,3]: mean2, population variance2/3.
KD3 range[0,4], close3: RSV75,K=175/3,D=475/9.
MACD2/3/2 [1,2,3,4]: difference .5; signal .5; hist0.
VWAP typical1 volume2, typical4 volume1: (2+4)/3=2.
"""

from collections import deque
from decimal import Decimal
from decimal import Decimal as D
import random
from types import SimpleNamespace
import unittest
from contextlib import contextmanager


@contextmanager
def raises(error):
    try:
        yield
    except error:
        return
    raise AssertionError(f'Expected {error}')


from quantlab.indicators import sma, ema, rsi, macd, kd, bollinger, session_vwap
from quantlab import indicators


def test_frozen_averages_and_warmup():
    assert sma([1, 2, 3, 4], period=3) == (None, None, D(2), D(3))
    assert ema([1, 2, 3, 4], period=3) == (None, None, D(2), D(3))
    for n in (5, 10, 20, 60):
        assert sma([7] * n, period=n) == (None,) * (n - 1) + (D(7),)


def test_frozen_rsi_seeds():
    assert rsi([1, 2, 3, 2], period=3)[-1] == D(100) - D(100) / (1 + D(2))
    assert rsi([2] * 16)[14:] == (D(50), D(50))
    assert rsi(range(16))[14:] == (D(100), D(100))
    assert rsi(range(16, 0, -1))[14:] == (D(0), D(0))


def test_frozen_macd_kd_bands():
    m = macd([1, 2, 3, 4], fast=2, slow=3, signal=2)
    assert m['macd'] == (None, None, D('.5'), D('.5'))
    assert m['signal'] == (None, None, None, D('.5'))
    assert m['histogram'] == (None, None, None, D(0))
    out = kd([4] * 3, [0] * 3, [3] * 3, period=3)
    assert abs(out['k'][-1] - D(175) / 3) < D('1e-25')
    assert abs(out['d'][-1] - D(475) / 9) < D('1e-25')
    flat = kd([2] * 10, [2] * 10, [2] * 10)
    assert flat['k'][-1] == flat['d'][-1] == D(50)
    b = bollinger([1, 2, 3], period=3)
    assert b['middle'][-1] == 2
    assert b['upper'][-1] == D(2) + 2 * (D(2) / 3).sqrt()


def test_gaps_reset_and_prefix_causality():
    values = [D(i % 11) for i in range(90)]
    values[35] = None
    for fn in (sma, ema, rsi, macd, bollinger):
        full = fn(values)
        for n in (1, 15, 36, 55, 89):
            short = fn(values[:n])
            if isinstance(full, dict):
                assert short == {k: v[:n] for k, v in full.items()}
            else:
                assert short == full[:n]
    assert ema([1, 2, None, 3, 4, 5], period=3) == (None, None, None, None, None, D(4))


def bar(price, volume, session='day', date='2026-10-09', symbol='x'):
    return SimpleNamespace(high=D(price), low=D(price), close=D(price), volume=volume, session=session, trade_date=date, contract_id=symbol)


def test_session_vwap_zero_missing_and_contract_reset():
    bs = [bar(1, 0), bar(1, 2), bar(4, 1), bar(9, 0, 'night'), bar(5, 2, 'night'), bar(7, None, 'night'), bar(8, 1, 'night'), bar(2, 1, symbol='y')]
    assert session_vwap(bs) == (None, D(1), D(2), None, D(5), None, D(8), D(2))


def test_bad_period():
    for bad in [True, 0, -1, 2.5]:
        with raises(ValueError):
            sma([1, 2], period=bad)


def test_nonfinite_input():
    for bad in [True, float('nan'), float('inf'), 'NaN']:
        with raises(ValueError):
            ema([bad])


def test_wilder_recursive_step_and_default_macd_warmup():
    # Wilder3: gains 2/3 then10/9, losses1/3 then2/9 => RS5 => RSI250/3.
    assert abs(rsi([1, 2, 3, 2, 4], period=3)[-1] - D(250) / 3) < D('1e-25')
    result = macd([10] * 40)
    assert result['macd'][:25] == (None,) * 25
    assert result['macd'][25:] == (D(0),) * 15
    assert result['signal'][:33] == (None,) * 33
    assert result['histogram'][33:] == (D(0),) * 7


def test_kd_and_vwap_prefix_gap():
    values = [D(i % 7) for i in range(30)]
    highs = [v + 1 for v in values]
    lows = [v - 1 for v in values]
    highs[12] = None
    full = kd(highs, lows, values)
    for n in range(1, 30):
        assert kd(highs[:n], lows[:n], values[:n]) == {k: v[:n] for k, v in full.items()}
    assert full['k'][12:21] == (None,) * 9
    bs = [bar(1, 2), bar(4, 1), None, bar(8, 1)]
    assert session_vwap(bs) == (D(1), D(2), None, D(8))
    for n in range(1, 4):
        assert session_vwap(bs[:n]) == session_vwap(bs)[:n]


def test_zero_bands_and_gap_seed():
    assert bollinger([0] * 20)['upper'][-1] == D(0)
    assert bollinger([1, 2, None, 3, 4, 5], period=3)['middle'] == (None, None, None, None, None, D(4))
    assert rsi([1, 2, 3, None, 4, 5, 6, 7], period=3) == (None, None, None, None, None, None, None, D(100))


def test_fixed_decimal_context_all_public_functions_and_no_leak():
    from decimal import localcontext, getcontext, ROUND_UP, Inexact, Rounded

    values = [D(i % 13) + D('0.1') for i in range(80)]
    highs = [v + D(1) for v in values]
    lows = [v - D(1) for v in values]
    bs = [bar(1, 2), bar(4, 1), bar(7, 4)]
    calls = [
        lambda: sma(values, period=3),
        lambda: ema(values, period=3),
        lambda: rsi(values, period=3),
        lambda: macd(values),
        lambda: kd(highs, lows, values),
        lambda: bollinger(values),
        lambda: session_vwap(bs),
    ]
    expected = [repr(call()) for call in calls]

    def state(ctx):
        return (ctx.prec, ctx.rounding, ctx.Emin, ctx.Emax, ctx.capitals, ctx.clamp, dict(ctx.flags), dict(ctx.traps))

    original = state(getcontext())
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.rounding = ROUND_UP
        ctx.Emin = -9
        ctx.Emax = 9
        ctx.traps[Inexact] = True
        ctx.flags[Rounded] = True
        before = state(ctx)
        assert [repr(call()) for call in calls] == expected
        assert state(ctx) == before
        with raises(ValueError):
            ema([D('1e10000')])
        assert state(ctx) == before
    assert state(getcontext()) == original


def test_bounded_numeric_period_and_work_inputs():
    from quantlab.indicators import MAX_OBSERVATIONS, MAX_PERIOD

    for bad in (D('1e10000'), D('1e-10000'), D('1000000001'), D('-1000000001'), '1' * 129, D('1.12345678901234567890123456789')):
        for fn in (sma, ema, rsi, macd, bollinger):
            with raises(ValueError):
                fn([bad])
    for fn in (sma, ema, rsi, bollinger):
        with raises(ValueError):
            fn([1], period=MAX_PERIOD + 1)
        with raises(ValueError):
            fn(iter([1] * (MAX_OBSERVATIONS + 1)))
    with raises(ValueError):
        kd([1], [0], [1], period=MAX_PERIOD + 1)
    with raises(ValueError):
        macd([1], signal=MAX_PERIOD + 1)
    with raises(ValueError):
        bollinger([1] * 1001, period=5000)
    with raises(ValueError):
        kd([1] * 1001, [0] * 1001, [1] * 1001, period=5000)
    with raises(ValueError):
        session_vwap([bar(1, 10**15 + 1)])
    assert ema(values=[1, 2, 3], period=3) == (None, None, D(2))


class IndicatorTests(unittest.TestCase):
    pass


for _name, _test in list(globals().items()):
    if _name.startswith("test_"):
        setattr(IndicatorTests, _name, lambda self, fn=_test: fn())
del _name, _test


def _reference_kd(highs, lows, closes, *, period=9, k_period=3, d_period=3):
    """Frozen copy of the pre-OPT-1 KD loop (per-step max/min over the window), the oracle for P3."""
    indicators._period(period), indicators._period(k_period), indicators._period(d_period)
    highs, lows, closes = tuple(highs), tuple(lows), tuple(closes)
    if len(highs) != len(lows) or len(lows) != len(closes):
        raise ValueError('OHLC sequences must have matching lengths')
    if len(highs) * period > indicators.MAX_WINDOW_WORK:
        raise indicators.IndicatorResourceLimitError('KD rolling-window work limit exceeded')
    window, kvals, dvals = deque(), [], []
    k, d = Decimal(50), Decimal(50)
    for high, low, close in zip(highs, lows, closes):
        high, low, close = map(indicators._number, (high, low, close))
        if high is None or low is None or close is None:
            window.clear()
            k, d = Decimal(50), Decimal(50)
            kvals.append(None)
            dvals.append(None)
            continue
        if not low <= close <= high:
            raise ValueError('close outside high/low range')
        window.append((high, low))
        if len(window) > period:
            window.popleft()
        if len(window) < period:
            kvals.append(None)
            dvals.append(None)
            continue
        highest, lowest = max(x[0] for x in window), min(x[1] for x in window)
        rsv = Decimal(50) if highest == lowest else 100 * (close - lowest) / (highest - lowest)
        k = ((k_period - 1) * k + rsv) / k_period
        d = ((d_period - 1) * d + k) / d_period
        kvals.append(k)
        dvals.append(d)
    return {'k': tuple(kvals), 'd': tuple(dvals)}


_REFERENCE_KD = indicators._fixed_context(_reference_kd)


def _exact(result):
    # str() keeps the Decimal exponent, so '50' and '50.0' are different results.
    return {key: tuple(None if value is None else str(value) for value in values) for key, values in result.items()}


class KdMonotonicWindowEquivalenceTests(unittest.TestCase):
    """OPT-1 P3: the O(N) monotonic-deque KD equals the old per-step max/min KD digit for digit."""

    def assertSameKd(self, highs, lows, closes, **params):
        self.assertEqual(_exact(indicators.kd(highs, lows, closes, **params)), _exact(_REFERENCE_KD(highs, lows, closes, **params)))

    def test_random_series_with_gaps_ties_and_mixed_exponents(self):
        generator = random.Random(20261120)
        steps = ('0.5', '0.50', '1', '1.0', '0', '0.25', '2.5')
        for case in range(300):
            length = generator.randint(0, 80)
            highs, lows, closes = [], [], []
            level = Decimal(generator.choice(('10', '10.0', '100.00', '7.5')))
            for _ in range(length):
                level = max(Decimal('0.5'), level + Decimal(generator.choice(steps)) * generator.choice((-1, 1)))
                high = level + Decimal(generator.choice(steps))
                low = max(Decimal('0.1'), level - Decimal(generator.choice(('0', '0.0', '0.5', '1'))))
                row = [high, low, generator.choice((high, low, level, (high + low) / 2))]
                if generator.random() < 0.06:
                    row[generator.randrange(3)] = None  # any single missing field resets the window
                highs.append(row[0])
                lows.append(row[1])
                closes.append(row[2])
            params = {'period': generator.randint(1, 12), 'k_period': generator.randint(1, 5), 'd_period': generator.randint(1, 5)}
            with self.subTest(case=case, length=length, **params):
                self.assertSameKd(highs, lows, closes, **params)

    def test_flat_window_and_equal_extremes_with_different_exponents(self):
        highs = ['10', '10.0', '10.00', '10', '9.5', '10.0', '10']
        lows = ['10', '10.0', '9.0', '9', '9.00', '9.0', '9.000']
        closes = ['10', '10.0', '9.50', '9.5', '9.25', '10.0', '9.000']
        for period in range(1, 9):
            with self.subTest(period=period):
                self.assertSameKd(highs, lows, closes, period=period)
        self.assertEqual(indicators.kd(['5'] * 4, ['5'] * 4, ['5'] * 4, period=2)['k'][1:], (Decimal('50'),) * 3)

    def test_warmup_boundaries_and_none_reset(self):
        rows = [('3', '1', '2'), ('4', '2', '3'), ('5', '3', '4'), (None, '1', '1'), ('6', '4', '5'), ('7', '5', '6'), ('8', '6', '7'), ('9', '7', '8')]
        highs, lows, closes = zip(*rows)
        for period in (1, 2, 3, 4, 8, 9):
            with self.subTest(period=period):
                self.assertSameKd(highs, lows, closes, period=period, k_period=2, d_period=2)
        result = indicators.kd(highs, lows, closes, period=3)
        self.assertEqual(result['k'][:3].count(None), 2)
        self.assertIsNone(result['k'][3])
        self.assertEqual(result['k'][4:6], (None, None))

    def test_validation_and_resource_bound_are_unchanged(self):
        for highs, lows, closes, error in (
            (['2'], ['1'], ['3'], ValueError),  # close above high
            (['2', '2'], ['1'], ['1', '1'], ValueError),  # length mismatch
            (['2'], ['1'], ['x'], ValueError),  # invalid number
        ):
            with self.subTest(highs=highs, closes=closes):
                with self.assertRaises(error) as new:
                    indicators.kd(highs, lows, closes)
                with self.assertRaises(error) as old:
                    _REFERENCE_KD(highs, lows, closes)
                self.assertEqual(str(new.exception), str(old.exception))
        size = indicators.MAX_WINDOW_WORK // 100 + 1
        with self.assertRaises(indicators.IndicatorResourceLimitError):
            indicators.kd(['2'] * size, ['1'] * size, ['1'] * size, period=100)
