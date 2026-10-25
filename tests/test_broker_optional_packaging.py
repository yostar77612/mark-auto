"""Optional SDK collection is explicit, byte-verified and never starts a client."""

from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class FakeDistribution:
    version = '1.7.9'
    requires = ('pytest>=7; extra == "test"',)

    def __init__(self, site, files):
        self.site, self.files = site, tuple(files)

    def locate_file(self, name):
        return self.site / str(name)


class OptionalBrokerPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.module = runpy.run_path(str(ROOT / 'packaging/broker_package.py'))
        self.globals = self.module['inspect_wheel'].__globals__
        files = {
            'shioaji/__init__.py': b'__version__="1.7.9"\n',
            'shioaji/_core.pyd': b'SYNTHETIC-NATIVE-ONLY-NOT-IMPORTABLE',
            'shioaji/account.py': b'# synthetic shape fixture\n',
            'shioaji-1.7.9.dist-info/METADATA': b'Name: shioaji\nVersion: 1.7.9\n',
            'shioaji-1.7.9.dist-info/WHEEL': b'Wheel-Version: 1.0\n',
            'shioaji-1.7.9.dist-info/sboms/shioaji-python.cyclonedx.json': b'{"bomFormat":"CycloneDX"}',
            'shioaji-1.7.9.data/scripts/shioaji.exe': b'SYNTHETIC-UNRELATED-CLI-MUST-NOT-SHIP',
        }
        self.wheel = self.root / 'sdk.whl'
        with zipfile.ZipFile(self.wheel, 'w') as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        self.site = (self.root / 'site').resolve()
        for name, raw in files.items():
            path = self.site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.distribution = FakeDistribution(self.site, files)
        self.sdk_hash_patch = patch.dict(
            self.globals, SDK_WHEEL_SHA256=sha256(self.wheel.read_bytes()).hexdigest(), SDK_CORE_SHA256=sha256(files['shioaji/_core.pyd']).hexdigest()
        )
        self.sdk_hash_patch.start()
        self.addCleanup(self.sdk_hash_patch.stop)

    def test_default_analysis_is_untouched_without_wheel_or_sdk_lookup(self):
        analysis = object()
        with patch.dict(self.globals, distribution=lambda _: (_ for _ in ()).throw(AssertionError('no SDK lookup'))):
            self.assertIs(self.module['configure_analysis'](analysis, self.root, None, environment={}), analysis)
            self.assertIs(self.module['configure_analysis'](analysis, self.root, None, environment={'MARKAUTO_BROKER_BUILD': '0'}), analysis)
        with self.assertRaises(RuntimeError):
            self.module['configure_analysis'](analysis, self.root, None, environment={'MARKAUTO_BROKER_BUILD': 'yes'})

    def test_complete_wheel_and_installed_package_are_verified_without_standalone_cli(self):
        _, _, core, info = self.module['installed_sdk'](self.wheel, sdk_distribution=self.distribution)
        self.assertEqual(core.read_bytes(), b'SYNTHETIC-NATIVE-ONLY-NOT-IMPORTABLE')
        self.assertFalse(any('.data/' in name or name.endswith('.exe') for name in info['verified_sdk_files']))
        self.assertEqual(info['mandatory_sdk_dependencies'], [])
        self.assertFalse(info['sdk_client_created_by_build'])

    def test_tampered_package_extra_code_wrong_version_and_mandatory_dependency_fail(self):
        account = self.site / 'shioaji/account.py'
        account.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            self.module['installed_sdk'](self.wheel, sdk_distribution=self.distribution)
        account.write_bytes(b'# synthetic shape fixture\n')
        extra = self.site / 'shioaji/foreign.py'
        extra.write_text('raise AssertionError("must never load")')
        with self.assertRaises(RuntimeError):
            self.module['installed_sdk'](self.wheel, sdk_distribution=self.distribution)
        extra.unlink()
        self.distribution.version = 'unverified'
        with self.assertRaises(RuntimeError):
            self.module['installed_sdk'](self.wheel, sdk_distribution=self.distribution)
        self.distribution.version = '1.7.9'
        self.distribution.requires = ('new-unlocked-library>=1',)
        with self.assertRaises(RuntimeError):
            self.module['installed_sdk'](self.wheel, sdk_distribution=self.distribution)

    def test_explicit_flavor_keeps_security_exclusions_and_adds_only_package_native_metadata(self):
        captured = {}

        def analysis(*args, **kwargs):
            captured.update(kwargs)
            return 'captured'

        with patch.dict(self.globals, distribution=lambda _: self.distribution):
            configured = self.module['configure_analysis'](
                analysis, self.root, lambda name: [(name, 'metadata')], environment={'MARKAUTO_BROKER_BUILD': '1', 'MARKAUTO_BROKER_WHEEL': str(self.wheel)}
            )
            self.assertEqual(
                configured(
                    runtime_hooks=['sqlite-first', 'worker-second'],
                    hiddenimports=['base'],
                    excludes=['shioaji', 'trader', 'archives', 'streamlit'],
                    binaries=[],
                    datas=[],
                ),
                'captured',
            )
        self.assertEqual(captured['runtime_hooks'][:2], ['sqlite-first', 'worker-second'])
        self.assertTrue(captured['runtime_hooks'][2].endswith('broker_probe_runtime_hook.py'))
        self.assertEqual(captured['excludes'], ['trader', 'archives', 'streamlit'])
        self.assertIn('shioaji._core', captured['hiddenimports'])
        self.assertEqual(captured['binaries'], [(str(self.site / 'shioaji/_core.pyd'), 'shioaji')])
        self.assertFalse(any('.data/scripts' in str(item) or 'shioaji.exe' in str(item) for item in captured['datas'] + captured['binaries']))
        notice = self.root / 'build/broker-notices/SDK-NOTICE.txt'
        self.assertIn('does not declare an SDK license', notice.read_text(encoding='utf-8'))
        manifest = json.loads((self.root / 'build/broker-build.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['flavor'], 'broker-enabled')
        self.assertFalse(manifest['default_execution_enabled'])

    def test_bad_wheel_hash_is_refused_before_any_installed_package_lookup(self):
        self.wheel.write_bytes(self.wheel.read_bytes() + b'changed')
        with self.assertRaises(RuntimeError):
            self.module['inspect_wheel'](self.wheel)


class OptionalBrokerProbeTests(unittest.TestCase):
    def test_private_builder_environment_handles_windows_canonical_uppercase_keys(self):
        module = runpy.run_path(str(ROOT / 'packaging/build_broker_portable.py'))
        with patch.dict(os.environ, {'SYSTEMROOT': 'C:/Windows', 'PYTHONHOME': 'unwanted', 'QT_PLUGIN_PATH': 'unwanted'}, clear=True):
            environment = module['_environment'](Path('C:/private/python.exe'))
        self.assertNotIn('PYTHONHOME', environment)
        self.assertNotIn('QT_PLUGIN_PATH', environment)
        self.assertIn('Windows', environment['PATH'])
        self.assertEqual(environment['PYTHONNOUSERSITE'], '1')

    def test_native_and_wheel_pins_match_build_and_probe(self):
        helper = runpy.run_path(str(ROOT / 'packaging/broker_package.py'))
        probe = runpy.run_path(str(ROOT / 'packaging/broker_probe.py'))
        for key in ('SDK_WHEEL_SHA256', 'SDK_CORE_SHA256'):
            self.assertEqual(helper[key], probe[key])

    def test_mocked_frozen_probe_denies_client_constructor_and_refuses_overwrite(self):
        probe = runpy.run_path(str(ROOT / 'packaging/broker_probe.py'))
        function = probe['run_probe']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / 'shioaji'
            package.mkdir()
            native_file = package / '_core.pyd'
            native_file.write_bytes(b'SYNTHETIC-NATIVE-PROBE-FIXTURE')
            core_hash = sha256(native_file.read_bytes()).hexdigest()
            constructors = []

            class SDKClient:
                def __init__(self):
                    constructors.append(True)
                    raise AssertionError('must not construct SDK client')

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
            ):
                setattr(SDKClient, name, lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not call SDK')))
            sdk = SimpleNamespace(
                __file__=str(package / '__init__.py'),
                __version__='1.7.9',
                Shioaji=SDKClient,
                QuoteVersion=SimpleNamespace(v1=SimpleNamespace(value='v1')),
                Unit=SimpleNamespace(Share=SimpleNamespace(value='Share')),
            )
            info = root / 'broker-build.json'
            info.write_text(
                json.dumps({'flavor': 'broker-enabled', 'sdk_version': '1.7.9', 'sdk_wheel_sha256': 'a' * 64, 'sdk_native_core_sha256': core_hash}),
                encoding='utf-8',
            )
            output = root / 'proof.json'
            with (
                patch.dict(function.__globals__, import_module=lambda _: sdk, version=lambda _: '1.7.9', SDK_WHEEL_SHA256='a' * 64, SDK_CORE_SHA256=core_hash),
                patch.object(sys, 'frozen', True, create=True),
                patch.object(sys, '_MEIPASS', str(root), create=True),
                patch.dict(sys.modules, {'shioaji._core': SimpleNamespace(__file__=str(native_file))}),
            ):
                self.assertEqual(function(output, info), 0)
                with self.assertRaises(RuntimeError):
                    function(output, info)
            self.assertEqual(constructors, [])
            self.assertIs(sdk.Shioaji, SDKClient)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertTrue(result['frozen'])
            self.assertEqual(result['application_sdk_client_constructions'], 0)
            self.assertFalse(result['broker_login_performed'])

    def test_probe_hook_is_passive_for_normal_parent_and_worker_arguments(self):
        hook = ROOT / 'packaging/broker_probe_runtime_hook.py'
        for args in (['MarkAuto.exe'], ['MarkAuto.exe', '--multiprocessing-fork', 'pipe_handle=1']):
            with self.subTest(args=args), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'argv', args):
                before = 'shioaji' in sys.modules
                runpy.run_path(str(hook))
                self.assertEqual('shioaji' in sys.modules, before)
