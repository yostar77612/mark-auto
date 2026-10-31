"""Offline smoke market; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations

from pathlib import Path
from desktop_app.smoke.fixtures import _smoke_steps


def _market_smoke_ui(app):
    """Disposable engineering-fixture widgets; never bind user persistence signals."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import hashlib
    import shiboken6
    from desktop_app.features.market.dashboard import MarketDashboard
    from desktop_app.components.charts import CandlestickChart
    from desktop_app.features.strategy.forms import StrategyForm
    from desktop_app.features.research.forms import CampaignForm
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance
    from quantlab.core import canonical_json

    widgets = []
    try:
        dashboard = MarketDashboard()
        widgets.append(dashboard)
        dashboard.setWindowTitle('SYNTHETIC ENGINEERING FIXTURE — not market acceptance')
        dashboard.resize(1280, 900)
        instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202610', '202610')
        start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
        bars = tuple(
            MarketBar(
                instrument,
                '2026-10-01',
                'day',
                Decimal(100 + i % 7),
                Decimal(111),
                Decimal(90),
                Decimal(101 + i % 7),
                100 + i,
                interval='1m',
                timestamp=start + timedelta(minutes=i),
                end=start + timedelta(minutes=i + 1),
                session_open=start,
                session_end=start + timedelta(minutes=120),
            )
            for i in range(120)
        )
        fixture_hash = hashlib.sha256(canonical_json(bars).encode('utf-8')).hexdigest()
        source = SourceProvenance(
            'https://example.invalid/synthetic-engineering-fixture',
            fixture_hash,
            'SYNTHETIC ENGINEERING FIXTURE — not official market data',
            'https://example.invalid/fixture-not-a-license',
            start,
            '2026-10-01',
            '2026-10-01',
            '2026-10-01',
            mode='offline',
            warnings=('Synthetic packaging smoke only; no market acceptance.',),
        )
        dashboard.set_market_series(MarketSeries(instrument, bars, source))
        if not isinstance(dashboard.chart, CandlestickChart):
            raise ValueError('Market chart module contract failed')
        counts = {}
        for timeframe in ('1m', '5m', '1d', '1w'):
            dashboard.timeframe_combo.setCurrentIndex(dashboard.timeframe_combo.findData(timeframe))
            counts[timeframe] = len(dashboard.chart.bars)
        if counts != {'1m': 120, '5m': 24, '1d': 1, '1w': 1}:
            raise ValueError('Market timeframe aggregation failed')
        dashboard.timeframe_combo.setCurrentIndex(dashboard.timeframe_combo.findData('1m'))
        for checkbox, controls in dashboard._indicator_widgets.values():
            checkbox.setChecked(True)
        if not dashboard.chart.overlays or not dashboard.chart.panes:
            raise ValueError('Market indicators missing')
        if not all(any(value is not None for value in values) for values in (*dashboard.chart.overlays.values(), *dashboard.chart.panes.values())):
            raise ValueError('Market indicators did not warm up')
        dashboard.show()
        app.processEvents()
        pixmap = dashboard.chart.grab()
        image = pixmap.toImage()
        colors = {
            image.pixel(x, y) for x in range(0, image.width(), max(1, image.width() // 20)) for y in range(0, image.height(), max(1, image.height() // 20))
        }
        if pixmap.isNull() or dashboard.chart.last_rendered_bar_count < 1 or len(colors) < 4:
            raise ValueError('Market chart did not render nonempty candles')
        strategy = StrategyForm()
        campaign = CampaignForm()
        widgets.extend((strategy, campaign))
        strategy.fields['fast'].setText('5')
        strategy.fields['slow'].setText('20')
        candidate = strategy.build_payload()
        config = _smoke_steps()[3][1]['config']
        # No selection/holdout reuse in this additional packaging-only evaluation.
        config['ranking']['minimum'] = '1000000000000'
        campaign.from_payload(config)
        typed_config = campaign.build_payload()
        if candidate['family'] != 'trend' or candidate['parameters']['fast'] != 5 or typed_config['max_trials'] != 1:
            raise ValueError('Typed forms changed the bounded smoke payload')
        return (
            {
                'status': 'pending',
                'source_type': 'synthetic',
                'generator': 'fixture',
                'scope': 'engineering packaging smoke only; not official-data or real-model acceptance',
                'network_used': False,
                'live_status': 'disabled',
                'fixture_sha256': fixture_hash,
                'modules': [
                    'desktop_app.features.market.dashboard',
                    'desktop_app.components.charts',
                    'desktop_app.features.strategy.forms',
                    'desktop_app.features.research.forms',
                ],
                'chart_rendered_bars': dashboard.chart.last_rendered_bar_count,
                'timeframe_bars': counts,
                'indicator_series': len(dashboard.chart.overlays) + len(dashboard.chart.panes),
                'typed_payload': True,
                'steps': [],
            },
            typed_config,
            candidate,
        )
    finally:
        for widget in reversed(widgets):
            widget.close()
            shiboken6.delete(widget)


def _market_smoke_response(request, candidate):
    """Create a clearly synthetic response from typed local input, never a model call."""
    from quantlab.core import canonical_json

    response = {key: request[key] for key in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
    response['candidates'] = [{'family': 'trend', 'context_hash': request['families'][0]['context_hash'], 'candidate': candidate}]
    return canonical_json(response)


def _check_market_worker_result(phase, result, export_path):
    """Fail closed on missing provenance, bundled-source failures or fake completion."""
    import re
    from quantlab.core import content_hash

    if phase == 'manual_export':
        import json
        from quantlab import manual_exchange

        request = result['request']
        if result.get('mode') != 'manual_unverified' or json.loads(export_path.read_text(encoding='utf-8')) != request:
            raise ValueError('Manual export was not written by the worker')
        expected_source = content_hash(Path(manual_exchange.__file__).read_text(encoding='utf-8'))
        if request['module_source_hash'] != expected_source or not re.fullmatch('[0-9a-f]{64}', request['request_id']):
            raise ValueError('Manual source provenance missing or mismatched')
        return {'module_source_hash': expected_source, 'request_id': request['request_id']}
    if phase != 'manual_import':
        raise ValueError('Unknown market smoke phase')
    hashes = result.get('binding', {}).get('engine_source_hashes', {})
    from quantlab import research

    expected = {
        name: content_hash((Path(research.__file__).parent / name).read_text(encoding='utf-8'))
        for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py', 'research_core/domain/receipts.py')
    }
    if (
        result.get('status') != 'completed'
        or result.get('real_model_status') != 'not_verified'
        or result.get('binding', {}).get('provider', {}).get('mode') != 'manual_unverified'
        or result.get('source_manifest', {}).get('source_type') != 'synthetic'
        or hashes != expected
        or len(result.get('attempts', [])) != 1
        or result['attempts'][0].get('status') != 'evaluated'
    ):
        raise ValueError('Manual import or frozen source provenance failed')
    return {'engine_source_hashes': hashes, 'real_model_status': 'not_verified'}
