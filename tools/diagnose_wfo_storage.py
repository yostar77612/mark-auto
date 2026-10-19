"""Bounded synthetic WFO storage A/B observation, never a product acceptance gate."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
MODES = ('DELETE', 'PERSIST', 'PERSIST', 'DELETE', 'DELETE')
WAL_MODES = ('DELETE', 'WAL', 'WAL', 'DELETE')
WAL_ROUNDS = tuple(('journal_mode', mode, 'replace') for mode in WAL_MODES) + tuple(
    ('sql_operation', 'DELETE', operation) for operation in ('replace', 'upsert', 'upsert', 'replace')
)
OPERATIONS = {
    'replace': 'INSERT OR REPLACE INTO state VALUES (1,?)',
    'upsert': 'INSERT INTO state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
}
MAX_ARCHIVE = 128 * 1024
MAX_EXPANDED = 1024 * 1024
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_STREAM = 80 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_operations(state, operations):
    for kind, path, value in operations:
        if kind == 'append':
            target = state
            for key in path:
                target = target[key]
            target.append(copy.deepcopy(value))
        else:
            target = state
            for key in path[:-1]:
                target = target[key]
            if kind == 'set':
                if not path:
                    state = copy.deepcopy(value)
                else:
                    target[path[-1]] = copy.deepcopy(value)
            elif kind == 'del':
                del target[path[-1]]
            else:
                raise ValueError('Unknown fixture operation')
    return state


def load_stream(name):
    # Only checked-in synthetic, hash-pinned archives; no user-selected input.
    manifest = json.loads((FIXTURES / 'wfo-storage-manifest.json').read_text(encoding='utf-8'))[name]
    path = FIXTURES / ('wfo-storage-' + name + '.json.gz')
    with path.open('rb') as source:
        compressed = source.read(MAX_ARCHIVE + 1)
    if len(compressed) > MAX_ARCHIVE or digest(compressed) != manifest['archive_sha256']:
        raise ValueError('Fixture archive size/hash mismatch')
    with gzip.open(path, 'rb') as source:
        expanded = source.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise ValueError('Expanded fixture exceeds bound')
    changes = json.loads(expanded)
    if len(changes) != manifest['count']:
        raise ValueError('Fixture count mismatch')
    state = {}
    payloads = []
    size = 0
    stream_hash = hashlib.sha256()
    encoding_seconds = 0.0
    for operations in changes:
        state = apply_operations(state, operations)
        expected = state['state_hash']
        then = time.perf_counter()
        without_hash = {key: value for key, value in state.items() if key != 'state_hash'}
        if digest(canonical(without_hash).encode('utf-8')) != expected:
            raise ValueError('Fixture state hash mismatch')
        encoded = canonical(state)
        encoding_seconds += time.perf_counter() - then
        raw = encoded.encode('utf-8')
        size += len(raw)
        if len(raw) > MAX_PAYLOAD or size > MAX_STREAM:
            raise ValueError('Fixture payload bound exceeded')
        stream_hash.update(raw)
        payloads.append(encoded)
    if size != manifest['payload_bytes'] or stream_hash.hexdigest() != manifest['stream_sha256']:
        raise ValueError('Reconstructed stream size/hash mismatch')
    return payloads, dict(manifest, canonical_hash_and_encoding_seconds=encoding_seconds)


def summary(samples):
    ordered = sorted(samples)
    return {
        'total_seconds': sum(samples),
        'median_seconds': statistics.median(samples),
        'p95_seconds': ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
    }


class TimedClosing(closing):
    def __init__(self, thing, samples):
        super().__init__(thing)
        self.samples = samples

    def __exit__(self, *args):
        started = time.perf_counter()
        try:
            return super().__exit__(*args)
        finally:
            self.samples.append(time.perf_counter() - started)


def replay(payloads, directory, mode, measured=True, wal_observation=False, operation='replace'):
    if mode not in (('DELETE', 'WAL') if wal_observation else ('DELETE', 'PERSIST')):
        raise ValueError('Unsupported diagnostic mode')
    if operation not in OPERATIONS or (not wal_observation and operation != 'replace'):
        raise ValueError('Unsupported diagnostic SQL operation')
    directory.mkdir()
    times = {key: [] for key in ('execute', 'commit', 'export', 'verify')}
    close_samples = []
    checkpoint_samples = []
    checkpoint_result = None
    wal_peak = 0
    before_checkpoint = {}
    payload_bytes = 0
    autocheckpoint = None
    pages_before = {}
    pages_reopened = {}

    def sizes():
        return {p.name: p.stat().st_size for p in directory.iterdir()}

    def connection():
        db = sqlite3.connect(directory / 'walk_forward.sqlite3')
        return TimedClosing(db, close_samples) if wal_observation else closing(db)

    committed = exports = 0
    stream_hash = hashlib.sha256()
    started = time.perf_counter()
    with connection() as db:
        actual_mode = db.execute('PRAGMA journal_mode=' + mode).fetchone()[0]
        db.execute('PRAGMA synchronous=FULL')
        if actual_mode != mode.lower() or db.execute('PRAGMA synchronous').fetchone()[0] != 2:
            raise RuntimeError('Storage profile readback failed')
        if db.execute('PRAGMA locking_mode').fetchone()[0] != 'normal':
            raise RuntimeError('Unexpected locking mode')
        if wal_observation:
            autocheckpoint = db.execute('PRAGMA wal_autocheckpoint').fetchone()[0]
            if autocheckpoint != 1000:
                raise RuntimeError('Unexpected WAL autocheckpoint profile')
        db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        for encoded in payloads:
            then = time.perf_counter() if measured else 0
            db.execute(OPERATIONS[operation], (encoded,))
            if measured:
                times['execute'].append(time.perf_counter() - then)
                then = time.perf_counter()
            db.commit()
            committed += 1
            if measured:
                times['commit'].append(time.perf_counter() - then)
                then = time.perf_counter()
            temporary = directory / 'walk_forward.json.tmp'
            temporary.write_text(encoded, encoding='utf-8')
            temporary.replace(directory / 'walk_forward.json')
            exports += 1
            if measured:
                times['export'].append(time.perf_counter() - then)
                then = time.perf_counter()
            stored = db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
            exported = (directory / 'walk_forward.json').read_text(encoding='utf-8')
            if stored != encoded or exported != encoded:
                raise RuntimeError('Committed/exported snapshot mismatch')
            stream_hash.update(stored.encode('utf-8'))
            if wal_observation:
                payload_bytes += len(stored.encode('utf-8'))
                if db.execute('PRAGMA synchronous').fetchone()[0] != 2:
                    raise RuntimeError('Per-commit FULL readback failed')
                wal_peak = max(wal_peak, sizes().get('walk_forward.sqlite3-wal', 0))
            if measured:
                times['verify'].append(time.perf_counter() - then)
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('Integrity check failed')
        if wal_observation:
            if db.execute('PRAGMA journal_mode').fetchone()[0] != mode.lower() or db.execute('PRAGMA synchronous').fetchone()[0] != 2:
                raise RuntimeError('Final storage profile readback failed')
            before_checkpoint = sizes()
            pages_before = {key: db.execute('PRAGMA ' + key).fetchone()[0] for key in ('page_count', 'freelist_count')}
            if mode == 'WAL':
                then = time.perf_counter()
                checkpoint_result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                checkpoint_samples.append(time.perf_counter() - then)
                if checkpoint_result != (0, 0, 0):
                    raise RuntimeError('WAL checkpoint did not complete')
    with connection() as db:
        if db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0] != payloads[-1]:
            raise RuntimeError('Reopened final snapshot mismatch')
        if wal_observation:
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise RuntimeError('Reopened integrity check failed')
            if db.execute('PRAGMA journal_mode').fetchone()[0] != mode.lower() or db.execute('PRAGMA synchronous').fetchone()[0] != 2:
                raise RuntimeError('Reopened storage profile readback failed')
            pages_reopened = {key: db.execute('PRAGMA ' + key).fetchone()[0] for key in ('page_count', 'freelist_count')}
    result = {
        'mode': mode,
        'synchronous': 2,
        'instrumented': measured,
        'commits': committed,
        'exports': exports,
        'stream_sha256': stream_hash.hexdigest(),
        'elapsed_seconds': time.perf_counter() - started,
        'phases': {key: summary(values) for key, values in times.items() if values},
        'retained_bytes': {p.name: p.stat().st_size for p in directory.iterdir()},
    }
    if wal_observation:
        result.update(
            sql_operation=operation,
            sql_statement=OPERATIONS[operation],
            pages_before_checkpoint=pages_before,
            pages_reopened=pages_reopened,
            payload_bytes=payload_bytes,
            journal_mode_readback=mode.lower(),
            reopened_integrity='ok',
            reopened_synchronous=2,
            locking_mode='normal',
            wal_autocheckpoint=autocheckpoint,
            full_readback_count=committed,
            wal_peak_observed_bytes=wal_peak,
            pre_checkpoint_bytes=before_checkpoint,
            checkpoint_result=checkpoint_result,
            checkpoint_seconds=sum(checkpoint_samples),
            close_seconds=sum(close_samples),
            close_count=len(close_samples),
            cost_scope='elapsed includes setup, every commit/export/read, checkpoint, close and reopen; WAL peak sampled after each export',
        )
    return result


def write_report(path, report):
    # Exclusively create our own sibling; never truncate an existing temp file
    # or follow a predictable sibling symlink while publishing evidence.
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def worker(args):
    sys.path.insert(0, str(ROOT))
    from quantlab.sqlite_runtime import verify

    runtime = verify(ROOT / 'packaging/sqlite-runtime.json', args.runtime_root, args.library_sha256)
    wal = getattr(args, 'wal_abba', False)
    rounds = WAL_ROUNDS if wal else tuple((None, mode, 'replace') for mode in MODES)
    modes = tuple(mode for _, mode, _ in rounds)
    report = {
        'status': 'INCOMPLETE',
        'scope': 'synthetic diagnostic only; not native acceptance or crash parity',
        'host': platform.platform(),
        'storage_location': str(args.storage_root.resolve()),
        'runtime': runtime,
        'mode_order': list(modes),
        'fixtures': {},
        'rounds': [],
    }
    if wal:
        report.update(
            observation_only=True,
            acceptance='NOT_ESTABLISHED',
            round_plan=[{'comparison': pair, 'mode': mode, 'sql_operation': operation} for pair, mode, operation in rounds],
            tempfile_gettempdir=tempfile.gettempdir(),
            storage_volume=args.storage_root.resolve().anchor,
            environment_temp={k: os.environ.get(k) for k in ('TEMP', 'TMP', 'RUNNER_TEMP')},
            head_sha=os.environ.get('GITHUB_SHA'),
            source_sha256={
                p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
                for p in (
                    Path(__file__).resolve(),
                    ROOT / 'packaging/sqlite-runtime.json',
                    ROOT / 'tools/diagnose_research_phases.py',
                    ROOT / 'quantlab/analysis_recovery_windows.py',
                    FIXTURES / 'wfo-storage-manifest.json',
                    FIXTURES / 'wfo-storage-smoke.json.gz',
                )
            },
        )
    write_report(args.report, report)
    with tempfile.TemporaryDirectory(prefix='wfo-storage-probe-', dir=args.storage_root) as temporary:
        report['database_location'] = temporary
        for name in (args.fixture,):
            payloads, metadata = load_stream(name)
            report['fixtures'][name] = metadata
            for index, (comparison, mode, operation) in enumerate(rounds):
                report['active_round'] = {'fixture': name, 'index': index, 'mode': mode}
                if wal:
                    report['active_round'].update(comparison=comparison, sql_operation=operation)
                write_report(args.report, report)
                options = {'wal_observation': True, 'operation': operation} if wal else {}
                result = replay(payloads, Path(temporary) / f'{name}-{index}', mode, measured=wal or index != 4, **options)
                if (
                    result['commits'] != metadata['count']
                    or result['exports'] != metadata['count']
                    or result['stream_sha256'] != metadata['stream_sha256']
                    or (wal and result['payload_bytes'] != metadata['payload_bytes'])
                ):
                    raise RuntimeError('Round correctness/count mismatch')
                if wal:
                    result['comparison'] = comparison
                report['rounds'].append(dict(result, fixture=name, index=index))
                write_report(args.report, report)
    report.pop('active_round', None)
    report['status'] = 'COMPLETE'
    write_report(args.report, report)


def supervise(args):
    # Separate owned process gives a hard wall-clock bound even if fsync blocks.
    with tempfile.TemporaryDirectory(prefix='wfo-storage-report-') as temporary:
        partial = Path(temporary) / 'partial.json'
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            '--worker',
            '--report',
            str(partial),
            '--runtime-root',
            str(args.runtime_root),
            '--storage-root',
            str(args.storage_root),
            '--fixture',
            args.fixture,
        ]
        if args.library_sha256:
            command += ['--library-sha256', args.library_sha256]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        expired = False
        termination_confirmed = True
        try:
            code = process.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            expired = True
            process.kill()
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                code = None
                termination_confirmed = False
        report = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else {'rounds': []}
        if expired:
            report.update(
                status='INCOMPLETE', reason='diagnostic_deadline', partial_round_counts_unknown=True, worker_termination_confirmed=termination_confirmed
            )
        elif code != 0:
            report.update(status='ERROR', reason='worker_failed')
        report['deadline_seconds'] = args.seconds
        write_report(args.report, report)
        return 0 if report.get('status') == 'COMPLETE' else 2


def supervise_wal(args):
    # Reuse the gated, original-handle ownership already exercised by research
    # diagnostics. This path cannot spawn fixture work before containment.
    sys.path.insert(0, str(ROOT))
    from tools.diagnose_research_phases import evidence_directory, stop_owned

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'status': 'INCOMPLETE',
        'observation_only': True,
        'acceptance': 'NOT_ESTABLISHED',
        'rounds': [],
        'mode_order': [mode for _, mode, _ in WAL_ROUNDS],
        'round_plan': [{'comparison': pair, 'mode': mode, 'sql_operation': operation} for pair, mode, operation in WAL_ROUNDS],
        'tempfile_gettempdir': tempfile.gettempdir(),
    }
    write_report(args.report, report)
    with evidence_directory() as evidence:
        partial = Path(evidence['path']) / 'partial.json'
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--wal-abba', '--report', str(partial), '--runtime-root', str(args.runtime_root)]
        if args.library_sha256:
            command += ['--library-sha256', args.library_sha256]
        process = job = None
        code = None
        reason = None
        started = time.monotonic()
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != 'nt')
            if os.name == 'nt':
                from quantlab.analysis_recovery_windows import _OriginalJob, _kernel

                job = _OriginalJob(_kernel(), process._handle)
            process.stdin.write(b'1')
            process.stdin.close()
            code = process.wait(timeout=max(0.001, args.seconds - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            reason = 'diagnostic_deadline'
        except BaseException as exc:
            reason = type(exc).__name__
        finally:
            confirmed = stop_owned(process, job) if process is not None else True
        evidence['cleanup_confirmed'] = confirmed
        if partial.exists():
            try:
                report = json.loads(partial.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                reason = reason or 'invalid_partial_report'
        if reason or code != 0 or not confirmed:
            report.update(status='INCOMPLETE', reason=reason or 'worker_or_cleanup_failed', partial_round_counts_unknown=True)
        if not confirmed:
            report['retained_partial_directory'] = evidence['path']
        report.update(
            deadline_seconds=args.seconds, worker_exit_code=code, worker_termination_confirmed=confirmed, supervisor_wall_seconds=time.monotonic() - started
        )
        write_report(args.report, report)
    return 0 if report['status'] == 'COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--library-sha256')
    parser.add_argument('--storage-root', type=Path)
    parser.add_argument('--wal-abba', action='store_true', help='Observe fixed smoke journal-mode and SQL-operation ABBA on actual Python temp volume')
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--fixture', choices=('smoke', 'large'), default='smoke')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.wal_abba:
        actual_temp = Path(tempfile.gettempdir()).resolve()
        if args.fixture != 'smoke' or (args.storage_root is not None and args.storage_root.resolve() != actual_temp):
            parser.error('WAL observation requires the complete smoke fixture on actual Python temp storage')
        args.storage_root = actual_temp
    if not 1 <= args.seconds <= 180 or args.storage_root is None or not args.storage_root.is_dir():
        parser.error('Use an existing disposable storage parent and a deadline from 1 to 180 seconds')
    if args.worker:
        if args.wal_abba and sys.stdin.buffer.read(1) != b'1':
            return 2
        worker(args)
        return 0
    return supervise_wal(args) if args.wal_abba else supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
