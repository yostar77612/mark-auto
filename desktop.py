"""Frozen Windows desktop entry point; no web server, browser, or Python setup."""
from __future__ import annotations

import argparse
import multiprocessing
from pathlib import Path
import sys


class _SmokeSettingsView:
    """Validated settings snapshot for automated smoke; never writes user preferences."""
    def __init__(self, settings):
        from copy import deepcopy
        self._settings = deepcopy(settings)

    def load(self):
        from copy import deepcopy
        return deepcopy(self._settings)

    def save(self, settings):
        from copy import deepcopy
        if not isinstance(settings, dict):
            raise ValueError('Smoke preferences must be a dictionary')
        self._settings = deepcopy(settings)


def _auth_smoke_dependencies():
    """Offline synthetic packaging proof; no host registration, vault or model calls."""
    import json
    import socket
    import time
    import jwt
    import cffi
    import pycparser
    import cryptography
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends.openssl.backend import backend
    import desktop_chatgpt_auth as auth
    from desktop_chatgpt_provider import implementation_provenance

    def deny_network(*args, **kwargs):
        raise RuntimeError('Network forbidden in synthetic auth packaging smoke')

    versions = {'PyJWT': jwt.__version__, 'cryptography': cryptography.__version__,
                'cffi': cffi.__version__, 'pycparser': pycparser.__version__}
    expected = {'PyJWT': '2.15.1', 'cryptography': '50.0.2', 'cffi': '2.1.1', 'pycparser': '3.11'}
    if versions != expected or 'OpenSSL 4.0.3' not in backend.openssl_version_text():
        raise ValueError('Auth packaging dependency mismatch')
    before = set(Path.cwd().iterdir())
    network_functions = {name: getattr(socket, name) for name in ('socket', 'create_connection', 'getaddrinfo')}
    try:
        for name in network_functions:
            setattr(socket, name, deny_network)
        provenance = implementation_provenance()
        parsed = pycparser.CParser().parse('typedef unsigned long size_t; struct sample { int value; };')
        ffi = cffi.FFI()
        ffi.cdef('struct sample { int value; };')
        if len(parsed.ext) != 2 or ffi.new('struct sample *', {'value': 17}).value != 17:
            raise ValueError('Parser or native CFFI packaging failed')
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
                   kid='packaging-fixture', alg='RS256', use='sig')
        claims = dict(iss=auth.ISSUER, sub='packaging-fixture', aud='fixture-client',
                      nonce='fixture-nonce', iat=int(time.time()), exp=int(time.time()) + 60)
        token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'packaging-fixture'})

        class FixtureTransport:
            def request(self, method, url, *, form=None):
                if method != 'GET' or form is not None:
                    raise ValueError('Unexpected synthetic auth operation')
                if url == auth.DISCOVERY:
                    value = dict(auth.PINNED_DISCOVERY, id_token_signing_alg_values_supported=['RS256'])
                elif url == auth.JWKS:
                    value = {'keys': [jwk]}
                else:
                    raise ValueError('Unexpected synthetic auth endpoint')
                return auth.HttpResponse(200, json.dumps(value).encode('utf-8'))

        validator = auth.IdentityValidator(FixtureTransport())
        identity = validator.verify(token, 'fixture-client', 'fixture-nonce')
        if identity.get('subject') != 'packaging-fixture':
            raise ValueError('Synthetic identity validation failed')
        for client, nonce in [('different-client', 'fixture-nonce'), ('fixture-client', 'wrong-nonce')]:
            try:
                validator.verify(token, client, nonce)
            except auth.AuthError:
                pass
            else:
                raise ValueError('Identity binding failure accepted')
        try:
            jwt.decode(token, jwt.PyJWK.from_dict(jwk), algorithms=['HS256'],
                       issuer=auth.ISSUER, audience='fixture-client')
        except jwt.InvalidAlgorithmError:
            pass
        else:
            raise ValueError('JWT algorithm confusion accepted')
    finally:
        for name, function in network_functions.items():
            setattr(socket, name, function)
    if set(Path.cwd().iterdir()) != before:
        raise ValueError('Auth packaging parser wrote into working directory')
    return {'status': 'passed', 'source_type': 'synthetic', 'network_used': False,
            'versions': versions, 'native_openssl': backend.openssl_version_text(),
            'parser_and_cffi': True, 'rs256_identity_binding': True, 'implementation_provenance': provenance,
            'real_oauth_status': 'not_verified', 'real_model_status': 'not_verified',
            'scope': 'offline packaging only; not an account grant or actual model verification'}


def _smoke_steps():
    """Fixed offline fixtures only. No endpoints, credentials, or arbitrary commands."""
    from quantlab.core import to_dict
    from quantlab.reporting import demo_config, synthetic_dataset
    from quantlab.research import demo_campaign_config
    campaign = to_dict(demo_campaign_config(synthetic_dataset(120), demo_config()))
    campaign.update(families=['trend'], max_trials=1, max_improvements=0, max_runtime_seconds=45)
    campaign['ranking']['minimum'] = '-100000000'
    contract = 'TAIFEX:TMF:202601'
    policy = {'contract_id': contract, 'risk_sessions': [{'open': '2026-01-05T00:45:00Z',
        'end': '2026-01-05T02:45:00Z', 'trade_date': '2026-01-05', 'session': 'day',
        'contract_id': contract, 'source': 'explicit synthetic smoke fixture'}],
        'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}]}
    snapshot = {'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}
    return [
        ('ui_demo', {'bars': 120}),
        ('ui_backtest', {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'config': to_dict(demo_config()), 'batch': False}),
        ('ui_select', {}),  # Filled only from the preceding verified report result.
        ('ui_campaign', {'config': campaign, 'provider': {'mode': 'fixture'}}),
        ('ui_paper_reconcile', {'policy': policy, 'snapshot': snapshot}),
        ('ui_paper_replay', {'policy': policy, 'snapshot': snapshot, 'reconcile_confirmed': True, 'max_bars': 25}),
        ('ui_paper_kill', {'policy': policy}),
    ]


def _market_smoke_ui(app):
    """Disposable engineering-fixture widgets; never bind user persistence signals."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import hashlib
    import shiboken6
    from desktop_market import MarketDashboard
    from desktop_charts import CandlestickChart
    from desktop_forms import StrategyForm, CampaignForm
    from quantlab.market import InstrumentRef, MarketBar, MarketSeries, SourceProvenance
    from quantlab.core import canonical_json
    widgets = []
    try:
        dashboard = MarketDashboard(); widgets.append(dashboard)
        dashboard.setWindowTitle('SYNTHETIC ENGINEERING FIXTURE — not market acceptance')
        dashboard.resize(1280, 900)
        instrument = InstrumentRef('TAIFEX', 'TMF', 'TAIFEX:TMF:202610', '202610')
        start = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
        bars = tuple(MarketBar(instrument, '2026-10-01', 'day', Decimal(100 + i % 7),
            Decimal(111), Decimal(90), Decimal(101 + i % 7), 100 + i, interval='1m',
            timestamp=start + timedelta(minutes=i), end=start + timedelta(minutes=i + 1),
            session_open=start, session_end=start + timedelta(minutes=120)) for i in range(120))
        fixture_hash = hashlib.sha256(canonical_json(bars).encode('utf-8')).hexdigest()
        source = SourceProvenance('https://example.invalid/synthetic-engineering-fixture', fixture_hash,
            'SYNTHETIC ENGINEERING FIXTURE — not official market data',
            'https://example.invalid/fixture-not-a-license', start, '2026-10-01', '2026-10-01',
            '2026-10-01', mode='offline', warnings=('Synthetic packaging smoke only; no market acceptance.',))
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
        if not all(any(value is not None for value in values)
                   for values in (*dashboard.chart.overlays.values(), *dashboard.chart.panes.values())):
            raise ValueError('Market indicators did not warm up')
        dashboard.show(); app.processEvents()
        pixmap = dashboard.chart.grab()
        image = pixmap.toImage()
        colors = {image.pixel(x, y) for x in range(0, image.width(), max(1, image.width() // 20))
                  for y in range(0, image.height(), max(1, image.height() // 20))}
        if pixmap.isNull() or dashboard.chart.last_rendered_bar_count < 1 or len(colors) < 4:
            raise ValueError('Market chart did not render nonempty candles')
        strategy = StrategyForm(); campaign = CampaignForm(); widgets.extend((strategy, campaign))
        strategy.fields['fast'].setText('5'); strategy.fields['slow'].setText('20')
        candidate = strategy.build_payload()
        config = _smoke_steps()[3][1]['config']
        # No selection/holdout reuse in this additional packaging-only evaluation.
        config['ranking']['minimum'] = '1000000000000'
        campaign.from_payload(config)
        typed_config = campaign.build_payload()
        if candidate['family'] != 'trend' or candidate['parameters']['fast'] != 5 or typed_config['max_trials'] != 1:
            raise ValueError('Typed forms changed the bounded smoke payload')
        return {'status': 'pending', 'source_type': 'synthetic', 'generator': 'fixture',
            'scope': 'engineering packaging smoke only; not official-data or real-model acceptance',
            'network_used': False, 'live_status': 'disabled', 'fixture_sha256': fixture_hash,
            'modules': ['desktop_market', 'desktop_charts', 'desktop_forms'],
            'chart_rendered_bars': dashboard.chart.last_rendered_bar_count,
            'timeframe_bars': counts, 'indicator_series': len(dashboard.chart.overlays) + len(dashboard.chart.panes),
            'typed_payload': True, 'steps': []}, typed_config, candidate
    finally:
        for widget in reversed(widgets):
            widget.close(); shiboken6.delete(widget)


def _market_smoke_response(request, candidate):
    """Create a clearly synthetic response from typed local input, never a model call."""
    from quantlab.core import canonical_json
    response = {key: request[key] for key in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
    response['candidates'] = [{'family': 'trend', 'context_hash': request['families'][0]['context_hash'],
                               'candidate': candidate}]
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
    expected = {name: content_hash(Path(research.__file__).with_name(name).read_text(encoding='utf-8'))
                for name in ('research.py', 'provider.py', 'core.py', 'strategies.py', 'backtest.py')}
    if (result.get('status') != 'completed' or result.get('real_model_status') != 'not_verified'
            or result.get('binding', {}).get('provider', {}).get('mode') != 'manual_unverified'
            or result.get('source_manifest', {}).get('source_type') != 'synthetic'
            or hashes != expected or len(result.get('attempts', [])) != 1
            or result['attempts'][0].get('status') != 'evaluated'):
        raise ValueError('Manual import or frozen source provenance failed')
    return {'engine_source_hashes': hashes, 'real_model_status': 'not_verified'}


def _history_smoke_fixture(workspace):
    """Tiny invented native-schema CSV and explicit synthetic dated session policy."""
    from datetime import datetime, timedelta
    import hashlib
    from quantlab.market_history import PRODUCT_SOURCES
    header = '成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),近月價格,遠月價格,開盤集合競價\n'
    rows, sessions = [], []
    for product, base in (('TX', 100), ('MTX', 200), ('TMF', 300)):
        for index, minute in enumerate((0, 1, 2, 3, 5, 15, 30, 59, 60)):
            stamp = datetime(2026, 10, 8, 8, 45) + timedelta(minutes=minute)
            rows.append(f'20261008,{product},202610,{stamp:%H%M%S},{base + index},2,-,-,')
            if minute == 0:
                rows.append(f'20261008,{product},202610,084559,{base + 2},4,-,-,')
        sessions.append({'contract_id': f'TAIFEX:{product}:202610', 'trade_date': '2026-10-08',
            'session': 'day', 'open': '2026-10-08T00:45:00+00:00',
            'end': '2026-10-08T01:46:00+00:00', 'include_end': False,
            'source': PRODUCT_SOURCES[product]})
    raw = (header + '\n'.join(rows) + '\n').encode('utf-8')
    path = Path(workspace) / 'SYNTHETIC-packaging-fixture-not-exchange-data.csv'
    path.write_bytes(raw)
    payload = {'history_import': True, 'local_path': str(path), 'sessions': sessions,
               'dated_policy_confirmed': True}
    return {'status': 'pending', 'source_type': 'synthetic', 'generator': 'fixture',
        'scope': 'synthetic packaging proof only; not actual market or Windows-client acceptance',
        'network_used': False, 'live_status': 'disabled', 'real_model_status': 'not_verified',
        'real_market_status': 'not_verified', 'windows_client_status': 'not_verified',
        'fixture_sha256': hashlib.sha256(raw).hexdigest(), 'steps': []}, payload


def _check_history_worker_result(result, paths, payload, fixture_sha256):
    """Reload the worker's bounded cache; never accept an IPC-only success claim."""
    import hashlib
    import json
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from quantlab.market_history import load_history, list_history
    with Path(payload['local_path']).open('rb') as stream:
        source = stream.read(2049)  # This fixed fixture is smaller than 2 KiB.
    if len(source) > 2048 or hashlib.sha256(source).hexdigest() != fixture_sha256:
        raise ValueError('Synthetic history source changed')
    cache = paths.state / 'market_history'
    loaded = load_history(cache, result.get('cache_id'))
    if tuple(item.cache_id for item in list_history(cache)) != (loaded.cache_id,):
        raise ValueError('Unexpected history cache contents')
    policy = sorted(payload['sessions'], key=lambda row: (row['contract_id'], row['open']))
    policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False).encode('utf-8')).hexdigest()
    counters = {'rows': 30, 'accepted_ticks': 30, 'spread_rows': 0,
                'excluded_rows': 0, 'outside_session_rows': 0, 'missing_minutes': 156}
    if (result.get('mode') != 'local_unverified_history' or result.get('contracts') != 3
            or result.get('bars') != 27 or result.get('source_hash') != fixture_sha256
            or loaded.source_hash != fixture_sha256 or result.get('policy_hash') != policy_hash
            or loaded.policy_hash != policy_hash or result.get('counters') != counters
            or dict(loaded.counters) != counters or not loaded.warnings
            or result.get('warnings') != list(loaded.warnings)):
        raise ValueError('History worker result or cache provenance mismatch')
    expected = {'TAIFEX:TX:202610': ('TX', 100), 'TAIFEX:MTX:202610': ('MXF', 200),
                'TAIFEX:TMF:202610': ('TMF', 300)}
    if {item.instrument.contract_id for item in loaded.series} != set(expected):
        raise ValueError('History product identities missing')
    start = datetime(2026, 10, 8, 0, 45, tzinfo=timezone.utc)
    for item in loaded.series:
        symbol, base = expected[item.instrument.contract_id]
        if (item.instrument.symbol != symbol or item.instrument.expiry != '202610'
                or len(item.bars) != 9 or item.provenance.mode != 'history'
                or item.provenance.sha256 != fixture_sha256):
            raise ValueError('History series identity or provenance mismatch')
        for index, (bar, minute) in enumerate(zip(item.bars, (0, 1, 2, 3, 5, 15, 30, 59, 60))):
            price = Decimal(base + index)
            high = Decimal(base + 2) if index == 0 else price
            if ((bar.open, bar.high, bar.low, bar.close, bar.volume) !=
                    (price, high, price, high, 3 if index == 0 else 1)
                    or bar.timestamp != start + timedelta(minutes=minute)
                    or bar.end != start + timedelta(minutes=minute + 1)
                    or bar.session_open != start or bar.session_end != start + timedelta(minutes=61)
                    or bar.trade_date != '2026-10-08' or bar.session != 'day'
                    or bar.interval != '1m' or not bar.partial or bar.source_id != fixture_sha256):
                raise ValueError('History synthetic tick normalization mismatch')
    return loaded.series, {'cache_id': loaded.cache_id, 'policy_hash': policy_hash,
        'source_hash': loaded.source_hash, 'counters': counters, 'cache_reloaded': True,
        'contracts': sorted(expected), 'bars': 27, 'mode': result['mode']}


def _history_smoke_ui(app, series):
    """Render all product/timeframe combinations from the reloaded worker cache."""
    import shiboken6
    from desktop_market import MarketDashboard
    from desktop_charts import CandlestickChart
    dashboard = MarketDashboard()
    try:
        dashboard.setWindowTitle('SYNTHETIC HISTORY FIXTURE — not actual market acceptance')
        dashboard.resize(1280, 900)
        dashboard.set_market_series(series)
        dashboard.show(); app.processEvents()
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
                pixmap = dashboard.chart.grab(); image = pixmap.toImage()
                colors = {image.pixel(x, y) for x in range(0, image.width(), max(1, image.width() // 20))
                          for y in range(0, image.height(), max(1, image.height() // 20))}
                bars = dashboard.chart.bars
                if (len(bars) != count or any(bar.contract_id != contract for bar in bars)
                        or pixmap.isNull() or dashboard.chart.last_rendered_bar_count != count or len(colors) < 4):
                    raise ValueError('History product/timeframe chart did not render expected candles')
                counts[contract][timeframe] = len(bars)
                rendered[contract][timeframe] = dashboard.chart.last_rendered_bar_count
        return {'timeframe_bars': counts, 'chart_rendered_bars': rendered,
                'chart_render_checks': 24, 'modules': ['quantlab.market_history', 'desktop_market', 'desktop_charts']}
    finally:
        dashboard.close(); shiboken6.delete(dashboard)


def _walk_forward_smoke_fixture(paths):
    """Generated engineering bars only, in a separate disposable worker workspace."""
    from dataclasses import replace
    from decimal import Decimal
    from quantlab.core import Dataset, content_hash, to_dict
    from quantlab.reporting import demo_config, save_dataset, synthetic_dataset
    from quantlab.walk_forward import build_walk_forward_plan
    data = synthetic_dataset(200)
    cycle = (-120, -80, -40, 0, 40, 80, 120, 80, 40, 0, -40, -80)
    bars = []
    for index, bar in enumerate(data.bars):
        price = Decimal(20000 + cycle[index % len(cycle)])
        bars.append(replace(bar, open=price, high=price + 2, low=price - 2,
                            close=price, source_id='synthetic-walk-forward-smoke-v1'))
    manifest = {**data.manifest, 'source_filename': 'generated walk-forward engineering smoke',
                'source_hash': content_hash(bars), 'data_hash': content_hash(bars)}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items()
                                            if k not in ('imported_at', 'manifest_hash')})
    data = Dataset(tuple(bars), manifest, dict(data.quality))
    # Default minimum one closed lot and 10% drawdown gate are NOT relaxed.
    # Twenty train/validation evaluations plus two actual forward evaluations.
    plan = build_walk_forward_plan(backtest_config=demo_config(), train_bars=60,
        validation_bars=40, oos_bars=40, fold_count=2, final_holdout=(180, 200),
        max_runtime_seconds=30, max_bars=200, max_evaluations=22,
        process_start_method='spawn', max_ipc_bytes=65536)
    paths.ensure()
    save_dataset(data, paths.state / 'dataset.json')
    return {'status': 'pending', 'source_type': 'synthetic', 'generator': 'fixture',
        'scope': 'engineering synthetic packaging smoke only; never actual research PASS or Windows-client acceptance',
        'network_used': False, 'model_calls': 0, 'paper_eligible': False,
        'independent_oos': False, 'ranking_eligible': False, 'live_status': 'disabled',
        'real_model_status': 'not_verified', 'real_market_status': 'not_verified',
        'windows_client_status': 'not_verified', 'fixture_data_hash': manifest['data_hash'],
        'steps': []}, {'plan': to_dict(plan)}


def _check_walk_forward_smoke_result(operation, result, paths, payload, report):
    """Bind compact worker replies to source, frozen plan, and bounded real journal."""
    import hashlib
    import json
    from decimal import Decimal
    from quantlab.core import content_hash
    from quantlab.reporting import load_dataset
    from quantlab.walk_forward import read_walk_forward_state
    from desktop_walk_forward import compact_walk_forward, preview_walk_forward
    if type(result) is not dict or len(json.dumps(result, allow_nan=False).encode('utf-8')) > 65536:
        raise ValueError('Walk-forward smoke result exceeds compact reply bound')
    data = load_dataset(paths.state / 'dataset.json')
    if data.manifest['data_hash'] != report['fixture_data_hash'] or data.manifest['source_type'] != 'synthetic':
        raise ValueError('Walk-forward synthetic source changed')
    expected = preview_walk_forward(data, payload['plan'], paths)
    reference = expected['preview_identity']
    if operation == 'ui_walk_forward_preview':
        if (result != expected or (paths.state / 'walk_forward').exists()
                or (paths.controls / 'holdout-registry.sqlite3').exists()):
            raise ValueError('Walk-forward preview mismatch or unexpected mutation')
        return {'reference': reference, 'source_identity': expected['source_identity'],
            'engine_source_hashes': expected['source_hashes'],
            'candidate_pool_hash': content_hash(expected['candidate_pool']),
            'runtime_seconds': expected['runtime_seconds'], 'evaluation_limit': expected['evaluation_limit'],
            'final_holdout_status': expected['final_holdout_status'], 'preview_verified': True}
    if operation not in ('ui_walk_forward_run', 'ui_walk_forward_read'):
        raise ValueError('Unknown walk-forward smoke operation')
    if result.get('reference') != reference or report.get('reference') != reference:
        raise ValueError('Walk-forward smoke reference mismatch')
    folder = paths.state / 'walk_forward' / reference
    journal = folder / 'walk_forward.sqlite3'
    if journal.is_symlink() or not 0 < journal.stat().st_size <= 1048576:
        raise ValueError('Walk-forward smoke journal exceeds fixture bound')
    state = read_walk_forward_state(folder)  # Validates hashes, ledger, winner and no-winner decisions.
    summary = state['summary']
    if (result != compact_walk_forward(state, reference) or state['status'] != 'completed'
            or state['binding']['plan'] != payload['plan']
            or state['binding']['source_hashes'] != expected['source_hashes']
            or state['source_manifest'] != dict(data.manifest)
            or summary['planned_folds'] != 2 or summary['evaluated_oos_folds'] != 2
            or summary['evaluations_reserved'] != 22 or summary['evaluation_limit'] != 22
            or summary['model_calls'] != 0 or summary['final_holdout_status'] != 'excluded_not_evaluated'
            or summary['evidence_mode'] != 'synthetic_validation'
            or any(summary[key] is not False for key in ('independent_oos', 'ranking_eligible', 'paper_eligible'))):
        raise ValueError('Walk-forward smoke journal or result mismatch')
    folds = []
    for fold in state['folds']:
        selected = fold['selection']
        winner = fold['candidates'][selected['pool_index']]
        validation = winner['validation']['result']['metrics']
        oos = fold['oos']['result']['metrics']
        zero_trade = sum(c['validation']['result']['metrics']['trade_count'] == 0 for c in fold['candidates'])
        if (fold['status'] != 'evaluated' or len(fold['candidates']) != 5
                or selected['spec']['strategy_id'] != 'mean_reversion-v1'
                or validation['trade_count'] < 1 or oos['trade_count'] < 1
                or Decimal(validation['total_costs']) <= 0 or Decimal(oos['total_costs']) <= 0
                or zero_trade < 1):
            raise ValueError('Walk-forward smoke requires real closed trades and excludes zero-trade candidates')
        folds.append({'index': fold['index'], 'winner': selected['spec']['strategy_id'],
            'validation_closed_lots': validation['trade_count'], 'oos_closed_lots': oos['trade_count'],
            'zero_trade_candidates_excluded': zero_trade})
    for record in state['evaluations']:
        start, end = payload['plan']['folds'][record['fold']][record['role']]
        manifest = record['result']['manifest']
        split = manifest['dataset_manifest']['walk_forward_split']
        if (record['status'] != 'evaluated' or end > payload['plan']['final_holdout'][0]
                or split != {'fold': record['fold'], 'role': record['role'], 'start': start, 'end': end,
                             'warmup': 'independent_no_prior_access'}
                or manifest['source_type'] != 'synthetic' or manifest['data_hash'] != content_hash(data.bars[start:end])):
            raise ValueError('Walk-forward smoke evaluated unexpected source or excluded final holdout')
    if any((paths.state / name).exists() for name in
           ('selection.json', 'active_candidate.json', 'paper.sqlite3', 'paper_policy.json', 'campaigns')):
        raise ValueError('Walk-forward smoke unexpectedly mutated AI or paper state')
    digest = hashlib.sha256(journal.read_bytes()).hexdigest()
    if operation == 'ui_walk_forward_read' and report.get('journal_sha256') != digest:
        raise ValueError('Walk-forward smoke read mutated the completed journal')
    return {'journal_reloaded': True, 'journal_sha256': digest, 'state_hash': state['state_hash'],
        'summary': summary, 'folds': folds, 'compact_result_bytes': len(json.dumps(result).encode('utf-8')),
        'journal_bytes': journal.stat().st_size, 'read_verified': operation == 'ui_walk_forward_read'}


def _start_smoke_job(manager, operation, payload):
    # Every smoke job needs the existing bounded whole-subtree join protocol,
    # including ordinary fixture jobs which do not normally require that proof.
    try:
        return manager.start(operation, payload)
    finally:
        if manager.active:
            manager._requires_tree_quiescence = True


def _close_smoke_worker(manager):
    """Bounded cleanup evidence; process-local owner/join proof cannot be guessed."""
    if manager is None:
        return {'verified': True, 'error_type': None}
    error_type = None
    try:
        if manager.active:
            manager._requires_tree_quiescence = True
            if sys.platform == 'win32' and manager.tree is None:
                raise RuntimeError('Missing isolated worker tree')
        manager.close()
    except BaseException as exc:
        error_type = type(exc).__name__
    verified = error_type is None and not manager.active
    if manager._walk_forward_reference is not None:
        verified = verified and manager._quiesced_walk_forward == (manager.job_id, manager._walk_forward_reference)
    elif manager._requires_tree_quiescence:
        verified = verified and manager._tree_quiesced
    return {'verified': bool(verified), 'error_type': error_type}


def _retain_smoke_directory(directory):
    # An uncertain writer/owner forbids deleting its evidence. TemporaryDirectory
    # otherwise removes it at interpreter shutdown even when cleanup is skipped.
    if directory is not None:
        directory._finalizer.detach()


def main(argv=None):
    parser = argparse.ArgumentParser(description='MarkAuto native desktop research and paper trading')
    parser.add_argument('--smoke-test', type=Path, help='Show real native window, write launch report, then exit')
    parser.add_argument('--local-ai-smoke', type=Path, help='Explicit one-call actual local AI technical validation report')
    parser.add_argument('--local-ai-runtime-archive', type=Path)
    parser.add_argument('--local-ai-model', type=Path)
    parser.add_argument('--local-ai-root', type=Path)
    args = parser.parse_args(argv)
    local_args = (args.local_ai_smoke, args.local_ai_runtime_archive, args.local_ai_model, args.local_ai_root)
    if any(item is not None for item in local_args):
        if args.smoke_test or any(item is None or not item.is_absolute() for item in local_args):
            parser.error('Local AI validation requires four absolute paths and cannot combine with --smoke-test')
        from desktop_local_ai_smoke import run
        return run(*local_args)
    if args.smoke_test is not None and not args.smoke_test.is_absolute():
        parser.error('--smoke-test requires an absolute report path')
    from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from quantlab import __version__
    from quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, RuntimeGuard, SettingsStore, WorkspaceLocator, WindowsAppMutex, atomic_write, _json_bytes
    app = QApplication(sys.argv[:1])
    app.setApplicationName('MarkAuto')
    app.setOrganizationName('MarkAuto')
    app.setApplicationVersion(__version__)
    user_bootstrap = AppPaths.discover().root
    smoke_startup_directory = None
    if args.smoke_test:
        import tempfile
        # Isolate even GUI startup, recovery, guards and paper freeze. Only the
        # validated user settings snapshot is read from the configured workspace.
        smoke_startup_directory = tempfile.TemporaryDirectory(prefix='markauto-smoke-startup-')
    bootstrap = Path(smoke_startup_directory.name) if smoke_startup_directory else user_bootstrap
    bootstrap.mkdir(parents=True, exist_ok=True)
    locator = WorkspaceLocator(bootstrap)
    lock = QLockFile(str(locator.lock_path))
    lock.setStaleLockTime(0)  # Qt checks process liveness; never steal a live lock by age.
    if not lock.tryLock(0):
        QMessageBox.information(None, 'MarkAuto is already running', 'Use the existing MarkAuto window. A second worker will not be started.')
        if smoke_startup_directory is not None:
            smoke_startup_directory.cleanup()
        return 2
    jobs = guard = installation_guard = None
    smoke_jobs = smoke_directory = None
    settings_paths = None
    smoke_cleanup_verified = True
    smoke_shutdown_completed = False
    smoke_report = None
    try:
        installation_guard = WindowsAppMutex()
        paths = locator.load()
        backups = BackupManager(paths)
        backups.recover()  # Recover directory switch before creating the state directory.
        paths.ensure()
        guard = RuntimeGuard(paths)
        previous_unclean = guard.start()
        settings_paths = WorkspaceLocator(user_bootstrap).load(probe=False) if args.smoke_test else paths
        settings = SettingsStore(settings_paths.state / 'settings.json')
        validated_settings = settings.load()  # Fail closed on incompatible/corrupt state.
        if args.smoke_test:
            settings = _SmokeSettingsView(validated_settings)  # Smoke must preserve saved user bytes.
        jobs = JobManager(paths)
        backups.jobs = jobs
        from desktop_ui import MainWindow
        window = MainWindow(paths, jobs, settings=settings, backups=backups, guard=guard)
        window.show()
        if hasattr(window, 'freeze_paper'):
            window.freeze_paper('Previous session ended unexpectedly; reconcile paper account' if previous_unclean else 'Startup requires paper reconciliation')
        # Windows suspend/resume notifications complement wall/monotonic checks,
        # including short sleeps and platforms whose monotonic clock pauses.
        class PowerEvents(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if sys.platform == 'win32':
                    import ctypes
                    from ctypes import wintypes
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0218 and msg.wParam in (4, 6, 7, 18):
                        guard.reconciliation_required = True
                        jobs.cancel()
                        backups.recover()
                        if hasattr(window, 'freeze_paper'):
                            window.freeze_paper('Windows power event; reconcile paper account before resuming')
                return False, 0
        power_events = PowerEvents()
        app.installNativeEventFilter(power_events)
        timer = QTimer(window)
        timer.setInterval(1000)
        def clock_tick():
            if guard.check_clock():
                jobs.cancel()
                backups.recover()
                if hasattr(window, 'freeze_paper'):
                    window.freeze_paper('Sleep or clock change detected; reconcile paper account before resuming')
        timer.timeout.connect(clock_tick)
        timer.start()
        if args.smoke_test:
            import tempfile
            import time
            # Exercise the real frozen multiprocessing bootstrap in disposable
            # cache state, never replacing the user's research dataset.
            smoke_directory = tempfile.TemporaryDirectory(prefix='smoke-', dir=paths.cache)
            smoke_jobs = JobManager(AppPaths(Path(smoke_directory.name)))
            smoke_deadline = time.monotonic() + 120
            auth_report = _auth_smoke_dependencies()
            market_report, manual_config, manual_candidate = _market_smoke_ui(app)
            history_report, history_payload = _history_smoke_fixture(Path(smoke_directory.name))
            walk_forward_paths = AppPaths(Path(smoke_directory.name) / 'walk-forward-fixture')
            walk_forward_report, walk_forward_payload = _walk_forward_smoke_fixture(walk_forward_paths)
            manual_export_path = Path(smoke_directory.name) / 'manual-request.json'
            market_results = {}
            smoke_steps = _smoke_steps()
            original_step_count = len(smoke_steps)
            smoke_steps.extend([
                ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}, 'manual_export': str(manual_export_path)}),
                ('ui_campaign', {'config': manual_config, 'provider': {'mode': 'manual'}}),
                ('ui_market_refresh', history_payload),
                ('ui_walk_forward_preview', walk_forward_payload),
                ('ui_walk_forward_run', {}),  # Bound only to the verified preview.
                ('ui_walk_forward_read', {}),  # Reopen the same immutable journal.
            ])
            smoke_index = 0
            _start_smoke_job(smoke_jobs, *smoke_steps[0])
            smoke_result = {'failed': False, 'results': {}, 'steps': []}
            smoke_timer = QTimer(window)
            smoke_timer.setInterval(100)
            def complete_smoke():
                nonlocal smoke_index, smoke_jobs, smoke_report
                operation = smoke_steps[smoke_index][0]
                market_phase = ('manual_export' if smoke_index == original_step_count else 'manual_import') if original_step_count <= smoke_index < original_step_count + 2 else None
                history_phase = smoke_index == original_step_count + 2
                walk_forward_phase = operation.startswith('ui_walk_forward_')
                for event in smoke_jobs.poll():
                    if event['type'] == 'result':
                        result = event.get('result', {})
                        if walk_forward_phase:
                            try:
                                evidence = _check_walk_forward_smoke_result(operation, result, smoke_jobs.paths,
                                    walk_forward_payload, walk_forward_report)
                                walk_forward_report.update(evidence)
                                walk_forward_report['steps'].append({'operation': operation, 'passed': True})
                            except Exception as exc:
                                smoke_result['failed'] = True
                                walk_forward_report['steps'].append({'operation': operation, 'passed': False, 'error_type': type(exc).__name__})
                            continue
                        if history_phase:
                            try:
                                series, evidence = _check_history_worker_result(result, smoke_jobs.paths,
                                    history_payload, history_report['fixture_sha256'])
                                history_report.update(evidence)
                                history_report.update(_history_smoke_ui(app, series))
                                history_report['steps'].append({'operation': 'history_import', 'passed': True})
                            except Exception as exc:
                                smoke_result['failed'] = True
                                history_report['steps'].append({'operation': 'history_import', 'passed': False, 'error_type': type(exc).__name__})
                            continue
                        if market_phase:
                            try:
                                evidence = _check_market_worker_result(market_phase, result, manual_export_path)
                                if market_phase == 'manual_export':
                                    smoke_steps[original_step_count + 1][1]['provider']['response_text'] = _market_smoke_response(result['request'], manual_candidate)
                                market_results[market_phase] = result
                                market_report.update(evidence)
                                market_report['steps'].append({'operation': market_phase, 'passed': True})
                            except Exception as exc:
                                smoke_result['failed'] = True
                                market_report['steps'].append({'operation': market_phase, 'passed': False, 'error_type': type(exc).__name__})
                            continue
                        smoke_result['results'][operation] = result
                        valid = True
                        if operation == 'ui_demo':
                            valid = result.get('source_type') == 'synthetic' and result.get('bars') == 120
                        elif operation == 'ui_backtest':
                            valid = bool(result.get('reports')) and result.get('source_type') == 'synthetic'
                        elif operation == 'ui_campaign':
                            valid = result.get('status') == 'completed' and bool(result.get('attempts')) and all(row.get('status') == 'evaluated' for row in result['attempts']) and result.get('real_model_status') == 'not_verified'
                        elif operation == 'ui_paper_replay':
                            valid = result.get('replay', {}).get('cursor') == 25 and result.get('account', {}).get('kill_switch') is True
                        elif operation == 'ui_paper_kill':
                            valid = result.get('account', {}).get('kill_switch') is True
                        smoke_result['steps'].append({'operation': operation, 'passed': valid})
                        smoke_result['failed'] |= not valid
                    elif event['type'] in ('error', 'cancelled'):
                        smoke_result['failed'] = True
                        step_report = walk_forward_report['steps'] if walk_forward_phase else history_report['steps'] if history_phase else market_report['steps'] if market_phase else smoke_result['steps']
                        step_report.append({'operation': 'history_import' if history_phase else market_phase or operation, 'passed': False, 'error_type': event.get('error_type', event['type'])})
                timed_out = time.monotonic() > smoke_deadline
                if smoke_jobs.active and not timed_out:
                    return
                if not smoke_result['failed'] and not timed_out and smoke_index + 1 < len(smoke_steps):
                    smoke_index += 1
                    next_operation, payload = smoke_steps[smoke_index]
                    if next_operation == 'ui_select':
                        payload = {'result': smoke_result['results']['ui_backtest']['reports'][0]['result']}
                    try:
                        if next_operation == 'ui_walk_forward_preview':
                            smoke_jobs.close()
                            smoke_jobs = JobManager(walk_forward_paths)
                        elif next_operation == 'ui_walk_forward_run':
                            payload = {**walk_forward_payload, 'preview_identity': walk_forward_report['reference']}
                        elif next_operation == 'ui_walk_forward_read':
                            payload = {'reference': walk_forward_report['reference']}
                        _start_smoke_job(smoke_jobs, next_operation, payload)
                        return
                    except Exception as exc:
                        smoke_result['failed'] = True
                        rows = walk_forward_report['steps'] if next_operation.startswith('ui_walk_forward_') else smoke_result['steps']
                        rows.append({'operation': next_operation, 'passed': False, 'error_type': type(exc).__name__})
                smoke_timer.stop()
                smoke_jobs.close()
                completed = len(smoke_result['results']) == original_step_count
                market_report['status'] = 'passed' if len(market_results) == 2 and not smoke_result['failed'] and not timed_out else 'failed'
                history_report['status'] = 'passed' if len(history_report['steps']) == 1 and history_report['steps'][0]['passed'] and not smoke_result['failed'] and not timed_out else 'failed'
                walk_forward_report['status'] = 'passed' if [row['operation'] for row in walk_forward_report['steps']] == ['ui_walk_forward_preview', 'ui_walk_forward_run', 'ui_walk_forward_read'] and all(row['passed'] for row in walk_forward_report['steps']) and walk_forward_report.get('read_verified') and not smoke_result['failed'] and not timed_out else 'failed'
                passed = walk_forward_report['status'] == 'passed' and completed and auth_report['status'] == 'passed' and market_report['status'] == 'passed' and history_report['status'] == 'passed' and not smoke_result['failed'] and not timed_out and window.isVisible()
                completed_operations = {row['operation'] for row in smoke_result['steps'] if row['passed']}
                # data_dir remains the inspected settings location for installer
                # compatibility; mutable execution uses smoke_data_dir. The
                # explicitly requested report path is also written by the caller
                # contract and is excluded from the user-state read-only claim.
                smoke_report = {'status': 'passed' if passed else 'failed', 'data_dir': str(settings_paths.root),
                    'smoke_data_dir': str(paths.root), 'user_state_read_only': True,
                    'version': __version__, 'native_window_visible': window.isVisible(), 'worker_completed': completed,
                    'backtest_completed': 'ui_backtest' in completed_operations,
                    'campaign_completed': 'ui_campaign' in completed_operations,
                    'paper_completed': {'ui_paper_reconcile', 'ui_paper_replay', 'ui_paper_kill'} <= completed_operations,
                    'source_type': 'synthetic', 'generator': 'fixture', 'real_model_status': 'not_verified',
                    'live_status': 'disabled', 'timed_out': timed_out, 'steps': smoke_result['steps'], 'market_smoke': market_report, 'auth_smoke': auth_report, 'history_smoke': history_report,
                    'walk_forward_smoke': walk_forward_report}
                window.close()
                app.exit(0 if passed else 1)
            def guarded_complete_smoke():
                nonlocal smoke_cleanup_verified, smoke_report
                try:
                    complete_smoke()
                except BaseException as exc:
                    # Qt swallows timer exceptions. Always emit terminal failure
                    # and stop scheduling, without echoing exception values.
                    smoke_timer.stop()
                    cleanup = _close_smoke_worker(smoke_jobs)
                    smoke_cleanup_verified = cleanup['verified']
                    operation = smoke_steps[smoke_index][0]
                    rows = walk_forward_report['steps'] if operation.startswith('ui_walk_forward_') else smoke_result['steps']
                    rows.append({'operation': operation, 'passed': False, 'error_type': type(exc).__name__})
                    walk_forward_report['status'] = 'failed'
                    smoke_report = {'status': 'failed', 'version': __version__,
                        'data_dir': str(settings_paths.root), 'smoke_data_dir': str(paths.root),
                        'user_state_read_only': True, 'source_type': 'synthetic', 'generator': 'fixture',
                        'live_status': 'disabled', 'real_model_status': 'not_verified',
                        'native_window_visible': window.isVisible(), 'worker_completed': False,
                        'timed_out': time.monotonic() > smoke_deadline, 'error_type': type(exc).__name__,
                        'worker_cleanup': cleanup, 'steps': smoke_result['steps'],
                        'auth_smoke': auth_report, 'market_smoke': market_report,
                        'history_smoke': history_report, 'walk_forward_smoke': walk_forward_report}
                    app.exit(1)
            smoke_timer.timeout.connect(guarded_complete_smoke)
            smoke_timer.start()
        status = app.exec()
        jobs.close()
        guard.finish()
        smoke_shutdown_completed = True
        return status
    except Exception as exc:
        # No exception values or secret-bearing tracebacks in a general GUI dialog.
        if args.smoke_test:
            if smoke_report is None:
                smoke_report = {'status': 'failed', 'version': __version__,
                    'data_dir': str(settings_paths.root) if settings_paths else None,
                    'smoke_data_dir': str(bootstrap), 'user_state_read_only': True,
                    'steps': [], 'source_type': 'synthetic', 'generator': 'fixture', 'live_status': 'disabled',
                    'walk_forward_smoke': {'status': 'failed', 'error_type': type(exc).__name__,
                        'source_type': 'synthetic', 'real_model_status': 'not_verified',
                        'scope': 'engineering synthetic packaging smoke only; never actual research PASS or Windows-client acceptance'},
                    'market_smoke': {'status': 'failed', 'error_type': type(exc).__name__,
                        'scope': 'engineering packaging smoke only; not official-data or real-model acceptance'},
                    'history_smoke': {'status': 'failed', 'error_type': type(exc).__name__,
                        'source_type': 'synthetic',
                        'scope': 'synthetic packaging proof only; not actual market or Windows-client acceptance'}}
            smoke_report.update(status='failed', error_type=type(exc).__name__)
            return 1
        QMessageBox.critical(None, 'MarkAuto could not start', f'{type(exc).__name__}: startup failed. Your existing data has been preserved. Restore a compatible backup or reinstall the previous version.')
        return 1
    finally:
        if args.smoke_test:
            # Publish exactly once, after every cleanup step, so a late failure
            # cannot leave a successful report or a precomputed zero return code.
            cleanup_errors = []
            for manager in (smoke_jobs, jobs):
                cleanup = _close_smoke_worker(manager)
                smoke_cleanup_verified = smoke_cleanup_verified and cleanup['verified']
                if cleanup['error_type'] is not None:
                    cleanup_errors.append(cleanup['error_type'])
            for close in (installation_guard.close if installation_guard is not None else None, lock.unlock):
                if close is not None:
                    try:
                        close()
                    except BaseException as exc:
                        smoke_cleanup_verified = False
                        cleanup_errors.append(type(exc).__name__)
            directories = (smoke_directory, smoke_startup_directory)
            if smoke_cleanup_verified:
                for directory in directories:
                    if directory is not None:
                        try:
                            directory.cleanup()
                        except BaseException as exc:
                            smoke_cleanup_verified = False
                            cleanup_errors.append(type(exc).__name__)
                            break
            if not smoke_cleanup_verified:
                for directory in directories:
                    _retain_smoke_directory(directory)
            if smoke_report is None:
                smoke_report = {'status': 'failed', 'version': __version__, 'steps': [],
                    'source_type': 'synthetic', 'generator': 'fixture', 'live_status': 'disabled',
                    'data_dir': str(settings_paths.root) if settings_paths else None,
                    'smoke_data_dir': str(bootstrap), 'user_state_read_only': True,
                    'error_type': 'SmokeDidNotComplete'}
            if not smoke_cleanup_verified or not smoke_shutdown_completed:
                smoke_report['status'] = 'failed'
            if not smoke_shutdown_completed:
                smoke_report.setdefault('error_type', 'ShutdownIncomplete')
            smoke_report['worker_cleanup'] = {'verified': smoke_cleanup_verified,
                                              'error_types': cleanup_errors}
            try:
                atomic_write(args.smoke_test, _json_bytes(smoke_report))
            except BaseException:
                return 1  # An unwritable requested report path cannot mean PASS.
            return 0 if smoke_report['status'] == 'passed' else 1
        if jobs is not None:
            jobs.close()
        if installation_guard is not None:
            installation_guard.close()
        lock.unlock()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
