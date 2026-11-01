"""R6 repin tool: only regenerates expected values and refuses non-baseline failures."""

from collections import Counter
import contextlib
import io
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from tools import repin_baselines as repin

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
NO_PREVIOUS = {'removed': [], 'added': []}


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip('\n'), encoding='utf-8', newline='\n')


def git_init(root):
    subprocess.run(['git', 'init', '-q', str(root)], check=True)


class QuietMain:
    def run_main(self, root, *arguments):
        with contextlib.redirect_stdout(io.StringIO()):
            return repin.main(['--root', str(root), *arguments])


class PureHelperTests(unittest.TestCase):
    def test_contiguity_reports_duplicates_and_gaps_but_accepts_a_range(self):
        self.assertEqual(repin.contiguity_problems('catalog', [2, 0, 1]), [])
        message = repin.contiguity_problems('catalog', [0, 1, 1, 3])[0]
        self.assertIn('duplicates [1]', message)
        self.assertIn('missing [2]', message)

    def test_replace_literal_changes_only_the_captured_literal(self):
        source = "a(sorted(orders), list(range(5)))\nb(sorted(aliases), list(range(9)))\n"
        updated = repin.replace_literal(source, r'sorted\(orders\), list\(range\((\d+)\)', '7', 'x')
        self.assertEqual(updated, "a(sorted(orders), list(range(7)))\nb(sorted(aliases), list(range(9)))\n")
        for pattern in (r'nothing\((\d+)\)', r'range\((\d+)\)'):
            with self.assertRaises(repin.Blocked):
                repin.replace_literal(source, pattern, '1', 'x')

    def test_catalog_changes_separate_additions_from_reviewed_changes(self):
        old = {'lookups': {'zh-TW': {'a': '1', 'b': '2'}}, 'aliases': {'x': 'a'}, 'key_order': ['a', 'b'], 'alias_order': ['x']}
        added = {**old, 'lookups': {'zh-TW': {'a': '1', 'b': '2', 'c': '3'}}, 'key_order': ['a', 'b', 'c']}
        self.assertEqual(repin.catalog_changes(old, added)[2], [])
        changed = {**added, 'lookups': {'zh-TW': {'a': 'new', 'b': '2', 'c': '3'}}}
        self.assertEqual(repin.catalog_changes(old, changed)[2], ['zh-TW changed a'])
        removed = {**old, 'lookups': {'zh-TW': {'a': '1'}}, 'key_order': ['a']}
        self.assertEqual(repin.catalog_changes(old, removed)[2], ['zh-TW removed b'])
        reordered = {**old, 'key_order': ['b', 'a']}
        self.assertEqual(repin.catalog_changes(old, reordered)[2], ['key_order of existing keys was reordered'])

    def test_observer_delta_pins_exact_moves_and_refuses_real_service_changes(self):
        def point(line, name='x'):
            return {'file': 'tests/t.py', 'kind': 'patch', 'line': line, 'name': name, 'receiver': 'r'}

        alias = {'name': 'bars', 'page': 'data_page', 'attribute': 'bars', 'patch_sensitive': False}
        pre = {'services': [], 'state_copies': [], 'aliases': [alias], 'patch_points': [point(1), point(2, 'y'), point(2, 'y')]}
        cur = {**pre, 'aliases': [{**alias, 'patch_sensitive': True}], 'patch_points': [point(4), point(2, 'y'), point(2, 'y')]}
        patch_points, aliases, blockers = repin.observer_delta(pre, cur, NO_PREVIOUS)
        self.assertEqual(blockers, [])
        self.assertEqual(patch_points, {'removed': [{'row': point(1), 'count': 1}], 'added': [{'row': point(4), 'count': 1}]})
        self.assertEqual(aliases, [{'original': alias, 'current': {**alias, 'patch_sensitive': True}}])
        self.assertEqual(repin.observer_delta(pre, pre, NO_PREVIOUS)[0], {'removed': [], 'added': []})
        self.assertTrue(repin.observer_delta(pre, {**cur, 'services': [{'name': 'new'}]}, NO_PREVIOUS)[2])
        later = repin.observer_delta(pre, {**cur, 'patch_points': [point(9), point(4), point(2, 'y'), point(2, 'y')]}, patch_points)[0]
        self.assertEqual([item['row']['line'] for item in later['added']], [4, 9], 'existing rows keep their place, new rows are sorted after them')
        renamed = {**cur, 'aliases': [{**alias, 'attribute': 'other', 'patch_sensitive': True}]}
        self.assertTrue(repin.observer_delta(pre, renamed, NO_PREVIOUS)[2])

    def test_committed_files_round_trip_through_the_writers_byte_for_byte(self):
        for name in ('desktop_catalog_main_6b78239.json', 'download_auto_import_ui_delta.json'):
            raw = (FIXTURES / name).read_bytes().decode('utf-8')
            self.assertEqual(repin.render_json(json.loads(raw)), raw, name)
        delta = json.loads((FIXTURES / 'download_auto_import_ui_delta.json').read_text(encoding='utf-8'))['inventory']['m1_patch_points']
        for side in ('removed', 'added'):
            rows = Counter()
            for item in delta[side]:
                rows[repin.row_key(item['row'])] += item['count']
            self.assertEqual(repin.counted(rows, delta[side]), delta[side], 'committed order and shape must be preserved')

    def test_inserted_inventory_rows_follow_the_last_section_2_row(self):
        text = '## 2 x\n\n| `a.py` | 1 | tooling | `a.py` | n |\n\n## 3 y\n'
        self.assertEqual(repin.insert_rows(text, ['| `b.py` |']), '## 2 x\n\n| `a.py` | 1 | tooling | `a.py` | n |\n| `b.py` |\n\n## 3 y\n')


class InventoryPlanTests(QuietMain, unittest.TestCase):
    def make_root(self, folder):
        root = Path(folder)
        git_init(root)
        write(root, 'tools/layer_map.json', '{"prefixes": {"tools/": "tooling", "quantlab/": "domain"}, "overrides": {}, "ports": []}')
        write(root, 'tools/layer_relocations.json', '{}')
        write(root, 'tests/test_layer_gate.py', "def f():\n    metadata = {'quantlab/pkg/__init__.py': 'domain'}\n")
        write(root, 'docs/analysis/08_REFACTOR_INVENTORY.md', '## 2 rows\n\n| `tools/old.py` | 1 | tooling | `tools/old.py` | n |\n\n## 3 next\n')
        write(root, 'tools/old.py', 'x = 1\n')
        return root

    def test_new_sources_get_rows_with_layer_and_line_count_and_nothing_else_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            write(root, 'tools/new.py', 'a = 1\nb = 2\n')
            write(root, 'quantlab/pkg/__init__.py', '')
            plan = repin.inventory_plan(root)
            self.assertEqual(plan.blockers, [])
            rows = repin.inventory_rows(plan.edits[repin.INVENTORY_DOC])
            self.assertEqual(rows, {'tools/old.py': 'tooling', 'tools/new.py': 'tooling'})
            self.assertIn(f'| `tools/new.py` | 2 | tooling | `tools/new.py` | {repin.DEFAULT_NOTE} |', plan.edits[repin.INVENTORY_DOC])
            self.run_main(root, '--write', '--no-verify', '--only', 'inventory')
            self.assertEqual(repin.inventory_plan(root).edits, {})

    def test_unassigned_layer_and_wrong_layer_are_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            write(root, 'stray.py', 'x = 1\n')
            write(root, 'quantlab/wrong.py', 'x = 1\n')
            doc = root / repin.INVENTORY_DOC
            doc.write_text(doc.read_text().replace('\n\n## 3', '\n| `quantlab/wrong.py` | 1 | tooling | `quantlab/wrong.py` | n |\n\n## 3'))
            before = doc.read_bytes()
            plan = repin.inventory_plan(root)
            self.assertEqual(len(plan.blockers), 2)
            self.assertEqual(self.run_main(root, '--write', '--no-verify', '--only', 'inventory'), 2)
            self.assertEqual(doc.read_bytes(), before)

    def test_new_package_initializers_are_left_to_hand_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            write(root, 'tools/sub/__init__.py', '')
            self.assertIn('registered by hand', repin.inventory_plan(root).blockers[0])


class CatalogPlanTests(QuietMain, unittest.TestCase):
    ENTRY_FILE = "ENTRIES = (\n    (0, 0, 'a.one', 'one'),\n    (0, 1, 'a.two', 'two'),\n)\n"

    def make_root(self, folder):
        root = Path(folder)
        write(root, 'desktop_app/strings/__init__.py', '')
        write(root, 'desktop_app/strings/m.py', self.ENTRY_FILE)
        write(
            root,
            'desktop_app/strings/catalog.py',
            """
            from .m import ENTRIES

            ZH_TW = {key: value for _, _, key, value in ENTRIES}
            TEXT_ALIASES = {}
            LOCALES = {'zh-TW': ZH_TW}


            def ui_text(key, locale=None):
                return LOCALES.get(locale or 'zh-TW', ZH_TW)[key]
            """,
        )
        (root / 'tools/refactor').mkdir(parents=True)
        (root / 'tools/refactor/split_ui_catalog_check.py').write_bytes((ROOT / 'tools/refactor/split_ui_catalog_check.py').read_bytes())
        write(root, repin.CATALOG_TEST, "self.assertEqual(sorted(orders), list(range(2)))\nself.assertEqual(sorted(aliases), list(range(0)))\n")
        baseline = json.loads(repin.run_python(root, repin.CATALOG_CODE))
        write(root, repin.CATALOG_FIXTURE, repin.render_json({'source_commit': 'abc', **baseline}))
        return root

    def test_current_tree_is_up_to_date_and_additions_update_fixture_and_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            self.assertEqual(repin.catalog_plan(root).edits, {})
            write(root, 'desktop_app/strings/m.py', self.ENTRY_FILE.replace(')\n', "    (0, 2, 'a.three', 'three'),\n)\n"))
            plan = repin.catalog_plan(root)
            self.assertEqual(plan.blockers, [])
            fixture = json.loads(plan.edits[repin.CATALOG_FIXTURE])
            self.assertEqual(fixture['source_commit'], 'abc')
            self.assertEqual(fixture['key_order'], ['a.one', 'a.two', 'a.three'])
            self.assertIn('list(range(3))', plan.edits[repin.CATALOG_TEST])
            self.assertIn('list(range(0))', plan.edits[repin.CATALOG_TEST])

    def test_changed_text_needs_explicit_acceptance_and_gaps_are_never_papered_over(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            write(root, 'desktop_app/strings/m.py', self.ENTRY_FILE.replace("'two'", "'TWO'"))
            self.assertIn('--accept-changed', repin.catalog_plan(root).blockers[0])
            self.assertEqual(repin.catalog_plan(root, accept_changed=True).blockers, [])
            write(root, 'desktop_app/strings/m.py', self.ENTRY_FILE.replace('(0, 1,', '(0, 5,'))
            plan = repin.catalog_plan(root, accept_changed=True)
            self.assertIn('not contiguous', plan.blockers[0])
            before = (root / repin.CATALOG_TEST).read_bytes()
            self.assertEqual(self.run_main(root, '--write', '--no-verify', '--only', 'catalog', '--accept-changed'), 2)
            self.assertEqual((root / repin.CATALOG_TEST).read_bytes(), before)

    def test_restructured_test_is_refused_instead_of_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            write(root, repin.CATALOG_TEST, 'pass\n')
            with self.assertRaises(repin.Blocked):
                repin.catalog_plan(root)


class StylesheetPlanTests(unittest.TestCase):
    def test_only_the_hash_literals_change_and_a_non_dark_default_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root, 'desktop_app/shell/__init__.py', '')
            write(root, 'desktop_app/__init__.py', '')
            theme = """
                def build_app_stylesheet(name='dark'):
                    return 'app-' + name


                def build_market_stylesheet(name='dark'):
                    return 'market-' + name
            """
            write(root, 'desktop_app/shell/theme.py', theme)
            old = '0' * 64
            pin = f"(theme.build_app_stylesheet, '{old}'),\n(theme.build_market_stylesheet, '{hashlib.sha256(b'market-dark').hexdigest()}'),\n"
            write(root, repin.APPEARANCE_TEST, pin)
            plan = repin.stylesheet_plan(root)
            self.assertEqual(plan.blockers, [])
            self.assertEqual(plan.edits[repin.APPEARANCE_TEST], pin.replace(old, hashlib.sha256(b'app-dark').hexdigest()))
            write(root, 'desktop_app/shell/theme.py', theme.replace("name='dark'", "name='light'", 1))
            self.assertIn('no longer the dark theme', repin.stylesheet_plan(root).blockers[0])


class WriteAndVerifyTests(unittest.TestCase):
    def test_failed_verification_restores_every_file_and_passing_keeps_the_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root, 'tests/test_ok.py', "import unittest\n\n\nclass T(unittest.TestCase):\n    def test(self):\n        pass\n")
            write(root, 'tests/test_bad.py', "import unittest\n\n\nclass T(unittest.TestCase):\n    def test(self):\n        self.fail('still red')\n")
            write(root, 'pin.txt', 'old\n')
            kept = repin.Plan('kept', edits={'pin.txt': 'new\n'}, verify=('test_ok',))
            repin.apply(root, kept, True)
            self.assertEqual((root / 'pin.txt').read_text(), 'new\n')
            self.assertEqual(kept.failed, '')
            write(root, 'pin.txt', 'old\n')
            rolled = repin.Plan('rolled', edits={'pin.txt': 'new\n'}, verify=('test_ok', 'test_bad'))
            repin.apply(root, rolled, True)
            self.assertEqual((root / 'pin.txt').read_text(), 'old\n')
            self.assertIn('test_bad', rolled.failed)
            self.assertEqual(repin.status(rolled), 'FAILED-VERIFY (rolled back)')


if __name__ == '__main__':
    unittest.main()
