"""Offline smoke history; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations

from pathlib import Path
from desktop_app.strings.catalog import ui_text


def _history_smoke_fixture(workspace):
    from quantlab.windows_paths import canonical_path

    """Tiny invented native-schema CSV and explicit synthetic dated session policy."""
    from datetime import datetime, timedelta
    import hashlib
    from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES

    header = ui_text('desktop.history_smoke_fixture.tick_csv_header')
    rows, sessions = [], []
    for product, base in (('TX', 100), ('MTX', 200), ('TMF', 300)):
        for index, minute in enumerate((0, 1, 2, 3, 5, 15, 30, 59, 60)):
            stamp = datetime(2026, 10, 8, 8, 45) + timedelta(minutes=minute)
            rows.append(f'20261008,{product},202610,{stamp:%H%M%S},{base + index},2,-,-,')
            if minute == 0:
                rows.append(f'20261008,{product},202610,084559,{base + 2},4,-,-,')
        sessions.append(
            {
                'contract_id': f'TAIFEX:{product}:202610',
                'trade_date': '2026-10-08',
                'session': 'day',
                'open': '2026-10-08T00:45:00+00:00',
                'end': '2026-10-08T01:46:00+00:00',
                'include_end': False,
                'source': PRODUCT_SOURCES[product],
            }
        )
    raw = (header + '\n'.join(rows) + '\n').encode('utf-8')
    path = Path(workspace) / 'SYNTHETIC-packaging-fixture-not-exchange-data.csv'
    path.write_bytes(raw)
    payload = {'history_import': True, 'local_path': str(canonical_path(path)), 'sessions': sessions, 'dated_policy_confirmed': True}
    return {
        'status': 'pending',
        'source_type': 'synthetic',
        'generator': 'fixture',
        'scope': 'synthetic packaging proof only; not actual market or Windows-client acceptance',
        'network_used': False,
        'live_status': 'disabled',
        'real_model_status': 'not_verified',
        'real_market_status': 'not_verified',
        'windows_client_status': 'not_verified',
        'fixture_sha256': hashlib.sha256(raw).hexdigest(),
        'steps': [],
    }, payload


def _check_history_worker_result(result, paths, payload, fixture_sha256):
    """Reload the worker's bounded cache; never accept an IPC-only success claim."""
    import hashlib
    from quantlab.windows_paths import native_path
    import json
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from quantlab.research_core.adapters.market_history import load_history, list_history

    with native_path(payload['local_path']).open('rb') as stream:
        source = stream.read(2049)  # This fixed fixture is smaller than 2 KiB.
    if len(source) > 2048 or hashlib.sha256(source).hexdigest() != fixture_sha256:
        raise ValueError('Synthetic history source changed')
    cache = paths.state / 'market_history'
    loaded = load_history(cache, result.get('cache_id'))
    if tuple(item.cache_id for item in list_history(cache)) != (loaded.cache_id,):
        raise ValueError('Unexpected history cache contents')
    policy = sorted(payload['sessions'], key=lambda row: (row['contract_id'], row['open']))
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    counters = {'rows': 30, 'accepted_ticks': 30, 'spread_rows': 0, 'excluded_rows': 0, 'outside_session_rows': 0, 'missing_minutes': 156}
    if (
        result.get('mode') != 'local_unverified_history'
        or result.get('contracts') != 3
        or result.get('bars') != 27
        or result.get('source_hash') != fixture_sha256
        or loaded.source_hash != fixture_sha256
        or result.get('policy_hash') != policy_hash
        or loaded.policy_hash != policy_hash
        or result.get('counters') != counters
        or dict(loaded.counters) != counters
        or not loaded.warnings
        or result.get('warnings') != list(loaded.warnings)
    ):
        raise ValueError('History worker result or cache provenance mismatch')
    expected = {'TAIFEX:TX:202610': ('TX', 100), 'TAIFEX:MTX:202610': ('MXF', 200), 'TAIFEX:TMF:202610': ('TMF', 300)}
    if {item.instrument.contract_id for item in loaded.series} != set(expected):
        raise ValueError('History product identities missing')
    start = datetime(2026, 10, 8, 0, 45, tzinfo=timezone.utc)
    for item in loaded.series:
        symbol, base = expected[item.instrument.contract_id]
        if (
            item.instrument.symbol != symbol
            or item.instrument.expiry != '202610'
            or len(item.bars) != 9
            or item.provenance.mode != 'history'
            or item.provenance.sha256 != fixture_sha256
        ):
            raise ValueError('History series identity or provenance mismatch')
        for index, (bar, minute) in enumerate(zip(item.bars, (0, 1, 2, 3, 5, 15, 30, 59, 60))):
            price = Decimal(base + index)
            high = Decimal(base + 2) if index == 0 else price
            if (
                (bar.open, bar.high, bar.low, bar.close, bar.volume) != (price, high, price, high, 3 if index == 0 else 1)
                or bar.timestamp != start + timedelta(minutes=minute)
                or bar.end != start + timedelta(minutes=minute + 1)
                or bar.session_open != start
                or bar.session_end != start + timedelta(minutes=61)
                or bar.trade_date != '2026-10-08'
                or bar.session != 'day'
                or bar.interval != '1m'
                or not bar.partial
                or bar.source_id != fixture_sha256
            ):
                raise ValueError('History synthetic tick normalization mismatch')
    return loaded.series, {
        'cache_id': loaded.cache_id,
        'policy_hash': policy_hash,
        'source_hash': loaded.source_hash,
        'counters': counters,
        'cache_reloaded': True,
        'contracts': sorted(expected),
        'bars': 27,
        'mode': result['mode'],
    }


def _history_smoke_ui(app, series):
    """Render all product/timeframe combinations from the reloaded worker cache."""
    import shiboken6
    from desktop_app.features.market.dashboard import MarketDashboard
    from desktop_app.components.charts import CandlestickChart

    dashboard = MarketDashboard()
    try:
        dashboard.setWindowTitle('SYNTHETIC HISTORY FIXTURE — not actual market acceptance')
        dashboard.resize(1280, 900)
        dashboard.set_market_series(series)
        dashboard.show()
        app.processEvents()
        expected = {'1m': 9, '3m': 6, '5m': 6, '15m': 5, '30m': 3, '60m': 2, '1d': 1, '1w': 1}
        counts, rendered = {}, {}
        for item in series:
            contract = item.instrument.contract_id
            dashboard.contract_combo.setCurrentIndex(dashboard.contract_combo.findData(contract))
            if dashboard.selected_series() != item or not isinstance(dashboard.chart, CandlestickChart):
                raise ValueError('History chart product selection failed')
            counts[contract], rendered[contract] = {}, {}
            for timeframe, count in expected.items():
                index = dashboard.timeframe_combo.findData(timeframe)
                if index < 0:
                    raise ValueError('History chart timeframe missing')
                dashboard.timeframe_combo.setCurrentIndex(index)
                app.processEvents()
                pixmap = dashboard.chart.grab()
                image = pixmap.toImage()
                colors = {
                    image.pixel(x, y)
                    for x in range(0, image.width(), max(1, image.width() // 20))
                    for y in range(0, image.height(), max(1, image.height() // 20))
                }
                bars = dashboard.chart.bars
                if (
                    len(bars) != count
                    or any(bar.contract_id != contract for bar in bars)
                    or pixmap.isNull()
                    or dashboard.chart.last_rendered_bar_count != count
                    or len(colors) < 4
                ):
                    raise ValueError('History product/timeframe chart did not render expected candles')
                counts[contract][timeframe] = len(bars)
                rendered[contract][timeframe] = dashboard.chart.last_rendered_bar_count
        return {
            'timeframe_bars': counts,
            'chart_rendered_bars': rendered,
            'chart_render_checks': 24,
            'modules': ['quantlab.research_core.adapters.history_decoder', 'desktop_app.features.market.dashboard', 'desktop_app.components.charts'],
        }
    finally:
        dashboard.close()
        shiboken6.delete(dashboard)
