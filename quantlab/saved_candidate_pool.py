"""Read-only admission of one explicitly audited, immutable saved candidate pool.

Local consistency checks are not cryptographic authenticity, model verification,
independent market evidence, or a profitability claim. No provider is called and
no source score is returned to the walk-forward selector.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath, PureWindowsPath
from functools import wraps
from urllib.parse import urlsplit
from decimal import localcontext

from .core import (Bar, Dataset, StrategySpec, ValidationError, canonical_json,
                   content_hash, freeze, to_dict, validate_utc)
from .data import parse_timestamp, validate_dataset
from .research import (_campaign_config, _dataset_identity, _keys, _unique_keys,
                       candidate_fingerprint, validate_dsl, PARAMETER_CONTRACTS, training_summary)

MAX_AUDIT_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BARS = 100000
# Reviewed historical producer only. Never infer compatibility from the running
# checkout, import archived code, or accept a caller-supplied producer allowlist.
AUDITED_PRODUCER = freeze({
    'protocol': 'archived_campaign_74fa33dc_v1',
    'engine_source_hashes': {
        'research.py': '74fa33dcb298fe27c9323ddf2e4b7af3b7773c7ad6c9fc668a0614b44acdfdbe',
        'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
        'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
        'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
        'backtest.py': '2548b1ebc60147d9407065000430b4013ffe93840ecdea83d19085b6e0c86d9c'},
    'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
    'result_source_hashes': {
        'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
        'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
        'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
        'backtest.py': '73c636362542a9779a5d14e7417c6a81b584923255f6b909b101323e962a1f1c'}})


CURRENT_PRODUCER = freeze({'protocol': 'mark_auto_0_2_3_campaign_v1',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': '96d8c73b52c8cf337e1837ee0cb625cc0f5367e140b3cce595141d86cbdaffdb'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'e33e2c9e07624e9180a2ccebd844f84e68d9d69923b4bcfe8cdfb8a7dab70055',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64', 'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '2bc5acf8ee545e68580a308101041a2c864406ba8cda06b4009e3bc51343e645'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '9a1bdcef73499c4bc5ff06749301e859690581685f1905f23bfc883a463a2fb6',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}]})

# Reviewed dependency-target extension, separately versioned so old snapshots
# retain their original literal profile. Target support is not native acceptance.
CURRENT_CHATGPT_PROFILE_V2 = freeze({'protocol': 'mark_auto_0_2_3_campaign_chatgpt_dependencies_v2',
 'engine_source_hashes': {'research.py': 'a5b8dda5003553261e1cd85cd4b0843b57891c878fcc72a4dcfd63893a77fc2a',
                          'provider.py': 'ef7a1027b6b375cb1189a2282ce7f8025b60e023900b620f8c198a29d89e297f',
                          'core.py': '74478947203447b16b7bd25010a01cffec02ff71129eadbfa02438b98f29c9e6',
                          'strategies.py': '7fb84c7638a744aae714463db6aebd96aebd32702feb021a550dca6f40e721b0',
                          'backtest.py': '83b423487c002a533fa5d92de4d53369380b7de8cbad0c181725363573017c91'},
 'prompt_template_hash': '31c09f395b9ca6c5ee53751fcf30131907ad513bf1708e048359421516102845',
 'result_source_hashes': {'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                          'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                          'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                          'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
 'chatgpt_plan_implementations': [{'source_sha256': {'desktop_chatgpt_auth.py': '724b5811a74d7d25a537ba98616a8d4c5c18ea7e1257fa1ce234efbad29cb040',
                                                     'desktop_chatgpt_provider.py': 'd793a8d5c632fd1f4fa98812c81bbe1b5170bcae6e2b54c4291983e429fcaac3'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': '90d3663f337b563186082c8011cbf5c9b1e34fee963ec69009a16ee7cede60d4',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64',
                                                          'linux-cp311-x86_64',
                                                          'linux-cp312-x86_64']},
                                  {'source_sha256': {'desktop_chatgpt_auth.py': '358716a763635543c44ae624222a93157f86f7dde775a21c1fe0aa7fe168bdc4',
                                                     'desktop_chatgpt_provider.py': '832431f1ddbad981f38967222c385b4641e89891ce557f19147d7f99db15e7b4'},
                                   'dependency_versions': {'PyJWT': '2.15.1',
                                                           'cryptography': '50.0.2',
                                                           'cffi': '2.1.1',
                                                           'pycparser': '3.11'},
                                   'dependency_manifest_sha256': 'c19a5cfe550b7b254cc6cf5a0b0a5813422d65492be82b7f9fb9d7ffdf7f54f3',
                                   'dependency_artifact_evidence': 'hash_locked_build_manifest',
                                   'dependency_targets': ['windows-cp311-amd64',
                                                          'windows-cp312-amd64',
                                                          'windows-cp313-amd64']}],
 'result_source_hash_variants': [{'core.py': '62363665d7c209a3cc791b872607823cdac75a8ae4c35a858f903824785ee42b',
                                  'data.py': 'bd14fce1bacd1832ddf41a705b9bcaa3fa6226a27feba31d5e240b5f481e42e4',
                                  'strategies.py': 'f4bfcf36f99d6b2e3e373dca019a86030997e382a3c42480f388347ec8490def',
                                  'backtest.py': '009f6a9c2f1a2774ab496d20fd97899815f84380233af576e84badad0f08ee02'},
                                 {'core.py': '99174ffa3e52ca940909a9e0ec91d98da801bd4fcfb4136064cbd7bfb9a5f1c9',
                                  'data.py': '7ad965d33b856e345b4c5a091b675dd6a4b9a88fc5668170184347cd382ff0fb',
                                  'strategies.py': 'c35ed80ffe11787fbc93b964cbe6403d36921fbf9ca6d6f8a282301691da6132',
                                  'backtest.py': '9e9581b178afbce5d8df9d2377f535676e4c9854c6502045c7e50883643ed575'}],
 'provider_modes': ['chatgpt_plan']})

SUPPORTED_PRODUCERS = (AUDITED_PRODUCER, CURRENT_PRODUCER, CURRENT_CHATGPT_PROFILE_V2)


@dataclass(frozen=True)
class SavedCandidatePool:
    candidate_pool: tuple[StrategySpec, ...]
    admission: dict

    def __post_init__(self):
        object.__setattr__(self, 'candidate_pool', tuple(self.candidate_pool))
        object.__setattr__(self, 'admission', freeze(self.admission))


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


class SavedCandidatePoolError(ValidationError):
    """Only a fixed public reason code should cross a redacted desktop boundary."""
    def __init__(self, message, reason_code='source_invalid_evidence'):
        super().__init__(message)
        self.reason_code = reason_code


def _fail(message):
    code = 'source_invalid_evidence'
    for fragment, reason in (
        ('strictly before', 'source_temporal_overlap'),
        ('Duplicate source candidate', 'source_duplicate_structure'),
        ('terminal completed', 'source_not_completed'),
        ('producer protocol', 'source_producer_unsupported'),
        ('Source registry', 'source_registry_mismatch'),
        ('Manual source', 'source_manual_exchange_missing'),
        ('Source provider Decimal context', 'source_provider_decimal_context_unsupported'),
        ('provider protocol implementation', 'source_provider_provenance_invalid'),
        ('provider protocol descriptor', 'source_provider_provenance_invalid'),
        ('Source provider receipt', 'source_provider_receipt_invalid'),
        ('provider protocol', 'source_provider_unsupported'),
        ('journal/export mismatch', 'source_journal_mismatch'),
        ('original dataset identity', 'source_dataset_mismatch'),
        ('Original dataset', 'source_dataset_mismatch'),
        ('original Dataset', 'source_dataset_mismatch'),
        ('No evaluated candidates', 'source_no_evaluated_candidates'),
        ('1..15', 'source_candidate_limit'),
        ('resource bounds', 'source_resource_limit'),
        ('audit byte limit', 'source_resource_limit'),
        ('Missing', 'source_missing_evidence')):
        if fragment in message:
            code = reason
            break
    raise SavedCandidatePoolError(message, code)


def _safe_boundary(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SavedCandidatePoolError:
            raise
        except (ValidationError, KeyError, TypeError, ValueError, OverflowError, RecursionError, OSError) as exc:
            raise SavedCandidatePoolError('Invalid saved source evidence') from exc
    return wrapped


def _json_load(text):
    from .walk_forward import _exact_number
    def integer(value):
        if len(value) > 20:
            _fail('Source integer exceeds resource bounds')
        result = int(value)
        if result.bit_length() > 64:
            _fail('Source integer exceeds resource bounds')
        return result
    def number(value):
        _exact_number(value)
        result = float(value)
        if not math.isfinite(result):
            _fail('Source number exceeds resource bounds')
        return result
    try:
        value = json.loads(text, object_pairs_hook=_unique_keys, parse_int=integer,
                           parse_float=number, parse_constant=lambda _: _fail('Nonfinite source JSON'))
    except (ValueError, RecursionError, TypeError) as exc:
        raise SavedCandidatePoolError('Invalid bounded source JSON') from exc
    return value


def _read_file(path):
    try:
        path = Path(path)
        if not path.is_file():
            _fail('Missing or non-regular explicit source file')
        # Keep explicitly selected regular-file symlinks valid. Nonblocking open
        # plus fstat prevents a POSIX file-to-FIFO race from hanging the read.
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                _fail('Missing or non-regular explicit source file')
            if metadata.st_size > MAX_AUDIT_BYTES:
                _fail('Source file exceeds audit byte limit')
            raw = stream.read(MAX_AUDIT_BYTES + 1)
        if len(raw) > MAX_AUDIT_BYTES:
            _fail('Source file exceeds audit byte limit')
        return _json_load(raw.decode('utf-8'))
    except (OSError, UnicodeError) as exc:
        raise SavedCandidatePoolError('Missing or unreadable explicit source file', 'source_missing_evidence') from exc


def _audit_tree(value):
    """Bound untrusted journal nesting/numerics before canonical hashing.

    Engine summaries use 34-digit Decimal arithmetic and may carry fractional
    exponents below -32. These descriptive source values are never new ranking
    inputs; retain them within a finite 128-digit/exponent audit bound.
    """
    def source_number(value):
        parsed = Decimal(str(value))
        parts = parsed.as_tuple()
        if (not parsed.is_finite() or abs(parts.exponent) > 128 or len(parts.digits) > 128
            or parsed.copy_abs() > Decimal('1e15')):
            _fail('Source numeric value exceeds resource bounds')
    count = 0
    def visit(item, depth=0):
        nonlocal count
        count += 1
        if count > 500000 or depth > 32:
            _fail('Source journal structure exceeds resource bounds')
        if type(item) is dict:
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > 16384:
                _fail('Source journal string exceeds resource bounds')
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', item):
                source_number(item)
        elif type(item) in (int, float):
            source_number(item)
        elif item is not None and type(item) is not bool:
            _fail('Invalid source journal value')
    visit(value)


def _validate_original_dataset(dataset):
    from .walk_forward import _bounded_value, _bounded_number
    if not isinstance(dataset, Dataset) or not 1 <= len(dataset.bars) <= MAX_SOURCE_BARS:
        _fail('Exact original Dataset within bar bounds required')
    _bounded_value(dataset.manifest)
    _bounded_value(dataset.quality)
    byte_count = 0
    for bar in dataset.bars:
        for number in (bar.open, bar.high, bar.low, bar.close):
            _bounded_number(number)
        if type(bar.volume) is not int or bar.volume.bit_length() > 64:
            _fail('Original bar volume exceeds resource bounds')
        if type(bar.source_id) is not str or len(bar.source_id) > 4096:
            _fail('Original bar source exceeds resource bounds')
        byte_count += len(bar.source_id.encode('utf-8'))
        if byte_count > 16777216:
            _fail('Original source identifiers exceed resource bounds')
        bar.__post_init__()
    validate_dataset(dataset)
    if dataset.quality.get('missing_intervals', 0):
        _fail('Original source has missing intervals')
    if any(a.end > b.timestamp for a, b in zip(dataset.bars, dataset.bars[1:])):
        _fail('Original source events are nonchronological or overlapping')


@_safe_boundary
def load_original_dataset(path: Path) -> Dataset:
    """Load only the explicitly selected local dataset, bounding BEFORE hashing.

    This does not follow any filename or URL found in a campaign manifest.
    """
    from .walk_forward import _bounded_value, _exact_number
    envelope = _read_file(path)
    _keys(envelope, ('kind', 'sha256', 'payload'))
    if envelope['kind'] != 'quantlab_dataset_v1' or not _hash(envelope['sha256']):
        _fail('Expected exact original quantlab_dataset_v1 envelope')
    payload = envelope['payload']
    _keys(payload, ('bars', 'manifest', 'quality'))
    if type(payload['bars']) is not list or not 1 <= len(payload['bars']) <= MAX_SOURCE_BARS:
        _fail('Original dataset exceeds bar bounds')
    _bounded_value(payload['manifest'])
    _bounded_value(payload['quality'])
    bars = []
    source_bytes = 0
    try:
        for item in payload['bars']:
            _keys(item, ('timestamp', 'end', 'trade_date', 'session', 'contract_id',
                         'open', 'high', 'low', 'close', 'volume', 'source_id'))
            _bounded_value(item)
            row = dict(item)
            for key in ('open', 'high', 'low', 'close'):
                row[key] = _exact_number(row[key])
            for key in ('timestamp', 'end'):
                row[key] = parse_timestamp(row[key])
            if type(row['source_id']) is not str or len(row['source_id']) > 4096:
                _fail('Original bar source exceeds resource bounds')
            source_bytes += len(row['source_id'].encode('utf-8'))
            if source_bytes > 16777216:
                _fail('Original source identifiers exceed resource bounds')
            bars.append(Bar(**row))
        if content_hash(payload) != envelope['sha256']:
            _fail('Original dataset envelope hash mismatch')
        dataset = Dataset(tuple(bars), payload['manifest'], payload['quality'])
        _validate_original_dataset(dataset)
        return dataset
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise SavedCandidatePoolError('Invalid bounded original dataset', 'source_dataset_mismatch') from exc


def _prepare_bounded_read(db, tables):
    """Known real tables only; lock waits and query execution are both bounded."""
    deadline = time.monotonic() + 2
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_AUDIT_BYTES)
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    for table, expected in tables.items():
        metadata = db.execute('SELECT type, sql FROM sqlite_master WHERE name=?', (table,)).fetchmany(2)
        if (len(metadata) != 1 or metadata[0][0] != 'table' or type(metadata[0][1]) is not str
            or not metadata[0][1].lstrip().upper().startswith('CREATE TABLE')):
            _fail('Source SQLite evidence requires the audited real table schema')
        columns = db.execute('PRAGMA table_xinfo(' + table + ')').fetchmany(len(expected) + 1)
        if [tuple(row[1:]) for row in columns] != expected:
            _fail('Source SQLite evidence has unsupported table columns')
        if db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND tbl_name=? LIMIT 1',
                      ('trigger', table)).fetchone() is not None:
            _fail('Source SQLite evidence contains unaudited table triggers')


def _read_campaign(folder):
    folder = Path(folder).resolve()
    journal, export = folder / 'campaign.sqlite3', folder / 'campaign.json'
    if (not journal.is_file() or not export.is_file()
        or not journal.resolve().is_relative_to(folder) or not export.resolve().is_relative_to(folder)):
        _fail('Missing or escaping source campaign journal/export')
    try:
        with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            _prepare_bounded_read(db, {'state': [('id', 'INTEGER', 0, None, 1, 0),
                                               ('payload', 'TEXT', 1, None, 0, 0)]})
            metadata = db.execute('SELECT id, typeof(payload), length(CAST(payload AS BLOB)) FROM state').fetchmany(2)
            if len(metadata) != 1 or metadata[0][0] != 1 or metadata[0][1] != 'text' or not 0 < metadata[0][2] <= MAX_AUDIT_BYTES:
                _fail('Invalid source campaign journal or audit size')
            state = _json_load(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            exported = _read_file(export)
            _audit_tree(state)
            _audit_tree(exported)
            if canonical_json(state) != canonical_json(exported):
                _fail('Source campaign journal/export mismatch')
            return state
    except (sqlite3.Error, OSError) as exc:
        raise SavedCandidatePoolError('Unreadable authoritative source campaign journal', 'source_missing_evidence') from exc


def _check_result(result, split, spec, config, producer):
    """Check stored summary identities without evaluating or using its scores."""
    _keys(result, ('metrics', 'warnings', 'result_hash', 'manifest'))
    if not _hash(result['result_hash']) or type(result['metrics']) is not dict or type(result['warnings']) is not list:
        _fail('Invalid source split result summary')
    manifest = result['manifest']
    expected_manifest = {k: v for k, v in to_dict(split.manifest).items() if k != 'imported_at'}
    if (type(manifest) is not dict or manifest.get('schema_version') != 1
        or manifest.get('dataset_manifest') != expected_manifest
        or manifest.get('dataset_manifest_hash') != content_hash(expected_manifest)
        or manifest.get('data_hash') != split.manifest['data_hash']
        or manifest.get('spec_hash') != content_hash(spec) or manifest.get('strategy') != to_dict(spec)
        or manifest.get('config_hash') != content_hash(config) or manifest.get('config') != to_dict(config)
        or manifest.get('source_hashes') not in producer.get('result_source_hash_variants', (producer['result_source_hashes'],))
        or manifest.get('engine_hash') != content_hash(manifest.get('source_hashes'))
        or manifest.get('cost_hash') != content_hash((config.costs,) + tuple(config.cost_schedule))
        or manifest.get('source_commit') != config.source_commit or manifest.get('seed') != config.seed
        or manifest.get('source_type') != split.manifest['source_type']
        or manifest.get('calendar_hash') != split.manifest.get('calendar_hash')
        or manifest.get('calendar_version') != split.manifest.get('calendar_version')
        or manifest.get('settlement_mode') != config.settlement_mode
        or manifest.get('engine_version') != 'quantlab-event-v1'
        or type(manifest.get('schema_version')) is not int
        or not _hash(manifest.get('run_hash')) or manifest.get('reproducibility_hash') != manifest.get('run_hash')):
        _fail('Source split result manifest/binding mismatch')


@_safe_boundary
def admit_saved_campaign_pool(*, source_campaign_dir: Path, source_campaign_ref: str,
                              original_dataset: Dataset, original_dataset_ref: str,
                              first_training_timestamp: datetime,
                              authoritative_registry_path: Path | None = None) -> SavedCandidatePool:
    """Read/revalidate one audited source; return every evaluated attempt in order."""
    if not _hash(source_campaign_ref):
        _fail('Source campaign reference must be a normal 64-hex workspace reference')
    if (type(original_dataset_ref) is not str or not original_dataset_ref
        or len(original_dataset_ref) > 4096 or '\x00' in original_dataset_ref):
        _fail('Explicit local original dataset reference required')
    if Path(source_campaign_dir).name != source_campaign_ref:
        _fail('Source campaign directory does not match workspace reference')
    validate_utc(first_training_timestamp)
    _validate_original_dataset(original_dataset)
    first_event = min(bar.timestamp for bar in original_dataset.bars)
    last_event = max(bar.end for bar in original_dataset.bars)
    if last_event >= first_training_timestamp:
        _fail('Every original source event end must be strictly before new first training timestamp')
    state = _read_campaign(source_campaign_dir)
    try:
        _keys(state, ('campaign_id', 'binding', 'status', 'source_manifest', 'attempts', 'selected',
                      'evaluations', 'holdout_consumed', 'holdout_status', 'elapsed_seconds',
                      'real_model_status', 'provider_receipts', 'resource_enforcement', 'warnings', 'selection_hash'),
              ('holdout_registry', 'holdout_selection_hash'))
        binding = state['binding']
        _keys(binding, ('config', 'data_hash', 'split_hashes', 'provider', 'prompt_template_hash', 'engine_source_hashes'))
        producer = _select_producer(binding)
        current_schema = producer['protocol'] != AUDITED_PRODUCER['protocol']
        if state['status'] != 'completed':
            _fail('Source campaign must be terminal completed')
        if (state['campaign_id'] != content_hash(binding)
            or state['selection_hash'] != content_hash(state['selected'])):
            _fail('Source campaign/selection identity mismatch')
        if (binding['data_hash'] != _dataset_identity(original_dataset)
            or state['source_manifest'] != to_dict(original_dataset.manifest)):
            _fail('Exact original dataset identity/source manifest mismatch')
        if state['real_model_status'] != 'not_verified':
            _fail('Original real_model_status is inconsistent with the audited producer')
        provider = binding['provider']
        _validate_provider(provider, current_schema=current_schema)
        from .__main__ import config_from_json
        from .walk_forward import _bounded_value
        _bounded_value(binding['config'])
        config = dict(binding['config'])
        config['backtest_config'] = config_from_json(config['backtest_config'])
        splits = _campaign_config(original_dataset, config)
        if binding['split_hashes'] != {name: _dataset_identity(split) for name, split in splits.items()}:
            _fail('Original dataset split identity mismatch')
        attempts = state['attempts']
        if type(attempts) is not list or not 1 <= len(attempts) <= min(15, config['max_trials']):
            _fail('Source must contain 1..15 bounded attempts')
        schedule = [(family, iteration) for iteration in range(config['max_improvements'] + 1) for family in config['families']]
        previous, seen, pool, provenance, by_id = {}, {}, [], [], {}
        for index, attempt in enumerate(attempts, 1):
            _keys(attempt, ('attempt_id', 'sequence', 'parent_id', 'family', 'iteration', 'status',
                            'provider', 'prompt_template_hash', 'split_hashes', 'output', 'output_hash',
                            'strategy_hash', 'metrics', 'cost', 'elapsed_seconds', 'warnings'),
                  ('spec', 'generator_context') + (('candidate_fingerprint', 'duplicate_of') if current_schema else ()))
            family, iteration = schedule[index - 1]
            if (type(attempt['sequence']) is not int or attempt['sequence'] != index
                or type(attempt['iteration']) is not int or (attempt['family'], attempt['iteration']) != (family, iteration)
                or attempt['attempt_id'] != content_hash([state['campaign_id'], index])
                or attempt['parent_id'] != previous.get(family)
                or attempt['provider'] != provider or attempt['prompt_template_hash'] != binding['prompt_template_hash']
                or attempt['split_hashes'] != {k: binding['split_hashes'][k] for k in ('train', 'validation')}
                or attempt['status'] not in ('evaluated', 'rejected', 'failed', 'timed_out')):
                _fail('Invalid source attempt sequence, parent, status or provenance')
            parent = by_id.get(previous.get(family))
            expected_context = {
                'family': family, 'iteration': iteration, 'seed': config['seed'],
                'parameter_contract': PARAMETER_CONTRACTS[family],
                'training': training_summary(splits['train']),
                'validation': {'bar_count': len(splits['validation'].bars), 'hash': content_hash(splits['validation'].bars)},
                'previous': {'output': parent['output'], 'metrics': {k: v['metrics'] for k, v in parent['metrics'].items()},
                             'status': parent['status']} if parent else None}
            if attempt.get('generator_context') != expected_context:
                _fail('Source generation context disagrees with exact prior source splits/attempt')
            previous[family] = attempt['attempt_id']
            by_id[attempt['attempt_id']] = attempt
            output = attempt['output']
            if ((attempt['output_hash'] is None and output is not None)
                or (attempt['output_hash'] is not None and attempt['output_hash'] != content_hash(output))):
                _fail('Source attempt output hash mismatch')
            spec = None
            explicit_duplicate = False
            if 'spec' in attempt or attempt['status'] == 'evaluated':
                _bounded_value(output)
                spec = validate_dsl(output)
                if (to_dict(spec) != attempt.get('spec') or spec.family != family
                    or attempt['strategy_hash'] != content_hash(spec)):
                    _fail('Source original output/validated spec/strategy hash mismatch')
                fingerprint = candidate_fingerprint(spec)
                if current_schema and attempt.get('candidate_fingerprint') != fingerprint:
                    _fail('Source candidate fingerprint disagrees with validated behavior')
                if fingerprint in seen:
                    explicit_duplicate = (current_schema and attempt['status'] == 'rejected'
                        and attempt.get('duplicate_of') == seen[fingerprint]
                        and 'duplicate_candidate_not_retested' in attempt['warnings']
                        and attempt['metrics'] == {})
                    if not explicit_duplicate:
                        _fail('Duplicate source candidate behavioral structure is ambiguous')
                elif 'duplicate_of' in attempt:
                    _fail('Source duplicate rejection does not match an earlier candidate')
                else:
                    seen[fingerprint] = attempt['attempt_id']
            elif attempt['strategy_hash'] is not None or 'candidate_fingerprint' in attempt or 'duplicate_of' in attempt:
                _fail('Source strategy hash has no validated spec')
            if type(attempt['metrics']) is not dict or set(attempt['metrics']) - {'train', 'validation'}:
                _fail('Invalid source attempt split metrics')
            if attempt['status'] == 'evaluated' and set(attempt['metrics']) != {'train', 'validation'}:
                _fail('Evaluated source attempt is missing split results')
            for role, summary in attempt['metrics'].items():
                if spec is None:
                    _fail('Source split result has no validated spec')
                _check_result(summary, splits[role], spec, config['backtest_config'], producer)
            admitted = attempt['status'] == 'evaluated'
            row = {'attempt_id': attempt['attempt_id'], 'sequence': index, 'parent_id': attempt['parent_id'],
                   'family': family, 'iteration': iteration, 'source_status': attempt['status'],
                   'output_hash': attempt['output_hash'], 'strategy_hash': attempt['strategy_hash'],
                   'attempt_hash': content_hash(attempt), 'admitted': admitted,
                   'reason': ('evaluated_validated_candidate' if admitted else 'source_duplicate_rejected'
                              if explicit_duplicate else 'excluded_source_attempt_' + attempt['status'])}
            if explicit_duplicate:
                row['duplicate_of'] = attempt['duplicate_of']
            if spec is not None:
                row['behavioral_fingerprint'] = candidate_fingerprint(spec)
            if admitted:
                row['pool_index'] = len(pool)
                pool.append(spec)
            provenance.append(row)
        if not pool:
            _fail('No evaluated candidates remain in the saved source')
        if len(pool) > 15 or any(count > 3 for count in Counter(spec.family for spec in pool).values()):
            _fail('Saved pool requires 1..15 evaluated candidates and at most 3 per family')
        if provider['mode'] == 'chatgpt_plan':
            _validate_chatgpt_provider(provider, state, producer)
        else:
            _validate_legacy_receipts(provider, state, current_schema=current_schema)
        selected = state['selected']
        if type(selected) is not list or len(selected) > len(config['families']):
            _fail('Invalid source selection evidence')
        selected_families = []
        for candidate in selected:
            _keys(candidate, ('attempt_id', 'strategy_hash', 'spec', 'validation'))
            attempt = by_id.get(candidate['attempt_id'])
            if (attempt is None or attempt['status'] != 'evaluated'
                or any(candidate[key] != attempt[key] for key in ('strategy_hash', 'spec'))
                or candidate['validation'] != attempt['metrics']['validation']):
                _fail('Source selection does not match its evaluated attempt')
            selected_families.append(attempt['family'])
        if selected_families != [family for family in config['families'] if family in selected_families]:
            _fail('Duplicate or unordered source selection')
        _keys(state['evaluations'], ('oos', 'holdout'))
        for role in ('oos', 'holdout'):
            records = state['evaluations'][role]
            if type(records) is not list or len(records) != len(selected):
                _fail('Incomplete source forward evaluation evidence')
            for record, candidate in zip(records, selected):
                _keys(record, ('strategy_hash', 'status', 'metrics', 'warnings', 'result_hash', 'manifest'))
                if record['status'] != 'evaluated' or record['strategy_hash'] != candidate['strategy_hash']:
                    _fail('Invalid source forward evaluation identity')
                _check_result({k: v for k, v in record.items() if k not in ('strategy_hash', 'status')},
                              splits[role], validate_dsl(candidate['spec']), config['backtest_config'], producer)
        if selected:
            if (state['holdout_consumed'] is not True or state['holdout_status'] != 'reserved_consumed'
                or state.get('holdout_selection_hash') != state['selection_hash']
                or type(state.get('holdout_registry')) is not dict
                or state['holdout_registry'].get('status') != 'reserved_consumed'
                or state['holdout_registry'].get('holdout_hash') != content_hash(splits['holdout'].bars)):
                _fail('Invalid source consumed holdout evidence')
        elif (state['holdout_consumed'] is not False or state['holdout_status'] != 'not_accessed'
              or 'holdout_registry' in state or 'holdout_selection_hash' in state):
            _fail('Unexpected source holdout evidence')
        registry_identity = _validate_source_registry(state, splits['holdout'], authoritative_registry_path)
        snapshot = {'schema_version': 1, 'pool_origin': 'saved_campaign_pool',
            'source_campaign_ref': source_campaign_ref, 'source_campaign_id': state['campaign_id'],
            'source_journal_hash': content_hash(state), 'source_selection_hash': state['selection_hash'],
            'original_dataset_ref': original_dataset_ref, 'original_dataset_identity': binding['data_hash'],
            'original_data_hash': original_dataset.manifest['data_hash'],
            'original_manifest_hash': content_hash(state['source_manifest']),
            'source_event_bounds': {'first_timestamp': first_event, 'last_end': last_event},
            'first_training_timestamp': first_training_timestamp,
            'source_split_hashes': binding['split_hashes'], 'source_registry_identity': registry_identity,
            'producer': dict(producer),
            'provider_binding_hash': content_hash(provider), 'provider_mode': provider['mode'], 'real_model_status': state['real_model_status'],
            'attempts': provenance, 'candidate_pool_hash': content_hash(pool),
            'candidate_count': len(pool), 'model_calls': 0,
            'provenance_status': 'local_artifact_consistency_and_event_bounds_verified'}
        snapshot = to_dict(snapshot)
        snapshot['snapshot_hash'] = content_hash(snapshot)
        return SavedCandidatePool(tuple(pool), snapshot)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, SavedCandidatePoolError):
            raise
        raise SavedCandidatePoolError('Invalid source campaign schema/invariants') from exc


def _validate_provider(provider, *, current_schema=False):
    """Only the audited fixture and compatible-provider protocols are supported."""
    if type(provider) is not dict:
        _fail('Unsupported source provider protocol')
    if provider.get('mode') == 'fixture':
        _keys(provider, ('mode', 'model', 'endpoint'))
        if provider['model'] is not None or provider['endpoint'] is not None:
            _fail('Unsupported source provider protocol')
    elif provider.get('mode') in ('manual', 'manual_unverified'):
        _fail('Manual source lacks persisted sealed exchange package and audited implementation evidence')
    elif provider.get('mode') == 'chatgpt_plan' and current_schema:
        # Full pure-data descriptor/receipt validation follows attempt validation.
        try:
            _keys(provider, ('mode', 'model', 'endpoint', 'descriptor'))
        except ValidationError as exc:
            raise SavedCandidatePoolError('Unsupported source provider descriptor', 'source_provider_provenance_invalid') from exc
    elif provider.get('mode') == 'openai_compatible':
        _keys(provider, ('mode', 'model', 'endpoint', 'limits', 'network_opt_in', 'transport_type'), ('output_mode',))
        if (provider.get('output_mode', 'json_object') not in ('json_object', 'registry_json_schema')
            or provider['network_opt_in'] is not True
            or any(type(provider[name]) is not str or not provider[name] for name in ('model', 'endpoint', 'transport_type'))):
            _fail('Unsupported source provider protocol')
        endpoint = provider['endpoint']
        try:
            parsed = urlsplit(endpoint)
            invalid = (not endpoint.startswith(('https://', 'http://127.0.0.1:', 'http://localhost:', 'http://[::1]:'))
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or '?' in endpoint or '#' in endpoint
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint) or parsed.port == 0)
        except ValueError:
            invalid = True
        if invalid:
            _fail('Unsupported source provider protocol endpoint')
        _keys(provider['limits'], ('calls', 'tokens', 'spend', 'rate', 'tokens_per_call', 'timeout'))
        from .walk_forward import _exact_number
        for key, low, high in (('calls', 0, 100), ('tokens', 0, 1000000),
                               ('tokens_per_call', 1, 32768), ('timeout', 1, 120)):
            if type(provider['limits'][key]) is not int or not low <= provider['limits'][key] <= high:
                _fail('Unsupported source provider protocol')
        if _exact_number(provider['limits']['spend']) < 0 or _exact_number(provider['limits']['rate']) < 0:
            _fail('Unsupported source provider protocol')
        # The audited protocols do not persist the inherited Decimal context.
        # Do not guess default precision/rounding or admit plausible charges.
        if _exact_number(provider['limits']['rate']) != 0:
            _fail('Source provider Decimal context is not recorded for nonzero-rate receipts')
    else:
        _fail('Unsupported source provider protocol')


def validate_admission_snapshot(snapshot, pool):
    """Validate immutable plan shape only; launch still must re-admit real inputs."""
    if not isinstance(snapshot, dict):
        _fail('Saved pool needs an immutable admission snapshot')
    required = ('schema_version', 'pool_origin', 'source_campaign_ref', 'source_campaign_id',
                'source_journal_hash', 'source_selection_hash', 'original_dataset_ref',
                'original_dataset_identity', 'original_data_hash', 'original_manifest_hash',
                'source_event_bounds', 'first_training_timestamp', 'source_split_hashes', 'source_registry_identity', 'producer',
                'provider_binding_hash', 'provider_mode', 'real_model_status', 'attempts',
                'candidate_pool_hash', 'candidate_count', 'model_calls', 'provenance_status', 'snapshot_hash')
    _keys(dict(snapshot), required)
    if (type(snapshot['schema_version']) is not int or snapshot['schema_version'] != 1
        or snapshot['pool_origin'] != 'saved_campaign_pool' or snapshot['producer'] not in SUPPORTED_PRODUCERS
        or snapshot['real_model_status'] != 'not_verified'
        or snapshot['provider_mode'] not in ('fixture', 'openai_compatible', 'chatgpt_plan')
        or (snapshot['provider_mode'] == 'chatgpt_plan' and snapshot['producer']['protocol'] == AUDITED_PRODUCER['protocol'])
        or snapshot['provider_mode'] not in snapshot['producer'].get('provider_modes', ('fixture', 'openai_compatible', 'chatgpt_plan'))
        or type(snapshot['model_calls']) is not int or snapshot['model_calls'] != 0
        or snapshot['provenance_status'] != 'local_artifact_consistency_and_event_bounds_verified'
        or not 1 <= len(pool) <= 15 or type(snapshot['candidate_count']) is not int
        or snapshot['candidate_count'] != len(pool) or snapshot['candidate_pool_hash'] != content_hash(pool)
        or snapshot['snapshot_hash'] != content_hash({k: v for k, v in snapshot.items() if k != 'snapshot_hash'})):
        _fail('Invalid saved pool admission snapshot identity')
    for key in ('source_campaign_ref', 'source_campaign_id', 'source_journal_hash', 'source_selection_hash',
                'original_dataset_identity', 'original_data_hash', 'original_manifest_hash',
                'provider_binding_hash', 'candidate_pool_hash', 'snapshot_hash'):
        if not _hash(snapshot[key]):
            _fail('Invalid saved pool admission identity hash')
    if any(count > 3 for count in Counter(spec.family for spec in pool).values()):
        _fail('Saved pool permits at most 3 candidates per family')
    fingerprints = [candidate_fingerprint(spec) for spec in pool]
    if len(set(fingerprints)) != len(fingerprints):
        _fail('Duplicate source candidate behavioral structure is ambiguous')
    attempts = snapshot['attempts']
    if not isinstance(attempts, (tuple, list)) or not len(pool) <= len(attempts) <= 15:
        _fail('Invalid saved pool attempt provenance')
    admitted = [row for row in attempts if row.get('admitted') is True]
    if len(admitted) != len(pool):
        _fail('Saved pool admission count mismatch')
    for index, row in enumerate(admitted):
        if (type(row.get('pool_index')) is not int or row['pool_index'] != index
            or row.get('family') != pool[index].family or row.get('source_status') != 'evaluated'
            or row.get('strategy_hash') != content_hash(pool[index])
            or row.get('behavioral_fingerprint') != fingerprints[index]):
            _fail('Saved pool order/provenance mismatch')

    identity = snapshot['source_registry_identity']
    _keys(dict(identity), ('resolved_path', 'reservation_id', 'agreement_policy'))
    if (identity['agreement_policy'] != 'persisted_source_reservation_matches_selected_authority'
        or not _hash(identity['reservation_id'])
        or type(identity['resolved_path']) is not str or not identity['resolved_path']
        or len(identity['resolved_path']) > 4096 or '\x00' in identity['resolved_path']
        or not (PurePosixPath(identity['resolved_path']).is_absolute()
                or PureWindowsPath(identity['resolved_path']).is_absolute())):
        _fail('Source registry snapshot identity is invalid')
    _keys(dict(snapshot['source_split_hashes']), ('train', 'validation', 'oos', 'holdout'))
    if any(not _hash(value) for value in snapshot['source_split_hashes'].values()):
        _fail('Invalid source split provenance hash')
    bounds = snapshot['source_event_bounds']
    _keys(dict(bounds), ('first_timestamp', 'last_end'))
    if not (parse_timestamp(bounds['first_timestamp']) < parse_timestamp(bounds['last_end'])
            < parse_timestamp(snapshot['first_training_timestamp'])):
        _fail('Every original source event end must be strictly before new first training timestamp')
    if (type(snapshot['original_dataset_ref']) is not str or not snapshot['original_dataset_ref']
        or len(snapshot['original_dataset_ref']) > 4096 or '\x00' in snapshot['original_dataset_ref']):
        _fail('Invalid original dataset reference')
    previous = {}
    for sequence, row in enumerate(attempts, 1):
        _keys(dict(row), ('attempt_id', 'sequence', 'parent_id', 'family', 'iteration', 'source_status',
                         'output_hash', 'strategy_hash', 'attempt_hash', 'admitted', 'reason'),
              ('pool_index', 'behavioral_fingerprint', 'duplicate_of'))
        if (type(row['sequence']) is not int or row['sequence'] != sequence
            or row['attempt_id'] != content_hash([snapshot['source_campaign_id'], sequence])
            or row['parent_id'] != previous.get(row['family'])
            or type(row['iteration']) is not int or not 0 <= row['iteration'] <= 2
            or row['source_status'] not in ('evaluated', 'failed', 'rejected', 'timed_out')
            or type(row['admitted']) is not bool or row['admitted'] != (row['source_status'] == 'evaluated')
            or row['reason'] != ('evaluated_validated_candidate' if row['admitted'] else 'source_duplicate_rejected'
                                if 'duplicate_of' in row else 'excluded_source_attempt_' + row['source_status'])
            or (not row['admitted'] and 'pool_index' in row)
            or not _hash(row['attempt_hash'])
            or any(value is not None and not _hash(value) for value in (row['output_hash'], row['strategy_hash']))):
            _fail('Invalid source attempt admission provenance')
        if 'duplicate_of' in row:
            if (snapshot['producer']['protocol'] == AUDITED_PRODUCER['protocol']
                or row['source_status'] != 'rejected' or row['admitted'] is not False
                or not any(prior['attempt_id'] == row['duplicate_of']
                           and prior.get('behavioral_fingerprint') == row.get('behavioral_fingerprint')
                           for prior in attempts[:sequence - 1])):
                _fail('Invalid explicitly excluded source duplicate')
        previous[row['family']] = row['attempt_id']


def _lexical_registry_path(value):
    # A persisted path is untrusted evidence. Do not resolve or open it.
    if (type(value) is not str or not value or len(value) > 4096 or '\x00' in value
        or not os.path.isabs(value)):
        _fail('Source registry requires an absolute persisted local identity')
    return os.path.normcase(os.path.normpath(value))


def _validate_source_registry(state, holdout, selected_path):
    """Check ONLY the selected authority, read-only, against source reservation.

    Local path/row consistency cannot detect a coherent full-database rollback.
    """
    evidence = state.get('holdout_registry')
    if selected_path is None or type(evidence) is not dict:
        _fail('Source registry proof and explicit authoritative registry required')
    source_identity = _lexical_registry_path(evidence.get('registry_path'))
    selected = Path(selected_path).resolve()
    if source_identity != _lexical_registry_path(str(selected)):
        _fail('Source registry differs from selected authoritative registry')
    coverage = {}
    for bar in holdout.bars:
        start = bar.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = bar.end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        old = coverage.get(bar.contract_id, (start, end))
        coverage[bar.contract_id] = (min(old[0], start), max(old[1], end))
    bar_hash = content_hash(holdout.bars)
    reservation_id = content_hash({'bars_hash': bar_hash, 'coverage': coverage})
    if (evidence.get('reservation_id') != reservation_id or evidence.get('holdout_hash') != bar_hash
        or evidence.get('status') != 'reserved_consumed' or evidence.get('conflicts') != []):
        _fail('Source registry reservation proof is invalid')
    try:
        if not selected.is_file() or selected.stat().st_size > MAX_AUDIT_BYTES:
            _fail('Source registry is missing or exceeds audit byte limit')
        with closing(sqlite3.connect(selected.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            _prepare_bounded_read(db, {
                'reservations': [('reservation_id', 'TEXT', 0, None, 1, 0),
                    ('holdout_hash', 'TEXT', 1, None, 0, 0), ('campaign_id', 'TEXT', 1, None, 0, 0),
                    ('selection_hash', 'TEXT', 1, None, 0, 0), ('source_directory', 'TEXT', 1, None, 0, 0)],
                'coverage': [('reservation_id', 'TEXT', 1, None, 1, 0),
                    ('contract_id', 'TEXT', 1, None, 2, 0), ('start', 'TEXT', 1, None, 0, 0),
                    ('end', 'TEXT', 1, None, 0, 0)]})
            expected = (reservation_id, bar_hash, state['campaign_id'], state['selection_hash'])
            rows = db.execute('SELECT reservation_id, holdout_hash, campaign_id, selection_hash, source_directory FROM reservations WHERE reservation_id=?',
                              (reservation_id,)).fetchmany(2)
            observed = db.execute('SELECT contract_id, start, end FROM coverage WHERE reservation_id=? ORDER BY contract_id',
                                  (reservation_id,)).fetchmany(len(coverage) + 1)
            if (len(rows) != 1 or rows[0][:4] != expected
                or type(rows[0][4]) is not str or not rows[0][4] or len(rows[0][4]) > 4096
                or observed != [(contract, *bounds) for contract, bounds in sorted(coverage.items())]):
                _fail('Source registry no longer contains its exact consumed reservation and coverage')
    except (sqlite3.Error, OSError) as exc:
        raise SavedCandidatePoolError('Source registry is unavailable or inconsistent', 'source_registry_mismatch') from exc
    return {'resolved_path': source_identity, 'reservation_id': reservation_id,
            'agreement_policy': 'persisted_source_reservation_matches_selected_authority'}


def _compatible_request(provider, original_context, iteration, current_schema):
    """Pure request reconstruction from the exact two audited source protocols."""
    from .research import PROMPT, registry_json_schema
    context = dict(original_context)
    if current_schema and iteration:
        context.update(task='improve_previous_candidate', improvement_instruction=(
            'Use previous training and validation feedback to propose a distinct candidate in the same family. '
            'Change parameters or rules, not just strategy_id. Keep risk controls unchanged. '
            'Do not claim performance improved before the new candidate is evaluated.'))
    response_format = {'type': 'json_object'}
    if provider.get('output_mode', 'json_object') == 'registry_json_schema':
        response_format = {'type': 'json_schema', 'json_schema': {
            'name': 'quantlab_registry_candidate', 'strict': True,
            'schema': registry_json_schema(context['family'])}}
        context['output_contract'] = (
            'registry_json_schema mode: choose your own integer parameter values, including basis points. '
            'Return rules={} to use the requested built-in family. Do not generate an AST. '
            'Choose lookbacks much shorter than training bar count; trend fast must be below slow.')
    suffix = ('\nBefore returning JSON, compare your chosen parameters with previous.output.parameters. '
              'At least one parameter value must differ. A new strategy_id alone is invalid. '
              'Choose the changed value yourself within the same schema; do not alter risk controls.'
              if current_schema and context.get('task') == 'improve_previous_candidate' else '')
    return {'model': provider['model'], 'messages': [
        {'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': canonical_json(context) + suffix}],
        'max_tokens': provider['limits']['tokens_per_call'], 'response_format': response_format}


def _validate_legacy_receipts(provider, state, *, current_schema=False):
    """Validate bounded observed receipts, never infer response authenticity.

    Compatible response hashes cover unavailable full response envelopes. They
    cannot be compared to candidate output hashes. Failed child generations may
    consume provider budget without returning a receipt or candidate.
    """
    receipts = state['provider_receipts']
    if provider['mode'] == 'fixture':
        if type(receipts) is not list or receipts:
            _fail('Source provider receipts must be empty for fixtures')
        return
    returned = [attempt for attempt in state['attempts'] if attempt['output_hash'] is not None]
    limits = provider['limits']
    if type(receipts) is not list or len(receipts) != len(returned) or len(receipts) > limits['calls']:
        _fail('Source provider receipts do not match returned generations')
    from .walk_forward import _exact_number
    tokens, spends = 0, []
    for receipt, attempt in zip(receipts, returned):
        try:
            _keys(receipt, ('response_hash', 'reserved_tokens', 'reserved_spend', 'status'))
            if (not _hash(receipt['response_hash']) or receipt['status'] != 'transport_returned_not_verified'
                or type(receipt['reserved_tokens']) is not int
                or not limits['tokens_per_call'] < receipt['reserved_tokens'] <= limits['tokens']):
                _fail('Source provider receipt shape/status/resource mismatch')
            request = _compatible_request(provider, attempt['generator_context'], attempt['iteration'], current_schema)
            if receipt['reserved_tokens'] != len(canonical_json(request).encode('utf-8')) + limits['tokens_per_call']:
                _fail('Source provider receipt token reservation disagrees with audited request')
            spend = _exact_number(receipt['reserved_spend'])
            if (not 0 <= spend <= _exact_number(limits['spend'])
                or (_exact_number(limits['rate']) == 0 and spend != 0)):
                _fail('Source provider receipt spend exceeds resource bounds')
        except ValidationError as exc:
            raise SavedCandidatePoolError('Invalid compatible source provider receipt', 'source_provider_receipt_invalid') from exc
        tokens += receipt['reserved_tokens']
        spends.append(spend)
    # Exact finite addition, independent of caller Decimal context.
    with localcontext() as context:
        context.prec = 160
        total_spend = sum(spends, Decimal(0))
    if tokens > limits['tokens'] or total_spend > _exact_number(limits['spend']):
        _fail('Source provider receipts exceed aggregate resource limits')


def _matches_chatgpt_implementation(descriptor, producer):
    """Exact reviewed tuple/target membership, independent of installed runtime."""
    if not isinstance(descriptor, dict):
        return False
    fields = ('source_sha256', 'dependency_versions', 'dependency_manifest_sha256',
              'dependency_artifact_evidence')
    return any(all(descriptor.get(key) == variant[key] for key in fields)
               and descriptor.get('dependency_target') in variant['dependency_targets']
               for variant in producer.get('chatgpt_plan_implementations', ()))


def _select_producer(binding):
    """Distinct immutable profiles may share one audited engine tuple.

    ChatGPT requires a unique matching descriptor profile. Fixture/compatible
    campaigns retain their original canonical profile and snapshot identity.
    """
    matches = [known for known in SUPPORTED_PRODUCERS
               if binding['engine_source_hashes'] == known['engine_source_hashes']
               and binding['prompt_template_hash'] == known['prompt_template_hash']]
    if not matches:
        _fail('Unsupported or missing audited source producer protocol')
    provider = binding['provider']
    if isinstance(provider, dict) and provider.get('mode') == 'chatgpt_plan':
        matches = [known for known in matches
                   if _matches_chatgpt_implementation(provider.get('descriptor'), known)]
        if len(matches) != 1:
            _fail('Unsupported source provider protocol implementation tuple or ambiguous profile')
    else:
        matches = [known for known in matches if known['protocol'] in
                   (AUDITED_PRODUCER['protocol'], CURRENT_PRODUCER['protocol'])]
        if len(matches) != 1:
            _fail('Unsupported or ambiguous audited source producer protocol')
    return matches[0]


def _validate_chatgpt_provider(provider, state, producer):
    """Pure archived descriptor/receipt checks; no auth modules or credentials."""
    from .research import PROMPT, _validated_provider_descriptor, _validated_receipt_snapshot
    _keys(provider, ('mode', 'model', 'endpoint', 'descriptor'))
    if (provider['mode'] != 'chatgpt_plan'
        or provider['endpoint'] != 'https://api.openai.com/v1/responses'
        or type(provider['model']) is not str
        or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', provider['model'])):
        _fail('Unsupported source provider protocol')
    try:
        descriptor = _validated_provider_descriptor(provider['descriptor'])
        _keys(descriptor, ('source_sha256', 'dependency_versions', 'dependency_manifest_sha256',
            'dependency_target', 'dependency_artifact_evidence', 'version', 'mode', 'model', 'endpoint',
            'registration', 'campaign_id', 'max_calls', 'timeout_seconds', 'stall_seconds',
            'max_request_bytes', 'max_response_bytes', 'max_event_bytes', 'max_candidate_bytes',
            'max_events', 'billing_route', 'paid_api_fallback', 'token_upper_bound_enforced',
            'spend_upper_bound_enforced', 'account_credit_policy', 'included_usage_policy_ack_required'))
    except ValidationError as exc:
        raise SavedCandidatePoolError('Unsupported source provider descriptor', 'source_provider_provenance_invalid') from exc
    if not _matches_chatgpt_implementation(descriptor, producer):
        _fail('Unsupported source provider protocol implementation tuple')
    if (descriptor['mode'] != provider['mode'] or descriptor['model'] != provider['model']
        or descriptor['endpoint'] != provider['endpoint']
        or type(descriptor['registration']) is not str
        or not re.fullmatch('[a-f0-9]{32}', descriptor['registration'])
        or type(descriptor['campaign_id']) is not str
        or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', descriptor['campaign_id'])
        or descriptor['billing_route'] != 'chatgpt_plan'
        or descriptor['account_credit_policy'] != 'unverified_user_setting'
        or descriptor['included_usage_policy_ack_required'] is not True
        or any(descriptor[key] is not False for key in (
            'paid_api_fallback', 'token_upper_bound_enforced', 'spend_upper_bound_enforced'))):
        _fail('Unsupported source provider protocol descriptor claims')
    for key, lower, upper in (('max_calls', 0, 100), ('timeout_seconds', 1, 120),
        ('stall_seconds', 1, 120), ('max_request_bytes', 1024, 65536),
        ('max_response_bytes', 1024, 1048576), ('max_event_bytes', 65536, 65536),
        ('max_candidate_bytes', 16384, 16384), ('max_events', 2048, 2048)):
        if type(descriptor[key]) is not int or not lower <= descriptor[key] <= upper:
            _fail('Unsupported source provider protocol descriptor limit')
    try:
        receipts = _validated_receipt_snapshot({'version': 1,
            'provider_descriptor_hash': content_hash(descriptor),
            'receipts': state['provider_receipts']}, descriptor)
    except ValidationError as exc:
        raise SavedCandidatePoolError('Source provider receipt validation failed', 'source_provider_receipt_invalid') from exc
    attempts = state['attempts']
    if len(receipts) != len(attempts) or len(receipts) > descriptor['max_calls']:
        _fail('Source provider receipts do not match consumed attempts')
    for attempt, receipt in zip(attempts, receipts):
        context = dict(attempt['generator_context'])
        if attempt['iteration'] != 0:
            context.update(task='improve_previous_candidate', improvement_instruction=(
                'Propose a distinct candidate in the same family using training and validation feedback only. Keep risk controls unchanged.'))
        request = {'model': provider['model'], 'instructions': PROMPT,
            'input': [{'role': 'user', 'content': canonical_json(context)}], 'store': False, 'stream': True}
        size = len(canonical_json(request).encode('utf-8'))
        if (receipt['status'] != 'completed' or receipt['request_hash'] != content_hash(request)
            or receipt['request_bytes'] != size or size > descriptor['max_request_bytes']
            or receipt['response_hash'] != attempt['output_hash'] or not _hash(attempt['output_hash'])
            or type(receipt['received_bytes']) is not int
            or not 0 < receipt['received_bytes'] <= descriptor['max_response_bytes']):
            _fail('Source provider receipt request/response evidence mismatch')
