"""Display adapters only: never write rounded values back to research records."""

from desktop_strings import ui_text
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re


STATUS_LABELS = {
    'synthetic': ui_text('presentation.labels.text_1'),
    'official_local': ui_text('presentation.labels.text_2'),
    'official': ui_text('presentation.labels.text_3'),
    'proxy': ui_text('presentation.labels.text_4'),
    'disabled': ui_text('presentation.labels.text_5'),
    'not_verified': ui_text('presentation.labels.text_6'),
    'evaluated': ui_text('presentation.labels.text_7'),
    'running': ui_text('presentation.labels.text_8'),
    'failed': ui_text('presentation.labels.text_9'),
    'cancelled': ui_text('presentation.labels.text_10'),
    'timed_out': ui_text('presentation.labels.text_11'),
    'budget_exhausted': ui_text('presentation.labels.text_12'),
    'not_accessed': ui_text('presentation.labels.text_13'),
    'not_evaluated': ui_text('presentation.labels.text_14'),
    'completed': ui_text('presentation.labels.text_15'),
    'pending': ui_text('presentation.labels.text_16'),
    'accepted': ui_text('presentation.labels.text_17'),
    'rejected': ui_text('presentation.labels.text_18'),
    'filled': ui_text('presentation.labels.text_19'),
    'partially_filled': ui_text('presentation.labels.text_20'),
    'buy': ui_text('presentation.labels.text_21'),
    'sell': ui_text('presentation.labels.text_22'),
    'market': ui_text('presentation.labels.text_23'),
    'limit': ui_text('presentation.labels.text_24'),
    'day': ui_text('presentation.labels.text_25'),
    'night': ui_text('presentation.labels.text_26'),
    'trend': ui_text('presentation.labels.text_27'),
    'mean_reversion': ui_text('presentation.labels.text_28'),
    'breakout': ui_text('presentation.labels.text_29'),
    'momentum': ui_text('presentation.labels.text_30'),
    'volatility': ui_text('presentation.labels.text_31'),
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
    return STATUS_LABELS.get(text.lower(), ui_text('presentation.display_status.text_1'))


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
        return ui_text('presentation.display_number.text_1')


def display_value(value, key=''):
    if value is None:
        return ui_text('presentation.display_value.text_1')
    if isinstance(value, bool):
        return ui_text('presentation.display_value.text_2') if value else ui_text('presentation.display_value.text_3')
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
    parameters = ui_text('presentation.result_name.text_1').join(f'{key}={display_number(value)}' for key, value in params.items()) or ui_text(
        'presentation.result_name.text_2'
    )
    parameters = re.sub(r'[0-9a-fA-F]{8,}', ui_text('presentation.result_name.text_3'), parameters)
    coverage = manifest.get('dataset_manifest', {}).get('coverage', {})
    dates = [str(coverage[key])[:10] for key in ('start', 'end') if coverage.get(key)]
    if len(dates) != 2:
        dates = [str(row.get('timestamp', row.get('trade_date', '')))[:10] for row in result.equity]
    interval = ui_text('presentation.result_name.text_4').format(dates[0], dates[-1]) if dates else ui_text('presentation.result_name.text_5')
    instant = datetime.fromtimestamp(created_at, timezone.utc).astimezone(timezone(timedelta(hours=8)))
    return ui_text('presentation.result_name.text_6').format(display_status(spec.get('family', '')), parameters, interval, instant)


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
        raise ValidationError(ui_text('ui.research_controls.text_1'))
    controls = Path(paths.controls)
    if controls.resolve().is_relative_to(state.resolve()):
        raise ValidationError(ui_text('ui.research_controls.text_2'))
    return controls


def _dataset(root, payload):
    data = load_dataset(Path(payload.get('dataset') or root / 'dataset.json'))
    start, end = payload.get('start_date'), payload.get('end_date')
    if start or end:
        if start and end and start > end:
            raise ValidationError(ui_text('ui._dataset.text_1'))
        bars = tuple(b for b in data.bars if (not start or b.trade_date >= start) and (not end or b.trade_date <= end))
        if not bars:
            raise ValidationError(ui_text('ui._dataset.text_2'))
        manifest = {
            **data.manifest,
            'parent_data_hash': data.manifest['data_hash'],
            'data_hash': content_hash(bars),
            'date_filter': {'start': start, 'end': end},
        }
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('imported_at', 'manifest_hash')})
        data = Dataset(bars, manifest, dict(data.quality))
    return data
