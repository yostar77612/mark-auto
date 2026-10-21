"""Read-only daily-return inference, independently implemented from standard formulas.

No reference-project code or flow was adapted. Outputs use 12 decimal places,
ROUND_HALF_EVEN; floats are internal only. Percentiles use linear interpolation.
Bootstrap p is the exceedance count / actual draws, without add-one correction.
The 1000-draw floor takes precedence over the work cap for n > 50,000.
"""

from collections import Counter
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import math
import random
import statistics

DEFAULT_SEED = 20261021
PRECISION = Decimal('0.000000000001')
BOOTSTRAP_WORK_CAP = 50_000_000
REQUIRED_OBSERVATIONS_CAP = 1_000_000_000
EXPLANATION = '假設沒有優勢時，出現至少這麼好結果的機率'
STATISTICS = ('n', 'mean', 'sd', 't', 'p_value_t', 'p_value_bootstrap', 'ci_lower', 'ci_upper', 'n_bootstrap_actual')
MISSING = '每日報酬有缺值，不補值'
NONFINITE = '每日報酬有缺值或非有限值，不補值'
OUT_OF_RANGE = '每日報酬超出計算範圍，不補值'
TOO_FEW = '觀測數少於 2'
ZERO_VARIANCE = '變異數為 0'
TEST_RANGE = '檢定超出計算範圍'
BOOTSTRAP_INVALID = '重抽設定無效'
NONPOSITIVE = '平均日報酬不大於 0'
REQUIRED_CAP = '所需樣本數超過上限 1000000000'


def _decimal(value):
    with localcontext(Context(prec=400, rounding=ROUND_HALF_EVEN)):
        return Decimal(str(value)).quantize(PRECISION, rounding=ROUND_HALF_EVEN)


def _empty(reason):
    return {**{key: None for key in STATISTICS}, **{key + '_reason': reason for key in STATISTICS}, 'explanation': EXPLANATION, 'bootstrap_note': None}


def _sample(returns):
    try:
        values = [Decimal(str(value)) for value in returns]
        if any(not value.is_finite() for value in values):
            return None, '每日報酬有缺值或非有限值，不補值'
        floats = [float(value) for value in values]
        if any(not math.isfinite(value) for value in floats):
            return None, '每日報酬超出計算範圍，不補值'
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None, '每日報酬有缺值，不補值'
    if len(floats) < 2:
        return None, '觀測數少於 2'
    return floats, None


def _beta_fraction(a, b, x):
    """Modified Lentz continued fraction for the regularized incomplete beta."""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 401):
        even = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        odd = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        for term in (even, odd):
            d = 1 + term * d
            d = d if abs(d) > tiny else tiny
            c = 1 + term / c
            c = c if abs(c) > tiny else tiny
            d = 1 / d
            delta = d * c
            result *= delta
        if abs(delta - 1) < 3e-14:
            return result
    raise ArithmeticError('beta convergence')


def _regularized_beta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    factor = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return factor * _beta_fraction(a, b, x) / a
    return 1 - factor * _beta_fraction(b, a, 1 - x) / b


def _t_tail(t, df):
    if t == 0:
        return 0.5
    tail = 0.5 * _regularized_beta(df / 2, 0.5, df / (df + t * t))
    return min(1.0, max(0.0, tail if t > 0 else 1 - tail))


def _binomial(rng, n, probability):
    """Exact beta order-statistic splitting; avoids n Bernoulli draws."""
    count = 0
    while n > 16 and 0 < probability < 1:
        a = 1 + n // 2
        b = n - a + 1
        pivot = rng.betavariate(a, b)
        if pivot >= probability:
            n, probability = a - 1, probability / pivot
        else:
            count += a
            n, probability = b - 1, (probability - pivot) / (1 - pivot)
    if probability >= 1:
        return count + n
    return count + sum(rng.random() < probability for _ in range(n))


def _resample_means(values, mean, actual, rng):
    centered = [value - mean for value in values]
    n = len(values)
    # Repeated observations admit the identical empirical distribution via counts.
    groups = tuple(Counter(centered).items()) if n > 1000 else ()
    if groups and len(groups) <= 64:
        for _ in range(actual):
            remaining, population, total = n, n, 0.0
            for value, frequency in groups[:-1]:
                count = _binomial(rng, remaining, frequency / population)
                total += count * value
                remaining -= count
                population -= frequency
            yield (total + remaining * groups[-1][0]) / n
    else:
        for _ in range(actual):
            yield math.fsum(rng.choices(centered, k=n)) / n


def _percentile(ordered, probability):
    position = (len(ordered) - 1) * probability
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def mean_positive_test(returns, *, n_bootstrap=5000, alpha=Decimal('0.05'), seed=DEFAULT_SEED):
    values, reason = _sample(returns)
    if reason:
        return _empty(reason)
    result = _empty(None)
    mean, sd = statistics.mean(values), statistics.stdev(values)
    if not math.isfinite(mean) or not math.isfinite(sd):
        return _empty('每日報酬超出計算範圍，不補值')
    result.update(n=len(values), mean=_decimal(mean), sd=_decimal(sd))
    if sd == 0:
        for key in STATISTICS[3:]:
            result[key + '_reason'] = '變異數為 0'
        return result
    t = mean / sd * math.sqrt(len(values))
    try:
        result.update(t=_decimal(t), p_value_t=_decimal(_t_tail(t, len(values) - 1)))
    except (ArithmeticError, ValueError):
        result['t_reason'] = result['p_value_t_reason'] = '檢定超出計算範圍'
    if type(n_bootstrap) is not int or n_bootstrap < 1 or not Decimal('0') < Decimal(str(alpha)) < Decimal('1'):
        for key in ('p_value_bootstrap', 'ci_lower', 'ci_upper', 'n_bootstrap_actual'):
            result[key + '_reason'] = '重抽設定無效'
        return result
    actual = min(n_bootstrap, max(1000, BOOTSTRAP_WORK_CAP // len(values)))
    if actual != n_bootstrap or len(values) * actual > BOOTSTRAP_WORK_CAP:
        result['bootstrap_note'] = 'work_cap_with_1000_draw_floor'
    samples = list(_resample_means(values, mean, actual, random.Random(seed)))
    p = sum(value >= mean for value in samples) / actual
    samples.sort()
    tail = float(alpha) / 2
    result.update(
        p_value_bootstrap=_decimal(p),
        ci_lower=_decimal(mean + _percentile(samples, tail)),
        ci_upper=_decimal(mean + _percentile(samples, 1 - tail)),
        n_bootstrap_actual=actual,
    )
    return result


def required_sample_size(mean, sd):
    """Fixed one-sided alpha .05/power .8 planning rule, capped at 1e9 days."""
    mean, sd = Decimal(str(mean)), Decimal(str(sd))
    reason = None
    if not mean.is_finite() or not sd.is_finite():
        reason = '每日報酬有缺值或非有限值，不補值'
    elif sd <= 0:
        reason = '變異數為 0'
    elif mean <= 0:
        reason = '平均日報酬不大於 0'
    else:
        with localcontext(Context(prec=40)):
            ratio = (Decimal('1.6449') + Decimal('0.8416')) * sd / mean
            if ratio > Decimal(REQUIRED_OBSERVATIONS_CAP).sqrt():
                reason = '所需樣本數超過上限 1000000000'
            else:
                count = max(30, math.ceil(ratio * ratio))
                return {'required_observations': count, 'required_observations_reason': None}
    return {'required_observations': None, 'required_observations_reason': reason}


def required_observations(returns, *, alpha=Decimal('0.05'), power=Decimal('0.8')):
    values, reason = _sample(returns)
    if Decimal(str(alpha)) != Decimal('0.05') or Decimal(str(power)) != Decimal('0.8'):
        reason = '僅支援 alpha=0.05、power=0.8'
    if reason:
        return {'required_observations': None, 'required_observations_reason': reason}
    return required_sample_size(statistics.mean(values), statistics.stdev(values))


def merge_oos_daily_returns(state):
    """Only evaluated folds in index order; atomic rejection, no holdout reads."""
    result = {'returns': None, 'reason': None, 'evaluated_folds': 0, 'skipped_folds': 0}
    if state.get('final_holdout_status') != 'excluded_not_evaluated':
        return {**result, 'reason': 'holdout_status_unconfirmed'}
    values, previous = [], None
    folds = state.get('folds', [])
    if len(folds) > 20:
        return {**result, 'reason': 'fold_limit_exceeded'}
    try:
        ordered = sorted(folds, key=lambda fold: fold['index'])
        if len({fold['index'] for fold in ordered}) != len(ordered):
            return {**result, 'reason': 'fold_index_invalid'}
        for fold in ordered:
            oos = fold.get('oos') or {}
            if fold.get('status') != 'evaluated' or oos.get('status') != 'evaluated':
                result['skipped_folds'] += 1
                continue
            result['evaluated_folds'] += 1
            rows = oos.get('result', {}).get('metrics', {}).get('daily_returns')
            if not isinstance(rows, list) or not rows:
                return {**result, 'reason': 'daily_returns_missing'}
            for row in rows:
                current = date.fromisoformat(row['trade_date'])
                if previous is not None and current <= previous:
                    return {**result, 'reason': 'dates_not_strictly_increasing'}
                previous = current
                values.append(row.get('return'))
    except (KeyError, TypeError, ValueError, AttributeError):
        return {**result, 'reason': 'daily_returns_invalid'}
    if not values:
        return {**result, 'reason': 'no_evaluated_folds'}
    return {**result, 'returns': values}
