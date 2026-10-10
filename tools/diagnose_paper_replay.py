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
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.values = {}
        self.stack = []
        self.boundaries = {}

    @contextmanager
    def measure(self, name):
        started = time.monotonic()
        with self.lock:
            self.stack.append((name, started))
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            with self.lock:
                self.stack.pop()
                value = self.values.setdefault(name, {'calls': 0, 'seconds': 0.0})
                value['calls'] += 1
                value['seconds'] += elapsed

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
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


def _diagnosed_worker(sender, gate, operation, payload, root, bootstrap, job_id):
    if operation != 'ui_paper_replay':
        return _original_worker(sender, gate, operation, payload, root, bootstrap, job_id)
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
            _original_worker(Sender(), gate, operation, payload, root, bootstrap, job_id)
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--broker-child', choices=['before_event_commit', 'after_event_commit'])
    parser.add_argument('--journal-child', choices=['DELETE', 'TRUNCATE', 'PERSIST'])
    parser.add_argument('--journal-root', type=Path)
    parser.add_argument('--persistence-only', action='store_true')
    args = parser.parse_args()
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
