"""Complete UI partition coverage may never accept missing, stale, skipped or failed work."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import run_test_group, ui_test_gate as gate


def fixture():
    core = [f'test_ui.UITests.test_{index}' for index in range(5)] + ['test_future.Core.test_a']
    research = ['test_research.Research.test_a']
    parts = {'core': core, 'research': research}
    expected = {'discovered_ids': core + research, 'partitions': parts}
    context = {'plan': gate.PLAN, 'head_sha': 'a' * 40, 'run_id': '123', 'run_attempt': '2', 'source_sha256': 'b' * 64, 'streamlit': '1.65.0'}
    version = json.loads((gate.ROOT / 'packaging/sqlite-runtime.json').read_text(encoding='utf-8'))['version']
    identity = {
        'source_sha256': 'c' * 64,
        'head_sha': context['head_sha'],
        'sqlite_version': version,
        'python': '3.12.13 fixture',
        'environment': {'QT_QPA_PLATFORM': 'offscreen'},
        'executable': '/fixture/python',
        'tempfile_gettempdir': '/fixture/tmp',
    }
    reports = [
        {
            **deepcopy(expected),
            'group': key,
            'head_sha': context['head_sha'],
            'platform': 'linux',
            'python': '3.12.13',
            'ui_context': deepcopy(context),
            'ui_identity_before': deepcopy(identity),
            'ui_identity_after': deepcopy(identity),
            'selected_ids': ids[:],
            'started_ids': ids[:],
            'stopped_ids': ids[:],
            'tests_run': len(ids),
            'run_completed': True,
            'successful': True,
            **{field: [] for field in ('discovery_errors', 'failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes')},
        }
        for key, ids in parts.items()
    ]
    return reports, expected, context, identity


class UiTestGateTests(unittest.TestCase):
    def test_context_binds_both_ui_packages_and_the_installed_streamlit_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package in ('desktop_pages', 'desktop_smoke'):
                (root / package).mkdir()
                (root / package / 'fixture.py').write_text('VALUE = 1\n', encoding='utf-8')
            (root / 'requirements-ui.lock').write_text('streamlit==1.65.0\n', encoding='utf-8')
            with (
                patch.object(gate, 'ROOT', root),
                patch.object(run_test_group, 'portable_source_identity', return_value='b' * 64),
                patch.object(gate.importlib.metadata, 'version', return_value='1.65.0') as installed,
            ):
                original = gate.context()['source_sha256']
                for package in ('desktop_pages', 'desktop_smoke'):
                    (root / package / 'fixture.py').write_text('VALUE = 2\n', encoding='utf-8')
                    current = gate.context()['source_sha256']
                    self.assertNotEqual(current, original)
                    original = current
                installed.return_value = '1.64.0'
                with self.assertRaises(ValueError):
                    gate.context()
                with self.assertRaises(ValueError):
                    gate.context('offline')
                installed.side_effect = gate.importlib.metadata.PackageNotFoundError
                self.assertIsNone(gate.context('offline')['streamlit'])
                with self.assertRaises(ValueError):
                    gate.context()

    def verify(self, reports, expected, context, identity, skips=None):
        with patch.object(gate.platform, 'python_version', return_value='3.12.13'):
            return gate.validate(reports, expected, context, identity, skips or [])

    def test_original_complete_partition_union_succeeds(self):
        values = fixture()
        result = self.verify(*values)
        self.assertTrue(result['successful'])
        self.assertEqual(result['tests_run'], 7)
        self.assertEqual(len(result['streamlit_cases']), 5)

    def test_offline_profiles_keep_exact_skips_and_cannot_substitute_for_ui(self):
        for version in ('3.11', '3.12'):
            reports, expected, context, identity = fixture()
            context.update(plan=gate.OFFLINE_PLAN, streamlit=None)
            identity['python'] = version + '.13 fixture'
            skips = [{'id': item, 'reason': 'Original offline dependency profile'} for item in expected['discovered_ids'][:5]]
            for report in reports:
                report.update(ui_context=deepcopy(context), python=version + '.13', ui_identity_before=deepcopy(identity), ui_identity_after=deepcopy(identity))
            reports[0]['skipped'] = skips
            with patch.object(gate.platform, 'python_version', return_value=version + '.13'):
                self.assertTrue(gate.validate(reports, expected, context, identity, skips, version)['successful'])
                with self.assertRaises(ValueError):
                    gate.validate(reports, expected, context, identity, [], version)
                with self.assertRaises(ValueError):
                    gate.validate(reports, expected, {**context, 'plan': gate.PLAN}, identity, skips, version)
                with self.assertRaises(ValueError):
                    gate.validate(reports, expected, context, identity, skips, '3.10')
                reports[0]['python'] = '3.13.1'
                with self.assertRaises(ValueError):
                    gate.validate(reports, expected, context, identity, skips, version)

    def test_applicability_baselines_are_original_and_only_offline_adds_five_streamlit_skips(self):
        root = gate.ROOT / 'tests/fixtures'
        ui = json.loads((root / 'ui_linux_applicability_skips.json').read_text(encoding='utf-8'))
        offline = json.loads((root / 'linux_offline_applicability_skips.json').read_text(encoding='utf-8'))
        self.assertEqual(
            hashlib.sha256(json.dumps(ui, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            '6433af69149278c4252c412d55664aa2082dcc15e7a6193ca43d5f0b9cb745a9',
        )
        self.assertEqual([row for row in offline if not row['id'].startswith('test_ui.UITests.')], ui)
        extras = [row for row in offline if row['id'].startswith('test_ui.UITests.')]
        self.assertEqual(len(extras), 5)
        self.assertEqual({row['reason'] for row in extras}, {'Optional Streamlit is not installed; UI verification not run'})

    def test_missing_duplicate_stale_failed_incomplete_and_new_skip_are_refused(self):
        for field, bad in (
            ('head_sha', 'd' * 40),
            ('platform', 'win32'),
            ('python', '3.11.9'),
            ('selected_ids', []),
            ('started_ids', []),
            ('stopped_ids', []),
            ('tests_run', True),
            ('run_completed', False),
            ('successful', False),
            ('discovery_errors', ['import failure']),
            ('failures', ['case']),
            ('errors', ['case']),
            ('expected_failures', ['case']),
            ('unexpected_successes', ['case']),
            ('skipped', [{'id': 'test_ui.UITests.test_0', 'reason': 'missing dependency'}]),
            ('identity_error', True),
            ('cleanup_error', 'unjoined'),
        ):
            values = fixture()
            values[0][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(*values)
        for mutation in (
            lambda rows: rows.pop(),
            lambda rows: rows.append(deepcopy(rows[0])),
            lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
            lambda rows: rows[0]['ui_context'].update(run_attempt='1'),
            lambda rows: rows[0]['ui_context'].update(source_sha256='d' * 64),
            lambda rows: rows[0]['ui_identity_after'].update(source_sha256='d' * 64),
        ):
            values = fixture()
            mutation(values[0])
            with self.assertRaises(ValueError):
                self.verify(*values)

    def test_wrong_independent_discovery_and_context_never_borrow_passes(self):
        for key in ('head_sha', 'run_id', 'run_attempt', 'source_sha256', 'plan', 'streamlit'):
            values = fixture()
            values[2][key] = None
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(*values)
        for change in ('missing', 'duplicate', 'overlap', 'missing_streamlit'):
            values = fixture()
            expected = values[1]
            if change == 'missing':
                expected['discovered_ids'].pop()
            elif change == 'duplicate':
                expected['discovered_ids'].append(expected['discovered_ids'][0])
            elif change == 'overlap':
                expected['partitions']['research'].append(expected['partitions']['core'][0])
            else:
                expected['discovered_ids'] = [item.replace('test_ui.UITests.', 'test_hidden.Other.') for item in expected['discovered_ids']]
                expected['partitions']['core'] = expected['discovered_ids'][:-1]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(*values)

    def test_runner_retains_original_case_producer_and_failure_status(self):
        for status, changed, successful in ((0, False, True), (1, False, True), (0, True, True), (0, False, False)):
            with self.subTest(status=status, changed=changed, successful=successful), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'ui-test-inventory.json'
                rows, _, context, identity = fixture()
                rows[0]['successful'] = successful

                def produce(arguments):
                    Path(arguments[arguments.index('--manifest') + 1]).write_text(json.dumps(rows[0]), encoding='utf-8')
                    return status

                after = {**identity, 'source_sha256': 'd' * 64} if changed else identity
                with (
                    patch.object(gate, 'context', return_value=context),
                    patch.object(run_test_group, 'execution_identity', side_effect=[identity, after]),
                    patch.object(run_test_group, 'main', side_effect=produce) as original,
                ):
                    result = gate.run('core', destination)
                original.assert_called_once_with(['--group', 'core', '--manifest', str(destination.with_suffix('.cases.json'))])
                report = json.loads(destination.read_text(encoding='utf-8'))
                self.assertEqual(report['selected_ids'], rows[0]['selected_ids'])
                self.assertEqual(report['successful'], status == 0 and not changed and successful)
                self.assertEqual(result, 0 if status == 0 and not changed and successful else 1)

    def test_workflow_preserves_budgets_and_demands_same_attempt_aggregate(self):
        source = (gate.ROOT / '.github/workflows/quantlab.yml').read_text(encoding='utf-8')
        producers = source.split('  ui-tests:\n', 1)[1].split('  ui:\n', 1)[0]
        aggregate = source.split('  ui:\n', 1)[1].split('  quality:\n', 1)[0]
        self.assertIn('timeout-minutes: 15', producers)
        self.assertIn('group: [core, research]', producers)
        self.assertIn('fail-fast: false', producers)
        self.assertIn('python tools/ui_test_gate.py --group ${{ matrix.group }}', producers)
        self.assertIn('attempt-${{ github.run_attempt }}', producers)
        self.assertIn('needs: [changes, ui-tests]', aggregate)
        self.assertIn('attempt-${{ github.run_attempt }}', aggregate)
        self.assertIn('python tools/ui_test_gate.py --reports', aggregate)
        self.assertIn('UI_RESULT', aggregate)
        self.assertIn('ui, security', source.split('  gate:\n', 1)[1])
