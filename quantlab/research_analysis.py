"""Explicit, one-call research interpretation of locally verified evidence.

This module owns no network or credentials. The desktop injects its reviewed
subscription provider. Campaigns, selection, OOS/holdout and generation budgets
are never modified. A stopped/unknown analysis is never implicitly resubmitted.
"""

from __future__ import annotations

import copy
from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .core import ValidationError, canonical_json, content_hash, to_dict
from .research import (
    _campaign_config,
    _dataset_identity,
    _evaluate_split,
    _run_bounded,
    _unique_keys,
    _validated_provider_descriptor,
    _validated_receipt_snapshot,
    PARAMETER_CONTRACTS,
    validate_dsl,
)

from .analysis_contracts import (
    VERSION,
    MAX_CANDIDATES,
    MAX_WINDOW_BARS,
    MAX_CONTEXT_BYTES,
    MAX_RECORD_BYTES,
    METRICS,
    INDICATORS,
    KINDS,
    ANALYSIS_PROMPT,
    _fail,
    _keys,
    _hash,
    _bounded,
    _number,
    validate_analysis_context,
    _validate_packet,
    validate_analysis_response,
    make_analysis_plan,
    validate_analysis_plan,
    expected_provider_descriptor,
    analysis_request,
)


def _safe_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        _fail('Absolute managed analysis path required')
    for item in (path, *path.parents):
        if item.is_symlink():
            _fail('Analysis links refused')
        if item.exists():
            info = item.stat()
            if getattr(info, 'st_file_attributes', 0) & 0x400:
                _fail('Analysis reparse points refused')
    return path


def _implementation():
    root = Path(__file__).parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('research_analysis.py', 'indicators.py')}


def _training_packet(dataset):
    # Keep operation-specific dependencies out of module startup.
    from . import indicators

    groups = {}
    for bar in dataset.bars:
        groups.setdefault(bar.contract_id, []).append(bar)
    selected = {content_hash(bar) for bar in dataset.bars[-MAX_WINDOW_BARS:]}
    rows = []
    for contract, bars in groups.items():
        closes = [bar.close for bar in bars]
        line = indicators.macd(closes)
        values = {
            'sma_20': indicators.sma(closes, period=20),
            'rsi_14': indicators.rsi(closes, period=14),
            'macd': line['macd'],
            'macd_signal': line['signal'],
            'macd_histogram': line['histogram'],
        }
        for index, bar in enumerate(bars):
            if content_hash(bar) not in selected:
                continue
            rows.append(
                {
                    'timestamp': bar.timestamp.isoformat(),
                    'end': bar.end.isoformat(),
                    'contract_id': contract,
                    **{key: str(getattr(bar, key)) for key in ('open', 'high', 'low', 'close')},
                    'volume': bar.volume,
                    'indicators': {key: None if series[index] is None else str(series[index]) for key, series in values.items()},
                }
            )
    rows.sort(key=lambda row: (row['timestamp'], row['contract_id']))
    packet = {
        'bar_count': len(dataset.bars),
        'window_count': len(rows),
        'window_policy': 'last_64_training_bars_only',
        'data_hash': content_hash(dataset.bars),
        'formula_version': indicators.FORMULA_VERSION,
        'bars': rows,
    }
    packet['evidence_id'] = content_hash(packet)
    return packet


def build_analysis_packet(*, source_campaign_dir, original_dataset, attempt_ids, task='critique', max_runtime_seconds=120, cancelled=None):
    """Recompute selected training/validation summaries; never rerun held-out data.

    The caller's worker must also enforce its normal process-tree deadline. The
    dataset must be the exact original; source paths never enter model context.
    """
    # Keep operation-specific dependencies out of module startup.
    from .saved_candidate_pool import _read_campaign, _validate_original_dataset

    folder = _safe_path(source_campaign_dir)
    if not _hash(folder.name):
        _fail('Invalid source campaign reference')
    if type(max_runtime_seconds) is not int or not 1 <= max_runtime_seconds <= 7200:
        _fail('Explicit analysis preparation runtime required')
    deadline = time.monotonic() + max_runtime_seconds

    def check():
        if cancelled is not None and cancelled():
            _fail('Analysis preparation cancelled')
        if time.monotonic() >= deadline:
            _fail('Analysis preparation deadline exceeded')

    check()
    _validate_original_dataset(original_dataset)
    state = _read_campaign(folder)
    if state.get('status') not in ('completed', 'completed_with_errors'):
        _fail('A terminal saved campaign is required')
    binding = state.get('binding')
    if not isinstance(binding, dict) or state.get('campaign_id') != content_hash(binding):
        _fail('Invalid source campaign identity')
    if binding.get('data_hash') != _dataset_identity(original_dataset) or state.get('source_manifest') != to_dict(original_dataset.manifest):
        _fail('Exact original dataset required for analysis')
    # Keep operation-specific dependencies out of module startup.
    from .configuration import config_from_json

    config = copy.deepcopy(binding['config'])
    config['backtest_config'] = config_from_json(config['backtest_config'])
    splits = _campaign_config(original_dataset, config)
    if binding.get('split_hashes') != {name: _dataset_identity(split) for name, split in splits.items()}:
        _fail('Source split bindings differ')
    if (
        type(attempt_ids) is not list
        or not 1 <= len(attempt_ids) <= MAX_CANDIDATES
        or any(not _hash(value) for value in attempt_ids)
        or len(set(attempt_ids)) != len(attempt_ids)
    ):
        _fail('Select bounded distinct saved attempts')
    attempts = state.get('attempts')
    if type(attempts) is not list or not 1 <= len(attempts) <= 15:
        _fail('Invalid source attempts')
    selected = []
    for reference in sorted(attempt_ids):
        matches = [row for row in attempts if isinstance(row, dict) and row.get('attempt_id') == reference]
        if len(matches) != 1:
            _fail('Missing or duplicate saved attempt')
        row = matches[0]
        if row.get('status') != 'evaluated':
            _fail('Selected attempt was not evaluated')
        spec = validate_dsl(row.get('spec'))
        if (
            row.get('strategy_hash') != content_hash(spec)
            or content_hash(validate_dsl(row.get('output'))) != content_hash(spec)
            or row.get('output_hash') != content_hash(row['output'])
            or set(row.get('metrics', {})) != {'train', 'validation'}
        ):
            _fail('Invalid saved strategy or split results')
        selected.append((row, spec))
    check()
    training = _run_bounded(_training_packet, (splits['train'],), deadline=deadline, config=config)['value']
    context = {'schema_version': VERSION, 'task': task, 'training': training, 'strategies': [], 'evidence': []}
    links = []
    for attempt, spec in selected:
        context['strategies'].append({'strategy_hash': content_hash(spec), 'spec': to_dict(spec)})
        for role in ('train', 'validation'):
            check()
            summary = _run_bounded(_evaluate_split, (splits[role], spec, config['backtest_config']), deadline=deadline, config=config)['value']
            stored = attempt['metrics'][role]
            if (
                type(stored) is not dict
                or stored.get('metrics') != summary['metrics']
                or stored.get('warnings') != summary['warnings']
                or not _hash(stored.get('result_hash'))
            ):
                _fail('Stored scores do not match deterministic re-evaluation')
            manifest = stored.get('manifest', {})
            for key in (
                'data_hash',
                'dataset_manifest_hash',
                'spec_hash',
                'strategy',
                'config_hash',
                'config',
                'cost_hash',
                'calendar_hash',
                'calendar_version',
            ):
                if manifest.get(key) != summary['manifest'].get(key):
                    _fail('Stored result input bindings differ')
            evidence = {
                'strategy_hash': content_hash(spec),
                'split': role,
                'data_hash': content_hash(splits[role].bars),
                'config_hash': content_hash(config['backtest_config']),
                'metrics': {key: summary['metrics'].get(key) for key in METRICS},
            }
            evidence['evidence_id'] = content_hash(evidence)
            context['evidence'].append(evidence)
            links.append(
                {
                    'evidence_id': evidence['evidence_id'],
                    'attempt_id': attempt['attempt_id'],
                    'parent_id': attempt.get('parent_id'),
                    'stored_result_hash': stored['result_hash'],
                    'recomputed_result_hash': summary['result_hash'],
                    'recomputed_engine_hash': summary['manifest']['engine_hash'],
                }
            )
    validate_analysis_context(context)
    check()
    packet = {
        'schema_version': VERSION,
        'context': context,
        'provenance': {
            'campaign_ref': folder.name,
            'campaign_id': state['campaign_id'],
            'source_journal_hash': content_hash(state),
            'original_dataset_identity': _dataset_identity(original_dataset),
            'verification': 'selected_train_validation_recomputed',
            'archived_result_status': 'reference_only_unverified',
            'result_links': links,
        },
        'implementation': _implementation(),
    }
    packet['packet_hash'] = content_hash(packet)
    _validate_packet(packet)
    return packet


def _descriptor_for_plan(plan, descriptor):
    """Pure binding checks also protect offline reads, not just live admission."""
    descriptor = _validated_provider_descriptor(descriptor)
    expected = expected_provider_descriptor(plan)
    # Canonical serialization distinguishes booleans from integers.
    if canonical_json(descriptor) != canonical_json(expected):
        _fail('Analysis provider differs from approved preview')
    return descriptor


def _provider(plan, provider):
    descriptor = _descriptor_for_plan(plan, provider.provider_descriptor())
    if Path(provider.path).name != 'chatgpt-analysis-' + plan['analysis_id'] + '.sqlite3':
        _fail('Analysis control ledger identity differs')
    return descriptor


def _snapshot(provider, descriptor):
    snapshot = provider.read_receipt_snapshot()
    _validated_receipt_snapshot(snapshot, descriptor)
    return snapshot


def _folder(root, identity):
    if not _hash(identity):
        _fail('Invalid analysis reference')
    return _safe_path(_safe_path(root) / identity)


def _read_journal(folder):
    journal = _safe_path(folder / 'analysis.sqlite3')
    if not journal.is_file():
        _fail('Missing saved analysis evidence')
    if journal.stat().st_size > 2 * MAX_RECORD_BYTES:
        _fail('Analysis journal size limit')
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=0)) as db:
        # Keep operation-specific dependencies out of module startup.
        from .saved_candidate_pool import _prepare_bounded_read

        _prepare_bounded_read(db, {'state': [('id', 'INTEGER', 0, None, 1, 0), ('payload', 'TEXT', 1, None, 0, 0)]})
        size = db.execute('SELECT id, length(CAST(payload AS BLOB)) FROM state').fetchmany(2)
        if len(size) != 1 or size[0][0] != 1 or not 1 <= size[0][1] <= MAX_RECORD_BYTES:
            _fail('Invalid analysis journal')
        text = db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
    value = json.loads(text, object_pairs_hook=_unique_keys)
    _validate_record(value)
    if value['plan']['analysis_id'] != folder.name:
        _fail('Analysis directory identity mismatch')
    return value


def _read_projection(folder):
    projection = _safe_path(folder / 'analysis.json')
    if not projection.is_file():
        _fail('Missing saved analysis evidence')
    if projection.stat().st_size > MAX_RECORD_BYTES:
        _fail('Analysis export size limit')
    with projection.open('rb') as source:
        raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        _fail('Analysis export size limit')
    return json.loads(raw, object_pairs_hook=_unique_keys)


def _read(folder):
    value = _read_journal(folder)
    if canonical_json(value) != canonical_json(_read_projection(folder)):
        _fail('Analysis journal/export mismatch')
    return value


def _read_analysis_journal(output_root, analysis_id):
    # Internal desktop provider preparation only. Not a replacement for strict
    # saved reads; reconciliation rereads this evidence under its own lock.
    return _read_journal(_folder(output_root, analysis_id))


def _validate_record(record):
    _bounded(record)
    _keys(record, ('schema_version', 'plan', 'provider_descriptor', 'status', 'response', 'response_hash', 'receipt_snapshot', 'real_model_status'))
    if type(record['schema_version']) is not int or record['schema_version'] != VERSION or record['status'] not in ('running', 'completed', 'blocked'):
        _fail('Invalid analysis record state')
    validate_analysis_plan(record['plan'])
    descriptor = _descriptor_for_plan(record['plan'], record['provider_descriptor'])
    receipts = _validated_receipt_snapshot(record['receipt_snapshot'], descriptor)
    if len(receipts) > 1 or record['real_model_status'] != 'not_verified':
        _fail('Invalid analysis receipt claim')
    if record['status'] == 'completed':
        validate_analysis_response(record['response'], record['plan']['binding']['packet']['context'])
        request = analysis_request(record['plan'])
        if (
            record['response_hash'] != content_hash(record['response'])
            or len(receipts) != 1
            or receipts[0]['status'] != 'completed'
            or receipts[0]['response_hash'] != record['response_hash']
            or receipts[0]['request_hash'] != content_hash(request)
            or receipts[0]['request_bytes'] != len(canonical_json(request).encode('utf-8'))
        ):
            _fail('Analysis response lacks matching completed receipt')
    elif record['response'] is not None or record['response_hash'] is not None:
        _fail('Incomplete analysis cannot publish output')


def _save(folder, record):
    _validate_record(record)
    text = canonical_json(record)
    journal = _safe_path(folder / 'analysis.sqlite3')
    with closing(sqlite3.connect(journal.as_uri() + '?mode=rwc', uri=True, timeout=0)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (text,))
    _write_projection(folder, text)


def _write_projection(folder, text):
    temporary = _safe_path(folder / 'analysis.json.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(_safe_path(folder / 'analysis.json'))


def read_analysis(output_root, analysis_id):
    """Offline saved-artifact read; it grants no authority to submit/retry a call."""
    record = _read(_folder(output_root, analysis_id))
    if record['plan']['analysis_id'] != analysis_id:
        _fail('Analysis directory identity mismatch')
    return record


def run_analysis(*, output_root, plan, provider, expected_analysis_id, user_confirmed=False, cancelled=None):
    """Use one independent durable provider budget; never mutate a source campaign.

    Host must rebuild the packet from source refs and compare this preview identity
    immediately before invoking. Cancellation must retain normal subtree controls.
    """
    plan = validate_analysis_plan(plan)
    if expected_analysis_id != plan['analysis_id']:
        _fail('Analysis inputs changed after preview')
    descriptor = _provider(plan, provider)
    folder = _folder(output_root, plan['analysis_id'])
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_path(folder / 'analysis.lock.sqlite3')
    with closing(sqlite3.connect(lock_path.as_uri() + '?mode=rwc', uri=True, timeout=0)) as lock:
        try:
            lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:
            _fail('Analysis is already running')
        snapshot = _snapshot(provider, descriptor)
        journal = folder / 'analysis.sqlite3'
        if journal.exists() or (folder / 'analysis.json').exists():
            record = read_analysis(output_root, plan['analysis_id'])
            if record['plan'] != plan or record['provider_descriptor'] != descriptor:
                _fail('Existing analysis controls are immutable')
            if record['status'] == 'completed':
                if record['receipt_snapshot'] != snapshot:
                    _fail('Saved analysis/control receipt mismatch')
                return {'record': record, 'cache_hit': True}
            _fail('Analysis interrupted or blocked; no implicit retry')
        if snapshot['receipts']:
            _fail('Analysis output missing after a consumed reservation; no resubmission')
        if (
            user_confirmed is not True
            or getattr(provider, 'network_opt_in', False) is not True
            or getattr(provider, 'included_usage_policy_confirmed', False) is not True
        ):
            _fail('Explicit one-call analysis authorization required')
        if cancelled is not None and cancelled():
            _fail('Analysis cancelled before submission')
        if plan['binding']['packet']['implementation'] != _implementation():
            _fail('Analysis preparation implementation changed; rebuild the preview')
        request = analysis_request(plan)
        if len(canonical_json(request).encode('utf-8')) > descriptor['max_request_bytes']:
            _fail('Analysis request byte limit')
        provider.analysis_preflight()  # Local-only: paused accounts must not consume an analysis task.
        record = {
            'schema_version': VERSION,
            'plan': copy.deepcopy(plan),
            'provider_descriptor': descriptor,
            'status': 'running',
            'response': None,
            'response_hash': None,
            'receipt_snapshot': snapshot,
            'real_model_status': 'not_verified',
        }
        _save(folder, record)
        try:
            response = provider.analyze(plan['binding']['packet']['context'], cancelled=cancelled)
            response = validate_analysis_response(response, plan['binding']['packet']['context'])
            record.update(status='completed', response=response, response_hash=content_hash(response), receipt_snapshot=_snapshot(provider, descriptor))
            _save(folder, record)
            return {'record': record, 'cache_hit': False}
        except BaseException:
            record.update(status='blocked', response=None, response_hash=None)
            try:
                record['receipt_snapshot'] = _snapshot(provider, descriptor)
                _save(folder, record)
            except Exception:
                pass  # Preserve running evidence; never mask/reset the durable ledger.
            raise


def reconcile_analysis(*, output_root, analysis_id, provider, descendants_stopped=False, recovery=None):
    # Installation admission precedes the analysis lock and spans the final
    # write, so a concurrent restore cannot invalidate a just-checked epoch.
    if recovery is not None:
        if not isinstance(recovery, tuple) or len(recovery) != 2:
            _fail('Invalid durable analysis recovery reference')
        # Keep operation-specific dependencies out of module startup.
        from .analysis_recovery import admission, supports_durable_recovery

        if not supports_durable_recovery():
            _fail('Durable analysis recovery requires the original Windows installation')
        with admission(recovery[0]):
            return _reconcile_analysis(
                output_root=output_root, analysis_id=analysis_id, provider=provider, descendants_stopped=descendants_stopped, recovery=recovery
            )
    return _reconcile_analysis(output_root=output_root, analysis_id=analysis_id, provider=provider, descendants_stopped=descendants_stopped)


def _reconcile_analysis(*, output_root, analysis_id, provider, descendants_stopped=False, recovery=None):
    """Local-only repair using original live-host proof or exact durable stop evidence."""
    if descendants_stopped is not True and recovery is None:
        _fail('Analysis descendants must be stopped')
    if recovery is not None:
        # Keep operation-specific dependencies out of module startup.
        from .analysis_recovery import supports_durable_recovery

        if not supports_durable_recovery():
            _fail('Durable analysis recovery requires the original Windows installation')
        if not isinstance(recovery, tuple) or len(recovery) != 2:
            _fail('Invalid durable analysis recovery reference')
        paths, launch_id = recovery
        if Path(output_root) != paths.state / 'analyses':
            _fail('Original recovery workspace differs')
    folder = _folder(output_root, analysis_id)
    lock_path = _safe_path(folder / 'analysis.lock.sqlite3')
    if not lock_path.is_file():
        _fail('Missing analysis lock evidence')
    with closing(sqlite3.connect(lock_path.as_uri() + '?mode=rw', uri=True, timeout=0)) as lock:
        try:
            lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:
            _fail('Analysis is still running')
        record = _read_analysis_journal(output_root, analysis_id)
        if recovery is not None:
            # Keep operation-specific dependencies out of module startup.
            from .analysis_recovery import validate_stop_receipt

            launch = validate_stop_receipt(paths, launch_id, record=record)
            if launch['analysis_id'] != analysis_id:
                _fail('Original recovery analysis differs')
        descriptor = _provider(record['plan'], provider)
        if descriptor != record['provider_descriptor']:
            _fail('Original analysis provider required')
        snapshot = _snapshot(provider, descriptor)
        # A terminal journal must match the original durable provider ledger.
        # Never repair restored/forged evidence or reset a consumed reservation.
        if record['status'] != 'running' and record['receipt_snapshot'] != snapshot:
            _fail('Saved analysis/control receipt mismatch')
        if record['status'] == 'running' and record['receipt_snapshot']['receipts']:
            _fail('Invalid initial analysis receipts')
        if snapshot['receipts']:
            request = analysis_request(record['plan'])
            if (
                len(snapshot['receipts']) != 1
                or snapshot['receipts'][0]['request_hash'] != content_hash(request)
                or snapshot['receipts'][0]['request_bytes'] != len(canonical_json(request).encode('utf-8'))
            ):
                _fail('Analysis recovery receipt request mismatch')
        projection = _safe_path(folder / 'analysis.json')
        if projection.exists():
            exported = _read_projection(folder)
            if canonical_json(exported) != canonical_json(record):
                # Only the exact initial running projection can lag a terminal
                # commit. A corrupt or altered export is not a crash checkpoint.
                initial = copy.deepcopy(record)
                initial.update(status='running', response=None, response_hash=None, receipt_snapshot={**record['receipt_snapshot'], 'receipts': []})
                if canonical_json(exported) != canonical_json(initial):
                    _fail('Analysis journal/export mismatch')
        if record['status'] == 'running':
            record.update(status='blocked', receipt_snapshot=snapshot)
            _save(folder, record)
        else:
            _write_projection(folder, canonical_json(record))
        return record
