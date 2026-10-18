"""Offline installer contract fixtures; mocked pip is never native install proof."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import desktop_chatgpt_provider as provider
from tools import install_desktop_auth as installer


class AuthInstallerTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.manifest, self.versions = provider._dependency_manifest()
        self.target = 'linux-cp312-x86_64'

    def fixture_report(self, target=None):
        return {'version': '1', 'install': [
            {'metadata': {'name': item['distribution'], 'version': item['version']},
             'download_info': {'url': 'https://files.pythonhosted.org/fixture.whl',
                               'archive_info': {'hashes': {'sha256': item['wheel_sha256']}}}}
            for item in self.manifest['targets'][target or self.target]['dependencies']]}

    def test_manifest_generates_exact_locks_and_report_checks_for_all_targets(self):
        for target, entry in self.manifest['targets'].items():
            with self.subTest(target=target):
                lines = installer.requirements_text(self.manifest, target).splitlines()
                self.assertEqual(len(lines), 4)
                self.assertTrue(any(line.startswith('PyJWT[crypto]==2.15.1 ') for line in lines))
                for item, line in zip(entry['dependencies'], lines):
                    self.assertIn('==' + item['version'] + ' --hash=sha256:' + item['wheel_sha256'], line)
                installer.validate_install_report(self.fixture_report(target), entry['dependencies'])

    def test_report_rejects_missing_extra_duplicate_version_hash_and_nonwheel(self):
        baseline = self.fixture_report()
        mutations = []
        report = copy.deepcopy(baseline); report['install'].pop(); mutations.append(report)
        report = copy.deepcopy(baseline); report['install'].append(report['install'][0]); mutations.append(report)
        report = copy.deepcopy(baseline); report['install'][1] = report['install'][0]; mutations.append(report)
        for field, value in (('name', 'unknown'), ('version', '0.0.0')):
            report = copy.deepcopy(baseline); report['install'][0]['metadata'][field] = value; mutations.append(report)
        report = copy.deepcopy(baseline); report['install'][0]['download_info']['archive_info']['hashes']['sha256'] = '0'*64; mutations.append(report)
        report = copy.deepcopy(baseline); report['install'][0]['download_info']['url'] = 'https://files.pythonhosted.org/fixture.tar.gz'; mutations.append(report)
        for index, report in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                installer.validate_install_report(report, self.manifest['targets'][self.target]['dependencies'])

    def test_install_forces_hash_checked_full_closure_and_saves_evidence(self):
        provenance = {'dependency_target': self.target, 'dependency_manifest_sha256': hashlib.sha256(self.raw).hexdigest()}
        captured = []
        def fake_pip(command, check):
            self.assertTrue(check)
            captured.append(command)
            lock = Path(command[command.index('-r') + 1]).read_text(encoding='utf-8')
            self.assertEqual(lock, installer.requirements_text(self.manifest, self.target))
            Path(command[command.index('--report') + 1]).write_text(json.dumps(self.fixture_report()), encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            with patch.object(installer, '_dependency_target', return_value=self.target), patch.object(installer.subprocess, 'run', side_effect=fake_pip), patch.object(installer, 'implementation_provenance', return_value=provenance), patch('builtins.print'):
                result = installer.install(output)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), result)
            self.assertTrue(result['markauto_auth']['hash_locked_install_verified'])
        command = captured[0]
        for flag in ('--isolated', '--require-hashes', '--only-binary=:all:', '--force-reinstall', '--no-cache-dir'):
            self.assertIn(flag, command)
        self.assertNotIn('--no-deps', command)
        self.assertEqual(command[command.index('--index-url')+1], 'https://pypi.org/simple')

    def test_invalid_manifest_or_unsupported_target_never_starts_pip(self):
        for helper in ('_dependency_manifest', '_dependency_target'):
            with self.subTest(helper=helper), patch.object(installer, helper, side_effect=provider.PlanError('fixture')), patch.object(installer.subprocess, 'run') as run:
                with self.assertRaises(provider.PlanError):installer.install(Path('never-written.json'))
                run.assert_not_called()

    def test_failed_pip_or_changed_manifest_never_writes_success_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            with patch.object(installer, '_dependency_target', return_value=self.target), patch.object(installer.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pip')):
                with self.assertRaises(subprocess.CalledProcessError):installer.install(output)
            self.assertFalse(output.exists())
            def fake_pip(command, check):
                Path(command[command.index('--report')+1]).write_text(json.dumps(self.fixture_report()), encoding='utf-8')
            changed = {'dependency_target': self.target, 'dependency_manifest_sha256': '0'*64}
            with patch.object(installer, '_dependency_target', return_value=self.target), patch.object(installer.subprocess, 'run', side_effect=fake_pip), patch.object(installer, 'implementation_provenance', return_value=changed):
                with self.assertRaisesRegex(ValueError, 'auth_install_manifest_changed'):installer.install(output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
