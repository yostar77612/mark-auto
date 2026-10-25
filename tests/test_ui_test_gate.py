"""Complete UI partition coverage may never accept missing, stale, skipped or failed work."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools import run_test_group, ui_test_gate as gate


def fixture():
    core = [f'test_ui.UITests.test_{index}' for index in range(5)] + [
        'test_future.Core.test_a',
        'test_desktop_fixture.Core.test_a',
        'test_trading_fixture.Core.test_a',
    ]
    research = ['test_research.Research.test_a']
    parts = {'core': core, 'research': research}
    expected = {'discovered_ids': core + research, 'partitions': parts}
    context = {
        'plan': gate.PLAN,
        'head_sha': 'a' * 40,
        'run_id': '123',
        'run_attempt': '2',
        'source_sha256': 'b' * 64,
        'core_source_sha256': 'e' * 64,
        'streamlit': '1.65.0',
    }
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
    selections = {'paper-remaining': core[:6], 'desktop-trading': core[6:], 'research': research}
    reports = []
    for key, ids in selections.items():
        report = {
            **deepcopy(expected),
            'group': 'research' if key == 'research' else 'core',
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
        if key != 'research':
            report.update(
                core_slice=key,
                core_slice_plan=run_test_group.LINUX_CORE_PLAN,
                core_slice_assignments={name: selections[name][:] for name in ('desktop-trading', 'paper-remaining')},
                core_slice_context={
                    'head_sha': context['head_sha'],
                    'run_id': context['run_id'],
                    'run_attempt': context['run_attempt'],
                    'python_profile': '3.12',
                    'source_sha256': context['core_source_sha256'],
                },
                source_sha256_after=context['core_source_sha256'],
                local_identity_before=deepcopy(identity),
                local_identity_after=deepcopy(identity),
            )
        reports.append(report)
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
        self.assertEqual(result['tests_run'], 9)
        self.assertEqual(len(result['streamlit_cases']), 5)
        self.assertEqual(result['producers'], ['desktop-trading', 'paper-remaining', 'research'])

    def test_each_slice_and_research_must_have_its_own_current_proof(self):
        for role in ('desktop-trading', 'paper-remaining', 'research'):
            for mode in ('missing', 'duplicate', 'incomplete', 'wrong-attempt', 'wrong-source', 'native-source', 'assignment', 'old-plan', 'new-skip'):
                values = fixture()
                reports = values[0]
                row = next(item for item in reports if (item.get('core_slice') or item['group']) == role)
                if mode == 'missing':
                    reports.remove(row)
                elif mode == 'duplicate':
                    reports.append(deepcopy(row))
                elif mode == 'incomplete':
                    row['stopped_ids'].pop()
                elif mode == 'wrong-attempt':
                    row['ui_context']['run_attempt'] = '1'
                elif mode == 'wrong-source':
                    row['ui_context']['core_source_sha256'] = 'f' * 64
                elif mode == 'new-skip':
                    row['skipped'] = [{'id': row['selected_ids'][0], 'reason': 'temporary'}]
                elif role == 'research':
                    row['core_slice'] = 'desktop-trading'
                elif mode == 'native-source':
                    row['source_sha256_after'] = 'f' * 64
                elif mode == 'assignment':
                    row['core_slice_assignments']['paper-remaining'].pop()
                else:
                    row['core_slice_plan'] = 'obsolete-plan'
                with self.subTest(role=role, mode=mode), self.assertRaises(ValueError):
                    self.verify(*values)

    def test_correlated_slice_forgery_cannot_redefine_independent_discovery(self):
        for mode in ('omit', 'move', 'duplicate'):
            values = fixture()
            reports, expected, _, _ = values
            target = 'test_trading_fixture.Core.test_a'
            for row in reports:
                if row['group'] != 'core':
                    continue
                assignments = row['core_slice_assignments']
                if mode != 'duplicate':
                    assignments['desktop-trading'].remove(target)
                if mode != 'omit':
                    assignments['paper-remaining'].append(target)
                ids = assignments[row['core_slice']]
                for field in ('selected_ids', 'started_ids', 'stopped_ids'):
                    row[field] = ids[:]
                row['tests_run'] = len(ids)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.verify(reports, expected, values[2], values[3])

    def test_slice_producer_delegates_actual_runner_without_rewriting_started_order(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'ui-test-inventory.json'
            rows, _, context, identity = fixture()

            def produce(arguments):
                Path(arguments[arguments.index('--manifest') + 1]).write_text(json.dumps(rows[0]), encoding='utf-8')
                return 0

            with (
                patch.object(gate, 'context', return_value=context),
                patch.object(run_test_group, 'execution_identity', side_effect=[identity, identity]),
                patch.object(run_test_group, 'main', side_effect=produce) as original,
            ):
                self.assertEqual(gate.run('core', destination, core_slice='paper-remaining'), 0)
            original.assert_called_once_with(
                [
                    '--group',
                    'core',
                    '--manifest',
                    str(destination.with_suffix('.cases.json')),
                    '--core-slice',
                    'paper-remaining',
                ]
            )
            report = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(report['started_ids'], rows[0]['started_ids'])
            self.assertEqual(report['stopped_ids'], rows[0]['stopped_ids'])

    def test_offline_profiles_keep_exact_skips_and_cannot_substitute_for_ui(self):
        for version in ('3.11', '3.12'):
            reports, expected, context, identity = fixture()
            context.update(plan=gate.OFFLINE_PLAN, streamlit=None)
            identity['python'] = version + '.13 fixture'
            skips = [{'id': item, 'reason': 'Original offline dependency profile'} for item in expected['discovered_ids'][:5]]
            for report in reports:
                report.update(ui_context=deepcopy(context), python=version + '.13', ui_identity_before=deepcopy(identity), ui_identity_after=deepcopy(identity))
                if report['group'] == 'core':
                    report.update(local_identity_before=deepcopy(identity), local_identity_after=deepcopy(identity))
                    report['core_slice_context']['python_profile'] = version
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
        for key in ('head_sha', 'run_id', 'run_attempt', 'source_sha256', 'core_source_sha256', 'plan', 'streamlit'):
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
        rows = re.findall(r'^          - \{group: ([^,}]+)(?:, core_slice: ([^}]+))?\}$', producers, re.MULTILINE)
        self.assertCountEqual(rows, [('core', 'desktop-trading'), ('core', 'paper-remaining'), ('research', '')])
        self.assertEqual(len(rows), 3)
        self.assertIn(
            "name: desktop-auth-ui-linux312-${{ matrix.group }}${{ matrix.core_slice && format('-{0}', matrix.core_slice) || '' }}-attempt-${{ github.run_attempt }}",
            producers,
        )
        self.assertIn("format('--core-slice {0}', matrix.core_slice)", producers)
        self.assertIn('fail-fast: false', producers)
        self.assertIn('python tools/ui_test_gate.py --group ${{ matrix.group }}', producers)
        self.assertIn('attempt-${{ github.run_attempt }}', producers)
        self.assertIn('needs: [changes, ui-tests]', aggregate)
        self.assertIn('attempt-${{ github.run_attempt }}', aggregate)
        self.assertIn('python tools/ui_test_gate.py --reports', aggregate)
        self.assertIn('UI_RESULT', aggregate)
        self.assertIn('ui, security', source.split('  gate:\n', 1)[1])
