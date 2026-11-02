"""Admit only the eleven existing native-registry applicability rows, preserving history."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools import repin_baselines as repin


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'tests/test_autostart.py'
FIXTURES = ('tests/fixtures/ui_linux_applicability_skips.json', 'tests/fixtures/linux_offline_applicability_skips.json')
METHODS = (
    'test_correct_registration_has_no_write',
    'test_create_error_is_specific',
    'test_default_off_does_not_create_key',
    'test_delete_error_preserves_registration',
    'test_disable_missing_key_is_idempotent',
    'test_disable_removes_only_owned_value',
    'test_enable_quotes_only_executable_under_hkcu',
    'test_query_error_is_not_treated_as_disabled',
    'test_read_access_error_is_specific',
    'test_repair_follows_updated_or_moved_executable',
    'test_write_error_is_specific',
)
ADDITIONS = [{'id': 'test_autostart.RunAutostartTests.' + method, 'reason': 'Windows registry required'} for method in METHODS]


class RegistryApplicabilityPlanTests(unittest.TestCase):
    def setUp(self):
        self.scope = tempfile.TemporaryDirectory(prefix='registry-repin-')
        self.addCleanup(self.scope.cleanup)
        self.root = Path(self.scope.name)
        self.source = (ROOT / SOURCE).read_text(encoding='utf-8')
        self.store(SOURCE, self.source)
        added_ids = {row['id'] for row in ADDITIONS}
        self.historical = {}
        for name in FIXTURES:
            rows = json.loads((ROOT / name).read_text(encoding='utf-8'))
            self.historical[name] = [row for row in rows if row['id'] not in added_ids]
            self.store(name, repin.render_json(self.historical[name]))

    def store(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')

    def test_plan_adds_exactly_eleven_rows_and_never_writes_during_planning(self):
        before = {name: (self.root / name).read_bytes() for name in (*FIXTURES, SOURCE)}
        plan = repin.registry_applicability_plan(self.root)
        self.assertEqual(plan.blockers, [])
        self.assertEqual(set(plan.edits), set(FIXTURES))
        self.assertIn('test_ui_test_gate', plan.verify)
        for name, text in plan.edits.items():
            rows = json.loads(text)
            self.assertEqual([row for row in rows if row['id'].startswith('test_autostart.')], ADDITIONS)
            self.assertEqual([row for row in rows if not row['id'].startswith('test_autostart.')], self.historical[name])
            self.assertEqual(len(rows), len(self.historical[name]) + 11)
            self.assertEqual(rows, sorted(rows, key=lambda row: row['id']))
        self.assertEqual({name: (self.root / name).read_bytes() for name in before}, before)

    def test_cli_registration_and_written_plan_are_idempotent(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(repin.main(['--root', str(self.root), '--only', 'registry_applicability']), 1)
        plan = repin.registry_applicability_plan(self.root)
        repin.apply(self.root, plan, check=False)
        self.assertEqual(repin.registry_applicability_plan(self.root).edits, {})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(repin.main(['--root', str(self.root), '--only', 'registry_applicability']), 0)

    def test_changed_class_skip_condition_or_reason_is_refused(self):
        for original, replacement in (
            ('unittest.skipIf(', 'unittest.skipUnless('),
            ('autostart.winreg is None', 'autostart.winreg is not None'),
            ("'Windows registry required'", "'arbitrary skip'"),
            ('class RunAutostartTests(', 'class OtherRegistryTests('),
        ):
            with self.subTest(replacement=replacement):
                self.store(SOURCE, self.source.replace(original, replacement, 1))
                with self.assertRaises(repin.Blocked):
                    repin.registry_applicability_plan(self.root)

    def test_added_removed_or_renamed_test_cannot_expand_the_skip_authority(self):
        for source in (
            self.source.replace('def test_default_off_does_not_create_key(', 'def helper_default_off('),
            self.source.replace('def test_default_off_does_not_create_key(', 'def test_unreviewed_case('),
            self.source.replace('class InstalledAutostartTests', '    def test_unreviewed_case(self):\n        pass\n\n\nclass InstalledAutostartTests', 1),
            self.source.replace(
                '    def test_default_off_does_not_create_key(', "    @unittest.skip('new reason')\n    def test_default_off_does_not_create_key(", 1
            ),
        ):
            with self.subTest(source_change=source != self.source):
                self.store(SOURCE, source)
                with self.assertRaises(repin.Blocked):
                    repin.registry_applicability_plan(self.root)

    def test_every_historical_entry_reason_and_order_remains_frozen(self):
        for name in FIXTURES:
            original = self.historical[name]
            variants = (
                original[1:],
                [{**original[0], 'reason': 'changed'}, *original[1:]],
                [*original, {'id': 'test_other.T.test_new', 'reason': 'unreviewed'}],
                [original[1], original[0], *original[2:]],
            )
            for changed in variants:
                with self.subTest(name=name, changed_count=len(changed)):
                    self.store(name, repin.render_json(changed))
                    with self.assertRaises(repin.Blocked):
                        repin.registry_applicability_plan(self.root)
            self.store(name, repin.render_json(original))

    def test_existing_reviewed_rows_are_preserved_but_changed_or_duplicate_rows_are_refused(self):
        name = FIXTURES[0]
        existing = sorted(self.historical[name] + ADDITIONS[:1], key=lambda row: row['id'])
        self.store(name, repin.render_json(existing))
        plan = repin.registry_applicability_plan(self.root)
        self.assertEqual(json.loads(plan.edits[name]), sorted(self.historical[name] + ADDITIONS, key=lambda row: row['id']))
        for rows in (
            self.historical[name] + [{**ADDITIONS[0], 'reason': 'changed'}],
            self.historical[name] + [ADDITIONS[0], ADDITIONS[0]],
            self.historical[name] + [{'id': 'test_autostart.RunAutostartTests.test_unknown', 'reason': 'Windows registry required'}],
        ):
            with self.subTest(rows_count=len(rows)):
                self.store(name, repin.render_json(rows))
                with self.assertRaises(repin.Blocked):
                    repin.registry_applicability_plan(self.root)

    def test_test_module_is_read_as_ast_and_never_imported(self):
        self.store(SOURCE, "raise AssertionError('must not execute this module')\n" + self.source)
        self.assertEqual(len(repin.registry_applicability_plan(self.root).edits), 2)

    def test_a_blocked_second_fixture_prevents_writing_either_fixture(self):
        self.store(FIXTURES[1], repin.render_json(self.historical[FIXTURES[1]][1:]))
        before = {name: (self.root / name).read_bytes() for name in FIXTURES}
        with contextlib.redirect_stdout(io.StringIO()):
            status = repin.main(['--root', str(self.root), '--only', 'registry_applicability', '--write', '--no-verify'])
        self.assertEqual(status, 2)
        self.assertEqual({name: (self.root / name).read_bytes() for name in FIXTURES}, before)
