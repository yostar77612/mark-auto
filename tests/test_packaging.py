"""Cross-platform static safeguards; Windows execution is a separate CI gate."""
import importlib.util
import os
from pathlib import Path
import re
import runpy
import shutil
import tempfile
import sys
import types
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell unavailable; actual Parser.ParseFile runs in early Windows CI gate')
    def test_actual_powershell_parser_accepts_scripts_and_rejects_broken_quote(self):
        validator = ROOT / 'packaging/validate_powershell.ps1'
        valid = subprocess.run(['pwsh', '-NoProfile', '-File', str(validator)], capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'broken.ps1').write_text('Set-Content "missing-closing-quote\n', encoding='utf-8')
            invalid = subprocess.run(['pwsh', '-NoProfile', '-File', str(validator), '-Directory', folder], capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn('broken.ps1', invalid.stdout)

    def test_powershell_gate_precedes_expensive_build(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        build_job = workflow.split('  build:', 1)[1]
        self.assertLess(build_job.index('validate_powershell.ps1'), build_job.index('actions/setup-python@'))
        build = (ROOT / 'packaging/build.ps1').read_text()
        self.assertLess(build.index('validate_powershell.ps1'), build.index('python -m pip'))
        validator = (ROOT / 'packaging/validate_powershell.ps1').read_text()
        self.assertIn('[System.Management.Automation.Language.Parser]::ParseFile', validator)
        self.assertIn("-Filter '*.ps1' -File -Recurse", validator)

    def test_real_release_baseline_pin_matches_upgrade_workflow(self):
        import runpy
        baseline = runpy.run_path(str(ROOT / 'packaging/fetch_baseline.py'))
        names = [name for name in baseline['ASSETS'] if name.endswith('.exe')]
        self.assertEqual(len(names), 1)
        baseline_version = names[0].removeprefix('MarkAuto-').removesuffix('-windows-x64-setup.exe')
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        self.assertIn(f'-BaselineVersion {baseline_version} ', workflow)
        self.assertIn(f'--baseline-version {baseline_version} ', workflow)
        self.assertIn('baseline/' + names[0], workflow)

    def test_manifest_includes_every_root_desktop_component(self):
        source = (ROOT / 'packaging/build_manifest.py').read_text()
        self.assertIn("'desktop*.py'", source)
        included = {path.name for path in ROOT.glob('desktop*.py')}
        self.assertTrue({'desktop.py', 'desktop_ui.py', 'desktop_market.py',
                         'desktop_charts.py', 'desktop_forms.py'} <= included)

    def test_build_inputs_are_committed_not_silently_gitignored(self):
        required = {'desktop.py', 'desktop_ui.py', 'requirements-desktop.lock',
                    'packaging/markauto.spec', 'packaging/markauto.iss',
                    'packaging/build.ps1', 'packaging/collect_licenses.py',
                    'packaging/THIRD_PARTY_NOTICES.md', 'LICENSE',
                    'desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py',
                    'desktop_chatgpt_dependency_manifest.json',
                    'packaging/third_party/chatgpt-auth-native-notices.zip',
                    'packaging/third_party/README.md', '.gitattributes',
                    'packaging/qt_licenses.py', 'packaging/qt_notices/manifest.json',
                    'packaging/qt_notices/QT-NOTICE.txt', 'packaging/qt_notices/QT-NATIVE-NOTICES.zip',
                    'packaging/qt_notices/GPL-3.0-only.txt', 'packaging/qt_notices/LGPL-3.0-only.txt'}
        required.update('quantlab/' + name for name in ('core.py', 'data.py', 'strategies.py', 'backtest.py', 'research.py', 'provider.py'))
        for name in required:
            self.assertTrue((ROOT / name).is_file(), name)
        if (ROOT / '.git').exists():
            tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
            self.assertFalse(required - tracked, f'Build inputs absent from Git: {sorted(required - tracked)}')

    def test_freezer_bundles_exact_hash_provenance_source_files(self):
        captured = {}
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_data_files = lambda name: []
        metadata_names = []
        hooks.copy_metadata = lambda name: metadata_names.append(name) or []
        def analysis(*args, **kwargs):
            captured.update(kwargs)
            # Real Analysis output is destination-first TOC, unlike its source-first inputs.
            datas = [(str(Path(destination) / Path(source).name), source, 'DATA')
                     for source, destination in kwargs['datas']]
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=datas)
        with patch.dict(sys.modules, {'PyInstaller.utils.hooks': hooks}), \
                patch('quantlab.sqlite_runtime.verify') as verify_sqlite, \
                patch('quantlab.sqlite_runtime.verify_binaries') as verify_binaries, \
                patch('quantlab.local_ai.collect_support_binaries', return_value=[('inert-verified-vc.dll','local-ai-dependencies')]) as collect_local_ai:
            runpy.run_path(str(ROOT / 'packaging/markauto.spec'), init_globals={
                'SPECPATH': str(ROOT / 'packaging'), 'Analysis': analysis,
                'PYZ': lambda *a, **kw: None, 'EXE': lambda *a, **kw: None,
                'COLLECT': lambda *a, **kw: None})
        collect_local_ai.assert_called_once()
        self.assertEqual(captured['binaries'], [('inert-verified-vc.dll','local-ai-dependencies')])
        verify_sqlite.assert_called_once()
        verify_binaries.assert_called_once()
        self.assertIn(str(ROOT / 'packaging/sqlite_runtime_hook.py'), captured['runtime_hooks'])
        datas = set(captured['datas'])
        self.assertEqual(metadata_names, ['PyJWT', 'cryptography', 'cffi', 'pycparser'])
        for name in ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py', 'desktop_chatgpt_dependency_manifest.json'):
            self.assertIn((str(ROOT / name), '.'), datas)
        for name in ('jwt', 'cryptography.hazmat.bindings._rust', '_cffi_backend', 'pycparser'):
            self.assertIn(name, captured['hiddenimports'])
        for name in ('core.py', 'data.py', 'strategies.py', 'backtest.py', 'research.py', 'provider.py'):
            self.assertIn((str(ROOT / 'quantlab' / name), 'quantlab'), datas)
        harness = (ROOT / 'packaging/test_installer.ps1').read_text()
        self.assertIn('Get-FileHash $shipped', harness)
        for name in ('backtest_completed', 'campaign_completed', 'paper_completed', 'performance-observation.json'):
            self.assertIn(name, harness)

    def gate_module(self):
        spec = importlib.util.spec_from_file_location('desktop_gates', ROOT / 'packaging/wait_for_gates.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_publication_requires_successful_exact_sha_and_all_jobs(self):
        gate = self.gate_module()
        run = {'head_sha': 'abc', 'event': 'push', 'run_number': 1, 'run_attempt': 1,
               'status': 'completed', 'conclusion': 'success', 'id': 2, 'html_url': 'https://example.test/run'}
        with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='abc'):
            with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', side_effect=[{'workflow_runs': [run]},
                              {'jobs': [{'name': name, 'conclusion': 'success'} for name in gate.REQUIRED_JOBS], 'total_count': len(gate.REQUIRED_JOBS)}]):
                gate.main()
            with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', side_effect=[{'workflow_runs': [run]},
                              {'jobs': [{'name': name, 'conclusion': 'skipped'} for name in gate.REQUIRED_JOBS], 'total_count': len(gate.REQUIRED_JOBS)}]):
                with self.assertRaises(RuntimeError):
                    gate.main()
            run['conclusion'] = 'failure'
            with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', return_value={'workflow_runs': [run]}):
                with self.assertRaises(RuntimeError):
                    gate.main()
            with patch.object(gate, 'require_main_ancestry'), patch.object(gate.time, 'monotonic', side_effect=[0, 1201]):
                with self.assertRaises(RuntimeError):
                    gate.main()

    def test_dependency_lock_has_only_pinned_hashed_wheels(self):
        lock = (ROOT / 'requirements-desktop.lock').read_text()
        records = lock.replace('\\\n', '').splitlines()
        for record in records:
            if record and not record.startswith('#'):
                self.assertRegex(record, r'^[-\w]+(?:\[[\w,.-]+\])?==[\d.]+\s+--hash=sha256:[a-f0-9]{64}')
        self.assertIn('PySide6==6.12.0', lock)
        self.assertNotIn('shioaji', lock.lower())

    def test_auth_notice_and_provenance_build_inputs(self):
        import hashlib
        source = (ROOT / 'packaging/build_manifest.py').read_text()
        for pattern in ('desktop*.py', 'desktop_chatgpt_dependency_manifest.json', 'packaging/third_party/*'):
            self.assertIn(pattern, source)
        archive = ROOT / 'packaging/third_party/chatgpt-auth-native-notices.zip'
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         'cbf2c6123cd25e53b33e766fb27bea9c9b4d8d174deb5ae54519d07f62dc9b24')
        self.assertIn('_internal/licenses/chatgpt-auth-native-notices.zip',
                      (ROOT / 'packaging/THIRD_PARTY_NOTICES.md').read_text())
        for name in ('PyJWT[crypto]==2.15.1', 'cryptography==50.0.2', 'cffi==2.1.1', 'pycparser==3.11'):
            self.assertIn(name, (ROOT / 'requirements-desktop.txt').read_text())
            self.assertIn(name, (ROOT / 'requirements-desktop.lock').read_text())
        for name in ('PyJWT[crypto]==2.15.1', 'cryptography==50.0.2', 'cffi==2.1.1', 'pycparser==3.11'):
            self.assertNotIn(name, (ROOT / 'requirements.txt').read_text())

    def test_source_manifest_hashes_auth_and_notice_inputs(self):
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'packaging/third_party').mkdir(parents=True)
            (root / 'dist/validation').mkdir(parents=True)
            (root / 'dist/validation/sqlite-runtime.json').write_text(json.dumps({'runtime': 'test-only'}))
            shutil.copyfile(ROOT / 'packaging/build_manifest.py', root / 'packaging/build_manifest.py')
            names = ('desktop_chatgpt_auth.py', 'desktop_chatgpt_provider.py',
                     'desktop_chatgpt_ui.py', 'desktop_chatgpt_dependency_manifest.json',
                     'packaging/third_party/chatgpt-auth-native-notices.zip',
                     'packaging/third_party/README.md', 'requirements-desktop.lock')
            for name in names:
                (root / name).write_bytes(('fixture:' + name).encode())
            with patch.dict(os.environ, GITHUB_SHA='fixture-source-commit'), \
                    patch('importlib.metadata.distributions', return_value=[]):
                runpy.run_path(str(root / 'packaging/build_manifest.py'), run_name='__main__')
            manifest = json.loads((root / 'dist/build-manifest.json').read_text())
            for name in names:
                self.assertEqual(manifest['inputs_sha256'][name],
                                 hashlib.sha256((root / name).read_bytes()).hexdigest())

    def test_installer_is_per_user_and_preserves_data(self):
        source = (ROOT / 'packaging/markauto.iss').read_text()
        self.assertIn('PrivilegesRequired=lowest', source)
        self.assertIn(r'DefaultDirName={localappdata}\Programs\MarkAuto', source)
        self.assertIn('MinVersion=10.0.19045', source)
        self.assertIn('CloseApplications=no', source)
        self.assertIn('RestartApplications=no', source)
        self.assertIn('AppMutex=Local', source)
        self.assertIn('RejectRunningApplication', source)
        self.assertIn('skipifsilent unchecked', source)
        self.assertIn('{userprograms}', source)
        self.assertIn('{userdesktop}', source)
        self.assertNotRegex(source, r'(?m)^\[UninstallDelete\]')
        self.assertNotIn('runascurrentuser', source)  # not needed for per-user context

    def test_actions_are_commit_pinned_and_publication_is_gated(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        for action in re.findall(r'uses:\s*(\S+)', workflow):
            self.assertRegex(action, r'@[a-f0-9]{40}$')
        self.assertEqual(workflow.count('contents: write'), 1)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn('--prerelease', workflow)
        self.assertIn('needs: [build, quality]', workflow)
        self.assertIn('python packaging/wait_for_gates.py', workflow)
        self.assertIn('windows-2022', workflow)
        self.assertNotIn('pull_request_target', workflow)
        self.assertNotIn('secrets.', workflow)

    def test_binary_builder_is_official_and_hash_checked(self):
        build = (ROOT / 'packaging/build.ps1').read_text()
        self.assertIn('https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/', build)
        self.assertIn('Get-FileHash', build)
        self.assertIn('f3c42116542c4cc57263c5ba6c4feabfc49fe771f2f98a79d2f7628b8762723b', build)
        self.assertIn('--require-hashes', build)
        self.assertLess(build.index('from PySide6.QtWidgets'), build.index('unittest discover'))
        self.assertLess(build.index('unittest discover'), build.index('-m PyInstaller'))
        self.assertNotIn('SkipCertificateCheck', build)

    def test_dynamic_qt_and_no_browser_ui(self):
        spec = (ROOT / 'packaging/markauto.spec').read_text()
        self.assertIn('COLLECT(', spec)
        self.assertIn('console=False', spec)
        self.assertIn('desktop.py', spec)
        self.assertIn('licenses', spec)

    def test_client_os_acceptance_is_not_fabricated(self):
        source = (ROOT / 'packaging/test_installer.ps1').read_text()
        self.assertIn('Get-CimInstance Win32_OperatingSystem', source)
        self.assertIn("client_os_acceptance='BLOCKED'", source)
        for stage in ('installed', 'upgraded'):
            self.assertIn(f"Smoke '{stage}'", source)
        self.assertIn('Assert-Sentinel', source)
        self.assertIn('unins000.exe', source)
        self.assertIn('native_window_visible', source)


if __name__ == '__main__':
    unittest.main()


class LocalAIActualFreezePinTests(unittest.TestCase):
    def test_actual_freezer_calls_strict_existing_dependency_verifier(self):
        from quantlab import local_ai
        from unittest.mock import patch
        folder=Path('/inert/verified/shiboken6')
        with patch.object(local_ai.sys,'platform','win32'), patch.object(local_ai,'application_dependencies',return_value=folder) as verify:
            result=local_ai.collect_support_binaries()
        verify.assert_called_once()
        self.assertEqual(result,[(str(folder/name),'local-ai-dependencies') for name in local_ai.manifest()['support_dlls']])

    def test_actual_freezer_refuses_different_qt_vc_bytes(self):
        from quantlab import local_ai
        from unittest.mock import patch
        with patch.object(local_ai.sys,'platform','win32'),patch.object(local_ai,'application_dependencies',side_effect=local_ai.LocalAIError('dependency')):
            with self.assertRaises(local_ai.LocalAIError):local_ai.collect_support_binaries()

    def test_actual_freezer_is_not_a_linux_structural_mock(self):
        from quantlab import local_ai
        from unittest.mock import patch
        with patch.object(local_ai.sys,'platform','linux'),patch.object(local_ai,'application_dependencies') as verify:
            with self.assertRaises(local_ai.LocalAIError):local_ai.collect_support_binaries()
            verify.assert_not_called()
