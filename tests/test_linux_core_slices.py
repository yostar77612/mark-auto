"""Exact Linux job slices use actual whole-module CLI execution and drift guards."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import test_core_shards as core_fixture
from tools import run_test_group as group


class LinuxCoreSliceTests(unittest.TestCase):
    def run_slice(self, root, name, drift=None):
        code = "import sys\nfrom tools import run_test_group as g\ng.sys.platform='linux'\n"
        if drift is not None:
            code += (
                'original=g.' + drift + '\ncalls=0\n'
                'def changing(start):\n global calls\n calls+=1\n value=original(start)\n'
                ' if calls>1:\n'
                "  if isinstance(value,dict): value['source_sha256']+='-changed'\n"
                "  else: value='0'*64 if value!='0'*64 else '1'*64\n"
                ' return value\ng.' + drift + '=changing\n'
            )
        output = root / (name + '.json')
        code += "raise SystemExit(g.main(['--group','core','--core-slice',sys.argv[2],'--start-directory',sys.argv[1],'--manifest',sys.argv[3]]))\n"
        result = subprocess.run(
            [sys.executable, '-c', code, str(root), name, str(output)],
            cwd=group.ROOT,
            env=dict(os.environ, GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='2'),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result, json.loads(output.read_text(encoding='utf-8'))

    def test_actual_two_job_union_preserves_modules_order_fixtures_and_native_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core_fixture.CoreShardRunnerTests().write_suite(root)
            reports = []
            for name, modules in (
                ('desktop-trading', ('test_desktop_synthetic', 'test_trading_synthetic')),
                ('paper-remaining', ('test_future_synthetic', 'test_paper')),
            ):
                result, report = self.run_slice(root, name)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = [module + '.Fixture.' + method for module in modules for method in ('test_a', 'test_b')]
                for key in ('selected_ids', 'started_ids', 'stopped_ids'):
                    self.assertEqual(report[key], expected)
                self.assertEqual(report['tests_run'], 4)
                self.assertTrue(report['run_completed'])
                self.assertEqual(report['core_slice_plan'], 'linux-core-whole-modules-v1')
                self.assertEqual(report['local_identity_before'], report['local_identity_after'])
                self.assertEqual(report['source_sha256_after'], report['core_slice_context']['source_sha256'])
                self.assertEqual(report['core_slice_context']['run_attempt'], '2')
                for module in modules:
                    for marker in ('MODULE_SETUP:', 'MODULE_TEARDOWN:', 'CLASS_SETUP:', 'CLASS_TEARDOWN:'):
                        self.assertEqual(result.stdout.count(marker + module), 1)
                self.assertNotIn('test_research', result.stdout)
                reports.append(report)
            selected = reports[0]['started_ids'] + reports[1]['started_ids']
            self.assertEqual(len(selected), len(set(selected)))
            self.assertEqual(set(selected), set(reports[0]['partitions']['core']))
            self.assertEqual(reports[0]['core_slice_assignments'], reports[1]['core_slice_assignments'])
            self.assertEqual(reports[0]['core_slice_context'], reports[1]['core_slice_context'])

    def test_actual_failure_and_skip_remain_owned_by_unmodified_result(self):
        for outcome, code, field in (("self.fail('synthetic failure')", 1, 'failures'), ("self.skipTest('synthetic skip')", 0, 'skipped')):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                core_fixture.CoreShardRunnerTests().write_suite(root, outcome=outcome)
                result, report = self.run_slice(root, 'desktop-trading')
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(report['tests_run'], 4)
                self.assertEqual(len(report[field]), 2)
                self.assertEqual(report['errors'], [])
                self.assertEqual(report['started_ids'], report['selected_ids'])
                self.assertEqual(report['stopped_ids'], report['selected_ids'])

    def test_actual_source_and_local_drift_fail_even_after_fixture_success(self):
        for drift in ('portable_source_identity', 'execution_identity'):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                core_fixture.CoreShardRunnerTests().write_suite(root)
                result, report = self.run_slice(root, 'paper-remaining', drift)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(report['run_completed'])
                self.assertFalse(report['successful'])
                self.assertIn('shard_identity_error', report)
                self.assertEqual(report['failures'], [])
                self.assertEqual(report['errors'], [])

    def test_invalid_linux_slice_roles_are_rejected_before_discovery(self):
        for platform, arguments in (
            ('win32', ['--group', 'core']),
            ('linux', ['--group', 'research']),
            ('linux', ['--group', 'all']),
            ('linux', ['--group', 'core', '--workers', '2']),
            ('linux', ['--group', 'core', '--core-shard', 'desktop']),
            ('linux', ['--group', 'core', '--worker-index', '0']),
            ('linux', ['--group', 'core', '--worker-token', 'a' * 32]),
        ):
            with self.subTest(platform=platform, args=arguments), patch.object(group.sys, 'platform', platform):
                with patch.object(group.unittest.TestLoader, 'discover') as discover:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        group.main(arguments + ['--core-slice', 'desktop-trading', '--manifest', 'unused.json'])
                    self.assertEqual(error.exception.code, 2)
                    discover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
