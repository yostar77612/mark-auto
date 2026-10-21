"""R3: pre-migration bytes, one-hop aliases and AST catalog coverage."""

import ast
from collections import defaultdict
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import desktop_strings as strings

ROOT = Path(__file__).resolve().parents[1]
GENERIC = re.compile(r'(?:^|\.)text_\d+$')
SEMANTIC = re.compile(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,}$')
FROZEN = {
    'quantlab/research.py',
    'quantlab/provider.py',
    'quantlab/core.py',
    'quantlab/strategies.py',
    'quantlab/backtest.py',
    'quantlab/data.py',
    'desktop_chatgpt_auth.py',
    'desktop_chatgpt_provider.py',
    'quantlab/saved_candidate_pool.py',
}

# Finite dynamic families, tied to their existing consumers. Expanding one
# requires reviewing its suffix list, rather than exempting an entire scope.
DYNAMIC_PREFIXES = {
    'job.stage.': (
        'desktop_pages/job_progress.py',
        ('unknown', 'prepare_operation', 'load_data', 'build_candidates', 'run_backtest', 'run_campaign', 'run_operation', 'write_result'),
    ),
    'compare.': ('desktop_pages/compare_table.py', ('name', 'family', 'parameters', 'range', 'created')),
    'results.': (
        'desktop_pages/result_widgets.py',
        ('evaluations_reserved', 'evaluation_limit', 'folds', 'evaluated_oos_folds', 'orders', 'fills', 'positions', 'stop'),
    ),
    'settings.': ('desktop_pages/settings_layout.py', ('general', 'connection', 'backup', 'about')),
    'strategy.tabs.': ('desktop_pages/strategy_tabs.py', ('settings', 'research', 'walk_forward')),
    'wf.': ('desktop_pages/wf_wizard.py', ('quick', 'standard', 'strict', 'custom', 'train', 'validation', 'oos', 'holdout')),
    'wf.step.': ('desktop_pages/wf_wizard.py', ('0', '1', '2', '3', '4')),
}


def source_paths():
    """Application/tool sources plus tests; exclude archived fixture code."""
    yield from ROOT.glob('*.py')
    for package in ('desktop_pages', 'desktop_smoke', 'quantlab', 'tools', 'tests'):
        for path in (ROOT / package).rglob('*.py'):
            if 'fixtures' not in path.relative_to(ROOT).parts:
                yield path


class DesktopTextAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / 'tests/fixtures/desktop_text_alias_map.json').read_text(encoding='utf-8'))
        cls.old = cls.fixture['strings']
        cls.trees = {}
        for path in source_paths():
            name = path.relative_to(ROOT).as_posix()
            source = path.read_text(encoding='utf-8-sig')
            # Tests contribute only to the forbidden-literal check. Avoid
            # parsing hundreds of unrelated test modules on every CI run.
            if name.startswith('tests/') and not re.search(r'\.text_\d+', source):
                continue
            cls.trees[name] = ast.parse(source, filename=name, feature_version=(3, 11))

    def test_snapshot_provenance_and_complete_alias_set(self):
        self.assertEqual(self.fixture['source_commit'], 'd96fd4cbce3f127e50a9d7ada0a27729630a8769')
        self.assertEqual(self.fixture['source_path'], 'desktop_strings.py')
        self.assertEqual(self.fixture['source_sha256'], '03eedc0c9a53d68aa6791e84d6c94fb2e30dd1c34b87d01435d7a5ae073b477f')
        self.assertEqual(len(self.old), 1323)
        self.assertEqual(set(strings.TEXT_ALIASES), set(self.old))
        self.assertTrue(all(GENERIC.search(key) for key in self.old))

    def test_every_historical_string_and_utf8_byte_sequence(self):
        for old, expected in self.old.items():
            new = strings.TEXT_ALIASES[old]
            with self.subTest(old=old, new=new):
                for locale in (None, strings.DEFAULT_LOCALE, 'unknown-locale'):
                    actual = strings.ui_text(old, locale)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual.encode('utf-8'), expected.encode('utf-8'))
                    self.assertEqual(actual, strings.ui_text(new, locale))

    def test_semantic_targets_are_unique_or_documented_identical_merges(self):
        grouped = defaultdict(list)
        previous = self.fixture['preserved']['catalog']
        for old, new in strings.TEXT_ALIASES.items():
            self.assertIsNotNone(SEMANTIC.fullmatch(new), new)
            self.assertIsNone(GENERIC.search(new))
            self.assertIn(new, strings.ZH_TW)
            self.assertNotIn(new, strings.TEXT_ALIASES)
            self.assertNotIn(new, previous)
            grouped[new].append(old)
        merges = json.loads((ROOT / 'tests/fixtures/desktop_text_alias_merges.json').read_text(encoding='utf-8'))
        self.assertEqual({key: values for key, values in grouped.items() if len(values) > 1}, merges)
        for old_keys in merges.values():
            self.assertEqual(len({self.old[key] for key in old_keys}), 1)

    def test_existing_catalog_patches_and_registries_are_preserved(self):
        previous = self.fixture['preserved']
        self.assertEqual({key: strings.ZH_TW[key] for key in previous['catalog']}, previous['catalog'])
        for name, value in previous['registries'].items():
            self.assertEqual(json.loads(json.dumps(getattr(strings, name))), value, name)
        self.assertEqual(set(strings.ZH_TW), set(previous['catalog']) | set(strings.TEXT_ALIASES.values()))
        self.assertFalse(set(strings.ZH_TW) & set(self.old))
        self.assertIs(strings.LOCALES[strings.DEFAULT_LOCALE], strings.ZH_TW)

    def test_alias_lookup_is_single_hop_and_reads_locale_at_call_time(self):
        old = next(iter(self.old))
        new = strings.TEXT_ALIASES[old]

        class CountingAliases(dict):
            reads = 0

            def get(self, key, default=None):
                self.reads += 1
                return super().get(key, default)

        aliases = CountingAliases(strings.TEXT_ALIASES)
        with patch.object(strings, 'TEXT_ALIASES', aliases), patch.dict(strings.LOCALES, {'partial': {new: 'Translated {0}'}}):
            self.assertEqual(strings.ui_text(old, 'partial'), 'Translated {0}')
            self.assertEqual(aliases.reads, 1)
            with patch.dict(strings.LOCALES['partial'], {new: 'Changed at call time'}):
                self.assertEqual(strings.ui_text(old, 'partial'), 'Changed at call time')
            strings.LOCALES['partial'].clear()
            self.assertEqual(strings.ui_text(old, 'partial'), self.old[old])
        for locale in (None, 'unknown-locale'):
            with self.assertRaises(KeyError):
                strings.ui_text('missing.semantic.key', locale)

    def test_no_generic_literals_outside_alias_table(self):
        for name, tree in self.trees.items():
            if name in FROZEN or name == 'tests/test_desktop_text_aliases.py':
                continue
            allowed_nodes = set()
            if name == 'desktop_strings.py':
                alias = next(
                    node
                    for node in tree.body
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'TEXT_ALIASES' for target in node.targets)
                )
                allowed_nodes = {id(node) for node in ast.walk(alias)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in allowed_nodes:
                    self.assertIsNone(GENERIC.search(node.value), f'{name}:{node.lineno}: {node.value}')

    def test_no_missing_literal_lookups_or_unused_catalog_keys(self):
        referenced = set(strings.TEXT_ALIASES.values()) | set(strings.RETAINED_CATALOG_KEYS)
        referenced.update(strings.LOG_OPERATION_NAMES.values())
        referenced.update(strings.LOG_EVENT_NAMES.values())
        valid = set(strings.ZH_TW) | set(strings.TEXT_ALIASES)
        for prefix, (consumer, suffixes) in DYNAMIC_PREFIXES.items():
            self.assertTrue(any(isinstance(node, ast.Constant) and node.value == prefix for node in ast.walk(self.trees[consumer])), consumer)
            for suffix in suffixes:
                key = prefix + suffix
                self.assertIn(key, valid)
                referenced.add(key)
        for name, tree in self.trees.items():
            if name in FROZEN or name.startswith('tests/'):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and name != 'desktop_strings.py':
                    referenced.add(node.value)
                if isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Name) and node.func.id == 'ui_text') or (isinstance(node.func, ast.Attribute) and node.func.attr == 'ui_text')
                ):
                    args = [node.args[0]]
                    while args:
                        arg = args.pop()
                        if isinstance(arg, ast.IfExp):
                            args.extend((arg.body, arg.orelse))
                        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            self.assertTrue(arg.value in valid, f'{name}:{node.lineno}: {arg.value}')
                            referenced.add(arg.value)
        self.assertEqual(set(strings.ZH_TW) - referenced, set())

    def test_no_duplicate_catalog_dict_keys_and_frozen_alias_compatibility(self):
        for node in ast.walk(self.trees['desktop_strings.py']):
            if isinstance(node, ast.Dict):
                keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
                self.assertEqual(len(keys), len(set(keys)), f'duplicate dict key at {node.lineno}')
        # Frozen files currently contain no old callers. If an unchangeable
        # caller is added, it must resolve through the same pinned fixture.
        for name in FROZEN:
            for node in ast.walk(self.trees[name]):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and GENERIC.search(node.value):
                    self.assertEqual(strings.ui_text(node.value), self.old[node.value])

    def test_help_widget_names_still_match_the_unchanged_baseline(self):
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
        from desktop_help import MOVED_STRINGS, help_button

        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        layout = QVBoxLayout(parent)
        baseline = json.loads((ROOT / 'tests/fixtures/desktop_widget_names.json').read_text(encoding='utf-8'))
        try:
            for key in MOVED_STRINGS:
                button = help_button(layout, key, strings.ui_text(key))
                self.assertIn(button.objectName(), baseline)
                self.assertEqual(button.toolTip(), strings.ui_text(key))
            self.assertIsNotNone(app)
        finally:
            parent.close()


if __name__ == '__main__':
    unittest.main()
