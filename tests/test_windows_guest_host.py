"""Read-only capability observations must not imply client acceptance."""
import ast
import contextlib
import errno
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

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

    def test_default_report_never_calls_device_query(self):
        with patch.object(probe, 'query_kvm_api') as query, \
                patch.object(probe.os, 'open') as device_open:
            report = probe.collect_report(Path.cwd())
        query.assert_not_called()
        device_open.assert_not_called()
        self.assertNotIn('kvm_api', report)

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


class KvmApiQueryTests(unittest.TestCase):
    def setUp(self):
        # Replace the entire OS interface: these tests cannot touch a device
        # even on a host with /dev/kvm and passwordless sudo.
        self.os = SimpleNamespace(
            O_RDWR=2, O_CLOEXEC=0x80000, O_NOFOLLOW=0x20000, O_NONBLOCK=0x800,
            open=Mock(return_value=7),
            fstat=Mock(return_value=SimpleNamespace(st_mode=stat.S_IFCHR,
                                                  st_rdev=123)),
            major=Mock(return_value=10), minor=Mock(return_value=232),
            close=Mock())
        self.fcntl = SimpleNamespace(ioctl=Mock(side_effect=[12, 1, 1, 4, 256]))
        for target, name, value in (
                (probe, 'os', self.os), (probe, 'fcntl', self.fcntl),
                (probe.platform, 'system', Mock(return_value='Linux')),
                (probe.platform, 'machine', Mock(return_value='x86_64'))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_closed(self):
        self.os.close.assert_called_once_with(7)

    def test_fixed_device_flags_and_only_allowlisted_query_ioctls(self):
        result = probe.query_kvm_api()
        self.os.open.assert_called_once_with('/dev/kvm', 2 | 0x80000 | 0x20000 | 0x800)
        self.os.fstat.assert_called_once_with(7)
        self.os.major.assert_called_once_with(123)
        self.os.minor.assert_called_once_with(123)
        self.assertEqual(self.fcntl.ioctl.call_args_list, [
            call(7, 0xAE00, 0), call(7, 0xAE03, 0), call(7, 0xAE03, 3),
            call(7, 0xAE03, 9), call(7, 0xAE03, 66)])
        self.assertEqual(result['status'], 'api_available')
        self.assertEqual(result['api_version'], 12)
        self.assertEqual(result['extensions']['KVM_CAP_NR_VCPUS']['value'], 4)
        self.assertEqual(result['extensions']['KVM_CAP_MAX_VCPUS']['value'], 256)
        self.assertEqual(result['close_status'], 'closed')
        self.assert_closed()

    def test_api_available_does_not_establish_guest_or_windows_acceptance(self):
        result = probe.collect_kvm_api_report()
        self.assertTrue(result['observation_only'])
        self.assertFalse(result['guest_started'])
        self.assertEqual(result['windows_client_acceptance'], 'NOT_RUN')
        self.assertEqual(set(result), {'schema_version', 'observation_only',
            'windows_client_acceptance', 'guest_started', 'kvm_api', 'limits'})
        self.assertIn('not a product acceptance gate', ' '.join(result['limits']))
        self.assert_closed()

    def test_unsupported_platform_never_opens(self):
        probe.platform.system.return_value = 'Windows'
        result = probe.query_kvm_api()
        self.assertEqual(result['status'], 'unsupported_platform')
        self.os.open.assert_not_called()
        self.os.close.assert_not_called()
        self.fcntl.ioctl.assert_not_called()

    def test_unsupported_architecture_never_opens(self):
        probe.platform.machine.return_value = 'aarch64'
        self.assertEqual(probe.query_kvm_api()['status'], 'unsupported_architecture')
        self.os.open.assert_not_called()

    def test_missing_fcntl_and_open_safety_flags_never_open(self):
        with patch.object(probe, 'fcntl', None):
            self.assertEqual(probe.query_kvm_api()['status'], 'query_support_unavailable')
        for flag in ('O_CLOEXEC', 'O_NOFOLLOW', 'O_NONBLOCK'):
            with self.subTest(flag=flag):
                value = getattr(self.os, flag)
                delattr(self.os, flag)
                self.assertEqual(probe.query_kvm_api()['status'], 'query_support_unavailable')
                setattr(self.os, flag, value)
        self.os.open.assert_not_called()

    def test_open_errors_are_sanitized_and_do_not_close_an_unopened_fd(self):
        for number, status in (
                (errno.ENOENT, 'device_missing'), (errno.EACCES, 'permission_denied'),
                (errno.EPERM, 'permission_denied'), (errno.ELOOP, 'symlink_refused'),
                (errno.ENODEV, 'query_failed'), (errno.EIO, 'query_failed')):
            with self.subTest(number=number):
                self.os.open.side_effect = OSError(number, 'private-host-id /private/path')
                result = probe.query_kvm_api()
                self.assertEqual(result['status'], status)
                self.assertEqual(result['stage'], 'open')
                self.assertEqual(result['errno'], number)
                self.assertNotIn('private', json.dumps(result))
        self.os.fstat.assert_not_called()
        self.fcntl.ioctl.assert_not_called()
        self.os.close.assert_not_called()

    def test_non_character_device_is_closed_without_ioctl(self):
        for mode in (stat.S_IFREG, stat.S_IFIFO, stat.S_IFDIR):
            with self.subTest(mode=mode):
                self.os.fstat.return_value.st_mode = mode
                self.assertEqual(probe.query_kvm_api()['status'], 'not_character_device')
        self.assertEqual(self.os.close.call_args_list, [call(7)] * 3)
        self.fcntl.ioctl.assert_not_called()

    def test_unrelated_character_device_is_closed_without_ioctl(self):
        self.os.minor.return_value = 1
        self.assertEqual(probe.query_kvm_api()['status'], 'unexpected_device')
        self.fcntl.ioctl.assert_not_called()
        self.assert_closed()

    def test_fstat_failure_is_sanitized_and_closes_fd(self):
        self.os.fstat.side_effect = OSError(errno.EIO, 'private-host-id')
        result = probe.query_kvm_api()
        self.assertEqual((result['status'], result['stage'], result['errno']),
                         ('query_failed', 'fstat', errno.EIO))
        self.assertNotIn('private', json.dumps(result))
        self.fcntl.ioctl.assert_not_called()
        self.assert_closed()

    def test_api_query_error_does_not_query_extensions_and_closes_fd(self):
        self.fcntl.ioctl.side_effect = OSError(errno.ENOTTY, 'private-host-id')
        result = probe.query_kvm_api()
        self.assertEqual((result['status'], result['stage'], result['errno']),
                         ('query_failed', 'api_version', errno.ENOTTY))
        self.assertEqual(result['extensions'], {})
        self.assertNotIn('private', json.dumps(result))
        self.fcntl.ioctl.assert_called_once_with(7, 0xAE00, 0)
        self.assert_closed()

    def test_unsupported_api_version_closes_fd_without_extension_queries(self):
        self.fcntl.ioctl.side_effect = [11]
        result = probe.query_kvm_api()
        self.assertEqual(result['status'], 'unsupported_api_version')
        self.assertEqual(result['api_version'], 11)
        self.fcntl.ioctl.assert_called_once_with(7, 0xAE00, 0)
        self.assert_closed()

    def test_extension_unsupported_and_query_error_are_distinct(self):
        self.fcntl.ioctl.side_effect = [12, 0, OSError(errno.EINVAL, 'private-host-id'), 4, -1]
        result = probe.query_kvm_api()
        self.assertEqual(result['extensions']['KVM_CAP_IRQCHIP'], {
            'status': 'unsupported', 'value': 0, 'errno': None})
        self.assertEqual(result['extensions']['KVM_CAP_USER_MEMORY'], {
            'status': 'query_failed', 'value': None, 'errno': errno.EINVAL})
        self.assertEqual(result['extensions']['KVM_CAP_NR_VCPUS']['value'], 4)
        self.assertEqual(result['extensions']['KVM_CAP_MAX_VCPUS']['status'], 'invalid_result')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(self.fcntl.ioctl.call_count, 5)
        self.assert_closed()

    def test_close_failure_is_recorded_and_not_retried(self):
        self.os.close.side_effect = OSError(errno.EINTR, 'private-host-id')
        result = probe.query_kvm_api()
        self.assertEqual(result['close_status'], 'close_failed')
        self.assertEqual(result['close_errno'], errno.EINTR)
        self.assertNotIn('private', json.dumps(result))
        self.assert_closed()

    def test_unexpected_exception_still_closes_fd(self):
        self.fcntl.ioctl.side_effect = RuntimeError('injected defect')
        with self.assertRaises(RuntimeError):
            probe.query_kvm_api()
        self.assert_closed()

    def test_stdout_only_cli_does_not_write_files_or_collect_host_identity(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch.object(probe, 'write_report') as write, \
                patch.object(probe, 'collect_report') as collect:
            self.assertEqual(probe.main(['--query-kvm-api']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['kvm_api']['status'], 'api_available')
        write.assert_not_called()
        collect.assert_not_called()

    def test_unavailable_host_is_a_successful_diagnostic_not_a_product_failure(self):
        self.os.open.side_effect = OSError(errno.EACCES, 'private-host-id')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(probe.main(['--query-kvm-api']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['kvm_api']['status'], 'permission_denied')
        self.assertEqual(result['windows_client_acceptance'], 'NOT_RUN')

    def test_cli_refuses_arbitrary_paths_query_options_and_abbreviations(self):
        for args in ([], ['--query-kvm-api', '--output', '/private/output'],
                     ['--query-kvm-api', '/dev/another'],
                     ['--query-kvm-api', '--device', '/dev/another'],
                     ['--query-kvm-api', '--ioctl', '0xAE01'],
                     ['--query-kvm-api', '--capability', '999'], ['--query-kvm']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    probe.main(args)
                self.assertEqual(error.exception.code, 2)
        self.os.open.assert_not_called()


class KvmWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.workflow = (cls.root / '.github/workflows/quantlab.yml').read_text(encoding='utf-8')
        cls.quality = cls.workflow.split('  quality:\n', 1)[1].split('  security:\n', 1)[0]

    def test_fixed_timed_isolated_root_invocation_stdout_is_unprivileged(self):
        expected = ('if timeout --kill-after=2s 10s sudo -n /usr/bin/python3 -I -B -S '
                    'tools/probe_windows_guest_host.py --query-kvm-api > '
                    'dist/validation/windows-guest-kvm-api.json 2>/dev/null; then')
        self.assertIn(expected, self.quality)
        self.assertEqual(self.quality.count('sudo '), 1)
        for forbidden in ('sudo sh', 'sudo bash', 'sudo tee', 'chmod', 'chown',
                          'usermod', 'modprobe', 'eval ', 'sh -c', 'bash -c'):
            self.assertNotIn(forbidden, self.quality)
        self.assertIn('shell: bash', self.quality)

    def test_diagnostic_failure_reports_unavailable_without_masking_product_gates(self):
        self.assertIn('status=$?', self.quality)
        self.assertIn('outcome=command_failed', self.quality)
        self.assertIn('124) outcome=command_timed_out', self.quality)
        self.assertIn('137) outcome=command_killed', self.quality)
        self.assertIn('"command_exit_code":%s', self.quality)
        self.assertIn('"windows_client_acceptance":"NOT_RUN"', self.quality)
        self.assertIn('"guest_started":false', self.quality)
        self.assertNotIn('continue-on-error', self.workflow)
        self.assertNotIn('|| true', self.quality)
        self.assertIn('- run: python tools/quality_gate.py --history', self.quality)
        self.assertIn('- run: python -m unittest discover -s tests -p test_quality_gate.py -v',
                      self.quality)
        self.assertIn('run: python -m unittest discover -s tests -p test_windows_guest_host.py -v',
                      self.quality)

    def test_both_separate_reports_are_preserved_even_after_failure(self):
        self.assertIn('run: python tools/probe_windows_guest_host.py --output '
                      'dist/validation/windows-guest-host.json', self.quality)
        upload = self.quality.split('      - name: Preserve host availability evidence', 1)[1]
        self.assertIn('if: always()', upload)
        self.assertIn('path: |\n            dist/validation/windows-guest-host.json\n'
                      '            dist/validation/windows-guest-kvm-api.json', upload)

    def test_privileged_script_imports_only_standard_library_and_no_process_launch(self):
        tree = ast.parse((self.root / 'tools/probe_windows_guest_host.py').read_text(encoding='utf-8'))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {'__future__', 'argparse', 'errno', 'fcntl', 'json',
                                  'os', 'pathlib', 'platform', 'shutil', 'stat', 'tempfile'})
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(calls & {'eval', 'exec', 'compile', '__import__'})


if __name__ == '__main__':
    unittest.main()
