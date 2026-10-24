"""Compose explicit downloads with the existing strict TMF research importer."""

import csv
import hashlib
import io
from pathlib import Path
import stat
import tempfile

from .core import Dataset, ValidationError, content_hash, to_dict, validate_contract
from .data import MAX_FILE_BYTES, MAX_ROWS, OFFICIAL_TICK_COLUMNS, SessionCalendar, import_taifex, validate_dataset
from .data_gap_report import reject_invalid_import
from .reporting import MAX_JSON_BYTES, read_json, save_dataset, write_json
from .runtime_support import atomic_write
from .windows_paths import canonical_path, native_path


def import_settings(value):
    if not isinstance(value, dict) or set(value) != {'calendar', 'contract', 'confirmed'} or value['confirmed'] is not True:
        raise ValidationError('download_import_settings_required')
    contract = value['contract']
    if not isinstance(contract, str) or not contract.startswith('TAIFEX:TMF:'):
        raise ValidationError('download_import_settings_required')
    name = value['calendar']
    if not isinstance(name, str) or not name.strip():
        raise ValidationError('download_import_settings_required')
    try:
        validate_contract(contract)
        calendar_value = read_json(Path(name))
        if not isinstance(calendar_value, dict) or set(calendar_value) != {'version', 'sessions'}:
            raise ValueError
        sessions = calendar_value['sessions']
        if not isinstance(sessions, list) or not 1 <= len(sessions) <= 256:
            raise ValueError
        calendar = SessionCalendar(sessions, version=calendar_value['version'])
    except (OSError, ValueError, TypeError, KeyError):
        raise ValidationError('download_import_settings_required') from None
    return contract, calendar_value, calendar


def _source(member, cache):
    _reject_links(Path(cache))
    cache = canonical_path(cache).resolve(strict=True)
    path = Path(member['path'])
    _reject_links(path)
    path = canonical_path(path).resolve(strict=True)
    if not path.is_relative_to(cache):
        raise ValidationError('download_import_source_invalid')
    with native_path(path).open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES or hashlib.sha256(raw).hexdigest() != member['sha256']:
        raise ValidationError('download_import_source_invalid')
    for encoding in ('utf-8-sig', 'cp950'):
        try:
            text = raw.decode(encoding)
            if '\x00' in text:
                raise ValidationError('download_import_source_invalid')
            return text
        except UnicodeDecodeError:
            pass
    raise ValidationError('download_import_source_invalid')


def _append_rows(output, member, cache, contract, count):
    reader = csv.DictReader(io.StringIO(_source(member, cache), newline=''), strict=True)
    columns = [name.strip().lstrip('\ufeff') for name in (reader.fieldnames or ())]
    if len(columns) != len(set(columns)) or set(columns) != set(OFFICIAL_TICK_COLUMNS):
        raise ValidationError('download_import_source_invalid')
    reader.fieldnames = columns
    writer = csv.DictWriter(output, fieldnames=OFFICIAL_TICK_COLUMNS, lineterminator='\n')
    month = contract.rsplit(':', 1)[1]
    for index, row in enumerate(reader, 1):
        if index > MAX_ROWS or None in row or any(value is None for value in row.values()):
            raise ValidationError('download_import_source_invalid')
        # Economic parsing, spread exclusion and all calendar checks stay in import_taifex.
        if row['商品代號'].strip() != 'TMF' or month not in row['到期月份(週別)'].strip().split('/'):
            continue
        count += 1
        if count > MAX_ROWS:
            raise ValidationError('download_import_source_invalid')
        writer.writerow(row)
        if output.tell() > MAX_FILE_BYTES:
            raise ValidationError('download_import_source_invalid')
    return count


def _combined(manifest, cache, destination, contract):
    archives = manifest['archives']
    if not isinstance(archives, list) or not 1 <= len(archives) <= 30:
        raise ValidationError('download_import_source_invalid')
    sources, seen, count = [], set(), 0
    with destination.open('w', encoding='utf-8', newline='') as output:
        csv.writer(output, lineterminator='\n').writerow(OFFICIAL_TICK_COLUMNS)
        for archive in sorted(archives, key=lambda value: value['trade_date']):
            if archive['format'] != 'csv' or len(archive['files']) != 1:
                raise ValidationError('download_import_source_invalid')
            member = archive['files'][0]
            identity = (archive['trade_date'], member['sha256'])
            if archive['trade_date'] in seen or member['sha256'] in seen:
                raise ValidationError('download_import_source_invalid')
            seen.update(identity)
            count = _append_rows(output, member, cache, contract, count)
            sources.append({key: archive[key] for key in ('trade_date', 'source_url', 'sha256')})
            sources[-1]['file_sha256'] = member['sha256']
    return sources


def _publish(data, calendar, root):
    root = native_path(root)
    targets = (root / 'dataset.json', root / 'dataset_calendar.json')
    previous = [_previous(path) for path in targets]
    # Retain the previous active files before replacing either member of the pair.
    backup = root / 'download_import_history' / content_hash([hashlib.sha256(raw).hexdigest() if raw is not None else None for raw in previous])
    for path, raw in zip(targets, previous):
        if raw is not None:
            _reject_links(backup / path.name)
            atomic_write(backup / path.name, raw, durable=True)
    try:
        save_dataset(data, targets[0])
        write_json(targets[1], calendar)
    except BaseException:
        for path, raw in zip(targets, previous):
            if raw is None:
                if path.exists():
                    path.unlink()
            else:
                atomic_write(path, raw, durable=True)
        raise


def _reject_links(path):
    for target in (path, *path.parents):
        try:
            info = target.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValidationError('download_import_source_invalid')


def _previous(path):
    _reject_links(path)
    if not path.exists():
        return None
    with path.open('rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValidationError('download_import_source_invalid')
    return raw


def download_and_import(cache, root, payload, *, emit=None):
    # Resolve the network client only for an explicitly consented download operation.
    from .downloads import refresh

    if payload.get('network_opt_in') is not True:
        raise ValidationError('network_disabled')
    contract, calendar_value, calendar = import_settings(payload['auto_import'])
    manifest = refresh(cache, days=payload.get('days', 1), kind='csv')
    try:
        with tempfile.TemporaryDirectory(prefix='.download-import-', dir=cache) as temporary:
            source = Path(temporary) / 'downloaded-tmf.csv'
            sources = _combined(manifest, cache, source, contract)
            data = import_taifex(source, kind='ticks', calendar=calendar, contract_id=contract)
            reject_invalid_import(data, emit)
            description = to_dict(data.manifest)
            description['download_sources'] = sources
            description['manifest_hash'] = content_hash({key: value for key, value in description.items() if key not in ('imported_at', 'manifest_hash')})
            data = Dataset(data.bars, description, to_dict(data.quality))
            validate_dataset(data)
            _publish(data, calendar_value, root)
    except (OSError, ValueError, KeyError, csv.Error):
        raise ValidationError('download_import_failed') from None
    return {**manifest, 'auto_import': {'status': 'imported', 'dataset': str(root / 'dataset.json'), 'bars': len(data.bars), 'contract': contract}}
