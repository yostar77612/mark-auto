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
    state = {}; payloads = []; size = 0; stream_hash = hashlib.sha256()
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
        raw = encoded.encode('utf-8'); size += len(raw)
        if len(raw) > MAX_PAYLOAD or size > MAX_STREAM:
            raise ValueError('Fixture payload bound exceeded')
        stream_hash.update(raw); payloads.append(encoded)
    if size != manifest['payload_bytes'] or stream_hash.hexdigest() != manifest['stream_sha256']:
        raise ValueError('Reconstructed stream size/hash mismatch')
    return payloads, dict(manifest, canonical_hash_and_encoding_seconds=encoding_seconds)


def summary(samples):
    ordered = sorted(samples)
    return {'total_seconds': sum(samples), 'median_seconds': statistics.median(samples),
            'p95_seconds': ordered[min(len(ordered)-1, int(len(ordered)*0.95))]}


def replay(payloads, directory, mode, measured=True):
    if mode not in ('DELETE', 'PERSIST'):
        raise ValueError('Unsupported diagnostic mode')
    directory.mkdir()
    times = {key: [] for key in ('execute', 'commit', 'export', 'verify')}
    committed = exports = 0; stream_hash = hashlib.sha256(); started = time.perf_counter()
    with closing(sqlite3.connect(directory / 'walk_forward.sqlite3')) as db:
        actual_mode = db.execute('PRAGMA journal_mode=' + mode).fetchone()[0]
        db.execute('PRAGMA synchronous=FULL')
        if actual_mode != mode.lower() or db.execute('PRAGMA synchronous').fetchone()[0] != 2:
            raise RuntimeError('Storage profile readback failed')
        if db.execute('PRAGMA locking_mode').fetchone()[0] != 'normal':
            raise RuntimeError('Unexpected locking mode')
        db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        for encoded in payloads:
            then = time.perf_counter() if measured else 0
            db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (encoded,))
            if measured:
                times['execute'].append(time.perf_counter()-then); then = time.perf_counter()
            db.commit(); committed += 1
            if measured:
                times['commit'].append(time.perf_counter()-then); then = time.perf_counter()
            temporary = directory / 'walk_forward.json.tmp'
            temporary.write_text(encoded, encoding='utf-8')
            temporary.replace(directory / 'walk_forward.json'); exports += 1
            if measured:
                times['export'].append(time.perf_counter()-then); then = time.perf_counter()
            stored = db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]
            exported = (directory / 'walk_forward.json').read_text(encoding='utf-8')
            if stored != encoded or exported != encoded:
                raise RuntimeError('Committed/exported snapshot mismatch')
            stream_hash.update(stored.encode('utf-8'))
            if measured:
                times['verify'].append(time.perf_counter()-then)
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('Integrity check failed')
    with closing(sqlite3.connect(directory / 'walk_forward.sqlite3')) as db:
        if db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0] != payloads[-1]:
            raise RuntimeError('Reopened final snapshot mismatch')
    return {'mode': mode, 'synchronous': 2, 'instrumented': measured,
            'commits': committed, 'exports': exports, 'stream_sha256': stream_hash.hexdigest(),
            'elapsed_seconds': time.perf_counter()-started,
            'phases': {key: summary(values) for key, values in times.items() if values},
            'retained_bytes': {p.name: p.stat().st_size for p in directory.iterdir()}}


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
    report = {'status': 'INCOMPLETE', 'scope': 'synthetic diagnostic only; not native acceptance or crash parity',
              'host': platform.platform(), 'storage_location': str(args.storage_root.resolve()),
              'runtime': runtime, 'mode_order': list(MODES), 'fixtures': {}, 'rounds': []}
    write_report(args.report, report)
    with tempfile.TemporaryDirectory(prefix='wfo-storage-probe-', dir=args.storage_root) as temporary:
        report['database_location'] = temporary
        for name in (args.fixture,):
            payloads, metadata = load_stream(name); report['fixtures'][name] = metadata
            for index, mode in enumerate(MODES):
                report['active_round'] = {'fixture': name, 'index': index, 'mode': mode}
                write_report(args.report, report)
                result = replay(payloads, Path(temporary) / f'{name}-{index}', mode, measured=index != 4)
                if (result['commits'] != metadata['count'] or result['exports'] != metadata['count']
                        or result['stream_sha256'] != metadata['stream_sha256']):
                    raise RuntimeError('Round correctness/count mismatch')
                report['rounds'].append(dict(result, fixture=name, index=index))
                write_report(args.report, report)
    report.pop('active_round', None); report['status'] = 'COMPLETE'
    write_report(args.report, report)


def supervise(args):
    # Separate owned process gives a hard wall-clock bound even if fsync blocks.
    with tempfile.TemporaryDirectory(prefix='wfo-storage-report-') as temporary:
        partial = Path(temporary) / 'partial.json'
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   '--report', str(partial), '--runtime-root', str(args.runtime_root),
                   '--storage-root', str(args.storage_root), '--fixture', args.fixture]
        if args.library_sha256:
            command += ['--library-sha256', args.library_sha256]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        expired = False; termination_confirmed = True
        try:
            code = process.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            expired = True; process.kill()
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                code = None; termination_confirmed = False
        report = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else {'rounds': []}
        if expired:
            report.update(status='INCOMPLETE', reason='diagnostic_deadline', partial_round_counts_unknown=True,
                          worker_termination_confirmed=termination_confirmed)
        elif code != 0:
            report.update(status='ERROR', reason='worker_failed')
        report['deadline_seconds'] = args.seconds
        write_report(args.report, report)
        return 0 if report.get('status') == 'COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--library-sha256')
    parser.add_argument('--storage-root', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--fixture', choices=('smoke', 'large'), default='smoke')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180 or not args.storage_root.is_dir():
        parser.error('Use an existing disposable storage parent and a deadline from 1 to 180 seconds')
    if args.worker:
        worker(args); return 0
    return supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
