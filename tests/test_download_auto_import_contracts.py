"""Pin historical UI contracts and admit only the reviewed automatic-import delta."""

import hashlib
import json
from collections import Counter
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent / 'fixtures'
NAMES = (
    'download_auto_import',
    'download_import_calendar',
    'download_import_calendar_path',
    'download_import_calendar_prerequisite',
    'download_import_contract',
    'download_import_status',
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class DownloadImportContractTests(unittest.TestCase):
    def test_widget_inventory_adds_exactly_six_names_and_preserves_every_historical_name(self):
        actual = json.loads((ROOT / 'desktop_widget_names.json').read_text(encoding='utf-8'))
        self.assertEqual(actual, sorted(set(actual)))
        self.assertLessEqual(set(NAMES), set(actual))
        historical = [name for name in actual if name not in NAMES]
        self.assertEqual(digest(historical), '366408108c0ac5de96107c5f3129f1b28753e6e1a02ca0c69e5f1098a3ae82e6')

    def test_historical_characterization_and_service_inventory_are_not_regenerated(self):
        # PR B: re-pin only reviewed path/module substitutions in the inventory
        # and R7 path keys; both normalized diffs are empty (f05328b precedent).
        expected = {
            'layered_paths/slice2_service_relocations.json': '00143849c2fd1ff59147d2f790fdbe09b8db4cc2bf8da5aed8a2c2245a8d9c22',
            'page_services_inventory.json': '39c5ca7d7e61cca59c62050fdef3b9c9eafd9dc9a04861849423616c3cca325c',
            'r7_base.json': '4507e432e092fc2f1921468ceee4e5f2730f81aa96cf067ad3c5ce00b8c895ba',
            'ui_redesign_characterization_delta.json': 'b5fa49227f1ec94b22661aa5769e0183d84e207227f4ac90d24ac3c1e1ac96f5',
        }
        for name, sha in expected.items():
            self.assertEqual(digest(json.loads((ROOT / name).read_text(encoding='utf-8'))), sha, name)

    def test_characterization_delta_changes_only_new_controls_and_the_download_caption(self):
        delta = json.loads((ROOT / 'download_auto_import_ui_delta.json').read_text(encoding='utf-8'))
        for kind, removed, added_names in (
            ('focus', ['refresh_data', '下載最近交易日資料', ''], set(NAMES) | {'refresh_data'}),
            (
                'refresh_states',
                ['refresh_data', '下載最近交易日資料', True, False],
                set(NAMES) - {'download_import_contract', 'download_import_calendar_path'} | {'refresh_data'},
            ),
        ):
            self.assertEqual(delta[kind]['removed'], [{'row': removed, 'count': 1}])
            self.assertEqual({item['row'][0] for item in delta[kind]['added']}, added_names)
            self.assertTrue(all(item['count'] == 1 for item in delta[kind]['added']))
            caption = next(item['row'] for item in delta[kind]['added'] if item['row'][0] == 'refresh_data')
            self.assertEqual(caption[1:], ['下載並自動匯入', *removed[2:]])
        inventory = delta['inventory']
        self.assertEqual(inventory['services'], {'removed': [], 'added': []})
        self.assertEqual(inventory['state_copies'], {'removed': [], 'added': []})
        self.assertEqual({item['row']['name'] for item in inventory['aliases']['removed']}, {'contract', 'run_backtest'})
        self.assertEqual({item['row']['name'] for item in inventory['aliases']['added']}, {'contract', 'run_backtest'})

    def test_inventory_observers_keep_every_existing_reference_and_add_only_five(self):
        delta = json.loads((ROOT / 'download_auto_import_ui_delta.json').read_text(encoding='utf-8'))['inventory']['patch_points']

        def without_lines(items):
            return Counter(
                json.dumps({key: value for key, value in item['row'].items() if key != 'line'}, sort_keys=True) for item in items for _ in range(item['count'])
            )

        old, new = without_lines(delta['removed']), without_lines(delta['added'])
        self.assertEqual(old - new, {})
        additions = [
            ('tests/test_download_auto_import.py', 'assignment', 'contract', 'self'),
            ('tests/test_download_auto_import.py', 'patch.object', 'write_json', 'workflow'),
            ('tests/test_download_auto_import_ui.py', 'patch.object', 'start_job', 'self.window'),
            ('tests/test_download_auto_import_ui.py', 'patch.object', 'start_job', 'self.window'),
            ('tests/test_report_promotion.py', 'patch.object', 'run_backtest', 'backtest'),
        ]
        expected = Counter(json.dumps(dict(zip(('file', 'kind', 'name', 'receiver'), values)), sort_keys=True) for values in additions)
        self.assertEqual(new - old, expected)
