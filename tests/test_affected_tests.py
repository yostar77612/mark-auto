"""R8 affected-test selection: import graph, string references and static rules."""

from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from tools import affected_tests as affected

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTING = """
The G3 locked file set covers the following 2 source files. They must not be edited
without owner approval:

- `quantlab/locked.py`
- `quantlab/other_locked.py`

The owner approved relocation.
"""


def write(root, relative, text=''):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip('\n'), encoding='utf-8', newline='\n')


def git(root, *args):
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-C', str(root), *args], check=True, capture_output=True)


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.folder.name)
        git(root, 'init', '-q')
        write(root, 'docs/CONTRIBUTING.md', CONTRIBUTING)
        write(root, 'pkg/__init__.py')
        write(root, 'pkg/a.py', 'VALUE = 1\n')
        write(root, 'pkg/b.py', 'from pkg import a\n')
        write(root, 'pkg/lazy.py', 'def f():\n    import pkg.b\n')
        write(root, 'pkg/solo.py', 'X = 1\n')
        write(root, 'pkg/named.py', 'X = 1\n')
        write(root, 'pkg/keys.py', "KEY = 'pkg.solo'\n")
        write(root, 'desktop_app/strings/data.py', 'ENTRIES = ()\n')
        write(root, 'desktop_app/strings/catalog.py', 'from . import data\n')
        write(root, 'desktop_app/ui.py', 'from desktop_app.strings import catalog\n')
        write(root, 'tests/test_ui_user.py', 'import desktop_app.ui\n')
        write(root, 'tests/test_catalog_direct.py', 'from desktop_app.strings import data\n')
        write(root, 'tests/test_uses_keys.py', 'import pkg.keys\n')
        write(root, 'quantlab/locked.py', 'X = 1\n')
        write(root, 'data/pinned.json', '{}\n')
        write(root, 'tests/__init__.py')
        write(root, 'tests/helper.py', 'import pkg.lazy\n')
        write(root, 'tests/test_direct.py', 'import pkg.a\n')
        write(root, 'tests/test_transitive.py', 'import pkg.lazy\n')
        write(root, 'tests/test_helper_user.py', 'from tests import helper\n')
        write(root, 'tests/test_relative.py', 'from .helper import *\n')
        write(root, 'tests/test_patch_string.py', "from unittest.mock import patch\npatch('pkg.solo.X', 2)\n")
        write(root, 'tests/test_reads_source.py', "SOURCE = 'pkg/named.py'\n")
        write(root, 'tests/test_reads_fixture.py', "FIXTURE = 'data/pinned.json'\n")
        write(root, 'tests/test_unrelated.py', 'import json\n')
        for name in (*affected.STRING_PINS, *affected.INVENTORY_PINS, *affected.STYLE_PINS, *affected.SERVICE_PINS, *affected.DOC_PINS):
            write(root, f'tests/{name}.py', 'import json\n')

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_imports_are_followed_transitively_including_function_level_and_relative(self):
        selected = affected.select({'pkg/a.py': 'M'}, self.root)[1]
        self.assertTrue({'test_direct', 'test_transitive', 'test_helper_user', 'test_relative'} <= selected.keys())
        self.assertNotIn('test_unrelated', selected)
        self.assertEqual(selected['test_direct'], 'depends on pkg/a.py')

    def test_changed_test_selects_itself_and_helper_changes_select_their_users(self):
        self.assertEqual(affected.select({'tests/test_unrelated.py': 'M'}, self.root)[1]['test_unrelated'], 'itself changed')
        selected = affected.select({'tests/helper.py': 'M'}, self.root)[1]
        self.assertTrue({'test_helper_user', 'test_relative'} <= selected.keys())
        self.assertNotIn('test_direct', selected)

    def test_patch_strings_and_file_paths_count_as_dependencies(self):
        self.assertIn('test_patch_string', affected.select({'pkg/solo.py': 'M'}, self.root)[1])
        self.assertIn('test_reads_source', affected.select({'pkg/named.py': 'M'}, self.root)[1])
        selected = affected.select({'data/pinned.json': 'M'}, self.root)[1]
        self.assertEqual(selected['test_reads_fixture'], 'references data/pinned.json')

    def test_string_keys_in_production_code_are_not_module_references(self):
        self.assertNotIn('test_uses_keys', affected.select({'pkg/solo.py': 'M'}, self.root)[1])

    def test_string_catalog_is_data_and_does_not_fan_out_to_every_ui_test(self):
        selected = affected.select({'desktop_app/strings/data.py': 'M'}, self.root)[1]
        self.assertIn('test_catalog_direct', selected)
        self.assertNotIn('test_ui_user', selected)
        self.assertTrue(set(affected.STRING_PINS) <= selected.keys())
        self.assertIn('test_ui_user', affected.select({'desktop_app/ui.py': 'M'}, self.root)[1])

    def test_deleted_module_selects_the_tests_that_name_it(self):
        selected = affected.select({'pkg/solo.py': 'D'}, self.root)[1]
        self.assertIn('test_patch_string', selected)

    def test_strings_inventory_style_and_service_changes_add_their_pinning_modules(self):
        cases = (
            ({'desktop_app/strings/new.py': 'M'}, affected.STRING_PINS),
            ({'pkg/brand_new.py': 'A'}, affected.INVENTORY_PINS),
            ({'docs/analysis/08_REFACTOR_INVENTORY.md': 'M'}, affected.INVENTORY_PINS),
            ({'desktop_app/shell/theme.py': 'M'}, affected.STYLE_PINS),
            ({'desktop_app/shell/window.py': 'M'}, affected.SERVICE_PINS),
            ({'tests/test_unrelated.py': 'M'}, affected.SERVICE_PINS),
            ({'docs/guide.md': 'M'}, affected.DOC_PINS),
        )
        for changes, pins in cases:
            with self.subTest(changes=changes):
                self.assertTrue(set(pins) <= affected.select(changes, self.root)[1].keys())

    def test_modification_of_an_existing_source_does_not_trigger_inventory_pins(self):
        self.assertFalse(set(affected.INVENTORY_PINS) & affected.select({'pkg/solo.py': 'M'}, self.root)[1].keys())

    def test_full_suite_triggers(self):
        for path in (
            'packaging/build.ps1',
            '.github/workflows/quantlab.yml',
            'requirements-desktop.lock',
            'markauto.spec',
            'installer.iss',
            'quantlab/locked.py',
            'quantlab/other_locked.py',
            'quantlab/saved_candidate_pool.py',
            'tools/layer_map.json',
            'tools/run_test_group.py',
            'pyproject.toml',
        ):
            with self.subTest(path=path):
                full, modules = affected.select({path: 'M'}, self.root)
                self.assertTrue(full)
                self.assertEqual(modules, {})

    def test_nothing_affected_prints_a_no_op_comment_and_full_prints_the_discover_command(self):
        self.assertEqual(affected.select({'pkg/solo_unused.py': 'M'}, self.root)[1], {})
        self.assertEqual(affected.FULL_COMMAND, 'python -m unittest discover -s tests')
        self.assertEqual(affected.command(['a', 'b'], False), 'python -m unittest tests.a tests.b')
        self.assertEqual(affected.command(['a', 'b'], True), 'python -m unittest discover -s tests -p a.py && python -m unittest discover -s tests -p b.py')


class ChangedFilesTests(unittest.TestCase):
    def test_diff_against_merge_base_reports_modified_deleted_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            git(root, 'init', '-q')
            write(root, 'keep.py', 'a = 1\n')
            write(root, 'gone.py', 'a = 1\n')
            git(root, 'add', '.')
            git(root, 'commit', '-qm', 'base')
            git(root, 'branch', 'base-ref')
            write(root, 'keep.py', 'a = 2\n')
            (root / 'gone.py').unlink()
            write(root, 'fresh.py', 'a = 1\n')
            self.assertEqual(affected.changed_files(root, 'base-ref'), {'keep.py': 'M', 'gone.py': 'D', 'fresh.py': 'A'})


class RepositoryTests(unittest.TestCase):
    def test_static_rule_modules_exist(self):
        for name in (*affected.STRING_PINS, *affected.INVENTORY_PINS, *affected.STYLE_PINS, *affected.SERVICE_PINS, *affected.DOC_PINS):
            with self.subTest(module=name):
                self.assertTrue((ROOT / 'tests' / f'{name}.py').is_file())

    def test_g3_locked_list_is_read_from_contributing(self):
        locked = affected.g3_locked(ROOT)
        self.assertEqual(len(locked), 31)
        self.assertIn('quantlab/research.py', locked)
        self.assertIn('quantlab/research_core/domain/__init__.py', locked)

    def test_this_change_selects_its_own_tests(self):
        full, modules = affected.select({'tools/affected_tests.py': 'M', 'tools/repin_baselines.py': 'M'}, ROOT)
        self.assertEqual(full, [])
        self.assertLessEqual({'test_affected_tests', 'test_repin_baselines'}, modules.keys())


if __name__ == '__main__':
    unittest.main()
