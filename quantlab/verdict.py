"""Pure display-only OOS conclusions; no reference-project code or flow adapted.

Drawdown uses the compounded merged OOS returns, including starting equity 1.
No fold metrics, holdout data, selection functions, persistence or permissions.
"""

from decimal import Context, Decimal, DecimalException, localcontext

INSUFFICIENT = 'insufficient'
NEGATIVE_EXPECTANCY = 'negative_expectancy'
LUCK_SUSPECTED = 'luck_suspected'
FRAGILE_EDGE = 'fragile_edge'
STATISTICAL_EDGE = 'statistical_edge'
NAMES = ('樣本不足', '負期望（不建議進入紙上驗證）', '疑似運氣', '脆弱優勢', '具統計優勢（仍非保證）')
LEVELS = (INSUFFICIENT, NEGATIVE_EXPECTANCY, LUCK_SUSPECTED, FRAGILE_EDGE, STATISTICAL_EDGE)
STATISTICS = (
    'mean',
    'sd',
    't',
    'p_value_t',
    'p_value_bootstrap',
    'ci_lower',
    'ci_upper',
    'n_bootstrap_actual',
    't_hac',
    'p_value_t_hac',
    'hac_lag',
    'p_value_block_bootstrap',
    'block_length',
)
# Every p value must clear alpha: the i.i.d. pair alone overstates serially correlated daily returns.
P_VALUES = ('p_value_t', 'p_value_bootstrap', 'p_value_t_hac', 'p_value_block_bootstrap')
# Daily returns of one long holding are not independent evidence; an edge needs this many round trips.
MIN_CLOSED_TRADES = 30
# Reason text is '<prefix><count or "unknown"> < <minimum>'; presenters parse it with this prefix.
CLOSED_TRADES_REASON = 'insufficient_closed_trades: '
_UNCHECKED = object()


def _number(value):
    if type(value) not in (int, float, str, Decimal):
        return None
    try:
        with localcontext(Context(prec=400)):
            number = Decimal(str(value))
            return number if number.is_finite() and abs(number.adjusted()) <= 1000 else None
    except (DecimalException, ValueError):
        return None


def compounded_drawdown(returns):
    """Return a Decimal ratio, or None for missing/invalid observations.

    Isolated precision 400, no intermediate quantization. A total loss is 1;
    returns below -1 are invalid. The comparison with 0.50 is unrounded.
    """
    if not isinstance(returns, (list, tuple)) or not returns:
        return None
    try:
        with localcontext(Context(prec=400)):
            equity = peak = Decimal(1)
            worst = Decimal(0)
            for raw in returns:
                value = _number(raw)
                if value is None or value < -1:
                    return None
                equity *= 1 + value
                peak = max(peak, equity)
                worst = max(worst, (peak - equity) / peak)
            return worst
    except DecimalException:
        return None


def _flags(flags):
    if not isinstance(flags, (list, tuple)):
        return []
    return sorted(
        {
            (flag['severity'], flag['code'])
            for flag in flags
            if isinstance(flag, dict)
            and flag.get('severity') in ('high', 'medium')
            and type(flag.get('code')) is str
            and flag['code']
            and flag['code'] != 'severe_drawdown'
        }
    )


def judge(oos_test, oos_required, oos_returns, flags, *, closed_trades=_UNCHECKED):
    """Return exactly level, display_name, reasons, recommended_observations.

    B2 statistics and required-observation dictionaries are read only. Reasons
    are ordered machine strings; unavailable planning includes B2's reason.
    An empty OOS sample has no verdict. Malformed samples are insufficient.
    Caller must suppress verdicts for failed/interrupted runs before calling.
    A supplied ``closed_trades`` below MIN_CLOSED_TRADES, or one that is not a
    non-negative integer (an unknown count), is insufficient.
    """
    stats = oos_test if isinstance(oos_test, dict) else {}
    required = oos_required if isinstance(oos_required, dict) else {}
    count = required.get('required_observations')
    count = count if type(count) is int and count > 0 else None
    result = {'level': None, 'display_name': None, 'reasons': [], 'recommended_observations': count}
    if isinstance(oos_returns, (list, tuple)) and not oos_returns:
        return {**result, 'reasons': ['no evaluated OOS fold']}
    n = stats.get('n', stats.get('n_obs'))
    values = {key: _number(stats.get(key)) for key in STATISTICS}
    drawdown = compounded_drawdown(oos_returns)
    invalid = any(value is None for value in values.values())
    if not invalid:
        invalid = values['sd'] < 0 or any(not 0 <= values[key] <= 1 for key in P_VALUES)
    alerts = _flags(flags)
    if drawdown is not None and drawdown > Decimal('0.50'):
        alerts.append(('high', 'severe_drawdown'))
    few_trades = closed_trades is not _UNCHECKED and (type(closed_trades) is not int or not MIN_CLOSED_TRADES <= closed_trades)
    short_sample = type(n) is not int or n < 30 or invalid or drawdown is None
    if short_sample or few_trades:
        level, reasons = INSUFFICIENT, []
        if short_sample:
            reasons.append('insufficient_statistics')
            why = required.get('required_observations_reason')
            reasons.append(
                f'recommended_observations: {count}' if count is not None else (why if type(why) is str and why else 'required_observations_unavailable')
            )
        if few_trades:
            reasons.append(f'{CLOSED_TRADES_REASON}{closed_trades if type(closed_trades) is int else "unknown"} < {MIN_CLOSED_TRADES}')
    elif values['mean'] < 0:
        level, reasons = NEGATIVE_EXPECTANCY, ['negative_mean']
    elif any(values[key] >= Decimal('0.05') for key in P_VALUES):
        level, reasons = LUCK_SUSPECTED, ['p_not_significant']
    elif any(severity == 'high' for severity, code in alerts):
        level, reasons = FRAGILE_EDGE, sorted(code for severity, code in alerts if severity == 'high')
    else:
        level, reasons = STATISTICAL_EDGE, ['positive_significant_mean']
        reasons.extend('note: ' + code for severity, code in alerts if severity == 'medium')
    return {**result, 'level': level, 'display_name': NAMES[LEVELS.index(level)], 'reasons': reasons}
