"""Successful test fixtures have the same lifetime as ordinary unittest runs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import run_test_group as group


class TestGroupRetentionTests(unittest.TestCase):
    def run_fixture(self, selected, first_outcome):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A weak reference to the actual first TestCase, not to a separate
            # sentinel. No gc.collect(), close replacement, or fixture mutation.
            (root / 'test_core_retention.py').write_text('''import unittest, weakref
reference = None
class Core(unittest.TestCase):
    def test_a(self):
        global reference
        reference = weakref.ref(self)
        self.owned_resource = bytearray(2 * 1024 * 1024)
        OUTCOME
    def test_b(self):
        self.assertEqual(reference() is None, EXPECT_RELEASED)
'''.replace('OUTCOME', first_outcome).replace('EXPECT_RELEASED', str(first_outcome == 'pass')))
            (root / 'test_research.py').write_text('''import unittest
class Research(unittest.TestCase):
    def test_a(self): pass
''')
            result = subprocess.run([sys.executable, str(group.ROOT / 'tools/run_test_group.py'),
                '--group', selected, '--start-directory', str(root),
                '--manifest', str(root / 'inventory.json')], capture_output=True, text=True, timeout=15)
            return result, json.loads((root / 'inventory.json').read_text())

    def test_successful_case_released_before_next_case_core_and_all(self):
        for selected, count in (('core', 2), ('all', 3)):
            with self.subTest(group=selected):
                result, report = self.run_fixture(selected, 'pass')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(report['tests_run'], count)
                self.assertEqual(report['started_ids'], report['selected_ids'])
                self.assertEqual(report['stopped_ids'], report['selected_ids'])
                self.assertEqual(len(report['discovered_ids']), 3)

    def test_failure_and_skip_retention_remain_owned_by_result(self):
        for outcome, expected, field in (("self.fail('expected')", 1, 'failures'),
                                        ("self.skipTest('expected')", 0, 'skipped')):
            with self.subTest(outcome=outcome):
                result, report = self.run_fixture('core', outcome)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(len(report[field]), 1)
                self.assertEqual(report['tests_run'], 2)
                self.assertEqual(report['started_ids'], report['selected_ids'])
                # The second case proves intentional result retention survived.
                if field == 'failures': self.assertEqual(len(report['failures']), 1)
                else: self.assertEqual(report['failures'], [])
