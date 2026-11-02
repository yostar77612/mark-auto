"""The M4a repin plan measures its added checkbox and preserves other UI budgets."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import repin_baselines as repin


class SettingsInputsPlanTests(unittest.TestCase):
    def setUp(self):
        self.scope = tempfile.TemporaryDirectory(prefix='m4a-repin-plan-')
        self.addCleanup(self.scope.cleanup)
        self.root = Path(self.scope.name)
        self.before = {
            'visible_input_count': 4,
            'button_count': 8,
            'label_char_count': 59,
            'unlabeled_inputs': [],
            'primary_button_count': 1,
            'visible_text': ['existing'],
            'combo_items': ['dark', 'light'],
            'table_headers': [],
        }
        self.presentation = {'pages': {'other': {'keep': 'unchanged'}, 'settings': self.before}}
        self.policy = {
            'default_input_counts': [3, 0, 0, 0, 3, 4, 4],
            'max_default_page_height': 1600,
            'max_default_primary_buttons': 1,
            'original_tooltips': {'preserved': 'old.tooltip'},
        }
        for name, value in ((repin.SETTINGS_PRESENTATION, self.presentation), (repin.SETTINGS_TOOLTIP_POLICY, self.policy)):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2), encoding='utf-8')
        self.actual = {
            **self.before,
            'visible_input_count': 5,
            'button_count': 9,
            'label_char_count': 100,
            'visible_text': ['existing', 'startup checkbox hint'],
            'page_height': 900,
        }
        self.measured = {'name': 'settings', 'settings': self.actual, 'counts': [3, 0, 0, 0, 3, 4, 5]}

    def plan(self):
        with patch.object(repin, 'run_python', return_value=json.dumps(self.measured)):
            return repin.settings_inputs_plan(self.root)

    def test_only_settings_expected_values_and_its_exact_input_count_change(self):
        original = {name: (self.root / name).read_bytes() for name in (repin.SETTINGS_PRESENTATION, repin.SETTINGS_TOOLTIP_POLICY)}
        plan = self.plan()
        self.assertEqual(plan.blockers, [])
        self.assertEqual(set(plan.edits), set(original))
        self.assertEqual(plan.verify, ('test_b4_appearance', 'test_t16_tooltips'))
        presentation = json.loads(plan.edits[repin.SETTINGS_PRESENTATION])
        self.assertEqual(presentation['pages']['other'], self.presentation['pages']['other'])
        self.assertEqual(presentation['pages']['settings'], {key: self.actual[key] for key in self.before})
        policy = json.loads(plan.edits[repin.SETTINGS_TOOLTIP_POLICY])
        self.assertEqual(policy, {**self.policy, 'default_input_counts': self.measured['counts']})
        self.assertEqual({name: (self.root / name).read_bytes() for name in original}, original, 'planning never writes fixtures')

    def test_unrelated_input_changes_are_not_registered(self):
        self.measured['counts'][0] += 1
        plan = self.plan()
        self.assertTrue(plan.blockers)
        self.assertEqual(plan.edits, {})

    def test_unlabeled_checkbox_cannot_be_papered_over(self):
        self.actual['unlabeled_inputs'] = ['autostart_enabled']
        plan = self.plan()
        self.assertTrue(plan.blockers)
        self.assertEqual(plan.edits, {})

    def test_existing_height_budget_is_never_raised(self):
        self.actual['page_height'] = 1601
        plan = self.plan()
        self.assertTrue(plan.blockers)
        self.assertEqual(plan.edits, {})

    def test_existing_primary_button_budget_is_never_raised(self):
        self.actual['primary_button_count'] = 2
        plan = self.plan()
        self.assertTrue(plan.blockers)
        self.assertEqual(plan.edits, {})
