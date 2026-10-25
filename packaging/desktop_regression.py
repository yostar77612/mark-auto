"""Fresh same-workflow full regression evidence; local builds still run directly.

Only the regression job produces evidence and only the build job consumes it.
Both independently identify current source/runtime/discovery; no arbitrary
success file, missing cases, unknown skips or stale run can authorize freezing.
"""

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import distribution
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FILES = ('receipt.json', 'tests.json', 'regression.log')
MAX_BYTES = 32 * 1024 * 1024


def digest(path):
    with Path(path).open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def document(path):
    path = Path(path)
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Redirected regression evidence')
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Missing, redirected or oversized regression evidence')

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate evidence field')
            value[key] = item
        return value

    return json.loads(
        path.read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite evidence'))
    )


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def ci_identity(job, environment=None):
    env = os.environ if environment is None else environment
    keys = ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKFLOW_REF', 'GITHUB_EVENT_NAME')
    if env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_JOB') != job:
        raise ValueError('External regression evidence is restricted to the designated workflow jobs')
    value = {name: env.get(name, '') for name in keys}
    if not re.fullmatch('[0-9a-f]{40}', value['GITHUB_SHA']) or not all(
        re.fullmatch('[1-9][0-9]*', value[key]) for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')
    ):
        raise ValueError('Missing exact run, attempt or commit identity')
    prefix = value['GITHUB_REPOSITORY'] + '/.github/workflows/windows-desktop.yml@'
    if not re.fullmatch(r'[^/\s]+/[^/\s]+', value['GITHUB_REPOSITORY']) or not value['GITHUB_WORKFLOW_REF'].startswith(prefix):
        raise ValueError('Wrong workflow identity')
    if value['GITHUB_EVENT_NAME'] not in ('pull_request', 'push', 'workflow_dispatch'):
        raise ValueError('Unsupported workflow event')
    return value


def runtime_identity():
    from quantlab.sqlite_runtime import verify as verify_sqlite

    if sys.platform != 'win32' or platform.python_version() != '3.13.16' or struct.calcsize('P') != 8:
        raise ValueError('Installer regression requires pinned Windows CPython 3.13.16 x64')
    sqlite = verify_sqlite(ROOT / 'packaging/sqlite-runtime.json', Path(sys.base_prefix))
    locked = {}
    for name, version in re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', (ROOT / 'requirements-desktop.lock').read_text(), re.M):
        item = distribution(name)
        if item.version != version:
            raise ValueError('Desktop dependency differs from the hash-locked version')
        metadata = item.read_text('METADATA')
        if not metadata:
            raise ValueError('Locked dependency metadata unavailable')
        locked[name.lower().replace('_', '-')] = {'version': version, 'metadata_sha256': sha256(metadata.encode('utf-8')).hexdigest()}
    if not locked:
        raise ValueError('Empty desktop dependency lock')
    return {
        'python': platform.python_version(),
        'platform': sys.platform,
        'bits': 64,
        'python_executable_sha256': digest(sys.executable),
        'sqlite': {key: sqlite[key] for key in ('sqlite_version', 'sqlite_source_id', 'library_sha256')},
        'dependency_lock_sha256': digest(ROOT / 'requirements-desktop.lock'),
        'locked_dependencies': locked,
    }


def context(job):
    ci = ci_identity(job)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if head != ci['GITHUB_SHA'] or subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, text=True).strip():
        raise ValueError('Regression requires the clean exact workflow checkout')
    subprocess.run(['git', 'cat-file', '-e', '4095c3e9fdd2e91f1423d6d1bf76466834cdb417^{commit}'], cwd=ROOT, check=True, capture_output=True)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    sources = {name: digest(ROOT / name) for name in names if name}
    return {'ci': ci, 'runtime': runtime_identity(), 'source_inputs': sources}


def discover():
    from tools.run_test_group import cases

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / 'tests'))
    if loader.errors:
        raise ValueError('Independent full discovery failed')
    selected = list(cases(suite))
    ids = [case.id() for case in selected]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Independent discovery is empty or duplicated')
    declared = {}
    for case in selected:
        method = getattr(case, case._testMethodName)
        target = type(case) if getattr(type(case), '__unittest_skip__', False) else method
        if getattr(target, '__unittest_skip__', False):
            declared[case.id()] = target.__unittest_skip_why__
    policy = document(ROOT / 'packaging/desktop_regression_skips.json')
    if policy.get('schema_version') != 1 or declared != policy.get('skips'):
        raise ValueError('Unknown, missing or changed original Windows applicability skip')
    return ids, [{'id': name, 'reason': declared[name]} for name in ids if name in declared]


def validate_manifest(manifest, ids, skips, head):
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Invalid independent inventory')
    if manifest.get('head_sha') != head or manifest.get('python') != '3.13.16' or manifest.get('platform') != 'win32' or manifest.get('group') != 'all':
        raise ValueError('Wrong regression suite/runtime/head')
    if (
        manifest.get('run_completed') is not True
        or manifest.get('successful') is not True
        or type(manifest.get('tests_run')) is not int
        or manifest['tests_run'] != len(ids)
    ):
        raise ValueError('Regression did not complete successfully')
    for name in ('discovered_ids', 'selected_ids', 'started_ids', 'stopped_ids'):
        if manifest.get(name) != ids:
            raise ValueError('Missing, duplicated, reordered or fixture-blocked regression cases: ' + name)
    for name in ('discovery_errors', 'failures', 'errors', 'expected_failures', 'unexpected_successes'):
        if manifest.get(name) != []:
            raise ValueError('Nonpassing or incomplete regression: ' + name)
    if manifest.get('skipped') != skips:
        raise ValueError('Unknown, omitted or altered applicability skip')


def validate(directory, current, ids, skips, *, now=None):
    receipt = document(directory / 'receipt.json')
    if (
        type(receipt.get('schema_version')) is not int
        or receipt['schema_version'] != 1
        or receipt.get('producer_job') != 'regression'
        or receipt.get('completed') is not True
        or receipt.get('successful') is not True
    ):
        raise ValueError('Not a completed designated regression proof')
    if type(receipt.get('returncode')) is not int or receipt['returncode'] != 0 or receipt.get('validation_error') is not None:
        raise ValueError('Original full runner failed or evidence was not validated')
    if receipt.get('context_before') != current or receipt.get('context_after') != current:
        raise ValueError('Workflow run/attempt/head/source/runtime identity differs')
    started = datetime.fromisoformat(receipt['started_at'])
    completed = datetime.fromisoformat(receipt['completed_at'])
    now = datetime.now(timezone.utc) if now is None else now
    if (
        started.utcoffset() is None
        or completed.utcoffset() is None
        or not 0 <= (completed - started).total_seconds() <= 2100
        or not -60 <= (now - completed).total_seconds() <= 7200
    ):
        raise ValueError('Regression evidence expired, future-dated or outside the unchanged job bound')
    for name in ('tests.json', 'regression.log'):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES or digest(path) != receipt.get('files', {}).get(name):
            raise ValueError('Missing or changed full regression evidence bytes')
    validate_manifest(document(directory / 'tests.json'), ids, skips, current['ci']['GITHUB_SHA'])
    return receipt


def run(directory):
    if directory.exists():
        raise ValueError('Regression producer requires a fresh evidence directory')
    directory.mkdir(parents=True)
    before = context('regression')
    started = datetime.now(timezone.utc)
    code = None
    validation_error = None
    try:
        with (directory / 'regression.log').open('xb') as log:
            env = dict(os.environ, PYTHONUTF8='1')
            code = subprocess.run(
                [sys.executable, '-X', 'utf8', 'tools/run_test_group.py', '--group', 'all', '--manifest', str(directory / 'tests.json')],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
        after = context('regression')
        ids, skips = discover()
        validate_manifest(document(directory / 'tests.json'), ids, skips, before['ci']['GITHUB_SHA'])
        if code != 0 or before != after:
            raise ValueError('Original full regression failed or inputs changed during execution')
    except Exception as error:
        validation_error = type(error).__name__ + ': ' + str(error)
        after = None
    receipt = {
        'schema_version': 1,
        'producer_job': 'regression',
        'completed': True,
        'successful': validation_error is None,
        'started_at': started.isoformat(),
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'context_before': before,
        'context_after': after,
        'returncode': code,
        'validation_error': validation_error,
        'files': {name: digest(directory / name) for name in ('tests.json', 'regression.log') if (directory / name).is_file()},
    }
    write(directory / 'receipt.json', receipt)
    print(json.dumps({'successful': receipt['successful'], 'returncode': code, 'validation_error': validation_error}))
    return 0 if receipt['successful'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('run', 'verify'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    if args.phase == 'run':
        return run(directory)
    if args.output is None:
        parser.error('Verification must preserve a build evidence receipt')
    current = context('build')
    ids, skips = discover()
    receipt = validate(directory, current, ids, skips)
    receipt_digest = digest(directory / 'receipt.json')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    retained = args.output.parent / 'desktop-regression'
    retained.mkdir()
    for name in FILES:
        shutil.copyfile(directory / name, retained / name)
        expected = receipt_digest if name == 'receipt.json' else receipt['files'][name]
        if digest(retained / name) != expected:
            raise ValueError('Regression evidence changed while preserving build proof')
    write(
        args.output,
        {
            'schema_version': 1,
            'verified': True,
            'context': current,
            'full_tests_run': len(ids),
            'original_applicability_skips': skips,
            'producer_receipt_sha256': receipt_digest,
            'files': receipt['files'],
        },
    )
    print('Complete same-run same-attempt exact-source regression verified before freezing')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
