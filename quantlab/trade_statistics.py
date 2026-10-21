"""Pure closed-FIFO-lot descriptive statistics, independently implemented.

Input is a list or tuple of mappings (including live BacktestResult.ledger).
Invalid ledger/P&L raises ValidationError, mapped to validation_failed by the UI.
All non-count numbers use eight decimal places, ROUND_HALF_UP, isolated context.
Reasons are semantic catalog keys; a defined value has a None reason.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from types import MappingProxyType

from .core import ValidationError


QUANTUM = Decimal('0.00000001')
THRESHOLDS = MappingProxyType(
    {
        'negative_expectancy': (Decimal('0'), 'high'),
        'single_trade_dominance': (Decimal('0.50'), 'high'),
        'small_wins_big_losses': (Decimal('0.70'), Decimal('0.40'), 'medium'),
        'thin_edge_margin': (Decimal('0'), Decimal('0.25'), 'medium'),
        'severe_drawdown': (Decimal('0.50'), 'high'),
        'long_losing_streak': (8, 'medium'),
        'marginal_profit_factor': (20, Decimal('0'), Decimal('1.1'), 'medium'),
    }
)
FIELDS = (
    'n',
    'wins',
    'losses',
    'ties',
    'expectancy',
    'avg_win',
    'avg_loss',
    'payoff_ratio',
    'win_rate',
    'max_losing_streak',
    'largest_win',
    'largest_win_share',
    'profit_factor',
)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValidationError('Invalid ledger net_pnl')
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValidationError('Invalid ledger net_pnl') from None
    if not number.is_finite():
        raise ValidationError('Nonfinite ledger net_pnl')
    return number


def _exit_key(row):
    value = row.get('exit_timestamp')
    if value is None:
        return (0, '')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(stamp, datetime):
            raise ValueError
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (1, stamp.astimezone(timezone.utc).isoformat())
    except (ValueError, TypeError, OverflowError):
        raise ValidationError('Invalid ledger exit_timestamp') from None


def _put(stats, name, value, reason=None):
    stats[name] = value if value is None or type(value) is int else value.quantize(QUANTUM, rounding=ROUND_HALF_UP)
    stats[name + '_reason'] = reason if value is None else None


def _streak(pnls):
    longest = current = 0
    for pnl in pnls:
        current = current + 1 if pnl < 0 else 0
        longest = max(longest, current)
    return longest


def describe(ledger):
    """Describe list/tuple ledger without mutation; ties reset losing streaks."""
    if not isinstance(ledger, (list, tuple)) or any(not isinstance(row, Mapping) for row in ledger):
        raise ValidationError('Ledger must be a list or tuple of mappings')
    pnls = [_number(row.get('net_pnl')) for row in sorted(ledger, key=_exit_key)]
    stats = {}
    if not pnls:
        for name in FIELDS:
            _put(stats, name, None, 'trade_structure.reason.no_closed_lots')
        return stats
    with localcontext(Context(prec=64, rounding=ROUND_HALF_UP)) as context:
        context.prec = max(64, max(len(p.as_tuple().digits) + abs(p.as_tuple().exponent) + abs(p.adjusted()) for p in pnls) * 2 + 32)
        return _describe_values(pnls)


def _describe_values(pnls):
    stats = {}
    wins, losses = [p for p in pnls if p > 0], [-p for p in pnls if p < 0]
    gain, loss = sum(wins, Decimal(0)), sum(losses, Decimal(0))
    for name, value in (('n', len(pnls)), ('wins', len(wins)), ('losses', len(losses)), ('ties', pnls.count(0))):
        _put(stats, name, value)
    _put(stats, 'expectancy', sum(pnls, Decimal(0)) / len(pnls))
    _put(stats, 'avg_win', gain / len(wins) if wins else None, 'trade_structure.reason.no_wins')
    _put(stats, 'avg_loss', loss / len(losses) if losses else None, 'trade_structure.reason.no_losses')
    payoff = (gain / len(wins)) / (loss / len(losses)) if wins and losses else None
    _put(stats, 'payoff_ratio', payoff, 'trade_structure.reason.no_losses' if not losses else 'trade_structure.reason.no_wins')
    _put(stats, 'win_rate', Decimal(len(wins)) / len(pnls))
    _put(stats, 'max_losing_streak', _streak(pnls))
    _put(stats, 'largest_win', max(wins) if wins else None, 'trade_structure.reason.no_wins')
    _put(stats, 'largest_win_share', max(wins) / gain if wins else None, 'trade_structure.reason.no_wins')
    _put(stats, 'profit_factor', gain / loss if losses else None, 'trade_structure.reason.no_losses')
    return stats


def breakeven(stats):
    """Break-even ratios; tie lots make the binary win-rate formula undefined."""
    result = {}
    with localcontext(Context(prec=64, rounding=ROUND_HALF_UP)):
        wins, losses, payoff = stats.get('wins'), stats.get('losses'), stats.get('payoff_ratio')
        ratio = Decimal(losses) / wins if wins else None
        _put(result, 'breakeven_payoff_ratio', ratio, 'trade_structure.reason.no_wins' if stats.get('n') else 'trade_structure.reason.no_closed_lots')
        reason = 'trade_structure.reason.tie_lots' if stats.get('ties') else stats.get('payoff_ratio_reason')
        rate = Decimal(1) / (1 + payoff) if payoff is not None and not stats.get('ties') else None
        _put(result, 'breakeven_win_rate', rate, reason or 'trade_structure.reason.no_closed_lots')
    return result


def red_flags(stats, max_drawdown_pct=None):
    """Deterministic table order; thin margin excludes both 0 and 25% edges."""
    if not stats.get('n'):
        return []
    t = THRESHOLDS
    expectancy, share, rate, payoff = (stats.get(k) for k in ('expectancy', 'largest_win_share', 'win_rate', 'payoff_ratio'))
    base = breakeven(stats)['breakeven_payoff_ratio']
    pf, streak = stats.get('profit_factor'), stats.get('max_losing_streak')
    drawdown = _number(max_drawdown_pct) if max_drawdown_pct is not None else None
    with localcontext(Context(prec=64, rounding=ROUND_HALF_UP)):
        conditions = (
            expectancy is not None and expectancy < t['negative_expectancy'][0],
            share is not None and share > t['single_trade_dominance'][0],
            rate is not None and payoff is not None and rate > t['small_wins_big_losses'][0] and payoff < t['small_wins_big_losses'][1],
            payoff is not None and base is not None and t['thin_edge_margin'][0] < payoff - base < base * t['thin_edge_margin'][1],
            drawdown is not None and drawdown > t['severe_drawdown'][0],
            streak is not None and streak >= t['long_losing_streak'][0],
            stats['n'] >= t['marginal_profit_factor'][0] and pf is not None and t['marginal_profit_factor'][1] < pf < t['marginal_profit_factor'][2],
        )
    return [{'code': code, 'severity': t[code][-1], 'key': 'trade_structure.flag.' + code} for code, applies in zip(t, conditions) if applies]
