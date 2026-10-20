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
        core = type(
            "Core",
            (unittest.TestCase,),
            {
                "__module__": "test_future_module",
                "test_a": lambda self: None,
                "test_b": lambda self: None,
            },
        )
        research = type(
            "Research",
            (unittest.TestCase,),
            {
                "__module__": "test_research",
                "test_a": lambda self: None,
            },
        )
        return unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(core), unittest.defaultTestLoader.loadTestsFromTestCase(research)])

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
        for suite in (unittest.TestSuite(), unittest.TestSuite([case, case]), unittest.TestSuite([case])):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                group.partition(suite)

    def test_class_fixtures_preserved(self):
        events = []
        case = type(
            'WithFixtures',
            (unittest.TestCase,),
            {
                '__module__': 'test_research',
                'setUpClass': classmethod(lambda cls: events.append('setup')),
                'tearDownClass': classmethod(lambda cls: events.append('teardown')),
                'test_a': lambda self: events.append('a'),
                'test_b': lambda self: events.append('b'),
            },
        )
        suite = self.suite()
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        result = unittest.TestResult()
        group.partition(suite)['research'].run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(events, ['setup', 'a', 'b', 'teardown'])

    def run_helper(self, root, selected):
        return subprocess.run(
            [
                sys.executable,
                str(group.ROOT / 'tools/run_test_group.py'),
                '--group',
                selected,
                '--start-directory',
                str(root),
                '--manifest',
                str(root / 'inventory.json'),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def write_suite(self, root, body='pass'):
        (root / 'test_core_fake.py').write_text(
            '''import unittest

def setUpModule():
    print('MODULE_SETUP')
def tearDownModule():
    print('MODULE_TEARDOWN')
class Core(unittest.TestCase):
    def test_one(self):
        pass
    def test_two(self):
        pass
''',
            encoding='utf-8',
        )
        (root / 'test_research.py').write_text(
            'import unittest\nclass Research(unittest.TestCase):\n    def test_one(self):\n        ' + body + '\n', encoding='utf-8'
        )

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
            self.assertEqual(set(manifest['discovered_ids']), set(sum(manifest['partitions'].values(), [])))
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
                file.write('    @classmethod\n    def setUpClass(cls):\n        raise RuntimeError("fixture failure")\n')
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


class ParallelResearchGroupTests(unittest.TestCase):
    """Synthetic harness contracts; never shorten or substitute product cases."""

    def records(self):
        assignments = [['test_walk_forward.Fixture.test_a'], ['test_research.Fixture.test_b']]
        selected = sorted(sum(assignments, []))
        parent = {
            'identity': {'fixture': 'same-source-runtime'},
            'discovered_ids': ['core'] + selected,
            'partitions': {'core': ['core'], 'research': selected},
            'selected_ids': selected,
        }
        reports = []
        for index, expected in enumerate(assignments):
            reports.append(
                dict(
                    parent,
                    group='research',
                    worker_index=index,
                    worker_token=str(index),
                    selected_ids=expected,
                    discovery_errors=[],
                    run_completed=True,
                    successful=True,
                    tests_run=len(expected),
                    started_ids=expected[:],
                    stopped_ids=expected[:],
                    failures=[],
                    errors=[],
                    skipped=[],
                    expected_failures=[],
                    unexpected_successes=[],
                )
            )
        return parent, assignments, reports, ['0', '1']

    def test_complete_reports_exact_once_and_no_original_selection_rewrite(self):
        parent, assigned, reports, tokens = self.records()
        before = json.dumps(parent, sort_keys=True)
        group.validate_worker_reports(parent, assigned, reports, tokens)
        self.assertEqual(json.dumps(parent, sort_keys=True), before)

    def test_missing_stale_corrupt_counts_ids_outcomes_and_fixtures_fail_closed(self):

        changes = [
            lambda r: r.update(worker_token='stale'),
            lambda r: r.update(worker_index=1),
            lambda r: r.update(worker_index=False),
            lambda r: r.update(identity={'wrong': 'source'}),
            lambda r: r.update(group='core'),
            lambda r: r.update(discovered_ids=[]),
            lambda r: r.update(partitions={}),
            lambda r: r.update(selected_ids=[]),
            lambda r: r.update(discovery_errors=['broken import']),
            lambda r: r.update(run_completed=False),
            lambda r: r.update(successful=False),
            lambda r: r.update(tests_run=True),
            lambda r: r.update(tests_run=0),
            lambda r: r.update(started_ids=r['started_ids'] * 2),
            lambda r: r.update(stopped_ids=[]),
            lambda r: r.update(failures=['case (subtest=1)']),
            lambda r: r.update(errors=['setUpClass']),
            lambda r: r.update(errors=['tearDownModule']),
            lambda r: r.update(expected_failures=['case']),
            lambda r: r.update(unexpected_successes=['case']),
            lambda r: r.update(skipped=[{'id': r['selected_ids'][0], 'reason': 'new skip'}]),
        ]
        for change in changes:
            parent, assigned, reports, tokens = self.records()
            change(reports[0])
            with self.subTest(change=repr(change)), self.assertRaises(ValueError):
                group.validate_worker_reports(parent, assigned, reports, tokens)
        for bad in ([], [None, {}], [{}, {}], [[], []]):
            parent, assigned, _, tokens = self.records()
            with self.assertRaises(ValueError):
                group.validate_worker_reports(parent, assigned, bad, tokens)

    def test_only_exact_original_windows_skip_id_and_reason_allowed(self):
        parent, assigned, reports, tokens = self.records()
        test_id, reason = next(iter(group.WINDOWS_RESEARCH_SKIPS.items()))
        assigned[0] = [test_id]
        parent['selected_ids'] = sorted(sum(assigned, []))
        reports[0].update(selected_ids=[test_id], started_ids=[test_id], stopped_ids=[test_id], skipped=[{'id': test_id, 'reason': reason}])
        group.validate_worker_reports(parent, assigned, reports, tokens)
        reports[0]['skipped'][0]['reason'] = 'Qt missing'
        with self.assertRaises(ValueError):
            group.validate_worker_reports(parent, assigned, reports, tokens)
        reports[0]['skipped'] = []
        with self.assertRaises(ValueError):
            group.validate_worker_reports(parent, assigned, reports, tokens)

    def test_assignments_preserve_whole_modules_order_and_reject_drift(self):
        classes = []
        for module in ('test_research', 'test_walk_forward', 'test_saved_candidate_pool'):
            case = type('Fixture', (unittest.TestCase,), {'__module__': module, 'test_b': lambda self: None, 'test_a': lambda self: None})
            classes.append(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        assigned = group.worker_assignments(unittest.TestSuite(classes))
        self.assertEqual(assigned[0], ['test_walk_forward.Fixture.test_a', 'test_walk_forward.Fixture.test_b'])
        self.assertEqual(len(assigned[1]), 4)
        with patch.object(group, 'RESEARCH_MODULES', group.RESEARCH_MODULES | {'test_future'}):
            with self.assertRaises(ValueError):
                group.worker_assignments(unittest.TestSuite(classes))

    def test_two_workers_rejected_outside_windows_research_before_discovery(self):
        for platform, selected in (('linux', 'research'), ('win32', 'core'), ('win32', 'all')):
            with patch.object(group.sys, 'platform', platform), patch.object(group.unittest.TestLoader, 'discover') as discover:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    group.main(['--group', selected, '--manifest', 'unused', '--workers', '2'])
                discover.assert_not_called()

    def write_fake_suite(self, root, body='pass', setup='pass', teardown='pass'):
        (root / 'test_core_fake.py').write_text('import unittest\nclass Core(unittest.TestCase):\n def test_core(self): pass\n')
        for name in ('test_research', 'test_walk_forward'):
            (root / (name + '.py')).write_text(
                "import unittest\ndef setUpModule(): print('MODULE_SETUP'); "
                + setup
                + "\ndef tearDownModule(): print('MODULE_TEARDOWN'); "
                + teardown
                + "\nclass Fixture(unittest.TestCase):\n @classmethod\n def setUpClass(cls): print('CLASS_SETUP')\n"
                " @classmethod\n def tearDownClass(cls): print('CLASS_TEARDOWN')\n"
                " def test_a(self):\n  " + body + "\n def test_b(self): pass\n",
                encoding='utf-8',
            )

    def run_fake(self, root, mode='normal', native=False):
        # POSIX exercises report/supervisor behavior with an explicit fake Job;
        # real nested Windows ownership is a separately labelled native test.
        script = '''import sys
from tools import run_test_group as g
'''
        if not native:
            script += '''class FakeTree:
 def __init__(self,pid): self.empty = MODE != 'leftover'
 def stop_and_join(self): self.empty = True
 def close(self): pass
def attach(pid):
 if MODE == 'attach_failure': raise RuntimeError('fixture attachment denial')
 return FakeTree(pid)
def empty(tree):
 if MODE == 'query_failure': raise RuntimeError('fixture unknown ownership')
 return tree.empty
g.new_owned_tree=attach; g.tree_empty=empty; g.sys.platform='win32'
'''.replace('MODE', repr(mode))
        script += "raise SystemExit(g.main(['--group','research','--workers','2','--start-directory',sys.argv[1],'--manifest',sys.argv[2]]))\n"
        return subprocess.run(
            [sys.executable, '-c', script, str(root), str(root / 'inventory.json')], cwd=group.ROOT, capture_output=True, text=True, timeout=30
        )

    def test_real_children_keep_fixtures_once_and_aggregate_actual_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fake_suite(root)
            result = self.run_fake(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr.count('MODULE_SETUP'), 2)
            self.assertEqual(result.stderr.count('MODULE_TEARDOWN'), 2)
            self.assertEqual(result.stderr.count('CLASS_SETUP'), 2)
            self.assertEqual(result.stderr.count('CLASS_TEARDOWN'), 2)
            report = json.loads((root / 'inventory.json').read_text())
            self.assertTrue(report['successful'])
            self.assertTrue(report['cleanup_confirmed'])
            self.assertEqual(report['tests_run'], 4)
            self.assertEqual(report['selected_ids'], report['partitions']['research'])
            self.assertEqual(set(report['started_ids']), set(report['selected_ids']))
            self.assertEqual(report['started_ids'], report['stopped_ids'])
            self.assertTrue(all(row['natural_exit_and_quiescent'] for row in report['owned_workers']))

    def test_abrupt_exit_subtest_setup_teardown_and_cleanup_never_pass(self):
        scenarios = [
            ('import os; os._exit(7)', 'pass', 'pass', 'normal'),
            ('import os; os._exit(0)', 'pass', 'pass', 'normal'),
            ("import os, sys; from pathlib import Path; Path(sys.argv[sys.argv.index('--manifest') + 1]).unlink(); os._exit(0)", 'pass', 'pass', 'normal'),
            ('with self.subTest(value=1): self.fail("fixture")', 'pass', 'pass', 'normal'),
            ('pass', 'raise RuntimeError("setup")', 'pass', 'normal'),
            ('pass', 'pass', 'raise RuntimeError("teardown")', 'normal'),
            ('pass', 'pass', 'pass', 'leftover'),
            ('pass', 'pass', 'pass', 'query_failure'),
            ('pass', 'pass', 'pass', 'attach_failure'),
        ]
        for body, setup, teardown, mode in scenarios:
            with self.subTest(mode=mode, body=body), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_fake_suite(root, body, setup, teardown)
                result = self.run_fake(root, mode)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                report = json.loads((root / 'inventory.json').read_text())
                self.assertFalse(report['successful'])
                if mode == 'leftover':
                    self.assertTrue(report['cleanup_confirmed'])
                if mode == 'query_failure':
                    self.assertFalse(report['cleanup_confirmed'])

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows Job Object/nested-job ownership requires Windows')
    def test_native_windows_nested_job_is_owned_and_reaped_before_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = (
                "import subprocess, sys; from quantlab.desktop_runtime import _WindowsProcessTree; "
                "child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.buffer.read(1)'], stdin=subprocess.PIPE); "
                "tree = _WindowsProcessTree(child.pid); child.stdin.write(b'x'); child.stdin.close(); "
                "child.wait(timeout=5); tree.stop_and_join(); tree.close(); self.assertEqual(child.returncode, 0)"
            )
            self.write_fake_suite(root, body)
            result = self.run_fake(root, native=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / 'inventory.json').read_text())
            self.assertTrue(report['successful'])
            self.assertTrue(report['cleanup_confirmed'])

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows descendant leak cleanup requires Windows')
    def test_native_windows_natural_parent_exit_with_descendant_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
            self.write_fake_suite(root, body)
            result = self.run_fake(root, native=True)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / 'inventory.json').read_text())
            self.assertFalse(report['successful'])
            self.assertTrue(report['cleanup_confirmed'])
            self.assertTrue(any(not row['natural_exit_and_quiescent'] for row in report['owned_workers']))

    def test_ambiguous_json_duplicate_keys_and_nonfinite_numbers_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'worker.json'
            for payload in (
                '{"successful":true,"successful":true}',
                '{"nested":{"worker_index":0,"worker_index":0}}',
                '{"value":NaN}',
                '{"value":Infinity}',
                '{',
            ):
                path.write_text(payload, encoding='utf-8')
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    group.read_worker_report(path)

    def test_duplicate_key_in_naturally_exited_worker_report_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = (
                "import atexit, sys; from pathlib import Path; "
                "p = Path(sys.argv[sys.argv.index('--manifest') + 1]); "
                "atexit.register(lambda: p.write_text(p.read_text(encoding='utf-8')[:-2] + "
                "', \"successful\": true}\\n', encoding='utf-8'))"
            )
            self.write_fake_suite(root, body)
            result = self.run_fake(root)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / 'inventory.json').read_text())
            self.assertFalse(report['successful'])
            self.assertTrue(all(row['natural_exit_and_quiescent'] for row in report['owned_workers']))
            self.assertTrue(all(row.get('report_error') == 'ValueError' for row in report['worker_results']))
