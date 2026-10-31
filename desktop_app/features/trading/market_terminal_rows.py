"""Terminal quote formatting, bounded status summaries, and Taipei diagnostics."""

from zoneinfo import ZoneInfo
from decimal import Decimal
from desktop_app.strings.catalog import ui_text
from desktop_app.features.trading.market_watch_rows import quote_detail_rows


def number(value, *, signed=False, percent=False):
    if value is None:
        return ui_text('watch.unknown')
    text = format(value, '+.2f' if signed else '.2f')
    return text + '%' if percent else text


def price_number(value, instrument, tick=None):
    if value is None:
        return ui_text('watch.unknown')
    # TW equity/ETF quotations use hundredths below 50, tenths below 500,
    # and integral ticks from 500. Indices use hundredths. Prices remain Decimal.
    digits = (
        max(0, -tick.as_tuple().exponent)
        if tick is not None
        else (2 if instrument is None or instrument.exchange == 'INDEX' or value < Decimal('50') else 1 if value < Decimal('500') else 0)
    )
    return format(value, f'.{digits}f')


def quota_text(usage):
    if usage is None:
        return ui_text('terminal.quota_unknown')
    megabyte = Decimal(1024 * 1024)
    return ui_text('terminal.quota').format(
        f'{Decimal(usage.used_bytes) / megabyte:.1f} MB',
        f'{Decimal(usage.limit_bytes) / megabyte:.0f} MB',
        f'{Decimal(usage.used_bytes) * 100 / Decimal(usage.limit_bytes):.1f}',
    )


def quote_values(instrument, view):
    known = view.health.freshness != 'UNKNOWN'
    return (
        instrument.code,
        instrument.name,
        price_number(view.price if known else None, instrument, view.price_tick),
        number(view.change, signed=True),
        number(view.change_percent, signed=True, percent=True),
        ui_text('terminal.volume_stock').format(f'{view.total_volume:,}')
        if instrument.exchange != 'INDEX' and view.total_volume is not None
        else ui_text('watch.unknown'),
    )


def state_label(freshness):
    return {
        'LIVE': ui_text('watch.live'),
        'DELAYED': ui_text('watch.delayed').split(' · ')[0],
        'STOPPED': ui_text('watch.stopped').split(' · ')[0],
        'CLOSED': ui_text('watch.closed').split(' · ')[0],
        'UNKNOWN': ui_text('watch.unknown'),
    }[freshness]


def market_summary(health):
    bad = [item for item in health.instruments if item.freshness != 'LIVE']
    if not bad:
        return ui_text('terminal.all_live') if health.instruments else ui_text('watch.unknown')
    text = ', '.join(item.instrument_id.split(':')[-1] + ' ' + state_label(item.freshness) for item in bad[:3])
    return text + (' ' + ui_text('terminal.others').format(len(bad) - 3) if len(bad) > 3 else '')


def source_text(environment):
    sources = {'LOCAL': ui_text('terminal.source_local'), 'BROKER_SIMULATION': ui_text('terminal.source_sim'), 'LIVE': ui_text('terminal.source_live')}
    return sources[environment.value]


def diagnostic_text(view, environment):
    values = list(quote_detail_rows(view))
    replacements = {
        ui_text('watch.source'): source_text(environment),
        ui_text('watch.updated'): taipei_time(view.received_at),
        ui_text('watch.source_time'): taipei_time(view.source_at),
        ui_text('watch.state'): state_label(view.health.freshness),
    }
    return '\n'.join(ui_text('watch.detail_line').format(key, replacements.get(key, value)) for key, value in values)


def taipei_time(value):
    return value.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S') if value is not None else ui_text('watch.unknown')
