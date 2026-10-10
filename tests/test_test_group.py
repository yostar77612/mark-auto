"""Coverage, fixture and exit-code contracts for the Windows CI partitions."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import run_test_group as group


class TestGroupTests(unittest.TestCase):
    def suite(self):
        core = type("Core", (unittest.TestCase,), {
            "__module__": "test_future_module", "test_a": lambda self: None,
            "test_b": lambda self: None,
        })
        research = type("Research", (unittest.TestCase,), {
            "__module__": "test_research", "test_a": lambda self: None,
        })
        return unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(core),
                                   unittest.defaultTestLoader.loadTestsFromTestCase(research)])

    def test_partitions_cover_all_once_in_discovery_order(self):
        suite = self.suite()
        ids = [case.id() for case in group.cases(suite)]
        parts = group.partition(suite)
        self.assertIs(parts['all'], suite)
        core = [case.id() for case in group.cases(parts['core'])]
        research = [case.id() for case in group.cases(parts['research'])]
        self.assertEqual(core, ids[:2])  # Future modules are automatically covered.
        self.assertEqual(research, ids[2:])
        self.assertFalse(set(core) & set(research))
        self.assertEqual(set(core) | set(research), set(ids))

    def test_empty_duplicate_and_empty_partition_rejected(self):
        case = next(group.cases(self.suite()))
        for suite in (unittest.TestSuite(), unittest.TestSuite([case, case]),
                      unittest.TestSuite([case])):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                group.partition(suite)

    def test_class_fixtures_preserved(self):
        events = []
        case = type('WithFixtures', (unittest.TestCase,), {
            '__module__': 'test_research',
            'setUpClass': classmethod(lambda cls: events.append('setup')),
            'tearDownClass': classmethod(lambda cls: events.append('teardown')),
            'test_a': lambda self: events.append('a'),
            'test_b': lambda self: events.append('b'),
        })
        suite = self.suite()
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        result = unittest.TestResult()
        group.partition(suite)['research'].run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(events, ['setup', 'a', 'b', 'teardown'])

    def run_helper(self, root, selected):
        return subprocess.run([
            sys.executable, str(group.ROOT / 'tools/run_test_group.py'),
            '--group', selected, '--start-directory', str(root),
            '--manifest', str(root / 'inventory.json'),
        ], capture_output=True, text=True, timeout=15)

    def write_suite(self, root, body='pass'):
        (root / 'test_core_fake.py').write_text('''import unittest

def setUpModule():
    print('MODULE_SETUP')
def tearDownModule():
    print('MODULE_TEARDOWN')
class Core(unittest.TestCase):
    def test_one(self):
        pass
    def test_two(self):
        pass
''', encoding='utf-8')
        (root / 'test_research.py').write_text(
            'import unittest\nclass Research(unittest.TestCase):\n'
            '    def test_one(self):\n        ' + body + '\n', encoding='utf-8')

    def test_module_fixtures_manifest_and_success_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_suite(root)
            result = self.run_helper(root, 'core')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('MODULE_SETUP'), 1)
            self.assertEqual(result.stdout.count('MODULE_TEARDOWN'), 1)
            manifest = json.loads((root / 'inventory.json').read_text())
            self.assertEqual(len(manifest['discovered_ids']), 3)
            self.assertEqual(len(manifest['selected_ids']), 2)
            self.assertEqual(manifest['selected_ids'], manifest['partitions']['core'])
            self.assertEqual(set(manifest['discovered_ids']),
                             set(sum(manifest['partitions'].values(), [])))
            self.assertEqual(manifest['discovery_errors'], [])
            self.assertTrue(manifest['run_completed'])
            self.assertEqual(manifest['started_ids'], manifest['selected_ids'])
            self.assertEqual(manifest['tests_run'], 2)

    def test_failure_error_skip_and_all_exit_propagation(self):
        for body, code, summary in [
            ('self.fail("expected failure")', 1, 'failures=1'),
            ('raise RuntimeError("expected error")', 1, 'errors=1'),
            ('self.skipTest("expected skip")', 0, 'skipped=1'),
        ]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_suite(root, body)
                for selected, count in [('research', 1), ('all', 3)]:
                    result = self.run_helper(root, selected)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertIn(summary, result.stderr)
                    self.assertIn(f'Ran {count} test', result.stderr)

    def test_discovery_errors_outside_selected_group_are_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_suite(root)
            (root / 'test_broken.py').write_text('raise RuntimeError("broken import")\n')
            result = self.run_helper(root, 'research')
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('broken import', result.stderr)
            manifest = json.loads((root / 'inventory.json').read_text())
            self.assertTrue(manifest['discovery_errors'])
            self.assertEqual(manifest['selected_ids'], [])

    def test_unknown_group_rejected_before_discovery(self):
        with patch.object(group.unittest.TestLoader, 'discover') as discover:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                group.main(['--group', 'typo', '--manifest', 'unused.json'])
            self.assertEqual(error.exception.code, 2)
            discover.assert_not_called()

    def test_fixture_failure_records_selected_but_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_suite(root)
            with (root / 'test_research.py').open('a') as file:
                file.write('    @classmethod\n    def setUpClass(cls):\n'
                           '        raise RuntimeError("fixture failure")\n')
            result = self.run_helper(root, 'research')
            self.assertEqual(result.returncode, 1, result.stderr)
            manifest = json.loads((root / 'inventory.json').read_text())
            self.assertTrue(manifest['run_completed'])
            self.assertEqual(len(manifest['selected_ids']), 1)
            self.assertEqual(manifest['started_ids'], [])
            self.assertEqual(manifest['tests_run'], 0)
            self.assertIn('setUpClass', manifest['errors'][0])

    def test_failed_subtest_is_reported_without_duplicate_started_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_suite(root, 'with self.subTest(value=1):\n            self.fail("subtest failure")')
            result = self.run_helper(root, 'research')
            self.assertEqual(result.returncode, 1, result.stderr)
            manifest = json.loads((root / 'inventory.json').read_text())
            self.assertEqual(manifest['started_ids'], manifest['selected_ids'])
            self.assertEqual(manifest['tests_run'], 1)
            self.assertIn('(value=1)', manifest['failures'][0])
