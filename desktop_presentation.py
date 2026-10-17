"""Display adapters only: never write rounded values back to research records."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re


STATUS_LABELS = {
    'synthetic': '合成示範資料', 'official_local': '官方格式本機資料',
    'official': '官方資料', 'proxy': '替代資料', 'disabled': '已停用',
    'not_verified': '尚未驗證', 'evaluated': '已評估', 'running': '評估中',
    'failed': '評估失敗', 'cancelled': '已取消', 'timed_out': '已逾時',
    'budget_exhausted': '額度已用盡', 'not_accessed': '尚未取用',
    'not_evaluated': '尚未評估', 'completed': '已完成', 'pending': '等待中',
    'accepted': '已接受', 'rejected': '已拒絕', 'filled': '已成交',
    'partially_filled': '部分成交', 'buy': '買進', 'sell': '賣出',
    'market': '市價', 'limit': '限價', 'day': '日盤', 'night': '夜盤',
    'trend': '趨勢', 'mean_reversion': '均值回歸', 'breakout': '突破',
    'momentum': '動能', 'volatility': '波動',
}
AMOUNTS = frozenset(('cash', 'initial_cash', 'final_equity', 'net_pnl', 'gross_pnl',
    'realized_gross_pnl', 'unrealized_pnl', 'total_costs', 'slippage_cost',
    'max_drawdown', 'commission', 'tax', 'margin_per_contract'))
RATIOS = frozenset(('return', 'win_rate', 'max_drawdown_pct', 'annual_risk_free_rate'))


def display_status(value):
    text = str(value)
    if re.search(r'[\u3400-\u9fff]', text): return text
    return STATUS_LABELS.get(text.lower(), '未知狀態，請查看進階診斷')


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
        return '請查看進階診斷'


def display_value(value, key=''):
    if value is None: return '未提供'
    if isinstance(value, bool): return '是' if value else '否'
    text = str(value)
    if key.endswith(('_id', '_hash')): return text
    if key in ('status', 'source_type', 'family', 'side', 'order_type'):
        return display_status(value)
    if isinstance(value, (int, float, Decimal)) or re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text):
        return display_number(value, key)
    if re.fullmatch(r'[A-Z][A-Z_]{2,}', text): return display_status(value)
    return text


def result_name(result, created_at):
    """Readable metadata; filesystem creation time is fallback for legacy reports."""
    manifest = result.manifest
    spec = manifest.get('strategy', {})
    params = spec.get('parameters', {})
    parameters = '、'.join(f'{key}={display_number(value)}' for key, value in params.items()) or '預設參數'
    parameters = re.sub(r'[0-9a-fA-F]{8,}', '識別碼見進階', parameters)
    coverage = manifest.get('dataset_manifest', {}).get('coverage', {})
    dates = [str(coverage[key])[:10] for key in ('start', 'end') if coverage.get(key)]
    if len(dates) != 2:
        dates = [str(row.get('timestamp', row.get('trade_date', '')))[:10] for row in result.equity]
    interval = f'{dates[0]}～{dates[-1]}' if dates else '資料區間未提供'
    instant = datetime.fromtimestamp(created_at, timezone.utc).astimezone(timezone(timedelta(hours=8)))
    return f"{display_status(spec.get('family', ''))}・{parameters}・{interval}・{instant:%Y-%m-%d %H:%M:%S}（台北）"
