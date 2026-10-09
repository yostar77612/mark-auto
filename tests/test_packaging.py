"""Cross-platform static safeguards; Windows execution is a separate CI gate."""
import importlib.util
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
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
            with patch.object(gate, 'api', side_effect=[{'workflow_runs': [run]},
                              {'jobs': [{'conclusion': 'success'}], 'total_count': 1}]):
                gate.main()
            with patch.object(gate, 'api', side_effect=[{'workflow_runs': [run]},
                              {'jobs': [{'conclusion': 'skipped'}], 'total_count': 1}]):
                with self.assertRaises(RuntimeError):
                    gate.main()
            run['conclusion'] = 'failure'
            with patch.object(gate, 'api', return_value={'workflow_runs': [run]}):
                with self.assertRaises(RuntimeError):
                    gate.main()
            with patch.object(gate.time, 'monotonic', side_effect=[0, 1201]):
                with self.assertRaises(RuntimeError):
                    gate.main()

    def test_dependency_lock_has_only_pinned_hashed_wheels(self):
        lock = (ROOT / 'requirements-desktop.lock').read_text()
        records = lock.replace('\\\n', '').splitlines()
        for record in records:
            if record and not record.startswith('#'):
                self.assertRegex(record, r'^[-\w]+==[\d.]+\s+--hash=sha256:[a-f0-9]{64}')
        self.assertIn('PySide6==6.12.0', lock)
        self.assertNotIn('shioaji', lock.lower())

    def test_installer_is_per_user_and_preserves_data(self):
        source = (ROOT / 'packaging/markauto.iss').read_text()
        self.assertIn('PrivilegesRequired=lowest', source)
        self.assertIn(r'DefaultDirName={localappdata}\Programs\MarkAuto', source)
        self.assertIn('MinVersion=10.0.19045', source)
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
