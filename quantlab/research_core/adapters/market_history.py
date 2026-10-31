"""Bounded history responsibility; validation, digest and publication ordering preserved."""

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
from quantlab.market import MarketBar, MarketValidationError, utc
from quantlab.windows_paths import canonical_path, native_path
from quantlab.research_core.domain.market_sessions import MAX_BARS, _fail, _hash, _session_dict, _sessions, _stamp, session_from_dict
from .history_decoder import MAX_FILE_BYTES, MAX_ROWS, VERSION, _check, _result


MAX_CACHE_BYTES = 16 * 1024 * 1024


MAX_IMPORTS = 64


def _local_path_text(path):
    text = os.fspath(path)
    if not isinstance(text, str) or not text or '\x00' in text:
        _fail('invalid local path')
    normalized = text.replace('\\', '/')
    if normalized.startswith('//'):
        _fail('UNC and device namespace paths are not local imports')
    for index, part in enumerate(normalized.split('/')):
        if ':' in part and not (index == 0 and re.fullmatch('[A-Za-z]:', part)):
            _fail('alternate stream/device path refused')
        stem = part.rstrip(' .').split('.')[0].upper()
        if PureWindowsPath(part).is_reserved() or stem in ('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$') or re.fullmatch(r'(?:COM|LPT)[1-9]', stem):
            _fail('reserved device path refused')
    return text


def _windows_local_drive(path):
    # GetDriveType checks the native drive classification before probing a file.
    # Reject mapped remote/unknown roots instead of trusting the absence of UNC.
    import ctypes

    function = ctypes.windll.kernel32.GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint
    if function(path.anchor) not in (2, 3, 5, 6):
        _fail('only verified local filesystem drives are supported')


def _safe(path, *, directory=False, create=False):
    path = Path(_local_path_text(path)).absolute()
    if os.name == 'nt':
        _windows_local_drive(path)
    if '..' in path.parts:
        _fail('path traversal refused')
    path = native_path(path)
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            _fail('symlink or reparse point refused')
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            _fail('unexpected path type')
    return path


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            _fail('duplicate cache key')
        result[k] = v
    return result


def load_history(root, cache_id):
    if not isinstance(cache_id, str) or not re.fullmatch('[a-f0-9]{64}', cache_id):
        _fail('invalid history cache identity')
    root = _safe(canonical_path(root), directory=True)
    path = _safe(canonical_path(root / (cache_id + '.json')))
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            _fail('history cache byte limit')
        envelope = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(envelope, dict) or set(envelope) != {'payload', 'sha256'}:
            _fail('invalid history cache envelope')
        payload = envelope['payload']
        if not isinstance(payload, dict) or set(payload) != {'version', 'source_hash', 'policy_hash', 'received_at', 'sessions', 'bars', 'counters'}:
            _fail('invalid history cache fields')
        if payload['version'] != VERSION or _hash(payload) != envelope['sha256']:
            _fail('history cache digest/version mismatch')
        if not re.fullmatch('[a-f0-9]{64}', payload['source_hash']):
            _fail('invalid source digest')
        sessions = _sessions([session_from_dict(s) for s in payload['sessions']])
        if _hash([_session_dict(s) for s in sessions]) != payload['policy_hash']:
            _fail('session policy digest mismatch')
        received_at = _stamp(payload['received_at'])
        utc(received_at)
        if not isinstance(payload['bars'], list) or not 1 <= len(payload['bars']) <= MAX_BARS:
            _fail('history bar count limit')
        counters = payload['counters']
        names = {'rows', 'accepted_ticks', 'spread_rows', 'excluded_rows', 'outside_session_rows', 'missing_minutes'}
        if not isinstance(counters, dict) or set(counters) != names or any(type(v) is not int or not 0 <= v <= MAX_ROWS for v in counters.values()):
            _fail('invalid history counters')
        bars = []
        keys = {'contract_id', 'trade_date', 'session', 'open', 'high', 'low', 'close', 'volume', 'timestamp', 'end', 'session_open', 'session_end', 'partial'}
        for row in payload['bars']:
            if not isinstance(row, dict) or set(row) != keys:
                _fail('invalid history bar fields')
            matches = [s for s in sessions if (s.instrument.contract_id, s.trade_date, s.session) == (row['contract_id'], row['trade_date'], row['session'])]
            if len(matches) != 1:
                _fail('history bar outside policy')
            s = matches[0]
            if any(not isinstance(row[k], str) or not re.fullmatch(r'[0-9]{1,10}', row[k]) or int(row[k]) <= 0 for k in ('open', 'high', 'low', 'close')):
                _fail('invalid cached integral price')
            b = MarketBar(
                s.instrument,
                s.trade_date,
                s.session,
                *[Decimal(row[k]) for k in ('open', 'high', 'low', 'close')],
                row['volume'],
                interval='1m',
                timestamp=_stamp(row['timestamp']),
                end=_stamp(row['end']),
                session_open=_stamp(row['session_open']),
                session_end=_stamp(row['session_end']),
                partial=row['partial'],
                source_id=payload['source_hash'],
            )
            if b.session_open != s.open or b.session_end != s.end:
                _fail('history bar session mismatch')
            if b.volume <= 0 or b.end - b.timestamp != timedelta(minutes=1):
                _fail('invalid normalized minute volume/duration')
            bars.append(b)
        missing = 0
        for s in sessions:
            selected = [b for b in bars if b.instrument == s.instrument and b.trade_date == s.trade_date and b.session == s.session]
            gap = int((s.end - s.open).total_seconds() / 60) - len(selected)
            missing += gap
            if any(b.partial != bool(gap) for b in selected):
                _fail('history partial coverage mismatch')
        if missing != counters['missing_minutes']:
            _fail('history gap counter mismatch')
        if counters['rows'] != sum(counters[k] for k in ('accepted_ticks', 'spread_rows', 'excluded_rows', 'outside_session_rows')):
            _fail('history row accounting mismatch')
        if counters['accepted_ticks'] < len(bars):
            _fail('history tick count mismatch')
        result = _result(bars, sessions, payload['source_hash'], counters, received_at)
        if result.cache_id != cache_id:
            _fail('history identity mismatch')
        return result
    except MarketValidationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation) as exc:
        raise MarketValidationError('invalid or unavailable history cache') from exc


def _entries(root, *, lock_held=False):
    paths = []
    total_bytes = 0
    count = 0
    identities = set()
    for p in root.iterdir():
        count += 1
        if count > MAX_IMPORTS * 3 + 1:
            _fail('history directory entry limit')
        temporary = bool(re.fullmatch(r'\.history-[a-zA-Z0-9_-]+\.tmp', p.name))
        try:
            _safe(canonical_path(p))
            info = p.stat()
            size = info.st_size
            identity = (info.st_dev, info.st_ino)
        except FileNotFoundError:
            if temporary:
                continue  # another importer cleaned up its owned temp
            _fail('history cache changed during listing')
        if p.suffix == '.json' and re.fullmatch('[a-f0-9]{64}', p.stem):
            if identity not in identities:
                total_bytes += size
                identities.add(identity)
            if total_bytes > MAX_FILE_BYTES:
                _fail('combined history cache byte limit')
            paths.append(p)
            if len(paths) > MAX_IMPORTS:
                _fail('history cache count limit')
        elif p.name == '.history.lock':
            if size not in (0, 1):
                _fail('unknown history lock file')
            # Windows byte locks prohibit reading byte0 through a second handle.
            # The owning descriptor already validated content after acquisition.
            if not lock_held:
                with p.open('rb') as stream:
                    if stream.read(2) not in (b'', b'\0'):
                        _fail('unknown history lock file')
        elif temporary:
            if size > MAX_CACHE_BYTES:
                _fail('orphan history temporary file too large')
            if identity not in identities:
                total_bytes += size
                identities.add(identity)
            if total_bytes > MAX_FILE_BYTES:
                _fail('combined history cache/temp byte limit')
        else:
            _fail('unknown history cache entry')
    return paths, total_bytes


@contextmanager
def _cache_lock(root):
    """OS advisory lock is released on cancellation/process death, unlike sentinels."""
    path = _safe(canonical_path(root / '.history.lock'))
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
    locked = False
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            os.lseek(fd, 0, os.SEEK_SET)
            if os.read(fd, 2) not in (b'', b'\0') or os.fstat(fd).st_size not in (0, 1):
                _fail('unknown history lock content')
            if os.fstat(fd).st_size == 0:
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, b'\0')
                os.fsync(fd)
        except OSError as exc:
            raise MarketValidationError('another history import is publishing; retry after it finishes') from exc
        yield
    finally:
        if locked:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def list_history(root):
    root = _safe(canonical_path(root), directory=True)
    if not root.exists():
        return ()
    paths, _ = _entries(root)
    return tuple(load_history(root, p.stem) for p in sorted(paths))


def _existing_result(root, result):
    cached = load_history(root, result.cache_id)
    if cached.counters != result.counters or tuple(s.bars for s in cached.series) != tuple(s.bars for s in result.series):
        _fail('existing history cache conflicts with decoded source; refusing reuse')
    return cached


def publish(root, target, result, content, deadline, cancelled):
    _safe(canonical_path(root), directory=True)
    _safe(canonical_path(target))
    _check(deadline, cancelled)
    with _cache_lock(root):
        paths, total_bytes = _entries(root, lock_held=True)
        if target.exists():
            return _existing_result(root, result)
        if len(paths) >= MAX_IMPORTS or total_bytes + len(content) > MAX_FILE_BYTES:
            _fail('history cache count/combined byte limit')
        _check(deadline, cancelled)
        fd, temp = tempfile.mkstemp(prefix='.history-', suffix='.tmp', dir=root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _safe(canonical_path(root), directory=True)
            _safe(canonical_path(target))
            _check(deadline, cancelled)
            # Exclusive hard-link publication is atomic and never overwrites another file.
            try:
                os.link(temp, target)
            except FileExistsError:
                return _existing_result(root, result)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return load_history(root, result.cache_id)
