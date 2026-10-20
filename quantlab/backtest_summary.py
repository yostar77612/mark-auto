"""Pure descriptive warning policy for reported backtest samples."""

MIN_SAMPLE_BARS = 30
MIN_SAMPLE_TRADES = 5


def warning_keys(bar_count, trade_count, closed_trade_count):
    """Return catalog keys; thresholds describe sample size, never merit."""
    keys = []
    if bar_count < MIN_SAMPLE_BARS or trade_count < MIN_SAMPLE_TRADES:
        keys.append('backtest.summary.sample_short')
    if closed_trade_count == 0:
        keys.append('backtest.summary.no_closed_trades')
    return tuple(keys)
