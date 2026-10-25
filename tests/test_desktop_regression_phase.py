"""Reject incomplete/stale build evidence; never execute the long suite here."""

import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'packaging/desktop_regression.py'))
GLOBALS = MODULE['validate'].__globals__


class FullRegressionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = datetime.now(timezone.utc)
        self.ids = ['test_a.First.test_one', 'test_a.First.test_two', 'test_b.Second.test_one']
        self.skips = [{'id': self.ids[1], 'reason': 'Original platform applicability'}]
        self.current = {
            'ci': {
                'GITHUB_SHA': 'a' * 40,
                'GITHUB_RUN_ID': '12',
                'GITHUB_RUN_ATTEMPT': '2',
                'GITHUB_REPOSITORY': 'owner/repo',
                'GITHUB_WORKFLOW_REF': 'owner/repo/.github/workflows/windows-desktop.yml@refs/heads/main',
                'GITHUB_EVENT_NAME': 'push',
            },
            'runtime': {
                'python': '3.13.16',
                'sqlite': {'library_sha256': 'b' * 64},
                'dependency_lock_sha256': 'c' * 64,
                'locked_dependencies': {'pyside6': {'version': '6.12.0'}},
            },
            'source_inputs': {'quantlab/core.py': 'd' * 64},
        }
        self.manifest = {
            'head_sha': 'a' * 40,
            'python': '3.13.16',
            'platform': 'win32',
            'group': 'all',
            'run_completed': True,
            'successful': True,
            'tests_run': len(self.ids),
            **{key: list(self.ids) for key in ('discovered_ids', 'selected_ids', 'started_ids', 'stopped_ids')},
            **{key: [] for key in ('discovery_errors', 'failures', 'errors', 'expected_failures', 'unexpected_successes')},
            'skipped': self.skips,
        }
        self.receipt = {
            'schema_version': 1,
            'producer_job': 'regression',
            'completed': True,
            'successful': True,
            'returncode': 0,
            'validation_error': None,
            'started_at': (self.now - timedelta(minutes=29)).isoformat(),
            'completed_at': self.now.isoformat(),
            'context_before': copy.deepcopy(self.current),
            'context_after': copy.deepcopy(self.current),
            'files': {},
        }
        (self.root / 'regression.log').write_bytes(b'actual bounded test fixture log\n')
        self.store()

    def store(self):
        (self.root / 'tests.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.receipt['files'] = {name: sha256((self.root / name).read_bytes()).hexdigest() for name in ('tests.json', 'regression.log')}
        (self.root / 'receipt.json').write_text(json.dumps(self.receipt), encoding='utf-8')

    def validate(self):
        return MODULE['validate'](self.root, self.current, self.ids, self.skips, now=self.now)

    def test_complete_real_bytes_and_full_order_are_accepted(self):
        self.assertEqual(self.validate(), self.receipt)

    def test_all_run_attempt_workflow_and_commit_mismatches_are_rejected(self):
        for key in self.current['ci']:
            with self.subTest(key=key):
                saved = copy.deepcopy(self.receipt)
                for phase in ('context_before', 'context_after'):
                    self.receipt[phase]['ci'][key] += '-different'
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt = saved

    def test_source_sqlite_lock_and_dependency_mismatch_are_rejected(self):
        for replacement in (
            {'source_inputs': {}},
            {'runtime': {'python': '3.13.15'}},
            {'runtime': {'sqlite': {'library_sha256': '0' * 64}}},
            {'runtime': {'dependency_lock_sha256': '0' * 64}},
            {'runtime': {'locked_dependencies': {}}},
        ):
            with self.subTest(replacement=replacement):
                saved = copy.deepcopy(self.receipt)
                self.receipt['context_after'].update(replacement)
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt = saved

    def test_missing_duplicate_reordered_and_fixture_blocked_cases_cannot_pass(self):
        for key in ('discovered_ids', 'selected_ids', 'started_ids', 'stopped_ids'):
            for value in ([], self.ids[:-1], [self.ids[0], self.ids[0], self.ids[2]], list(reversed(self.ids))):
                with self.subTest(key=key, value=value):
                    saved = copy.deepcopy(self.manifest)
                    self.manifest[key] = value
                    self.store()  # Rehash bytes so the semantic validator must reject.
                    with self.assertRaises(ValueError):
                        self.validate()
                    self.manifest = saved

    def test_failures_errors_discovery_fixture_and_expected_failure_are_rejected(self):
        for key in ('discovery_errors', 'failures', 'errors', 'expected_failures', 'unexpected_successes'):
            with self.subTest(key=key):
                self.manifest[key] = ['setUpClass (test_a.First)']
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()
                self.manifest[key] = []

    def test_empty_success_false_counts_nonfull_suite_and_false_completion_rejected(self):
        for key, value in (
            ('run_completed', False),
            ('successful', False),
            ('tests_run', 0),
            ('tests_run', True),
            ('group', 'core'),
            ('platform', 'linux'),
            ('python', '3.13.15'),
        ):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.manifest)
                self.manifest[key] = value
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()
                self.manifest = saved

    def test_unknown_omitted_or_changed_skip_is_rejected(self):
        for value in ([], [{'id': self.ids[0], 'reason': 'New skip'}], [{'id': self.ids[1], 'reason': 'Changed reason'}], self.skips * 2):
            with self.subTest(value=value):
                self.manifest['skipped'] = value
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_failed_producer_or_runner_never_authorizes_freeze(self):
        for key, value in (
            ('schema_version', True),
            ('producer_job', 'build'),
            ('successful', False),
            ('completed', False),
            ('returncode', 1),
            ('returncode', True),
            ('validation_error', 'fixture failure'),
        ):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.receipt)
                self.receipt[key] = value
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt = saved

    def test_stale_future_naive_reversed_and_overlong_evidence_rejected(self):
        for started, completed in (
            (self.now - timedelta(hours=3, minutes=29), self.now - timedelta(hours=3)),
            (self.now, self.now + timedelta(minutes=2)),
            (self.now.replace(tzinfo=None), self.now.replace(tzinfo=None)),
            (self.now, self.now - timedelta(seconds=1)),
            (self.now - timedelta(seconds=2101), self.now),
        ):
            with self.subTest(started=started, completed=completed):
                self.receipt.update(started_at=started.isoformat(), completed_at=completed.isoformat())
                self.store()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_tampered_or_missing_log_and_manifest_and_duplicate_json_refused(self):
        for name in ('regression.log', 'tests.json'):
            original = (self.root / name).read_bytes()
            with self.subTest(name=name):
                (self.root / name).write_bytes(original + b'changed')
                with self.assertRaises(ValueError):
                    self.validate()
                (self.root / name).unlink()
                with self.assertRaises(ValueError):
                    self.validate()
                (self.root / name).write_bytes(original)
        (self.root / 'receipt.json').write_text('{"successful":true,"successful":true}')
        with self.assertRaises(ValueError):
            self.validate()

    def test_producer_executes_original_all_runner_and_records_failure_honestly(self):
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                folder = self.root / ('producer-' + str(exit_code))

                def execute(command, **options):
                    self.assertEqual(command[-4:-2], ['--group', 'all'])
                    self.assertNotIn('--core-shard', command)
                    self.assertNotIn('--workers', command)
                    target = Path(command[-1])
                    target.write_text(json.dumps(self.manifest), encoding='utf-8')
                    options['stdout'].write(b'actual injected runner output\n')
                    return SimpleNamespace(returncode=exit_code)

                with (
                    patch.dict(GLOBALS, context=lambda job: copy.deepcopy(self.current), discover=lambda: (self.ids, self.skips)),
                    patch.object(GLOBALS['subprocess'], 'run', side_effect=execute),
                ):
                    self.assertEqual(MODULE['run'](folder), exit_code)
                proof = MODULE['document'](folder / 'receipt.json')
                self.assertEqual(proof['successful'], exit_code == 0)
                self.assertEqual(proof['returncode'], exit_code)


class RegressionWorkflowBoundaryTests(unittest.TestCase):
    def test_context_requires_exact_clean_head_and_full_history_baseline(self):
        ci = {'GITHUB_SHA': 'a' * 40}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'one.py').write_bytes(b'# exact source bytes\n')

            def git(command, **options):
                if command[1:3] == ['rev-parse', 'HEAD']:
                    return ci['GITHUB_SHA']
                if command[1] == 'status':
                    return ''
                return b'one.py\0'

            with (
                patch.dict(GLOBALS, ROOT=root, ci_identity=lambda job: ci, runtime_identity=lambda: {'test': 'synthetic runtime identity'}),
                patch.object(GLOBALS['subprocess'], 'check_output', side_effect=git),
                patch.object(GLOBALS['subprocess'], 'run') as baseline,
            ):
                value = MODULE['context']('build')
                self.assertEqual(value['source_inputs'], {'one.py': sha256((root / 'one.py').read_bytes()).hexdigest()})
                self.assertEqual(baseline.call_args.args[0], ['git', 'cat-file', '-e', '4095c3e9fdd2e91f1423d6d1bf76466834cdb417^{commit}'])
                baseline.side_effect = GLOBALS['subprocess'].CalledProcessError(1, 'git cat-file')
                with self.assertRaises(GLOBALS['subprocess'].CalledProcessError):
                    MODULE['context']('build')
            with patch.dict(GLOBALS, ci_identity=lambda job: ci), patch.object(GLOBALS['subprocess'], 'check_output', side_effect=['a' * 40, ' M changed.py']):
                with self.assertRaises(ValueError):
                    MODULE['context']('build')

    def test_ci_identity_rejects_local_wrong_job_missing_run_and_other_workflow(self):
        env = {
            'GITHUB_ACTIONS': 'true',
            'GITHUB_JOB': 'build',
            'GITHUB_SHA': 'a' * 40,
            'GITHUB_REPOSITORY': 'owner/repo',
            'GITHUB_RUN_ID': '12',
            'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_WORKFLOW_REF': 'owner/repo/.github/workflows/windows-desktop.yml@refs/heads/main',
            'GITHUB_EVENT_NAME': 'push',
        }
        self.assertEqual(MODULE['ci_identity']('build', env)['GITHUB_SHA'], 'a' * 40)
        for key, value in (
            ('GITHUB_ACTIONS', 'false'),
            ('GITHUB_JOB', 'quality'),
            ('GITHUB_RUN_ID', ''),
            ('GITHUB_RUN_ATTEMPT', '0'),
            ('GITHUB_WORKFLOW_REF', 'owner/repo/.github/workflows/other.yml@main'),
            ('GITHUB_SHA', 'unknown'),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    MODULE['ci_identity']('build', dict(env, **{key: value}))

    def test_declared_skip_not_in_reviewed_policy_fails_independent_discovery(self):
        class UnknownSkip(unittest.TestCase):
            @unittest.skip('Unreviewed platform escape')
            def test_unknown(self):
                pass

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'packaging').mkdir()
            (root / 'packaging/desktop_regression_skips.json').write_text('{"schema_version":1,"skips":{}}')
            with patch.dict(GLOBALS, ROOT=root), patch.object(unittest.TestLoader, 'discover', return_value=unittest.TestSuite([UnknownSkip('test_unknown')])):
                with self.assertRaises(ValueError):
                    MODULE['discover']()

    def test_default_local_regression_and_both_35_minute_jobs_remain_enforced(self):
        workflow = (ROOT / '.github/workflows/windows-desktop.yml').read_text()
        regression = workflow.split('  regression:', 1)[1].split('  build:', 1)[0]
        build = workflow.split('  build:', 1)[1].split('  release:', 1)[0]
        self.assertIn('timeout-minutes: 35', regression)
        self.assertIn('timeout-minutes: 35', build)
        self.assertIn('fetch-depth: 0', regression)
        self.assertIn('fetch-depth: 0', build)
        self.assertIn('needs: [quality, regression]', build)
        exact = 'desktop-full-regression-${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}'
        self.assertIn(exact, regression)
        self.assertIn(exact, build)
        script = (ROOT / 'packaging/build.ps1').read_text()
        self.assertIn('& $python -m unittest discover -s tests -v', script)
        self.assertLess(script.index('desktop_regression.py verify'), script.index('-m PyInstaller'))
        self.assertIn('Regression producer and receipt consumer are separate phases', script)
