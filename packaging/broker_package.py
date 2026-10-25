"""Explicit optional SDK packaging, verified against the complete pinned wheel.

Importing this build helper does not import the SDK. The default spec returns
its original Analysis callable unchanged. Only a broker-enabled build collects
the SDK package; the wheel's standalone CLI/server executable is never copied.
"""

from hashlib import sha256
from importlib.metadata import distribution
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

SDK_VERSION = '1.7.9'
SDK_WHEEL_SHA256 = '77c864aa5bcd0f873746cb10a55a484c7a38723df432a7778f328d5fb7f57be4'
SDK_CORE_SHA256 = '7844fb48ca1116fed793a03ab556c92049a243f9637062a4624a71590412de76'
BUILD_FLAG = 'MARKAUTO_BROKER_BUILD'
WHEEL_ENV = 'MARKAUTO_BROKER_WHEEL'


def digest(path):
    result = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def regular_local(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise RuntimeError('An explicit absolute local file is required')
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise RuntimeError('Redirected package input refused')
    if not path.is_file():
        raise RuntimeError('Package input must be a regular file')
    return path


def inspect_wheel(path):
    path = regular_local(path)
    if digest(path) != SDK_WHEEL_SHA256:
        raise RuntimeError('Broker wheel SHA256 mismatch')
    files = {}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Broker wheel CRC failed')
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename:
                raise RuntimeError('Unsafe broker wheel path')
            if item.is_dir():
                continue
            # .data/scripts contains the vendor's unrelated standalone CLI and
            # HTTP server. It is not part of the Python package selected here.
            if name.parts[0] == 'shioaji' or name.parts[0] == 'shioaji-1.7.9.dist-info' and name.name != 'RECORD':
                raw = archive.read(item)
                files[item.filename] = {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
    if files.get('shioaji/_core.pyd', {}).get('sha256') != SDK_CORE_SHA256:
        raise RuntimeError('Pinned broker native core does not match the wheel')
    return path, files


def installed_sdk(wheel, *, sdk_distribution=None):
    wheel, files = inspect_wheel(wheel)
    package = sdk_distribution if sdk_distribution is not None else distribution('shioaji')
    if package.version != SDK_VERSION:
        raise RuntimeError('Pinned broker SDK is required')
    package_root = Path(package.locate_file('shioaji')).resolve()
    expected_package = {name.removeprefix('shioaji/') for name in files if name.startswith('shioaji/')}
    actual_package = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo')
    }
    if actual_package != expected_package:
        raise RuntimeError('Installed broker package file coverage differs from the pinned wheel')
    for name, record in files.items():
        path = regular_local(Path(package.locate_file(name)).absolute())
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise RuntimeError('Installed broker file differs from the pinned wheel: ' + name)
    # This exact wheel has only non-Windows speed and test extras. Do not
    # silently accept a new mandatory dependency without its own hash lock.
    from packaging.requirements import Requirement

    mandatory = [
        text for text in package.requires or () if Requirement(text).marker is None or Requirement(text).marker.evaluate({'extra': '', 'sys_platform': 'win32'})
    ]
    if mandatory:
        raise RuntimeError('Broker mandatory dependencies changed; update the reviewed lock first')
    core = package_root / '_core.pyd'
    info = {
        'schema_version': 1,
        'flavor': 'broker-enabled',
        'sdk_version': SDK_VERSION,
        'sdk_wheel_sha256': SDK_WHEEL_SHA256,
        'sdk_native_core_sha256': SDK_CORE_SHA256,
        'sdk_native_core_bytes': core.stat().st_size,
        'mandatory_sdk_dependencies': [],
        'sdk_license_declaration': 'Not declared in the official wheel METADATA',
        'distribution_scope': 'local-only; no external distribution clearance asserted',
        'default_read_only': True,
        'default_execution_enabled': False,
        'sdk_client_created_by_build': False,
        'broker_login_performed': False,
        'verified_sdk_files': files,
    }
    return package, package_root, core, info


def retain_notices(package, output, *, verified_files=None):
    output = Path(output).absolute()
    for ancestor in (output, *output.parents):
        if ancestor.exists():
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise RuntimeError('Redirected broker notice output refused')
    output.mkdir(parents=True, exist_ok=True)
    retained = {}
    entries = verified_files if verified_files is not None else package.files or ()
    for entry in entries:
        name = str(entry).replace('\\', '/')
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe broker metadata path')
        # Keep all vendor-provided metadata/SBOM and actual notice texts. No
        # inference that absent SDK license metadata grants additional rights.
        if '.dist-info/' not in name or not any(word in name.lower() for word in ('metadata', 'wheel', 'sbom', 'license', 'copying', 'notice')):
            continue
        source = regular_local(Path(package.locate_file(entry)).absolute())
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        retained[name] = digest(target)
    (output / 'SDK-NOTICE.txt').write_text(
        'Shioaji 1.7.9 is an optional local-only dependency. Its official wheel METADATA does not declare an SDK license. Supplied metadata and native SBOM are retained. This build does not claim external distribution clearance, broker verification, login, CA activation or any asset operation.\n',
        encoding='utf-8',
    )
    return retained


def configure_analysis(analysis, root, copy_metadata, *, environment=None):
    environment = os.environ if environment is None else environment
    flag = environment.get(BUILD_FLAG, '0')
    if flag not in ('', '0', '1'):
        raise RuntimeError('Broker build flag must be explicitly 0 or 1')
    if flag != '1':
        return analysis
    wheel = environment.get(WHEEL_ENV)
    if not wheel:
        raise RuntimeError('Broker-enabled builds require the pinned wheel path')
    root = Path(root)
    package, package_root, core, info = installed_sdk(Path(wheel))
    build = root / 'build'
    build.mkdir(parents=True, exist_ok=True)
    info_file = build / 'broker-build.json'
    info_file.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    notices = build / 'broker-notices'
    retain_notices(package, notices, verified_files=info['verified_sdk_files'])
    hidden = ['shioaji', 'shioaji._core'] + sorted('shioaji.' + path.stem for path in package_root.glob('*.py') if path.name != '__init__.py')

    def broker_analysis(*args, **kwargs):
        options = dict(kwargs)
        options['runtime_hooks'] = [*kwargs['runtime_hooks'], str(root / 'packaging/broker_probe_runtime_hook.py')]
        options['hiddenimports'] = [*kwargs['hiddenimports'], *hidden]
        options['excludes'] = [name for name in kwargs['excludes'] if name != 'shioaji']
        options['binaries'] = [*kwargs['binaries'], (str(core), 'shioaji')]
        options['datas'] = [
            *kwargs['datas'],
            *copy_metadata('shioaji'),
            (str(info_file), '.'),
            (str(notices), 'licenses/shioaji'),
            (str(root / 'packaging/broker_probe.py'), 'packaging'),
        ]
        return analysis(*args, **options)

    return broker_analysis
