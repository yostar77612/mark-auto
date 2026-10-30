"""Display adapters only: never write rounded values back to research records."""

from desktop_app.strings.catalog import ui_text
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re


STATUS_LABELS = {
    'synthetic': ui_text('presentation.labels.synthetic'),
    'official_local': ui_text('presentation.labels.local_official'),
    'official': ui_text('presentation.labels.official'),
    'proxy': ui_text('presentation.labels.proxy'),
    'disabled': ui_text('presentation.labels.disabled'),
    'not_verified': ui_text('presentation.labels.unverified'),
    'evaluated': ui_text('presentation.labels.evaluated'),
    'running': ui_text('presentation.labels.evaluating'),
    'failed': ui_text('presentation.labels.evaluation_failed'),
    'cancelled': ui_text('presentation.labels.cancelled'),
    'timed_out': ui_text('presentation.labels.timed_out'),
    'budget_exhausted': ui_text('presentation.labels.budget_exhausted'),
    'not_accessed': ui_text('presentation.labels.unconsumed'),
    'not_evaluated': ui_text('presentation.labels.unevaluated'),
    'completed': ui_text('presentation.labels.completed'),
    'pending': ui_text('presentation.labels.waiting'),
    'accepted': ui_text('presentation.labels.accepted'),
    'rejected': ui_text('presentation.labels.rejected'),
    'filled': ui_text('presentation.labels.filled'),
    'partially_filled': ui_text('presentation.labels.partially_filled'),
    'buy': ui_text('presentation.labels.buy'),
    'sell': ui_text('presentation.labels.sell'),
    'market': ui_text('presentation.labels.market'),
    'limit': ui_text('presentation.labels.limit'),
    'day': ui_text('presentation.labels.day'),
    'night': ui_text('presentation.labels.night'),
    'trend': ui_text('presentation.labels.trend'),
    'mean_reversion': ui_text('presentation.labels.mean_reversion'),
    'breakout': ui_text('presentation.labels.breakout'),
    'momentum': ui_text('presentation.labels.momentum'),
    'volatility': ui_text('presentation.labels.volatility'),
}
AMOUNTS = frozenset(
    (
        'cash',
        'initial_cash',
        'final_equity',
        'net_pnl',
        'gross_pnl',
        'realized_gross_pnl',
        'unrealized_pnl',
        'total_costs',
        'slippage_cost',
        'max_drawdown',
        'commission',
        'tax',
        'margin_per_contract',
    )
)
RATIOS = frozenset(('return', 'win_rate', 'max_drawdown_pct', 'annual_risk_free_rate'))


def display_status(value):
    text = str(value)
    if re.search(r'[\u3400-\u9fff]', text):
        return text
    return STATUS_LABELS.get(text.lower(), ui_text('presentation.display_status.unknown_status'))


def display_number(value, key=''):
    try:
        if isinstance(value, bool) or len(str(value)) > 128:
            raise ValueError
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1e100'):
            raise ValueError
        with localcontext() as context:
            context.prec = 110
            if key in RATIOS:
                return f'{number * 100:.2f}%'
            if key in AMOUNTS:
                return f'{number:,.2f}'.rstrip('0').rstrip('.') + ' TWD'
            return f'{number:.4f}'.rstrip('0').rstrip('.') or '0'
    except (InvalidOperation, ValueError, TypeError):
        return ui_text('presentation.display_number.diagnostics_required')


def display_value(value, key=''):
    if value is None:
        return ui_text('presentation.display_value.not_provided')
    if isinstance(value, bool):
        return ui_text('presentation.display_value.yes') if value else ui_text('presentation.display_value.no')
    text = str(value)
    if key.endswith(('_id', '_hash')):
        return text
    if key in ('status', 'source_type', 'family', 'side', 'order_type'):
        return display_status(value)
    if isinstance(value, (int, float, Decimal)) or re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text):
        return display_number(value, key)
    if re.fullmatch(r'[A-Z][A-Z_]{2,}', text):
        return display_status(value)
    return text


def result_name(result, created_at):
    """Readable metadata; filesystem creation time is fallback for legacy reports."""
    manifest = result.manifest
    spec = manifest.get('strategy', {})
    params = spec.get('parameters', {})
    parameters = ui_text('presentation.result_name.parameter_separator').join(f'{key}={display_number(value)}' for key, value in params.items()) or ui_text(
        'presentation.result_name.default_parameters'
    )
    parameters = re.sub(r'[0-9a-fA-F]{8,}', ui_text('presentation.result_name.id_in_diagnostics'), parameters)
    coverage = manifest.get('dataset_manifest', {}).get('coverage', {})
    dates = [str(coverage[key])[:10] for key in ('start', 'end') if coverage.get(key)]
    if len(dates) != 2:
        dates = [str(row.get('timestamp', row.get('trade_date', '')))[:10] for row in result.equity]
    interval = ui_text('presentation.result_name.date_range').format(dates[0], dates[-1]) if dates else ui_text('presentation.result_name.dates_not_provided')
    instant = datetime.fromtimestamp(created_at, timezone.utc).astimezone(timezone(timedelta(hours=8)))
    return ui_text('presentation.result_name.strategy_parameters_dates_time').format(display_status(spec.get('family', '')), parameters, interval, instant)


# Shared operation inputs have no dependency on either UI dispatcher.
from pathlib import Path
from quantlab.core import Dataset, ValidationError, content_hash
from quantlab.reporting import load_dataset


def research_controls(paths):
    """Irreversible budget/holdout ledgers must never be rolled back with user state."""
    state = Path(paths.state)
    legacy = list((state / 'provider_budgets').glob('*'))
    legacy.extend((state / 'campaigns').glob('.holdout_registry.sqlite3*'))
    if any(path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in legacy):
        raise ValidationError(ui_text('ui.research_controls.legacy_budget_blocked'))
    controls = Path(paths.controls)
    if controls.resolve().is_relative_to(state.resolve()):
        raise ValidationError(ui_text('ui.research_controls.irreversible_record_location'))
    return controls


def _dataset(root, payload):
    data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
    start, end = payload.get('start_date'), payload.get('end_date')
    if start or end:
        if start and end and start > end:
            raise ValidationError(ui_text('ui.dataset.reversed_dates'))
        bars = tuple(b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end))
        if not bars:
            raise ValidationError(ui_text('ui.dataset.empty_date_range'))
        manifest = {
            **data.manifest,
            'parent_data_hash': data.manifest['data_hash'],
            'data_hash': content_hash(bars),
            'date_filter': {'start': start, 'end': end},
        }
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(data.quality))
    return data
