"""PR-C catalog equivalence pinned to main, including all locale/alias lookups."""

import ast
from collections import defaultdict
import json
from pathlib import Path
import unittest

from desktop_app.strings import catalog
from tools.refactor.split_ui_catalog_check import dump

ROOT = Path(__file__).resolve().parents[1]


class CatalogSplitTests(unittest.TestCase):
    def test_every_locale_key_value_alias_and_insertion_order_matches_main(self):
        expected = json.loads((ROOT / 'tests/fixtures/desktop_catalog_main_6b78239.json').read_text(encoding='utf-8'))
        self.assertEqual(expected.pop('source_commit'), '6b78239')
        self.assertEqual(dump(vars(catalog)), expected)

    def test_all_feature_records_are_literal_and_keep_unique_phase_keys(self):
        phases = defaultdict(set)
        orders = []
        aliases = []
        for path in (ROOT / 'desktop_app/strings').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not any(isinstance(t, ast.Name) and t.id == 'ENTRIES' for t in node.targets):
                    continue
                records = ast.literal_eval(node.value)
                for row in records:
                    if 'aliases' in path.parts:
                        order, key, value = row
                        aliases.append(order)
                        self.assertEqual(catalog.TEXT_ALIASES[key], value)
                    else:
                        phase, order, key, value = row
                        self.assertNotIn(key, phases[phase])
                        phases[phase].add(key)
                        orders.append(order)
                        self.assertEqual(catalog._ZH_TW_CHUNKS[phase][key], value)
        self.assertEqual(sorted(orders), list(range(2608)))
        self.assertEqual(sorted(aliases), list(range(1323)))
