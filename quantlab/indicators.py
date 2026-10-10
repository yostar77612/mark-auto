"""Causal Decimal indicators, formula version 1.

Periods count observations, not clock minutes. None breaks history and restarts
warmup (including EMA seeds and RSI differences); no implicit zero filling.
Inputs must be chronologically ordered for one contract. Missing *time* intervals
must be represented by None by the caller. Partial bars are provisional input and
must be labelled by the caller; appending future observations cannot change a prefix.
OHLCV VWAP is a typical-price approximation, never a tick-exact execution VWAP.
Arithmetic uses isolated precision-28 ROUND_HALF_EVEN context with default traps;
caller precision, rounding, flags and traps are untouched. Inputs are bounded to
100,000 observations, periods 1..10,000, prices ±1e9 / 24 digits / exponent ±12.
KD/Bollinger cap window work at 5 million observation-period operations.
"""
from collections import deque
from decimal import (Decimal, InvalidOperation, Context, localcontext, ROUND_HALF_EVEN,
                     DivisionByZero, Overflow)
from functools import wraps
from itertools import islice

FORMULA_VERSION = 'market-indicators-v1'
VWAP_LABEL = 'OHLCV typical-price volume approximation; session reset'
MAX_PERIOD = 10_000
MAX_OBSERVATIONS = 100_000
MAX_WINDOW_WORK = 5_000_000


def _fixed_context(function):
    @wraps(function)
    def calculate(*args, **kwargs):
        # Explicit constructor avoids caller context and mutable DefaultContext.
        context = Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                          capitals=1, clamp=0, flags=[],
                          traps=[InvalidOperation, DivisionByZero, Overflow])
        with localcontext(context):
            bounded = []
            for values in args:
                values = tuple(islice(iter(values), MAX_OBSERVATIONS + 1))
                if len(values) > MAX_OBSERVATIONS:
                    raise ValueError('indicator observation limit exceeded')
                bounded.append(values)
            # Payloads may also be supplied by keyword; bind them without changing API.
            for name in ('values', 'highs', 'lows', 'closes', 'bars'):
                if name in kwargs:
                    values = tuple(islice(iter(kwargs[name]), MAX_OBSERVATIONS + 1))
                    if len(values) > MAX_OBSERVATIONS:
                        raise ValueError('indicator observation limit exceeded')
                    kwargs[name] = values
            return function(*bounded, **kwargs)
    return calculate


def _period(value):
    if type(value) is not int or not 1 <= value <= MAX_PERIOD:
        raise ValueError(f'period must be an integer in 1..{MAX_PERIOD}')
    return value


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('boolean is not a price')
    if isinstance(value, str) and len(value) > 128:
        raise ValueError('numeric text is too long')
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid numeric observation') from exc
    if (not result.is_finite() or len(result.as_tuple().digits) > 24
            or abs(result.as_tuple().exponent) > 12 or abs(result) > Decimal('1000000000')):
        raise ValueError('observation must be finite, within ±1e9, at most 24 digits and exponent ±12')
    return result


@_fixed_context
def sma(values, *, period=20):
    period = _period(period)
    window, result = deque(), []
    total = Decimal(0)
    for raw in values:
        value = _number(raw)
        if value is None:
            window.clear()
            total = Decimal(0)
            result.append(None)
            continue
        window.append(value)
        total += value
        if len(window) > period:
            total -= window.popleft()
        result.append(total / period if len(window) == period else None)
    return tuple(result)


@_fixed_context
def ema(values, *, period=20):
    return _ema_values(tuple(_number(value) for value in values), period=_period(period))


def _ema_values(values, *, period):
    # Internal derived Decimal values may legitimately have extra decimal places.
    seed, previous, result = [], None, []
    alpha = Decimal(2) / (period + 1)
    for raw in values:
        value = raw
        if value is None:
            seed, previous = [], None
        elif previous is None:
            seed.append(value)
            if len(seed) == period:
                previous = sum(seed, Decimal(0)) / period
                seed = []
        else:
            previous = alpha * value + (1 - alpha) * previous
        result.append(previous)
    return tuple(result)


@_fixed_context
def rsi(values, *, period=14):
    period = _period(period)
    previous, average_gain, average_loss = None, None, None
    gains, losses, result = [], [], []
    for raw in values:
        value = _number(raw)
        if value is None:
            previous, average_gain, average_loss = None, None, None
            gains, losses = [], []
            result.append(None)
            continue
        if previous is None:
            previous = value
            result.append(None)
            continue
        delta, previous = value - previous, value
        gain, loss = max(delta, Decimal(0)), max(-delta, Decimal(0))
        if average_gain is None:
            gains.append(gain)
            losses.append(loss)
            if len(gains) < period:
                result.append(None)
                continue
            average_gain = sum(gains, Decimal(0)) / period
            average_loss = sum(losses, Decimal(0)) / period
            gains, losses = [], []
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_gain == average_loss == 0:
            result.append(Decimal(50))
        elif average_loss == 0:
            result.append(Decimal(100))
        else:
            result.append(100 - Decimal(100) / (1 + average_gain / average_loss))
    return tuple(result)


@_fixed_context
def macd(values, *, fast=12, slow=26, signal=9):
    _period(fast), _period(slow), _period(signal)
    if fast >= slow:
        raise ValueError('MACD fast period must be less than slow period')
    values = tuple(values)
    fast_values, slow_values = ema(values, period=fast), ema(values, period=slow)
    line = tuple(None if a is None or b is None else a - b for a, b in zip(fast_values, slow_values))
    signal_values = _ema_values(line, period=signal)
    histogram = tuple(None if a is None or b is None else a - b for a, b in zip(line, signal_values))
    return {'macd': line, 'signal': signal_values, 'histogram': histogram}


@_fixed_context
def kd(highs, lows, closes, *, period=9, k_period=3, d_period=3):
    _period(period), _period(k_period), _period(d_period)
    highs, lows, closes = tuple(highs), tuple(lows), tuple(closes)
    if len(highs) != len(lows) or len(lows) != len(closes):
        raise ValueError('OHLC sequences must have matching lengths')
    if len(highs) * period > MAX_WINDOW_WORK:
        raise ValueError('KD rolling-window work limit exceeded')
    window, kvals, dvals = deque(), [], []
    k, d = Decimal(50), Decimal(50)
    for high, low, close in zip(highs, lows, closes):
        high, low, close = map(_number, (high, low, close))
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


@_fixed_context
def bollinger(values, *, period=20, deviations=2):
    _period(period)
    if len(values) * period > MAX_WINDOW_WORK:
        raise ValueError('Bollinger rolling-window work limit exceeded')
    deviations = _number(deviations)
    if deviations is None or deviations < 0:
        raise ValueError('deviations must be nonnegative')
    window, middle, upper, lower = deque(), [], [], []
    for raw in values:
        value = _number(raw)
        if value is None:
            window.clear()
        else:
            window.append(value)
            if len(window) > period:
                window.popleft()
        if len(window) < period:
            middle.append(None)
            upper.append(None)
            lower.append(None)
            continue
        mean = sum(window, Decimal(0)) / period
        sigma = (sum(((x - mean) ** 2 for x in window), Decimal(0)) / period).sqrt()
        middle.append(mean)
        upper.append(mean + deviations * sigma)
        lower.append(mean - deviations * sigma)
    return {'middle': tuple(middle), 'upper': tuple(upper), 'lower': tuple(lower)}


@_fixed_context
def session_vwap(bars):
    """Approximate VWAP; unknown volume/null OHLC resets state, zero volume does not.

    Resets on contract, trade_date, session or explicit session_open changes.
    Combined day/week bars have no session VWAP and return None.
    """
    previous_key, weighted, volume, result = None, Decimal(0), 0, []
    for bar in bars:
        if bar is None:
            previous_key, weighted, volume = None, Decimal(0), 0
            result.append(None)
            continue
        key = (bar.contract_id, bar.trade_date, bar.session, getattr(bar, 'session_open', None))
        if key != previous_key:
            previous_key, weighted, volume = key, Decimal(0), 0
        high, low, close = map(_number, (bar.high, bar.low, bar.close))
        amount = bar.volume
        if amount is not None and (type(amount) is not int or not 0 <= amount <= 10**15):
            raise ValueError('volume must be a nonnegative integer or None')
        if amount is None or None in (high, low, close) or bar.session == 'combined':
            weighted, volume = Decimal(0), 0
            result.append(None)
            continue
        if not low <= close <= high:
            raise ValueError('close outside high/low range')
        weighted += (high + low + close) / 3 * amount
        volume += amount
        result.append(weighted / volume if volume else None)
    return tuple(result)
