"""Narrow original-analysis stop ledger; importing this module enables nothing.

Trusted application code owns registration and original-handle observation. Hashes
are consistency checks, not authentication against same-user control-store forgery
or complete rollback. No PID, boot identifier, elapsed time or absent process is
stop evidence. This module never executes a provider or repairs analysis journals.
"""

from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import threading
import time
import uuid

VERSION = 1
MAX_DATABASE = 16 * 1024 * 1024
MAX_ROWS = 4096
MAX_RECORD = 16384
LOCK_TIMEOUT = 0.25
_SENTINEL = '.analysis-recovery-v1.json'
_DATABASE = 'analysis-recovery-v1.sqlite3'
_LOCK = '.analysis-recovery-admission.lock'
_PROTOCOL = 'markauto.original-job-stop.v1'
_SCHEMA = {
    'events': 'CREATE TABLE events(sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)',
    'no_update': "CREATE TRIGGER no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END",
    'no_delete': "CREATE TRIGGER no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END",
}
# Fixed families, deliberately not a generic filesystem permission engine.
SOURCE_WRITERS = frozenset(
    {
        'demo',
        'campaign',
        'ui_demo',
        'ui_import',
        'ui_refresh',
        'ui_market_refresh',
        'ui_campaign',
        'ui_walk_forward_run',
        'ui_backup_restore',
        'restore_recovery',
    }
)
ANALYSIS_STARTS = frozenset({'ui_analysis_preview', 'ui_analysis_run'})
WORKSPACE_MUTATIONS = frozenset({'ui_backup_create', 'ui_backup_restore', 'restore_recovery'})
SAFE_OPERATIONS = frozenset(
    {
        'backtest',
        'ui_backtest',
        'ui_compare',
        'ui_analysis_read',
        'ui_walk_forward_read',
        'ui_select',
        'ui_disable',
        'ui_paper_snapshot',
        'ui_paper_reconcile',
        'ui_paper_kill',
        'ui_paper_submit',
        'ui_paper_cancel',
        'ui_paper_replay',
    }
)
_locks = {}
_locks_guard = threading.Lock()
_local = threading.local()


from .errors import RecoveryError, fail


def _fail(message):
    fail(message, RecoveryError)


def _json(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise RecoveryError('Invalid recovery record') from exc
    if len(raw.encode('utf-8')) > MAX_RECORD:
        _fail('Recovery record exceeds limit')
    return raw


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _fail('Invalid recovery record fields')


def _hex(value, size=64):
    if type(value) is not str or re.fullmatch('[a-f0-9]{%d}' % size, value) is None:
        _fail('Invalid recovery identity')
    return value


def _path(path, *, exists=True, directory=False):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == path and not exists:
                continue
            _fail('Recovery path is missing')
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            _fail('Recovery links and reparse points are forbidden')
        if part == path:
            if directory and not stat.S_ISDIR(info.st_mode):
                _fail('Recovery directory required')
            if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                _fail('Recovery regular unlinked file required')
    return path


def _directory(path):
    path = _path(path, directory=True)
    info = path.stat()
    return {'root': os.path.normcase(str(path)), 'device': info.st_dev, 'inode': info.st_ino}


def _location(paths):
    bootstrap = Path(getattr(paths, 'bootstrap', None) or paths.root)
    return bootstrap, bootstrap / 'control-v1' / _DATABASE, bootstrap / _SENTINEL


def _identity(value):
    _keys(value, ('root', 'device', 'inode'))
    if (
        type(value['root']) is not str
        or not 1 <= len(value['root']) <= 4096
        or not Path(value['root']).is_absolute()
        or any(type(value[k]) is not int or value[k] < 0 for k in ('device', 'inode'))
    ):
        _fail('Invalid directory identity')


def _decode(raw):
    if type(raw) is not str or len(raw.encode('utf-8')) > MAX_RECORD:
        _fail('Oversized recovery record')

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail('Duplicate recovery field')
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError, RecursionError) as exc:
        raise RecoveryError('Invalid recovery JSON') from exc
    if _json(value) != raw:
        _fail('Noncanonical recovery record')
    return value


@dataclass
class _Admission:
    root: str
    pid: int
    thread: int
    active: bool = True


@contextmanager
def admission(paths, *, timeout=LOCK_TIMEOUT):
    """Bounded, process-reentrant installation lock; hold through actual mutation.

    GUI registration must occur while the original GUI also owns its QLockFile.
    A worker must hold this context across its protected operation, not merely
    across process.start(). Nested BackupManager calls reuse the same lock.
    """
    bootstrap, _, _ = _location(paths)
    root = _directory(bootstrap)['root']
    if type(timeout) not in (int, float) or not 0 <= timeout <= 2:
        _fail('Invalid recovery admission timeout')
    with _locks_guard:
        lock = _locks.setdefault(root, threading.RLock())
    if not lock.acquire(timeout=timeout):
        _fail('Recovery admission busy')
    stream = None
    token = None
    try:
        held = getattr(_local, 'held', {})
        if root in held and held[root].pid == os.getpid():
            yield held[root]
            return
        name = _path(bootstrap / _LOCK, exists=False)
        fd = os.open(name, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        stream = os.fdopen(fd, 'r+b', buffering=0)
        _path(name)
        if os.fstat(fd).st_ino != name.stat().st_ino:
            _fail('Recovery admission file changed')
        if os.fstat(fd).st_size == 0:
            stream.write(b'0')
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    # Load this platform-specific API only on its supported execution path.
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    # Load this platform-specific API only on its supported execution path.
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    _fail('Recovery admission busy')
                time.sleep(0.01)
        token = _Admission(root, os.getpid(), threading.get_ident())
        _local.held = {**held, root: token}
        yield token
    finally:
        if token is not None:
            token.active = False
            _local.held = {k: v for k, v in _local.held.items() if k != root}
        if stream is not None:
            stream.close()  # Closing releases the operating-system lock.
        lock.release()


def _require_admission(paths, token):
    bootstrap, _, _ = _location(paths)
    if (
        not isinstance(token, _Admission)
        or not token.active
        or token.pid != os.getpid()
        or token.thread != threading.get_ident()
        or token.root != _directory(bootstrap)['root']
        or getattr(_local, 'held', {}).get(token.root) is not token
    ):
        _fail('Original active admission context required')


def _connect(path, *, write=False):
    _path(path)
    if path.stat().st_size > MAX_DATABASE:
        _fail('Recovery database exceeds limit')
    with path.open('rb') as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01' or header[16:18] != b'\x10\x00':
        _fail('Recovery ledger requires original rollback-journal format')
    for suffix in ('-journal', '-wal', '-shm'):
        _path(Path(str(path) + suffix), exists=False)
    query_deadline = time.monotonic() + 2
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=LOCK_TIMEOUT)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > query_deadline else 0, 1000)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA busy_timeout=250')
        if write:
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                _fail('Recovery ledger requires rollback journal')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA max_page_count=%d' % (MAX_DATABASE // 4096))
        else:
            db.execute('PRAGMA query_only=ON')
        return db
    except BaseException:
        db.close()
        raise


def _original_marker(paths):
    bootstrap, database, sentinel = _location(paths)
    marker_present = sentinel.exists() or sentinel.is_symlink()
    database_present = database.exists() or database.is_symlink()
    if not marker_present and not database_present:
        return None
    if not marker_present or not database_present:
        _fail('Original recovery controls missing')
    _path(sentinel)
    if sentinel.stat().st_size > MAX_RECORD:
        _fail('Oversized recovery installation marker')
    try:
        marker = _decode(sentinel.read_text(encoding='utf-8'))
    except (OSError, UnicodeError) as exc:
        raise RecoveryError('Unreadable original recovery marker') from exc
    _keys(marker, ('version', 'installation', 'bootstrap'))
    if type(marker['version']) is not int or marker['version'] != VERSION:
        _fail('Unsupported recovery marker version')
    _hex(marker['installation'], 32)
    _identity(marker['bootstrap'])
    if marker['bootstrap'] != _directory(bootstrap):
        _fail('Original recovery installation differs')
    return marker


def supports_durable_recovery():
    """Only Windows original-job helper receipts are a supported product route."""
    return sys.platform == 'win32'


def _load(paths):
    # No mkdir, lock creation, database initialization or journal adoption here.
    marker = _original_marker(paths)
    if marker is None:
        return None
    _, database, _ = _location(paths)
    try:
        with closing(_connect(database)) as db:
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                _fail('Unexpected recovery journal mode')
            schema = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
            if schema != _SCHEMA:
                _fail('Unexpected recovery schema')
            if db.execute('PRAGMA user_version').fetchone()[0] != VERSION:
                _fail('Unsupported recovery database version')
            if db.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
                _fail('Corrupt recovery database')
            rows = db.execute('SELECT sequence, payload, digest FROM events ORDER BY sequence LIMIT ?', (MAX_ROWS + 1,)).fetchall()
    except sqlite3.Error as exc:
        raise RecoveryError('Unreadable original recovery ledger') from exc
    if not rows or len(rows) > MAX_ROWS:
        _fail('Invalid recovery ledger length')
    launches, receipts, workspaces, transactions = {}, {}, {}, set()
    seen_analysis, seen_helper = set(), set()
    previous = '0' * 64
    for number, (sequence, raw, digest) in enumerate(rows, 1):
        if type(sequence) is not int or sequence != number:
            _fail('Recovery sequence mismatch')
        item = _decode(raw)
        _keys(item, ('version', 'previous', 'kind', 'value'))
        if type(item['version']) is not int or item['version'] != VERSION or item['previous'] != previous or _hex(digest) != _hash(item):
            _fail('Recovery chain mismatch')
        kind, value = item['kind'], item['value']
        if number == 1:
            if kind != 'installation' or value != marker:
                _fail('Recovery installation record mismatch')
        elif kind == 'workspace':
            _keys(value, ('identity', 'epoch'))
            _identity(value['identity'])
            root = value['identity']['root']
            if root in workspaces or type(value['epoch']) is not int or value['epoch'] != 0:
                _fail('Invalid original workspace record')
            workspaces[root] = value
        elif kind == 'epoch':
            _keys(value, ('root', 'transaction_id', 'epoch'))
            _hex(value['transaction_id'], 32)
            if (
                type(value['root']) is not str
                or value['root'] not in workspaces
                or (value['root'], value['transaction_id']) in transactions
                or type(value['epoch']) is not int
                or value['epoch'] != workspaces[value['root']]['epoch'] + 1
            ):
                _fail('Invalid restore epoch')
            transactions.add((value['root'], value['transaction_id']))
            workspaces[value['root']] = {**workspaces[value['root']], 'epoch': value['epoch']}
        elif kind == 'launch':
            _validate_launch(value)
            root = value['workspace']['root']
            if (
                value['installation'] != marker['installation']
                or root not in workspaces
                or value['workspace'] != workspaces[root]['identity']
                or value['epoch'] != workspaces[root]['epoch']
                or value['job_id'] in launches
                or value['analysis_id'] in seen_analysis
                or value['helper_nonce'] in seen_helper
            ):
                _fail('Duplicate or mismatched original analysis launch')
            launches[value['job_id']] = value
            seen_analysis.add(value['analysis_id'])
            seen_helper.add(value['helper_nonce'])
        elif kind == 'receipt':
            _keys(value, ('protocol', 'job_id', 'launch_hash', 'active_processes'))
            if (
                value['protocol'] != _PROTOCOL
                or value['job_id'] not in launches
                or value['job_id'] in receipts
                or value['launch_hash'] != _hash(launches[value['job_id']])
                or type(value['active_processes']) is not int
                or value['active_processes'] != 0
                or launches[value['job_id']]['epoch'] != workspaces[launches[value['job_id']]['workspace']['root']]['epoch']
            ):
                _fail('Invalid original-job stop receipt')
            receipts[value['job_id']] = value
        else:
            _fail('Unknown recovery event')
        previous = digest
    return {
        'marker': marker,
        'launches': launches,
        'receipts': receipts,
        'workspaces': workspaces,
        'transactions': transactions,
        'length': len(rows),
        'head': previous,
    }


def _validate_launch(value):
    _keys(
        value,
        (
            'installation',
            'workspace',
            'epoch',
            'job_id',
            'analysis_id',
            'registration',
            'plan_hash',
            'provider_hash',
            'request_hash',
            'request_bytes',
            'model',
            'timeout_seconds',
            'ledger_basename',
            'source_request_hash',
            'helper_protocol',
            'helper_nonce',
        ),
    )
    for key in ('installation', 'job_id', 'registration', 'helper_nonce'):
        _hex(value[key], 32)
    for key in ('analysis_id', 'plan_hash', 'provider_hash', 'request_hash', 'source_request_hash'):
        _hex(value[key])
    _identity(value['workspace'])
    if (
        type(value['epoch']) is not int
        or value['epoch'] < 0
        or type(value['request_bytes']) is not int
        or not 1 <= value['request_bytes'] <= 65536
        or type(value['timeout_seconds']) is not int
        or not 1 <= value['timeout_seconds'] <= 120
        or type(value['model']) is not str
        or re.fullmatch('[A-Za-z0-9._:-]{1,128}', value['model']) is None
        or value['ledger_basename'] != 'chatgpt-analysis-' + value['analysis_id'] + '.sqlite3'
        or value['helper_protocol'] != _PROTOCOL
    ):
        _fail('Invalid immutable launch binding')


def _append(db, state, events):
    count, previous = state['length'], state['head']
    outstanding = set(state.get('launches', {})) - set(state.get('receipts', {}))
    for kind, value in events:
        if kind == 'launch':
            outstanding.add(value['job_id'])
        elif kind == 'receipt':
            outstanding.discard(value['job_id'])
    if count + len(events) + len(outstanding) > MAX_ROWS:
        _fail('Recovery ledger receipt capacity reserved')
    for kind, value in events:
        item = {'version': VERSION, 'previous': previous, 'kind': kind, 'value': value}
        previous = _hash(item)
        count += 1
        db.execute('INSERT INTO events VALUES (?,?,?)', (count, _json(item), previous))
    # Reserve both an event and ample fixed-page headroom for every original
    # stop receipt. Failed registration/epoch writes roll back before commit.
    pages = db.execute('PRAGMA page_count').fetchone()[0]
    if (pages + 16 * len(outstanding)) * 4096 > MAX_DATABASE:
        _fail('Recovery ledger stop-publication space reserved')


def _initialize(paths):
    # Keep operation-specific dependencies out of module startup.
    from .runtime_support import atomic_write, _sync_directory

    bootstrap, database, sentinel = _location(paths)
    if sentinel.exists() or database.exists():
        _fail('Recovery controls already exist')
    controls = database.parent
    if not controls.exists():
        controls.mkdir()
        _sync_directory(bootstrap)
    _path(controls, directory=True)
    marker = {'version': VERSION, 'installation': uuid.uuid4().hex, 'bootstrap': _directory(bootstrap)}
    # Marker precedes initialization; a crash cannot turn lost controls into legacy.
    atomic_write(sentinel, _json(marker).encode('utf-8'), durable=True)
    with closing(sqlite3.connect(database, timeout=LOCK_TIMEOUT)) as db:
        db.execute('PRAGMA page_size=4096')
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA user_version=1')
        for statement in _SCHEMA.values():
            db.execute(statement)
        _append(db, {'length': 0, 'head': '0' * 64}, [('installation', marker)])
        db.commit()
    _sync_directory(controls)
    return _load(paths)


def plan_bindings(plan):
    """Pure approved-plan binding; no provider construction or credentials."""
    # Keep operation-specific dependencies out of module startup.
    from .core import content_hash, canonical_json

    # Keep operation-specific dependencies out of module startup.
    from .analysis_contracts import validate_analysis_plan, analysis_request, expected_provider_descriptor

    plan = validate_analysis_plan(plan)
    b = plan['binding']
    descriptor = expected_provider_descriptor(plan)
    request = analysis_request(plan)
    return {
        'analysis_id': plan['analysis_id'],
        'registration': b['registration'],
        'plan_hash': content_hash(plan),
        'provider_hash': content_hash(descriptor),
        'request_hash': content_hash(request),
        'request_bytes': len(canonical_json(request).encode('utf-8')),
        'model': b['model'],
        'timeout_seconds': b['timeout_seconds'],
        'ledger_basename': 'chatgpt-analysis-' + plan['analysis_id'] + '.sqlite3',
    }


@dataclass(frozen=True)
class RecoveryDisposition:
    legacy: bool
    launches: tuple
    unresolved: tuple
    workspace_unresolved: tuple
    workspace_stopped: tuple = ()  # Snapshot for display; never cached mutation authority.

    @property
    def status(self):
        return 'legacy' if self.legacy else ('unresolved' if self.unresolved else 'stopped')


def inspect_recovery(paths):
    """Read only. Missing/corrupt previously initialized controls raise."""
    state = _load(paths)
    if state is None:
        return RecoveryDisposition(True, (), (), ())
    root = os.path.normcase(os.path.abspath(paths.root))
    if root in state['workspaces'] and _directory(paths.root) != state['workspaces'][root]['identity']:
        _fail('Original workspace directory identity changed')
    launches = tuple(state['launches'].values())
    unresolved = tuple(v for v in launches if v['job_id'] not in state['receipts'])
    stopped = tuple(
        v for v in launches if v['job_id'] in state['receipts'] and v['workspace']['root'] == root and v['epoch'] == state['workspaces'][root]['epoch']
    )
    return RecoveryDisposition(False, launches, unresolved, tuple(v for v in unresolved if v['workspace']['root'] == root), stopped)


def require_operation(paths, operation):
    # These bounded operations need no stop authority. Unknown controls remain
    # unknown, but do not disable strict artifact reads or independent reports.
    if operation in SAFE_OPERATIONS:
        return None
    disposition = inspect_recovery(paths)
    if (operation in SOURCE_WRITERS | ANALYSIS_STARTS and disposition.unresolved) or (operation in WORKSPACE_MUTATIONS and disposition.workspace_unresolved):
        _fail('Original analysis stop receipt required for this operation')
    return disposition


@contextmanager
def operation_guard(paths, operation, *, timeout=LOCK_TIMEOUT):
    with admission(paths, timeout=timeout) as token:
        require_operation(paths, operation)
        yield token


def recover_control_journal(paths, *, admission):
    """Explicit SQLite rollback only, under original installation admission.

    A genuine hot journal can need writes even to read the database. Validate
    original bootstrap identity, bounded regular files and rollback-mode header
    before allowing SQLite to restore its own pre-transaction state. Never create
    a missing database or synthesize any launch, receipt or installation record.
    Read-only inspect_recovery deliberately never invokes this function.
    """
    _require_admission(paths, admission)
    if _original_marker(paths) is None:
        return False
    _, database, _ = _location(paths)
    journal = Path(str(database) + '-journal')
    present = journal.exists() or journal.is_symlink()
    if present:
        _path(journal)
        if journal.stat().st_size > MAX_DATABASE + 1024 * 1024:
            _fail('Recovery rollback journal exceeds limit')
        try:
            with closing(_connect(database, write=True)) as db:
                db.execute('SELECT sequence FROM events LIMIT 1').fetchone()
        except sqlite3.Error as exc:
            raise RecoveryError('Original control journal recovery failed') from exc
    _load(paths)  # Incomplete initialization and corrupt prior state still reject.
    return present


def register_launch(paths, *, job_id, helper_nonce, approved_plan, request, admission):
    """GUI-only call site, while GUI QLockFile and admission are both owned.

    Must commit before helper gate authorization. The helper may verify this row
    but must never register/adopt a launch itself after the GUI has disappeared.
    """
    # Keep operation-specific dependencies out of module startup.
    from .runtime_support import validate_analysis_request

    # Keep operation-specific dependencies out of module startup.
    from .core import content_hash

    _require_admission(paths, admission)
    _hex(job_id, 32)
    _hex(helper_nonce, 32)
    if helper_nonce == job_id:
        _fail('Distinct helper generation required')
    validate_analysis_request(request)
    binding = plan_bindings(approved_plan)
    if any(request[key] != binding[key] for key in ('model', 'registration', 'timeout_seconds')):
        _fail('Approved request/provider binding differs')
    packet = approved_plan['binding']['packet']
    if (
        request['campaign_reference'] != packet['provenance']['campaign_ref']
        or request['task'] != packet['context']['task']
        or sorted(request['attempt_ids']) != sorted({v['attempt_id'] for v in packet['provenance']['result_links']})
    ):
        _fail('Approved source request differs')
    recover_control_journal(paths, admission=admission)
    require_operation(paths, 'ui_analysis_run')
    state = _load(paths)
    if state is None:
        state = _initialize(paths)
    identity = _directory(paths.root)
    root = identity['root']
    workspace = state['workspaces'].get(root)
    if workspace is not None and workspace['identity'] != identity:
        _fail('Original workspace identity differs')
    if job_id in state['launches'] or any(v['analysis_id'] == binding['analysis_id'] or v['helper_nonce'] == helper_nonce for v in state['launches'].values()):
        _fail('Original analysis launch cannot be recycled')
    workspace = workspace or {'identity': identity, 'epoch': 0}
    launch = {
        **binding,
        'installation': state['marker']['installation'],
        'workspace': identity,
        'epoch': workspace['epoch'],
        'job_id': job_id,
        'source_request_hash': content_hash(request),
        'helper_protocol': _PROTOCOL,
        'helper_nonce': helper_nonce,
    }
    _validate_launch(launch)
    events = ([] if root in state['workspaces'] else [('workspace', workspace)]) + [('launch', launch)]
    _, database, _ = _location(paths)
    with closing(_connect(database, write=True)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _append(db, state, events)
    return launch


def read_launch(paths, launch_id, *, expected=None, for_admission=False):
    """Read an existing exact launch, never initialize; gate admission rejects receipts."""
    _hex(launch_id, 32)
    state = _load(paths)
    if state is None or launch_id not in state['launches']:
        _fail('Missing original analysis launch')
    launch = state['launches'][launch_id]
    identity = _directory(paths.root)
    if launch['workspace'] != identity or launch['epoch'] != state['workspaces'][identity['root']]['epoch']:
        _fail('Original workspace or restore epoch differs')
    if expected is not None and _json(launch) != _json(expected):
        _fail('Original launch binding differs')
    if for_admission and launch_id in state['receipts']:
        _fail('Stopped original launch cannot reopen its gate')
    return dict(launch)


def validate_stop_receipt(paths, launch_id, *, record=None):
    """Validate original controls and current epoch; caller holds analysis lock."""
    _hex(launch_id, 32)
    state = _load(paths)
    if state is None or launch_id not in state['launches'] or launch_id not in state['receipts']:
        _fail('Missing original analysis stop receipt')
    launch = state['launches'][launch_id]
    identity = _directory(paths.root)
    if launch['workspace'] != identity or launch['epoch'] != state['workspaces'][identity['root']]['epoch']:
        _fail('Original workspace or restore epoch differs')
    if record is not None:
        # Keep operation-specific dependencies out of module startup.
        from .core import content_hash

        bindings = plan_bindings(record['plan'])
        if any(launch[k] != v for k, v in bindings.items()) or content_hash(record['provider_descriptor']) != launch['provider_hash']:
            _fail('Original journal/plan/provider binding differs')
    return dict(launch)


class _StopPublisher:
    """Private trusted-helper capability, bound to its retained original job.

    query_original_job must query that sealed original object with its retained
    handle. Caller retains the handle through commit. A bool, failed query, PID
    absence or test receipt is never accepted. Python visibility is not a security
    boundary against same-user code; no on-disk token substitutes for the handle.
    """

    def __init__(self, paths, launch, query_original_job):
        _validate_launch(launch)
        if not callable(query_original_job):
            _fail('Original-job query required')
        self._paths, self._launch = paths, _decode(_json(launch))
        self._query = query_original_job

    def publish(self):
        observed = self._query()
        if type(observed) is not int or observed != 0:
            _fail('Original job is not observably empty')
        paths, launch = self._paths, self._launch
        with admission(paths) as ownership:
            recover_control_journal(paths, admission=ownership)
            state = _load(paths)
            if state is None or state['launches'].get(launch['job_id']) != launch:
                _fail('Original launch registration differs')
            if launch['workspace'] != _directory(paths.root) or launch['epoch'] != state['workspaces'][launch['workspace']['root']]['epoch']:
                _fail('Original workspace or epoch differs')
            receipt = {'protocol': _PROTOCOL, 'job_id': launch['job_id'], 'launch_hash': _hash(launch), 'active_processes': 0}
            if launch['job_id'] in state['receipts']:
                if state['receipts'][launch['job_id']] != receipt:
                    _fail('Conflicting original stop receipt')
                return receipt
            _, database, _ = _location(paths)
            with closing(_connect(database, write=True)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                _append(db, state, [('receipt', receipt)])
            return receipt


def advance_restore_epoch(paths, transaction_id, *, admission):
    """Before promotion, never reversed by rollback; repeated transaction is safe."""
    _require_admission(paths, admission)
    _hex(transaction_id, 32)
    require_operation(paths, 'ui_backup_restore')
    state = _load(paths)
    if state is None:
        return None  # Legacy restoration never initializes/adopts recovery controls.
    identity = _directory(paths.root)
    root = identity['root']
    if root not in state['workspaces']:
        return None
    if state['workspaces'][root]['identity'] != identity:
        _fail('Original workspace identity differs')
    if (root, transaction_id) in state['transactions']:
        return state['workspaces'][root]['epoch']
    value = {'root': root, 'transaction_id': transaction_id, 'epoch': state['workspaces'][root]['epoch'] + 1}
    _, database, _ = _location(paths)
    with closing(_connect(database, write=True)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _append(db, state, [('epoch', value)])
    return value['epoch']
