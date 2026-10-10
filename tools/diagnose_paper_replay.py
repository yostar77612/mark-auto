"""Offline timing observation only; never substitutes for the 30s native gate.

Runs the same typed 960-bar / 120000-margin UI and spawned-worker flow with a
separate 180s overall observation limit. SQLite calls retain their exact SQL,
transactions and durability settings. Timings are inclusive and overlap.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from quantlab.desktop_runtime import _job_worker as _original_worker


class Timings:
    def __init__(self):
        self.started = time.perf_counter()
        self.lock = threading.RLock()
        self.values = {}
        self.stack = []
        self.boundaries = {}

    @contextmanager
    def measure(self, name):
        started = time.perf_counter()
        with self.lock:
            self.stack.append((name, started))
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self.lock:
                self.stack.pop()
                value = self.values.setdefault(name, {'calls': 0, 'seconds': 0.0})
                value['calls'] += 1
                value['seconds'] += elapsed

    def snapshot(self):
        with self.lock:
            now = time.perf_counter()
            return {'elapsed_seconds': now - self.started,
                    'timings': {key: dict(value) for key, value in self.values.items()},
                    'active': [{'phase': name, 'seconds': now - started} for name, started in self.stack],
                    'boundaries': dict(self.boundaries)}


def _database_role(path):
    path = Path(path)
    if path.name.endswith('.lock'):
        return 'replay_lock'
    return 'replay' if path.parent.name == 'replays' else 'broker'


def _instrument_connect(real_connect, timings):
    class TimedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            verb = sql.lstrip().split(None, 1)[0].upper()
            category = 'read' if verb == 'SELECT' else 'pragma' if verb == 'PRAGMA' else 'begin' if verb == 'BEGIN' else 'write'
            if sql.startswith('UPDATE replay SET cursor='):
                category = 'cursor_write'
                self.transaction_kind = 'cursor_commit'
            elif sql.startswith('UPDATE replay SET plan='):
                category = 'plan_write'
                self.transaction_kind = 'plan_commit'
            if verb in ('CREATE', 'INSERT', 'UPDATE', 'DELETE', 'ALTER'):
                self.transaction_dirty = True
            with timings.measure(self.role + '.' + category):
                return super().execute(sql, parameters)

        def commit(self):
            category = '.write_commit' if getattr(self, 'transaction_dirty', False) else '.read_commit'
            try:
                with timings.measure(self.role + '.commit'), timings.measure(self.role + category):
                    return super().commit()
            finally:
                self.transaction_dirty = False

        def rollback(self):
            with timings.measure(self.role + '.rollback'):
                return super().rollback()

        def __exit__(self, *args):
            category = '.transaction_exit' if self.in_transaction else '.read_exit'
            kind = getattr(self, 'transaction_kind', None)
            if kind and args and args[0] is not None:
                kind = kind.replace('_commit', '_rollback')
            try:
                with timings.measure(self.role + category):
                    if kind:
                        with timings.measure(self.role + '.' + kind):
                            return super().__exit__(*args)
                    return super().__exit__(*args)
            finally:
                self.transaction_dirty = False
                self.transaction_kind = None

        def close(self):
            with timings.measure(self.role + '.close'):
                return super().close()

    def connect(database, *args, **kwargs):
        if 'factory' in kwargs:
            raise ValueError('Diagnostic does not replace caller connection factories')
        role = _database_role(database)
        with timings.measure(role + '.connect'):
            connection = real_connect(database, *args, factory=TimedConnection, **kwargs)
        connection.role = role
        return connection
    return connect


def _write_json(path, value):
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True).encode('utf-8')
    if len(raw) > 256 * 1024:
        raise ValueError('Diagnostic report exceeded its bound')
    partial = path.with_suffix('.partial')
    partial.write_bytes(raw)
    os.replace(partial, path)


def _filesystem(root):
    result = {'synthetic_workspace': str(root)}
    if sys.platform == 'win32':
        import ctypes
        volume = ctypes.create_unicode_buffer(1024)
        fs = ctypes.create_unicode_buffer(1024)
        kernel = ctypes.windll.kernel32
        if kernel.GetVolumePathNameW(str(root), volume, len(volume)):
            result['volume_root'] = volume.value
            if kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, fs, len(fs)):
                result['filesystem'] = fs.value
    else:
        info = os.statvfs(root)
        result['filesystem_block_size'] = info.f_bsize
    return result


def _diagnosed_worker(sender, gate, operation, payload, root, bootstrap, job_id,
                      reconciliation_admitted=False):
    if operation != 'ui_paper_replay':
        return _original_worker(sender, gate, operation, payload, root, bootstrap, job_id,
                                reconciliation_admitted)
    timings = Timings()
    target = Path(os.environ['MARKAUTO_DIAGNOSTIC_OUTPUT']) / (job_id + '.json')
    metadata = {'observation_only': True, 'worker_pid': os.getpid(), 'operation': operation,
                'python': sys.version, 'sqlite': sqlite3.sqlite_version,
                'os': platform.platform(), 'os_build': platform.version(), **_filesystem(root)}
    stop = threading.Event()
    def report():
        _write_json(target, {**metadata, **timings.snapshot()})
    def periodic():
        while not stop.wait(1):
            report()
    report()
    writer = threading.Thread(target=periodic, daemon=True)
    writer.start()
    import quantlab.paper as paper
    import quantlab.paper_replay as replay
    sqlite3.connect = _instrument_connect(sqlite3.connect, timings)
    original_connection = replay.PaperReplay._connection
    @contextmanager
    def observed_connection(self):
        with original_connection(self) as db:
            metadata['replay_storage'] = {
                'requested_profile': self.storage_profile,
                'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0],
                'synchronous': db.execute('PRAGMA synchronous').fetchone()[0],
                'wal_autocheckpoint': db.execute('PRAGMA wal_autocheckpoint').fetchone()[0],
                'sqlite_source_id': db.execute('SELECT sqlite_source_id()').fetchone()[0],
            }
            yield db
    replay.PaperReplay._connection = observed_connection
    def wrap(cls, name, label):
        original = getattr(cls, name)
        def call(self, *args, **kwargs):
            with timings.measure(label):
                return original(self, *args, **kwargs)
        setattr(cls, name, call)
    for cls, name, label in ((paper.PaperBroker, '_restore', 'broker.restore'),
                            (paper.PaperBroker, 'snapshot', 'broker.snapshot'),
                            (replay.PaperReplay, '__init__', 'replay.initialize_and_preflight'),
                            (replay.PaperReplay, 'snapshot', 'replay.snapshot'),
                            (replay.PaperReplay, '_quote_policy', 'replay.policy'),
                            (replay.PaperReplay, 'step', 'replay.step')):
        wrap(cls, name, label)
    original_fault = replay.PaperReplay._fault
    def boundary(self, point):
        original_fault(self, point)
        with timings.lock:
            timings.boundaries[point] = timings.boundaries.get(point, 0) + 1
    replay.PaperReplay._fault = boundary
    class Sender:
        def send_bytes(self, value):
            with timings.measure('ipc.send'):
                sender.send_bytes(value)
        def close(self):
            sender.close()
    try:
        with timings.measure('worker.body'):
            _original_worker(Sender(), gate, operation, payload, root, bootstrap, job_id,
                             reconciliation_admitted)
    finally:
        stop.set()
        writer.join()
        report()


def _broker_probe(output, point):
    # Reproduce the original process-death fixture, including its first setup
    # broker, then the second durable broker, reconciliation, submit and fill.
    timings = Timings()
    with timings.measure('fixture.imports'):
        from tests.test_paper import PaperTests
        from quantlab.paper import PaperBroker
    sqlite3.connect = _instrument_connect(sqlite3.connect, timings)
    fixture = PaperTests()
    def record(phase):
        _write_json(output, {'probe': point, 'phase': phase, **_filesystem(fixture.tmp.name), **timings.snapshot()})
    for label, action in (
            ('fixture.setup', lambda: fixture.setUp()),
            ('fixture.second_broker', lambda: setattr(fixture, 'broker', PaperBroker(Path(fixture.tmp.name) / 'second.sqlite3', **fixture.kw))),
            ('fixture.reconcile', lambda: fixture.broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))),
            ('fixture.submit', lambda: fixture.submit())):
        with timings.measure(label):
            action()
        record(label)
    def fail(boundary):
        if boundary == point:
            record(boundary)
            os._exit(73)
    fixture.broker._fault = fail
    with timings.measure('fixture.apply_event'):
        fixture.broker.apply_event(fixture.event())
    return 1  # The exact synthetic death boundary must have been reached.


def _process_probes(directory, deadline):
    import subprocess
    result = []
    commands = [('python_bootstrap', [sys.executable, '-c', 'pass'], 0)]
    for point in ('before_event_commit', 'after_event_commit'):
        output = directory / ('probe-' + point + '.json')
        commands.append((point, [sys.executable, str(Path(__file__).resolve()), str(output), '--broker-child', point], 73))
    for name, command, expected in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Diagnostic observation deadline reached')
        started = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, timeout=min(30, remaining),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            entry = {'probe': name, 'seconds': time.monotonic() - started,
                     'returncode': completed.returncode, 'expected_exit': completed.returncode == expected}
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for this no-descendant probe.
            entry = {'probe': name, 'seconds': time.monotonic() - started, 'timed_out': True}
        result.append(entry)
    return result


@contextmanager
def _rollback_connection(connect, path, mode):
    if mode not in ('DELETE', 'TRUNCATE', 'PERSIST'):
        raise ValueError('Unsupported diagnostic rollback mode')
    db = connect(path, timeout=1)
    try:
        selected = db.execute('PRAGMA journal_mode=' + mode).fetchone()[0]
        db.execute('PRAGMA synchronous=FULL')
        if selected != mode.lower() or db.execute('PRAGMA synchronous').fetchone()[0] != 2:
            raise RuntimeError('Diagnostic storage settings not accepted')
        with db:
            yield db
    finally:
        db.close()


def _journal_mode_probe(output, mode, root):
    """960 disposable cursor commits; no application database is ever opened."""
    if mode not in ('DELETE', 'TRUNCATE', 'PERSIST'):
        raise ValueError('Unsupported diagnostic rollback mode')
    root = Path(root)
    path = root / 'replays' / (mode.lower() + '.sqlite3')
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        raise ValueError('Diagnostic database must be new')
    timings = Timings()
    connect = _instrument_connect(sqlite3.connect, timings)
    metadata = {'probe': 'rollback_journal_comparison', 'mode': mode,
                'sqlite': sqlite3.sqlite_version, 'commits_expected': 960,
                'verified_pragmas': {'journal_mode': mode.lower(), 'synchronous': 2},
                **_filesystem(root)}
    consumed = 0
    def record(complete=False):
        _write_json(output, {**metadata, 'complete': complete,
                            'commits_completed': consumed, **timings.snapshot()})
    def connection():
        return _rollback_connection(connect, path, mode)
    with connection() as db:
        db.execute('CREATE TABLE replay (id INTEGER PRIMARY KEY, binding TEXT, cursor INTEGER, active INTEGER, plan TEXT)')
        db.execute('INSERT INTO replay VALUES (1, ?, 0, 1, NULL)', ('0' * 64,))
    record()
    last_report = time.monotonic()
    for index in range(960):
        # Match the ordinary empty-bar read/open/close and durable cursor shape.
        with connection() as db:
            row = db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone()
            if row != (index, 1, None):
                raise RuntimeError('Diagnostic cursor did not persist')
        with connection() as db:
            if db.execute('SELECT plan FROM replay WHERE id=1').fetchone()[0] is not None:
                raise RuntimeError('Unexpected diagnostic plan')
            db.execute('UPDATE replay SET cursor=cursor+1,plan=NULL WHERE id=1')
        consumed += 1
        if time.monotonic() - last_report >= 1:
            record()
            last_report = time.monotonic()
    class RollbackProbe(Exception):
        pass
    try:
        with connection() as db:
            db.execute('UPDATE replay SET cursor=-1 WHERE id=1')
            raise RollbackProbe()
    except RollbackProbe:
        pass
    # An ordinary new connection must recover the exact durable cursor, including
    # after the deliberate rollback. This also exercises default-mode reopening.
    db = sqlite3.connect(path, timeout=1)
    try:
        if db.execute('SELECT cursor FROM replay WHERE id=1').fetchone()[0] != 960:
            raise RuntimeError('Diagnostic durable cursor verification failed')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Diagnostic database integrity failed')
    finally:
        db.close()
    metadata['rollback_and_reopen_verified'] = True
    record(complete=True)
    return 0


def _journal_mode_comparison(directory, deadline):
    import subprocess
    import tempfile
    results = []
    # The controller owns the entire disposable tree, even if a probe is killed.
    # subprocess.run waits for the no-descendant child before this tree is removed.
    with tempfile.TemporaryDirectory(prefix='paper-sync-comparison-') as root:
        for mode in ('DELETE', 'TRUNCATE', 'PERSIST'):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                results.append({'mode': mode, 'complete': False, 'not_started': True, 'reason': 'deadline'})
                continue
            output = directory / ('journal-' + mode.lower() + '.json')
            command = [sys.executable, str(Path(__file__).resolve()), str(output),
                       '--journal-child', mode, '--journal-root', root]
            started = time.monotonic()
            try:
                completed = subprocess.run(command, cwd=ROOT, timeout=remaining,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                entry = {'mode': mode, 'seconds': time.monotonic() - started,
                         'returncode': completed.returncode, 'complete': completed.returncode == 0}
            except subprocess.TimeoutExpired:
                entry = {'mode': mode, 'seconds': time.monotonic() - started,
                         'timed_out': True, 'complete': False}
            if output.exists():
                observation = json.loads(output.read_text(encoding='utf-8'))
                entry['complete'] = (entry['complete'] and observation.get('complete') is True
                    and observation.get('mode') == mode and observation.get('commits_completed') == 960
                    and observation.get('verified_pragmas') == {'journal_mode': mode.lower(), 'synchronous': 2}
                    and observation.get('rollback_and_reopen_verified') is True
                    and observation.get('timings', {}).get('replay.cursor_commit', {}).get('calls') == 960)
            else:
                entry['complete'] = False
            results.append(entry)
    return results


def observe(output, *, limit=180):
    """Use normal controls and the original JobManager, with a diagnostic deadline."""
    started = time.monotonic()
    deadline = started + limit - 6  # Reserve the existing worker cancellation budget.
    from decimal import Decimal
    from tests.test_desktop_ui import NativeDesktopTests
    import quantlab.desktop_runtime as runtime
    from quantlab.reporting import read_json
    from desktop_ui import paper_risk_limits
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    worker_dir = Path(tempfile.mkdtemp(prefix='paper-timing-', dir=output.parent))
    os.environ['MARKAUTO_DIAGNOSTIC_OUTPUT'] = str(worker_dir)
    original = runtime._job_worker
    runtime._job_worker = _diagnosed_worker
    report = {'observation_only': True, 'acceptance_timeout_unchanged': 30,
              'observation_limit_seconds': limit, 'bars': 960, 'margin': '120000',
              'python': sys.version, 'sqlite': sqlite3.sqlite_version,
              'os': platform.platform(), 'os_build': platform.version(), 'jobs': []}
    fixture = None
    def action(name):
        began = time.monotonic()
        if began >= deadline:
            raise TimeoutError('Diagnostic observation deadline reached')
        fixture.click(name)
        while fixture.jobs.active and time.monotonic() < deadline:
            fixture.app.processEvents()
            fixture.window.poll_jobs()
            time.sleep(.02)
        elapsed = time.monotonic() - began
        if fixture.jobs.active:
            fixture.jobs.cancel()  # Existing platform process-tree cleanup.
            raise TimeoutError('Diagnostic observation deadline reached')
        fixture.window.poll_jobs()
        if '失敗' in fixture.window.status.text():
            raise AssertionError('Diagnostic worker reported failure')
        report['jobs'].append({'action': name, 'seconds': elapsed})
    try:
        report['process_probes'] = _process_probes(worker_dir, deadline)
        NativeDesktopTests.setUpClass()
        fixture = NativeDesktopTests()
        fixture.setUp()
        action('create_demo')
        action('run_backtest')
        action('select_strategy')
        fixture.click('demo_policy')
        fixture.window.policy_form.margins.table.item(0, 1).setText('120000')
        fixture.window.policy_form.margins.table.item(0, 2).setText('typed-synthetic-120000-v1')
        typed = fixture.window.policy_form.build_payload()
        assert typed['margin_schedule'][0]['margin_per_contract'] == '120000'
        action('paper_snapshot')
        action('paper_reconcile')
        fixture.window.replay_bars.setValue(1000)
        fixture.window.paper_confirm.setChecked(True)
        action('paper_replay')
        result = json.loads(fixture.window.paper_detail.toPlainText())
        assert result['replay']['total_bars'] == 960 and result['replay']['complete']
        assert result['account']['fills'] and result['account']['kill_switch']
        assert not fixture.window.paper_confirm.isChecked()
        assert read_json(fixture.paths.state / 'paper_policy.json') == typed
        limits = paper_risk_limits()
        assert (limits.max_position, limits.max_order_quantity, limits.max_daily_loss) == (1, 1, Decimal('1000'))
        fixture.window.snapshot_form.from_payload(result['account'])
        fixture.window.paper_confirm.setChecked(True)
        action('paper_replay')
        repeated = json.loads(fixture.window.paper_detail.toPlainText())
        assert repeated['replay']['binding'] == result['replay']['binding']
        for key in ('fills', 'orders', 'positions', 'cash', 'order_send_timestamps'):
            assert repeated['account'][key] == result['account'][key]
        report.update(status='measured', complete=True, cursor=result['replay']['cursor'],
                      orders=len(result['account']['orders']), fills=len(result['account']['fills']))
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='observation_incomplete', complete=False, error_type=type(error).__name__)
    finally:
        if fixture is not None:
            cleanup_ok = fixture.doCleanups()
            report['workers_stopped'] = not fixture.jobs.active
            if not cleanup_ok or fixture.jobs.active:
                report.update(status='cleanup_failed', complete=False)
        runtime._job_worker = original
        report['elapsed_seconds'] = time.monotonic() - started
        report['workers'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(worker_dir.glob('*.json')) if not path.name.startswith('probe-')]
        report['broker_probe_details'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(worker_dir.glob('probe-*.json'))]
        _write_json(output, report)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True), flush=True)
    return 0 if report['status'] == 'measured' and report['workers'] else 1


def observe_persistence(output, *, limit=180):
    """Separate bounded calibration; it never runs or replaces an acceptance test."""
    import tempfile
    started = time.monotonic()
    deadline = started + limit - 6
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='paper-journal-timing-', dir=output.parent))
    report = {'observation_only': True, 'kind': 'rollback_journal_comparison',
              'observation_limit_seconds': limit, 'commits_per_mode': 960,
              'python': sys.version, 'sqlite': sqlite3.sqlite_version,
              'os': platform.platform(), 'os_build': platform.version(),
              'status': 'observation_incomplete', 'complete': False}
    try:
        report['comparisons'] = _journal_mode_comparison(directory, deadline)
        if len(report['comparisons']) == 3 and all(item['complete'] for item in report['comparisons']):
            report.update(status='measured', complete=True)
    except (Exception, KeyboardInterrupt) as error:
        report['error_type'] = type(error).__name__
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        report['details'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(directory.glob('journal-*.json'))]
        _write_json(output, report)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True), flush=True)
    return 0 if report['complete'] else 1



CONNECTION_PROFILES = ('delete-reopen', 'delete-step', 'persist-reopen', 'persist-step')
CONNECTION_BLOCK_COMMITS = 120


def _probe_connection(connect, path, profile):
    if profile not in CONNECTION_PROFILES:
        raise ValueError('Unsupported connection comparison profile')
    db = connect(path, timeout=1)
    try:
        mode = profile.split('-')[0]
        if db.execute('PRAGMA journal_mode=' + mode.upper()).fetchone() != (mode,):
            raise RuntimeError('Diagnostic journal mode not accepted')
        db.execute('PRAGMA synchronous=FULL')
        if (db.execute('PRAGMA synchronous').fetchone() != (2,)
                or db.execute('PRAGMA locking_mode').fetchone() != ('normal',)):
            raise RuntimeError('Diagnostic FULL/normal settings not accepted')
        return db
    except BaseException:
        db.close()
        raise



def _owned_connection_path(root, profile):
    root = Path(root)
    owner = json.loads((root / 'connection-probe-owner.json').read_text(encoding='utf-8'))
    if (not root.name.startswith('paper-connection-probe-')
            or owner != {'profile': profile, 'controller_pid': os.getppid()}):
        raise ValueError('Connection probe must use its controller-owned fixture')
    return root / 'replays' / 'probe.sqlite3'


def _connection_observer(output, profile, root, action):
    """Controller-owned sibling process; never spawns descendants."""
    if action not in ('stop', 'start'):
        raise ValueError('Unsupported diagnostic observer action')
    path = _owned_connection_path(root, profile)
    if not path.is_file():
        raise ValueError('Missing owned diagnostic database')
    expected = CONNECTION_BLOCK_COMMITS
    before, after = (1, 0) if action == 'stop' else (0, 1)
    db = _probe_connection(sqlite3.connect, path, profile)
    try:
        if db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone() != (expected, before, None):
            raise RuntimeError('Observer did not read the committed boundary')
        with db:
            db.execute('UPDATE replay SET active=? WHERE id=1', (after,))
    finally:
        db.close()
    db = _probe_connection(sqlite3.connect, path, profile)
    try:
        if db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone() != (expected, after, None):
            raise RuntimeError('Observer control write did not survive reopen')
    finally:
        db.close()
    _write_json(output, {'action': action, 'cursor': expected, 'active': after,
                         'committed_and_reopened': True, 'pid': os.getpid()})
    return 0


def _connection_probe(output, profile, root):
    """One fixed 120-commit block, using only a newly owned disposable file."""
    output, root = Path(output), Path(root)
    path = _owned_connection_path(root, profile)
    path.parent.mkdir()
    if path.exists():
        raise ValueError('Diagnostic database must be new')
    timings = Timings()
    connect = _instrument_connect(sqlite3.connect, timings)
    held = None
    consumed = 0
    report = {'profile': profile, 'complete': False, 'phase': 'setup',
              'commits_expected': CONNECTION_BLOCK_COMMITS,
              'verified_pragmas': {'journal_mode': profile.split('-')[0],
                                   'synchronous': 2, 'locking_mode': 'normal'},
              'sqlite': sqlite3.sqlite_version, 'pid': os.getpid(), **_filesystem(root)}
    def record():
        _write_json(output, {**report, 'commits_completed': consumed, **timings.snapshot()})
    @contextmanager
    def transaction():
        db = held if held is not None else _probe_connection(connect, path, profile)
        try:
            with db:
                yield db
            if db.in_transaction:
                raise RuntimeError('Diagnostic transaction remained open')
        finally:
            if held is None:
                db.close()
    def observe_control(action, active):
        report['phase'] = 'waiting_external_' + action
        record()
        # Write-once readiness avoids Windows replace/read sharing races.
        _write_json(output.with_suffix('.ready-' + action + '.json'),
                    {'action': action, 'cursor': consumed, 'pid': os.getpid()})
        witness = output.with_suffix('.' + action + '.json')
        end = time.monotonic() + 10
        while not witness.exists():
            if time.monotonic() >= end:
                raise TimeoutError('External diagnostic control did not arrive')
            time.sleep(.02)
        proof = json.loads(witness.read_text(encoding='utf-8'))
        if (proof.get('action') != action or proof.get('cursor') != consumed
                or proof.get('active') != active or proof.get('committed_and_reopened') is not True
                or proof.get('pid') == os.getpid()):
            raise RuntimeError('Invalid external diagnostic control proof')
        with transaction() as db:
            if db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone() != (consumed, active, None):
                raise RuntimeError('Retained connection did not see external control')
        report['external_' + action] = proof
    try:
        with transaction() as db:
            db.execute('CREATE TABLE replay (id INTEGER PRIMARY KEY, binding TEXT, cursor INTEGER, active INTEGER, plan TEXT)')
            db.execute('INSERT INTO replay VALUES (1, ?, 0, 1, NULL)', ('0' * 64,))
        if profile.endswith('-step'):
            held = _probe_connection(connect, path, profile)
        report['phase'] = 'cursor_loop'
        record()
        with timings.measure('replay.cursor_loop'):
            for index in range(CONNECTION_BLOCK_COMMITS):
                with transaction() as db:
                    if db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone() != (index, 1, None):
                        raise RuntimeError('Diagnostic cursor did not persist')
                with transaction() as db:
                    if db.execute('SELECT plan FROM replay WHERE id=1').fetchone() != (None,):
                        raise RuntimeError('Unexpected diagnostic plan')
                    db.execute('UPDATE replay SET cursor=cursor+1,plan=NULL WHERE id=1')
                consumed += 1
                if consumed % 30 == 0:
                    record()  # Preserve observed progress if the controller deadline expires.
        # First connection is still open for the step profile, with no transaction.
        # The controller, not this child, launches each external control process.
        observe_control('stop', 0)
        observe_control('start', 1)
        class RollbackProbe(Exception):
            pass
        try:
            with transaction() as db:
                db.execute('UPDATE replay SET cursor=-1 WHERE id=1')
                raise RollbackProbe()
        except RollbackProbe:
            pass
        if held is not None:
            with timings.measure('replay.final_close'):
                held.close()
            held = None
        with transaction() as db:
            if db.execute('SELECT cursor,active,plan FROM replay WHERE id=1').fetchone() != (consumed, 1, None):
                raise RuntimeError('Diagnostic rollback/reopen did not preserve cursor')
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise RuntimeError('Diagnostic integrity check failed')
        journal = Path(str(path) + '-journal')
        report.update(complete=True, phase='complete', rollback_and_reopen_verified=True,
                      external_control_verified=True,
                      journal_after_close={'exists': journal.exists(),
                          'bytes': journal.stat().st_size if journal.exists() else 0,
                          'header': journal.read_bytes()[:28].hex() if journal.exists() else ''})
    except (Exception, KeyboardInterrupt) as error:
        report.update(complete=False, phase='failed', error_type=type(error).__name__)
    finally:
        if held is not None:
            try:
                held.close()
            except Exception as error:
                report.update(complete=False, phase='close_failed', error_type=type(error).__name__)
        record()
    return 0 if report['complete'] else 1


def _connection_case(output, profile, base, deadline):
    """Controller owns fixture cleanup and every direct, no-descendant child."""
    import subprocess
    import tempfile
    result = {'profile': profile, 'complete': False, 'workers_stopped': True}
    if time.monotonic() >= deadline:
        return {**result, 'not_started': True, 'reason': 'deadline'}
    started = time.perf_counter()
    import shutil
    root = tempfile.mkdtemp(prefix='paper-connection-probe-', dir=base)
    try:
        _write_json(Path(root) / 'connection-probe-owner.json', {'profile': profile, 'controller_pid': os.getpid()})
        result['fixture_root'] = root
        command = [sys.executable, str(Path(__file__).resolve()), str(output),
                   '--connection-child', profile, '--connection-root', root]
        child = None
        children = []
        observer_actions = []
        try:
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(child)
            result['workers_stopped'] = False
            while child.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 0)
                for action in ('stop', 'start'):
                    ready = output.with_suffix('.ready-' + action + '.json')
                    if ready.exists() and action not in observer_actions:
                        observer = [sys.executable, str(Path(__file__).resolve()),
                            str(output.with_suffix('.' + action + '.json')),
                            '--connection-child', profile, '--connection-root', root,
                            '--connection-observer', action]
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(observer, 0)
                        helper = subprocess.Popen(observer, cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        children.append(helper)
                        helper.wait(timeout=min(8, remaining))
                        observer_actions.append(action)
                        if helper.returncode != 0:
                            raise RuntimeError('External diagnostic observer failed')
                time.sleep(.02)
            result['returncode'] = child.returncode
        except subprocess.TimeoutExpired:
            result['timed_out'] = True
        except (Exception, KeyboardInterrupt) as error:
            result['error_type'] = type(error).__name__
        finally:
            # One shared cleanup reserve for the probe and all sibling observers.
            cleanup_end = min(deadline + 6, time.monotonic() + 6)
            for owned in children:
                if owned.poll() is None:
                    try:
                        owned.terminate()
                    except OSError as error:
                        result['cleanup_error_type'] = type(error).__name__
            terminate_end = min(cleanup_end, time.monotonic() + 3)
            for owned in children:
                try:
                    owned.wait(timeout=max(0, terminate_end - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
                except OSError as error:
                    result['cleanup_error_type'] = type(error).__name__
            for owned in children:
                if owned.poll() is None:
                    try:
                        owned.kill()
                    except OSError as error:
                        result['cleanup_error_type'] = type(error).__name__
            for owned in children:
                try:
                    owned.wait(timeout=max(0, cleanup_end - time.monotonic()))
                except (OSError, subprocess.TimeoutExpired) as error:
                    result['cleanup_error_type'] = type(error).__name__
            result['workers_stopped'] = all(owned.poll() is not None for owned in children)
            result['children'] = [{'pid': owned.pid, 'returncode': owned.returncode} for owned in children]
            result['observer_actions_completed'] = observer_actions
        if result['workers_stopped'] and output.exists():
            observation = json.loads(output.read_text(encoding='utf-8'))
            result['observation'] = observation
            result['complete'] = (result.get('returncode') == 0 and result['workers_stopped']
                and observer_actions == ['stop', 'start'] and observation.get('complete') is True
                and observation.get('profile') == profile
                and observation.get('commits_completed') == CONNECTION_BLOCK_COMMITS
                and observation.get('verified_pragmas') == {'journal_mode': profile.split('-')[0],
                    'synchronous': 2, 'locking_mode': 'normal'}
                and observation.get('external_control_verified') is True
                and observation.get('rollback_and_reopen_verified') is True
                and observation.get('timings', {}).get('replay.cursor_commit', {}).get('calls') == CONNECTION_BLOCK_COMMITS
                and observation.get('timings', {}).get('replay.cursor_rollback', {}).get('calls') == 1)
    finally:
        # A failed process teardown is a blocker, never permission to delete live state.
        if result['workers_stopped']:
            try:
                shutil.rmtree(root)
            except OSError as error:
                result['cleanup_error_type'] = type(error).__name__
        result['fixture_removed'] = not Path(root).exists()
    result['seconds'] = time.perf_counter() - started
    result['complete'] = result['complete'] and result['fixture_removed']
    return result


def _connection_location(path):
    import shutil
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Diagnostic root must be an existing directory')
    return {'canonical_path': str(path), 'device_id': path.stat().st_dev,
            'free_bytes': shutil.disk_usage(path).free, **_filesystem(path)}


def observe_connections(output, *, limit=180):
    """Fixed 2x120 commits/profile; never changes TEMP or runs acceptance tests."""
    import tempfile
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='paper-connection-timing-', dir=output.parent))
    started = time.monotonic()
    deadline = started + limit - 6
    report = {'observation_only': True, 'kind': 'connection_and_volume_comparison',
              'acceptance_timeout_unchanged': 30, 'acceptance_workload_unchanged': 960,
              'observation_limit_seconds': limit, 'blocks': 2,
              'commits_per_block': CONNECTION_BLOCK_COMMITS,
              'commits_per_profile': 2 * CONNECTION_BLOCK_COMMITS,
              'python': sys.version, 'sqlite': sqlite3.sqlite_version,
              'os': platform.platform(), 'os_build': platform.version(),
              'status': 'observation_incomplete', 'complete': False, 'comparisons': [],
              'environment': {key: os.environ.get(key) for key in ('TEMP', 'TMP', 'RUNNER_TEMP', 'ImageOS', 'ImageVersion')}}
    try:
        os_temp = _connection_location(tempfile.gettempdir())
        report['os_temp'] = os_temp
        runner_value = os.environ.get('RUNNER_TEMP')
        runner_temp = _connection_location(runner_value) if runner_value else None
        report['runner_temp'] = runner_temp
        if runner_temp:
            report['same_canonical_root'] = Path(os_temp['canonical_path']) == Path(runner_temp['canonical_path'])
            report['same_volume'] = os_temp['device_id'] == runner_temp['device_id']
        cases = [('os_temp', profile, os_temp['canonical_path']) for profile in CONNECTION_PROFILES]
        cases.append(('runner_temp', 'delete-reopen', runner_temp['canonical_path'] if runner_temp else None))
        for block in range(2):
            for location, profile, base in (cases if block == 0 else list(reversed(cases))):
                key = str(block) + '-' + location + '-' + profile
                if base is None:
                    entry = {'profile': profile, 'complete': False, 'not_started': True,
                             'workers_stopped': True, 'reason': 'RUNNER_TEMP unavailable'}
                else:
                    entry = _connection_case(directory / (key + '.json'), profile, base, deadline)
                report['comparisons'].append({'block': block, 'location': location, **entry})
                _write_json(output, report)
                if entry.get('workers_stopped') is not True:
                    raise RuntimeError('Connection diagnostic child teardown failed')
        if len(report['comparisons']) == 10 and all(item['complete'] for item in report['comparisons']):
            report.update(status='measured', complete=True)
    except (Exception, KeyboardInterrupt) as error:
        report['error_type'] = type(error).__name__
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        report['workers_stopped'] = all(item.get('workers_stopped') is True for item in report['comparisons'])
        _write_json(output, report)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True), flush=True)
    return 0 if report['complete'] and report['workers_stopped'] else 1


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--broker-child', choices=['before_event_commit', 'after_event_commit'])
    parser.add_argument('--journal-child', choices=['DELETE', 'TRUNCATE', 'PERSIST'])
    parser.add_argument('--journal-root', type=Path)
    parser.add_argument('--persistence-only', action='store_true')
    parser.add_argument('--connections-only', action='store_true')
    parser.add_argument('--connection-child', choices=CONNECTION_PROFILES)
    parser.add_argument('--connection-root', type=Path)
    parser.add_argument('--connection-observer', choices=['stop', 'start'])
    args = parser.parse_args()
    if args.connections_only or args.connection_child or args.connection_root or args.connection_observer:
        if args.persistence_only or args.journal_child or args.journal_root or args.broker_child:
            parser.error('Connection comparison cannot combine other diagnostic modes')
        if args.connections_only:
            if args.connection_child or args.connection_root or args.connection_observer:
                parser.error('Connection controller cannot combine child arguments')
            return observe_connections(args.output)
        if not args.connection_child or not args.connection_root:
            parser.error('Connection child requires its profile and owned fixture root')
        if args.connection_observer:
            return _connection_observer(args.output, args.connection_child, args.connection_root, args.connection_observer)
        return _connection_probe(args.output, args.connection_child, args.connection_root)
    if args.persistence_only:
        if args.journal_child or args.journal_root or args.broker_child:
            parser.error('Persistence-only mode cannot combine child arguments')
        return observe_persistence(args.output)
    if args.journal_child:
        if args.journal_root is None or args.broker_child:
            parser.error('Journal probe requires its owned fixture directory')
        return _journal_mode_probe(args.output, args.journal_child, args.journal_root)
    if args.broker_child:
        return _broker_probe(args.output, args.broker_child)
    return observe(args.output)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
