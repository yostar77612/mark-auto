"""Explicit SDK import/native-shape proof; no broker client or login is created."""

import argparse
from hashlib import sha256
from importlib import import_module
from importlib.metadata import version
import json
from pathlib import Path
import stat
import sys

SDK_WHEEL_SHA256 = '77c864aa5bcd0f873746cb10a55a484c7a38723df432a7778f328d5fb7f57be4'
SDK_CORE_SHA256 = '7844fb48ca1116fed793a03ab556c92049a243f9637062a4624a71590412de76'


def _output(path):
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')) or path.exists():
        raise RuntimeError('A fresh absolute local proof report is required')
    for ancestor in path.parents:
        if ancestor.exists():
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise RuntimeError('Redirected proof output refused')


def run_probe(output: Path, info_path: Path, *, require_frozen: bool = True) -> int:
    _output(output)
    frozen = bool(getattr(sys, 'frozen', False))
    if require_frozen and not frozen:
        raise RuntimeError('This acceptance proof requires the actual frozen executable')
    info = json.loads(info_path.read_text(encoding='utf-8'))
    if info.get('flavor') != 'broker-enabled' or info.get('sdk_version') != '1.7.9':
        raise RuntimeError('Broker flavor metadata missing or unsupported')
    if info.get('sdk_wheel_sha256') != SDK_WHEEL_SHA256 or info.get('sdk_native_core_sha256') != SDK_CORE_SHA256:
        raise RuntimeError('Broker build identity differs from the pinned dependency contract')
    base = Path(sys._MEIPASS if frozen else sys.base_prefix).resolve()
    module = import_module('shioaji')
    native = sys.modules.get('shioaji._core')
    if native is None or module.__version__ != info['sdk_version'] or version('shioaji') != info['sdk_version']:
        raise RuntimeError('Actual SDK/native module and metadata must agree')
    module_file, native_file = Path(module.__file__).resolve(), Path(native.__file__).resolve()
    if not module_file.is_relative_to(base) or not native_file.is_relative_to(base) or native_file.name != '_core.pyd':
        raise RuntimeError('SDK must load from this packaged runtime, not another Python environment')
    native_hash = sha256(native_file.read_bytes()).hexdigest()
    if native_hash != info['sdk_native_core_sha256']:
        raise RuntimeError('Loaded SDK native core hash differs from the pinned build')
    constructor = module.Shioaji
    constructors = []

    def forbidden_constructor(*args, **kwargs):
        constructors.append(True)
        raise AssertionError('No-login proof must not create a broker SDK client')

    module.Shioaji = forbidden_constructor
    try:
        from quantlab.trading.runtime.broker import ShioajiClientFactory
        from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade

        factory = ShioajiClientFactory(module)
        # Constructor is inert and cannot dereference the injected object. This
        # checks our real boundary while the SDK constructor is actively denied.
        facade = ShioajiSDKFacade(object(), module)
        shape = tuple(
            name
            for name in (
                'login',
                'logout',
                'list_accounts',
                'account_balance',
                'list_positions',
                'snapshots',
                'kbars',
                'subscribe',
                'update_status',
                'list_trades',
            )
            if callable(getattr(constructor, name, None))
        )
        if len(shape) != 10 or factory.sdk_version != '1.7.9' or facade.query_timeout_ms != 2500:
            raise RuntimeError('Pinned native API shape or inert composition failed')
        enum_values = {'quote_version': str(module.QuoteVersion.v1.value), 'share_unit': str(module.Unit.Share.value)}
        if constructors:
            raise RuntimeError('Unexpected SDK client construction')
    finally:
        module.Shioaji = constructor
    result = {
        'status': 'passed',
        'scope': 'actual frozen package' if frozen else 'source-runtime import only; not frozen acceptance',
        'frozen': frozen,
        'flavor': info['flavor'],
        'sdk_version': module.__version__,
        'sdk_module_inside_selected_runtime': True,
        'native_core_inside_selected_runtime': True,
        'sdk_native_core_sha256': native_hash,
        'sdk_wheel_sha256': info['sdk_wheel_sha256'],
        'native_api_shape': shape,
        'enum_values': enum_values,
        'application_sdk_client_constructions': len(constructors),
        'broker_login_performed': False,
        'ca_activation_performed': False,
        'asset_operations_performed': False,
        'gui_started': False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-info', type=Path, required=True)
    parser.add_argument('--source-runtime', action='store_true', help='Explicit preflight only; never counts as frozen acceptance')
    args = parser.parse_args(argv)
    return run_probe(args.output, args.build_info, require_frozen=not args.source_runtime)


if __name__ == '__main__':
    raise SystemExit(main())
