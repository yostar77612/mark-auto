"""Read-only IID fixed-capital bootstrap, with no filesystem dependencies.

Breach means strictly below threshold. Percentiles use linear interpolation at
(n - 1) * p (inclusive/type 7). Decimal context is isolated at precision 50,
ROUND_HALF_EVEN; every output Decimal has 12 fractional places. Cancellation
wins over deadline at each draw and before publication. Patch monotonic for an
injected clock; deadline is an absolute monotonic timestamp.
"""

from decimal import Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN
import math
import random
from time import monotonic

QUANTUM = Decimal('0.000000000001')
MAX_STEPS = 1_000_000


def empty_result(status, reason):
    return dict(status=status, reason=reason, breach_fraction=None, percentiles=None, actual_paths=None, breached_paths=None, inputs=None)


def _decimal(value, *, money=False):
    if isinstance(value, bool) or (money and not isinstance(value, (Decimal, str))):
        raise ValueError('invalid_decimal')
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('decimal_out_of_range')
    return number


def validate_inputs(*, start_equity, threshold, horizon_days, paths, seed):
    """Shared cheap validation; no allocations or control callbacks."""
    if type(paths) is not int or type(horizon_days) is not int or paths <= 0 or horizon_days <= 0:
        return 'positive_integer_required'
    if paths > MAX_STEPS or horizon_days > MAX_STEPS or paths * horizon_days > MAX_STEPS:
        return 'step_limit_exceeded'
    if type(seed) is not int:
        return 'integer_seed_required'
    try:
        start, limit = _decimal(start_equity, money=True), _decimal(threshold, money=True)
        if not 0 < limit < start:
            return 'threshold_must_be_below_start'
    except (DecimalException, ValueError, TypeError):
        return 'invalid_capital'
    return None


def _stopped(cancel, deadline):
    if cancel is not None and cancel():
        return empty_result('cancelled', 'cancelled')
    if deadline is not None and monotonic() >= deadline:
        return empty_result('timed_out', 'deadline_exceeded')
    return None


def simulate(daily_returns, *, start_equity, threshold, horizon_days, paths, seed, cancel, deadline):
    """Independent uniform draws with replacement; daily PnL = start * return.

    All incomplete outcomes discard every statistic, including partial counts.
    Validation precedes callbacks, draws and allocations proportional to paths.
    """
    inputs = dict(start_equity=start_equity, threshold=threshold, horizon_days=horizon_days, paths=paths, seed=seed)
    reason = validate_inputs(**inputs)
    if reason:
        return empty_result('rejected', reason)
    if cancel is not None and not callable(cancel):
        return empty_result('rejected', 'invalid_cancel')
    try:
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            return empty_result('rejected', 'invalid_deadline')
    except OverflowError:
        return empty_result('rejected', 'invalid_deadline')
    try:
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            start, limit = _decimal(start_equity, money=True), _decimal(threshold, money=True)
            sample = [_decimal(value) for value in daily_returns]
            if not sample or any(value <= -1 for value in sample):
                return empty_result('rejected', 'invalid_return_sample')
            changes = [start * value for value in sample]
            rng, finals, breached = random.Random(seed), [], 0
            for _ in range(paths):
                equity = start
                for _ in range(horizon_days):
                    stopped = _stopped(cancel, deadline)
                    if stopped:
                        return stopped
                    equity += rng.choice(changes)
                    if equity < limit:
                        breached += 1
                        break
                finals.append(equity)
            stopped = _stopped(cancel, deadline)
            if stopped:
                return stopped
            finals.sort()
            percentiles = {}
            for percent in (5, 25, 50, 75, 95):
                position = Decimal(paths - 1) * percent / 100
                lower = int(position)
                upper = min(lower + 1, paths - 1)
                percentiles[str(percent)] = (finals[lower] + (finals[upper] - finals[lower]) * (position - lower)).quantize(QUANTUM)
            return dict(
                status='completed',
                reason=None,
                breach_fraction=(Decimal(breached) / paths).quantize(QUANTUM),
                percentiles=percentiles,
                actual_paths=paths,
                breached_paths=breached,
                inputs={**inputs, 'start_equity': start.quantize(QUANTUM), 'threshold': limit.quantize(QUANTUM)},
            )
    except (DecimalException, ValueError, TypeError, OverflowError):
        return empty_result('rejected', 'invalid_return_sample')
