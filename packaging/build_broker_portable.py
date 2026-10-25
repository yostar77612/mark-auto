"""Opt-in local broker-enabled portable build; default desktop build is unchanged.

Run --prepare-only while engineering validation is in progress. A complete
build requires an explicit --freeze-reviewed-source and a clean Git checkout.
No SDK client/login, installer, global package installation or publication runs.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SUPPORT = runpy.run_path(str(Path(__file__).with_name('broker_package.py')))


def _run(command, *, environment, cwd=ROOT):
    subprocess.run([str(value) for value in command], cwd=cwd, env=environment, check=True)


def _inside(path, parent):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(parent.resolve()) or path.resolve() == parent.resolve():
        raise RuntimeError('Output must stay inside its dedicated project build directory')
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise RuntimeError('Redirected build output refused')
    return path


def _environment(python):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith(('PYTHON', 'QT_'))}
    windows = Path(os.environ.get('SystemRoot') or os.environ['SYSTEMROOT'])
    environment.update(
        PATH=os.pathsep.join((str(python.parent), str(windows / 'System32'), str(windows))),
        PYTHONPATH=str(ROOT),
        PYTHONNOUSERSITE='1',
        PYTHONDONTWRITEBYTECODE='1',
        PIP_DISABLE_PIP_VERSION_CHECK='1',
    )
    return environment


def prepare_runtime(base_python, destination, wheel):
    if os.name != 'nt':
        raise RuntimeError('Broker portable recipe requires Windows x64')
    base_python = SUPPORT['regular_local'](Path(base_python).absolute())
    destination = _inside(destination, ROOT / 'build')
    wheel, _ = SUPPORT['inspect_wheel'](wheel)
    marker = destination / 'markauto-broker-runtime.json'
    identity = {'schema_version': 1, 'base_python_sha256': SUPPORT['digest'](base_python), 'sdk_wheel_sha256': SUPPORT['SDK_WHEEL_SHA256']}
    validation = "from pathlib import Path; import json,sys,sqlite3; from quantlab.sqlite_runtime import verify; assert sys.version_info[:3]==(3,13,16) and sys.maxsize>2**32; verify(Path('packaging/sqlite-runtime.json'),Path(sys.base_prefix)); print(json.dumps({'prefix':sys.base_prefix,'sqlite':sqlite3.sqlite_version}))"
    base_environment = _environment(base_python)
    observed = json.loads(subprocess.check_output([str(base_python), '-X', 'utf8', '-c', validation], cwd=ROOT, env=base_environment, text=True))
    if Path(observed['prefix']).resolve() != base_python.parent.resolve():
        raise RuntimeError('Base must be the already pinned standalone private interpreter, not a venv or global package target')
    if destination.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != identity:
            raise RuntimeError('Existing broker runtime differs; preserve it and choose a fresh destination')
    else:
        shutil.copytree(base_python.parent, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        marker.write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
    python = destination / 'python.exe'
    environment = _environment(python)
    _run(
        [
            python,
            '-X',
            'utf8',
            '-m',
            'pip',
            'install',
            '--no-cache-dir',
            '--no-index',
            '--find-links',
            wheel.parent,
            '--require-hashes',
            '--only-binary=:all:',
            '-r',
            ROOT / 'requirements-shioaji-v2.lock',
        ],
        environment=environment,
    )
    _run([python, '-X', 'utf8', '-c', validation], environment=environment)
    # Read metadata/package bytes in the target interpreter, not the caller's
    # global environment. The selected helper performs no SDK import.
    inspect = "import json,runpy,sys; from pathlib import Path; m=runpy.run_path('packaging/broker_package.py'); p,r,c,i=m['installed_sdk'](Path(sys.argv[1])); print(json.dumps(i))"
    info = json.loads(subprocess.check_output([str(python), '-X', 'utf8', '-c', inspect, str(wheel)], cwd=ROOT, env=environment, text=True))
    info_file = destination.parent / (destination.name + '-prepared.json')
    info_file.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    return python, environment, info_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-python', type=Path, required=True, help='Existing pinned private Python 3.13.16 / SQLite 3.54.0')
    parser.add_argument('--sdk-wheel', type=Path, required=True, help='Exact downloaded 1.7.9 Windows abi3 wheel')
    parser.add_argument('--runtime', type=Path, default=ROOT / 'build/broker-python')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/broker-enabled')
    parser.add_argument('--version', default='0.2.2')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--freeze-reviewed-source', action='store_true')
    args = parser.parse_args(argv)
    version = runpy.run_path(str(ROOT / 'packaging/version_resource.py'))['render_version_resource'](args.version)
    if not args.prepare_only:
        if not args.freeze_reviewed_source:
            parser.error('Complete build requires explicit --freeze-reviewed-source after engineering gates pass')
        if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, text=True).strip():
            raise RuntimeError('Commit reviewed source locally before building; no dirty source attribution')
    python, environment, prepared = prepare_runtime(args.base_python, args.runtime, args.sdk_wheel)
    if args.prepare_only:
        print(
            json.dumps(
                {
                    'prepared_runtime': str(python),
                    'build_info': str(prepared),
                    'frozen_build_performed': False,
                    'sdk_client_created': False,
                    'login_performed': False,
                }
            )
        )
        return 0
    output = _inside(args.output, ROOT / 'dist')
    if output.exists():
        raise RuntimeError('Fresh broker output is required; never overwrite an earlier artifact')
    output.mkdir(parents=True)
    (ROOT / 'build/markauto-version.txt').write_text(version, encoding='utf-8')
    _run([python, '-X', 'utf8', 'packaging/collect_licenses.py'], environment=environment)
    environment[SUPPORT['BUILD_FLAG']] = '1'
    environment[SUPPORT['WHEEL_ENV']] = str(args.sdk_wheel.absolute())
    _run(
        [
            python,
            '-X',
            'utf8',
            '-m',
            'PyInstaller',
            '--noconfirm',
            '--clean',
            '--distpath',
            output,
            '--workpath',
            ROOT / 'build/broker-pyinstaller',
            ROOT / 'packaging/markauto.spec',
        ],
        environment=environment,
    )
    payload = output / 'MarkAuto'
    _run([python, '-X', 'utf8', 'packaging/qt_licenses.py', '--payload', payload, '--report', output / 'qt-license-audit.json'], environment=environment)
    _run(
        [python, '-X', 'utf8', 'packaging/payload_inventory.py', payload, output / 'payload-inventory.txt', output / 'payload-inventory.iss'],
        environment=environment,
    )
    probe = output / 'broker-sdk-frozen-no-login.json'
    _run([payload / 'MarkAuto.exe', '--broker-sdk-probe', probe], environment=environment)
    info = json.loads((ROOT / 'build/broker-build.json').read_text(encoding='utf-8'))
    forbidden = [
        path.relative_to(payload).as_posix()
        for path in payload.rglob('*')
        if path.is_file() and ('shioaji-' in path.name.lower() and path.suffix.lower() == '.exe' or '.data/scripts' in path.as_posix().lower())
    ]
    if forbidden:
        raise RuntimeError('Unrelated SDK standalone CLI/server must not be packaged')
    auxiliary = {}
    for source_name, destination_name in (
        ('open_multi_market_v2.cmd', '開啟多市場平台.cmd'),
        ('MULTI_MARKET_START.txt', '開始使用.txt'),
    ):
        destination = output / destination_name
        shutil.copyfile(ROOT / 'packaging' / source_name, destination)
        auxiliary[destination_name] = SUPPORT['digest'](destination)
    manifest = {
        'schema_version': 1,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_clean': True,
        'flavor': 'broker-enabled',
        'sdk': info,
        'frozen_no_login_probe': json.loads(probe.read_text(encoding='utf-8')),
        'payload_sha256': {path.relative_to(payload).as_posix(): SUPPORT['digest'](path) for path in sorted(payload.rglob('*')) if path.is_file()},
        'auxiliary_files_sha256': auxiliary,
        'sdk_client_created_by_build': False,
        'login_performed': False,
        'real_account_validation': 'PENDING_EXTERNAL',
        'published': False,
        'installed': False,
    }
    (output / 'broker-build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    archive = Path(shutil.make_archive(str(output.parent / ('MarkAuto-broker-enabled-' + manifest['source_commit'][:12] + '-local')), 'zip', output))
    (output / 'portable-archive-sha256.txt').write_text(sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='ascii')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
