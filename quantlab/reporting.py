"""Offline report persistence, comparison and spreadsheet-safe exports."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import csv
import json
import os
import tempfile

from .core import (Bar, Dataset, Fill, Signal, BacktestResult, CostSpec,
                   BacktestConfig, ValidationError, canonical_json, content_hash, to_dict)

MAX_JSON_BYTES = 32 * 1024 * 1024


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValidationError('JSON file exceeds 32 MiB limit')
    def reject(value):
        raise ValidationError(f'Invalid JSON constant: {value}')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject)


def write_json(path, value):
    """Atomic replacement; never follow an existing output symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValidationError('Refusing symlink output')
    data = canonical_json(value)
    fd, temporary = tempfile.mkstemp(prefix='.quantlab-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(data + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _datetime(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def save_dataset(dataset, path):
    payload = to_dict(dataset)
    write_json(path, {'kind': 'quantlab_dataset_v1', 'sha256': content_hash(payload), 'payload': payload})


def _read_envelope(path, kind):
    envelope = read_json(path)
    if not isinstance(envelope, dict) or envelope.get('kind') != kind:
        raise ValidationError(f'Expected {kind}')
    payload = envelope.get('payload')
    if content_hash(payload) != envelope.get('sha256'):
        raise ValidationError('Persisted content hash mismatch')
    return payload


def load_dataset(path):
    payload = _read_envelope(path, 'quantlab_dataset_v1')
    bars = []
    for item in payload['bars']:
        row = dict(item)
        for key in ('timestamp', 'end'):
            row[key] = _datetime(row[key])
        for key in ('open', 'high', 'low', 'close'):
            row[key] = Decimal(row[key])
        bars.append(Bar(**row))
    dataset = Dataset(tuple(bars), payload['manifest'], payload['quality'])
    manifest = dataset.manifest
    if manifest.get('data_hash') != content_hash(dataset.bars):
        raise ValidationError('Dataset bar hash mismatch')
    if manifest.get('manifest_hash') != content_hash({k: v for k, v in manifest.items() if k not in ('manifest_hash', 'imported_at')}):
        raise ValidationError('Dataset manifest hash mismatch')
    if manifest.get('source_type') not in ('synthetic', 'proxy', 'official_local'):
        raise ValidationError('Invalid dataset source classification')
    return dataset


def load_result(path, *, dataset=None):
    payload = _read_envelope(path, 'quantlab_result_v1')
    validate_result_payload(payload, dataset=dataset)
    signals = tuple(Signal(**{**r, 'timestamp': _datetime(r['timestamp'])}) for r in payload['signals'])
    fills = []
    for item in payload['fills']:
        row = {**item, 'timestamp': _datetime(item['timestamp'])}
        for key in ('price', 'commission', 'tax'):
            row[key] = Decimal(row[key])
        fills.append(Fill(**row))
    return BacktestResult(payload['manifest'], signals, tuple(fills), tuple(payload['ledger']),
                          tuple(payload['equity']), payload['metrics'], tuple(payload['rejects']), tuple(payload['warnings']))


def validate_result_payload(payload, *, dataset=None):
    """Check nested deterministic bindings, not just the transport checksum.

    Hashes detect inconsistent/stale rewriting, not authenticate who created data.
    Supplying dataset additionally binds the report to validated actual bars.
    """
    from .core import StrategySpec
    from .strategies import validate_strategy
    from .__main__ import config_from_json
    manifest = payload['manifest']
    unhashed = {**payload, 'manifest': {k: v for k, v in manifest.items() if k not in ('run_hash', 'reproducibility_hash')}}
    digest = content_hash(unhashed)
    if manifest.get('run_hash') != digest or manifest.get('reproducibility_hash') != digest:
        raise ValidationError('Internal reproducibility hash mismatch')
    spec = StrategySpec(**manifest['strategy'])
    validate_strategy(spec)
    config = config_from_json(manifest['config'])
    if content_hash(spec) != manifest.get('spec_hash') or content_hash(config) != manifest.get('config_hash'):
        raise ValidationError('Embedded strategy/config hash mismatch')
    if content_hash((config.costs,) + config.cost_schedule) != manifest.get('cost_hash'):
        raise ValidationError('Embedded cost hash mismatch')
    if content_hash(manifest['source_hashes']) != manifest.get('engine_hash'):
        raise ValidationError('Engine source binding mismatch')
    data_manifest = manifest.get('dataset_manifest')
    if not isinstance(data_manifest, dict):
        raise ValidationError('Embedded dataset manifest required for report validation')
    if content_hash(data_manifest) != manifest.get('dataset_manifest_hash'):
        raise ValidationError('Embedded dataset manifest hash mismatch')
    if content_hash({k: v for k, v in data_manifest.items() if k not in ('imported_at', 'manifest_hash')}) != data_manifest.get('manifest_hash'):
        raise ValidationError('Embedded dataset provenance hash mismatch')
    for name in ('data_hash', 'calendar_hash', 'calendar_version', 'source_type'):
        if manifest.get(name) != data_manifest.get(name):
            raise ValidationError('Dataset binding mismatch: ' + name)
    if dataset is not None:
        from .data import validate_dataset
        validate_dataset(dataset)
        expected = {k: v for k, v in dataset.manifest.items() if k != 'imported_at'}
        if content_hash(dataset.bars) != manifest['data_hash'] or content_hash(expected) != manifest['dataset_manifest_hash']:
            raise ValidationError('Result does not belong to supplied dataset')


def comparison_rows(results):
    rows = []
    for result in results:
        manifest = result.manifest
        rows.append({**to_dict(result.metrics), 'result_hash': content_hash(result), 'source_type': manifest.get('source_type', manifest.get('dataset_manifest', {}).get('source_type', 'see manifest')),
                     'strategy_hash': manifest.get('strategy_hash', manifest.get('spec_hash', 'see manifest')),
                     'fill_count': len(result.fills), 'equity_samples': len(result.equity),
                     'warnings': '; '.join(result.warnings)})
    return rows


def _cell(value):
    if isinstance(value, (dict, list, tuple)):
        value = canonical_json(value)
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def _csv(path, rows):
    if path.is_symlink():
        raise ValidationError('Refusing symlink output')
    keys = sorted({key for row in rows for key in row})
    with path.open('w', encoding='utf-8', newline='') as out:
        writer = csv.writer(out)
        writer.writerow([_cell(key) for key in keys])
        writer.writerows([_cell(row.get(key, '')) for key in keys] for row in rows)


def export_report(result, output_dir):
    """Fixed filenames and content-addressed directory ignore untrusted IDs."""
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    digest = content_hash(result)
    folder = root / digest
    if folder.is_symlink():
        raise ValidationError('Refusing symlink report directory')
    folder.mkdir(exist_ok=True)
    files = {}
    payload = to_dict(result)
    for name, value in [('result', {'kind': 'quantlab_result_v1', 'sha256': digest, 'payload': payload}),
                        ('manifest', result.manifest), ('ledger', result.ledger), ('metrics', result.metrics)]:
        path = folder / f'{name}.json'
        write_json(path, value)
        files[name] = str(path)
    for name in ('fills', 'equity'):
        path = folder / f'{name}.csv'
        _csv(path, payload[name])
        files[name] = str(path)
    files['result_hash'] = digest
    return files


def synthetic_dataset(count=240):
    """Deterministic invented prices, deliberately not a TAIFEX history claim."""
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValidationError('Synthetic count must be 1..10000')
    start = datetime(2026, 1, 5, 0, 45, tzinfo=timezone.utc)
    bars = []
    for i in range(count):
        day, minute = divmod(i, 240)
        ts = start + timedelta(days=day, minutes=minute)
        price = Decimal(20000 + (i % 60) * (1 if (i // 60) % 2 == 0 else -1))
        close = price + Decimal((i % 5) - 2)
        bars.append(Bar(ts, ts + timedelta(minutes=1), ts.date().isoformat(), 'day', 'TAIFEX:TMF:202601',
                        price, max(price, close) + 2, min(price, close) - 2, close, 20 + i % 10, 'synthetic-v1'))
    manifest = {'schema_version': 1, 'source_type': 'synthetic', 'source_url': None,
                'source_filename': 'generated synthetic fixture', 'source_hash': content_hash(bars), 'data_hash': content_hash(bars),
                'imported_at': '2026-01-05T00:00:00Z', 'product': 'TMF', 'coverage': {'bars': count},
                'encoding': 'generated', 'schema': 'quantlab-bars-v1', 'timezone': 'UTC',
                'calendar_hash': content_hash({'calendar': 'invented synthetic intervals'}), 'calendar_version': 'synthetic-only-v1', 'aggregation_version': 'synthetic-v1',
                'license_note': 'Invented demonstration data; not official market observations.',
                'validation_status': 'valid'}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k != 'imported_at'})
    return Dataset(tuple(bars), manifest, {'valid': True, 'errors': [], 'accepted_rows': count, 'rejected_rows': 0, 'warnings': ['SYNTHETIC prices and calendar']})


def demo_config():
    return BacktestConfig(Decimal('1000000'), CostSpec(Decimal('20'), Decimal('0.00002'), 1,
                          'half_up_twd', '2026-01-01', 'synthetic-assumption-v1'),
                          initial_margin_per_contract=Decimal('100000'), margin_version='synthetic-assumption-v1',
                          maintenance_margin_per_contract=Decimal('80000'))


def save_selection(strategy, result, path):
    from .core import StrategySpec
    from .strategies import validate_strategy
    spec = StrategySpec(**strategy)
    validate_strategy(spec)
    digest = content_hash(spec)
    if digest != result.manifest.get('spec_hash'):
        raise ValidationError('Strategy content does not match selected result')
    selection = {'strategy_hash': digest, 'strategy': to_dict(spec),
                 'result_hash': content_hash(result), 'scope': 'research_and_paper_only'}
    write_json(path, selection)
    return selection


def load_selection(path):
    from .core import StrategySpec
    from .strategies import validate_strategy
    selection = read_json(path)
    spec = StrategySpec(**selection['strategy'])
    validate_strategy(spec)
    if content_hash(spec) != selection.get('strategy_hash') or selection.get('scope') != 'research_and_paper_only':
        raise ValidationError('Invalid immutable strategy selection')
    return selection
