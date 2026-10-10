"""Read-only capability observations must not imply client acceptance."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import probe_windows_guest_host as probe


class WindowsGuestHostTests(unittest.TestCase):
    def test_missing_devices_and_cpu_info_are_observations_not_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'absent'
            self.assertEqual(probe.kvm_availability(missing), {
                'exists': False, 'character_device': False, 'readable': False,
                'writable': False, 'stat_available': True})
            self.assertEqual(probe.cpu_virtualization_flags(missing),
                             {'readable': False, 'flags': []})
            self.assertFalse(probe.disk_capacity(missing)['available'])

    def test_cpu_metadata_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cpuinfo'
            path.write_text('Serial: private-host-id\nflags : vmx secret svm vmx\n'
                            'model name: hidden\n', encoding='utf-8')
            self.assertEqual(probe.cpu_virtualization_flags(path),
                             {'readable': True, 'flags': ['svm', 'vmx']})

    def test_access_check_does_not_open_device_or_change_permissions(self):
        device = Mock()
        device.stat.return_value.st_mode = stat.S_IFCHR
        with patch.object(probe.os, 'access', side_effect=[True, False]):
            result = probe.kvm_availability(device)
        self.assertTrue(result['character_device'])
        self.assertTrue(result['readable'])
        self.assertFalse(result['writable'])
        device.open.assert_not_called()
        device.chmod.assert_not_called()

    def test_denied_device_stat_is_unknown(self):
        device = Mock()
        device.stat.side_effect = PermissionError('private path')
        result = probe.kvm_availability(device)
        self.assertIsNone(result['exists'])
        self.assertFalse(result['stat_available'])
        self.assertNotIn('private', json.dumps(result))

    def test_report_shape_excludes_host_identity_paths_and_environment(self):
        with patch.object(probe.platform, 'system', return_value='Linux'), \
                patch.object(probe.platform, 'release', return_value='6.0'), \
                patch.object(probe.platform, 'machine', return_value='x86_64'), \
                patch.object(probe.shutil, 'which', return_value='/private/tool'), \
                patch.object(probe, 'kvm_availability', return_value={}), \
                patch.object(probe, 'cpu_virtualization_flags', return_value={}):
            report = probe.collect_report(Path.cwd())
        self.assertEqual(set(report), {'schema_version', 'observation_only',
            'windows_client_acceptance', 'guest_started', 'os', 'kvm',
            'cpu_virtualization', 'disk', 'tools_on_path', 'limits'})
        self.assertEqual(report['windows_client_acceptance'], 'NOT_RUN')
        self.assertFalse(report['guest_started'])
        self.assertTrue(report['observation_only'])
        self.assertEqual(report['os'], {'system': 'Linux', 'release': '6.0',
                                       'architecture': 'x86_64'})
        self.assertEqual(set(report['disk']), {'workspace', 'temporary'})
        self.assertTrue(all(report['tools_on_path'].values()))
        self.assertNotIn('/private', json.dumps(report))

    def test_cli_writes_parseable_report_and_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'nested' / 'availability.json'
            self.assertEqual(probe.main(['--output', str(output)]), 0)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['windows_client_acceptance'], 'NOT_RUN')
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_write_failure_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'availability.json'
            probe.write_report(output, {'existing': True})
            with self.assertRaises(TypeError):
                probe.write_report(output, {'bad': object()})
            self.assertEqual(json.loads(output.read_text()), {'existing': True})
            self.assertEqual(list(output.parent.iterdir()), [output])


if __name__ == '__main__':
    unittest.main()
