"""R7: source movement preserves pins; observer identity and multiplicity do not drift."""

import ast
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from tests import page_services_inventory as inventory
from tools import repin_baselines as repin


SOURCE = '''
host.contract = marker

class Base:
    @patch.object(host, 'history')
    def observed(self):
        self.contract = marker
        with patch.object(self.window, 'run_backtest'):
            pass
        with patch.object(self.window, 'run_backtest'):
            pass
        def nested():
            self.contract = marker

    async def other(self):
        setattr(host, 'history', marker)
'''


class ObserverSymbolPinTests(unittest.TestCase):
    def points(self, source):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_fixture.py').write_text(textwrap.dedent(source), encoding='utf-8')
            with patch.object(inventory, 'ROOT', root):
                return inventory.symbolic_patch_points(inventory.patch_points({'contract', 'history', 'run_backtest'}, set()))

    def test_qualified_owners_and_repeated_references_keep_exact_evidence(self):
        points = self.points(SOURCE)
        self.assertEqual({point['symbol'] for point in points}, {'<module>', 'Base.observed', 'Base.observed.nested', 'Base.other'})
        self.assertTrue(all('line' not in point for point in points))
        repeated = [point for point in points if point['name'] == 'run_backtest']
        self.assertEqual(
            repeated,
            [
                {
                    'file': 'tests/test_fixture.py',
                    'symbol': 'Base.observed',
                    'occurrence': occurrence,
                    'kind': 'patch.object',
                    'name': 'run_backtest',
                    'receiver': 'self.window',
                }
                for occurrence in (3, 4)
            ],
        )
        decorated = next(point for point in points if point['kind'] == 'patch.object' and point['name'] == 'history')
        self.assertEqual(decorated['symbol'], 'Base.observed')

    def test_comments_blank_lines_and_unrelated_functions_do_not_change_locations(self):
        original = self.points(SOURCE)
        for source in (
            '\n# inserted comment\n' * 12 + SOURCE,
            SOURCE.replace('    def observed', '    # comment before method\n\n    def observed'),
            'def unrelated():\n    pass\n' + SOURCE,
        ):
            with self.subTest(source=source):
                self.assertEqual(self.points(source), original)

    def test_owner_receiver_kind_name_and_missing_duplicate_still_change_the_pin(self):
        original = self.points(SOURCE)
        for source in (
            SOURCE.replace('class Base:', 'class Other:'),
            SOURCE.replace('def observed(', 'def renamed('),
            SOURCE.replace('def nested(', 'def renamed_nested('),
            SOURCE.replace('self.window', 'self.other'),
            SOURCE.replace("        with patch.object(self.window, 'run_backtest'):\n            pass\n", '', 1),
            SOURCE.replace("with patch.object(self.window, 'run_backtest'):", "with patch.object(self.window, 'history'):", 1),
            SOURCE.replace("with patch.object(self.window, 'run_backtest'):\n            pass", "setattr(self.window, 'run_backtest', marker)", 1),
        ):
            with self.subTest(source=source):
                self.assertNotEqual(self.points(source), original)

    def test_order_of_distinct_observers_within_owner_is_retained(self):
        original = "        self.contract = marker\n        with patch.object(self.window, 'run_backtest'):\n            pass\n"
        reordered = "        with patch.object(self.window, 'run_backtest'):\n            pass\n        self.contract = marker\n"
        self.assertNotEqual(self.points(SOURCE.replace(original, reordered, 1)), self.points(SOURCE))

    def test_full_inventory_and_repin_ignore_uniform_source_line_movement(self):
        original, legacy = inventory.symbolic_inventory(), inventory.inventory()
        original_tree = inventory.tree

        def moved(path):
            parsed = ast.increment_lineno(original_tree(path), 31)
            parsed.body.insert(0, ast.parse('def unrelated_r7_symbol():\n    pass\n').body[0])
            return parsed

        with patch.object(inventory, 'tree', side_effect=moved):
            current = inventory.symbolic_inventory()
            self.assertEqual(current, original)
            self.assertNotEqual(inventory.inventory(), legacy)
        points, aliases, blockers = repin.observer_delta(original, current, {'removed': [], 'added': []})
        self.assertEqual(points, {'removed': [], 'added': []})
        self.assertEqual(aliases, [])
        self.assertEqual(blockers, [])

    def test_frozen_to_symbolic_projection_preserves_every_non_location_field(self):
        base = json.loads(inventory.FIXTURE.read_text(encoding='utf-8'))
        delta = json.loads((inventory.ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))['inventory']
        delta.update(json.loads((inventory.ROOT / 'tests/fixtures/page_service_observer_delta.json').read_text(encoding='utf-8'))['inventory'])
        # This proves the frozen one-to-one migration, before later observer changes.
        delta = copy.deepcopy(delta)
        delta['symbol_patch_points'] = {'removed': [], 'added': []}
        delta['symbol_aliases'] = []
        # The historical projection mutates its delta rows; compare independent inputs.
        legacy = inventory.reviewed_inventory(base, copy.deepcopy(delta))
        symbolic = inventory.reviewed_symbolic_inventory(base, delta)
        for field in ('services', 'aliases', 'state_copies'):
            self.assertEqual(symbolic[field], legacy[field])
        old = Counter(json.dumps({key: value for key, value in point.items() if key != 'line'}, sort_keys=True) for point in legacy['patch_points'])
        new = Counter(
            json.dumps({key: value for key, value in point.items() if key not in ('symbol', 'occurrence')}, sort_keys=True)
            for point in symbolic['patch_points']
        )
        self.assertEqual(new, old)

    def test_historical_projection_rejects_changed_receiver_name_and_count(self):
        base = json.loads(inventory.FIXTURE.read_text(encoding='utf-8'))
        delta = json.loads((inventory.ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))['inventory']
        delta.update(json.loads((inventory.ROOT / 'tests/fixtures/page_service_observer_delta.json').read_text(encoding='utf-8'))['inventory'])
        delta['symbol_patch_points'] = {'removed': [], 'added': []}
        delta['symbol_aliases'] = []
        path = inventory.ROOT / 'tests/fixtures/page_service_observer_symbols.json'
        frozen = json.loads(path.read_text(encoding='utf-8'))
        original_read = Path.read_text
        for field in ('receiver', 'name', 'count'):
            changed = copy.deepcopy(frozen)
            if field == 'count':
                changed['locations'].append(copy.deepcopy(changed['locations'][0]))
            else:
                changed['locations'][0]['original'][field] += '_changed'

            def read(selected, *args, **kwargs):
                return json.dumps(changed) if selected == path else original_read(selected, *args, **kwargs)

            with self.subTest(field=field), patch.object(Path, 'read_text', new=read):
                with self.assertRaises(AssertionError):
                    inventory.reviewed_symbolic_inventory(base, copy.deepcopy(delta))

    def test_current_full_inventory_still_rejects_a_dropped_new_observer(self):
        from tests import test_page_services_r1

        path = inventory.ROOT / 'tests/fixtures/page_service_observer_delta.json'
        changed = json.loads(path.read_text(encoding='utf-8'))
        added = changed['inventory']['symbol_patch_points']['added']
        self.assertTrue(added, 'this counterexample requires a reviewed current observer addition')
        self.assertGreater(added[0]['count'], 0)
        if added[0]['count'] == 1:
            del added[0]
        else:
            added[0]['count'] -= 1
        original_read = Path.read_text

        def read(selected, *args, **kwargs):
            return json.dumps(changed) if selected == path else original_read(selected, *args, **kwargs)

        case = test_page_services_r1.InventoryTests('test_complete_inventory_regenerates_exactly')
        with patch.object(Path, 'read_text', new=read), self.assertRaises(AssertionError):
            case.test_complete_inventory_regenerates_exactly()
