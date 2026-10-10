"""Publish only reviewed-main ancestry with all required, successful evidence."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_gate', ROOT / 'packaging/wait_for_gates.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ReleaseProvenanceTests(unittest.TestCase):
    def test_identical_and_ancestor_main_allowed(self):
        for status in ('identical', 'ahead'):
            with patch.object(gate, 'api', return_value={'status': status, 'merge_base_commit': {'sha': 'abc'}}):
                gate.require_main_ancestry('owner/repo', 'abc')

    def test_unmerged_or_unverifiable_tags_rejected(self):
        for response in ({}, {'status': 'behind', 'merge_base_commit': {'sha': 'abc'}},
                         {'status': 'diverged', 'merge_base_commit': {'sha': 'old'}},
                         {'status': 'ahead', 'merge_base_commit': {'sha': 'old'}}):
            with patch.object(gate, 'api', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'not reachable'):
                    gate.require_main_ancestry('owner/repo', 'abc')

    def test_successful_subset_or_duplicate_jobs_are_not_acceptance(self):
        run = {'head_sha': 'abc', 'event': 'push', 'run_number': 1, 'run_attempt': 1,
               'status': 'completed', 'conclusion': 'success', 'id': 2, 'html_url': 'https://example.test/run'}
        all_jobs = [{'name': name, 'conclusion': 'success'} for name in sorted(gate.REQUIRED_JOBS)]
        for jobs in (all_jobs[:1], all_jobs + [all_jobs[0]], [{'name': 'unknown', 'conclusion': 'success'}]):
            with patch.dict(gate.os.environ, GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='abc'):
                with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', side_effect=[
                    {'workflow_runs': [run]}, {'jobs': jobs, 'total_count': len(jobs)}]):
                    with self.assertRaisesRegex(RuntimeError, 'named jobs'):
                        gate.main()

    def test_windows_research_and_linux_qt_audit_are_required(self):
        required = {'offline research (windows-latest, 3.11)',
                    'offline research (windows-latest, 3.12)',
                    'Dependency audit (qt-linux311)'}
        self.assertTrue(required <= gate.REQUIRED_JOBS)
        run = {'head_sha': 'abc', 'event': 'push', 'run_number': 1, 'run_attempt': 1,
               'status': 'completed', 'conclusion': 'success', 'id': 2,
               'html_url': 'https://example.test/run'}
        for missing in required:
            jobs = [{'name': name, 'conclusion': 'success'}
                    for name in sorted(gate.REQUIRED_JOBS - {missing})]
            with self.subTest(missing=missing), patch.dict(
                    gate.os.environ, GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='abc'):
                with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', side_effect=[
                    {'workflow_runs': [run]}, {'jobs': jobs, 'total_count': len(jobs)}]):
                    with self.assertRaisesRegex(RuntimeError, 'named jobs'):
                        gate.main()

    def test_every_job_including_unexpected_jobs_must_succeed(self):
        run = {'head_sha': 'abc', 'event': 'push', 'run_number': 1, 'run_attempt': 1,
               'status': 'completed', 'conclusion': 'success', 'id': 2,
               'html_url': 'https://example.test/run'}
        for name in (*sorted(gate.REQUIRED_JOBS), 'additional gate'):
            for conclusion in ('failure', 'skipped', 'cancelled', None):
                jobs = [{'name': required, 'conclusion': 'success'}
                        for required in sorted(gate.REQUIRED_JOBS) if required != name]
                jobs.append({'name': name, 'conclusion': conclusion})
                with self.subTest(name=name, conclusion=conclusion), patch.dict(
                        gate.os.environ, GITHUB_REPOSITORY='owner/repo', GITHUB_SHA='abc'):
                    with patch.object(gate, 'require_main_ancestry'), patch.object(gate, 'api', side_effect=[
                        {'workflow_runs': [run]}, {'jobs': jobs, 'total_count': len(jobs)}]):
                        with self.assertRaisesRegex(RuntimeError, 'Every Quantlab job'):
                            gate.main()
