"""Cheap AST budgets and private stage boundaries for the R7 split."""

import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'desktop_app/shell/mount.py': ('mount_pages', None),
    'desktop_app/features/market/dashboard.py': ('__init__', 'MarketDashboard'),
    'desktop_app/components/charts.py': ('paintEvent', 'CandlestickChart'),
    'desktop_app/components/result_layers.py': ('result_snapshot_lines', None),
    'desktop_app/shell/views.py': ('refresh_views', 'ViewCoordinator'),
}
BASE = json.loads((ROOT / 'tests/fixtures/r7_base.json').read_text(encoding='utf-8'))


def target_node(tree, name, cls):
    container = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls) if cls else tree
    return next(n for n in container.body if isinstance(n, ast.FunctionDef) and n.name == name)


def measurements():
    """Emit the same AST evidence used by the budget tests, without importing Qt."""
    rows = {}
    for path, (name, cls) in TARGETS.items():
        source = (ROOT / path).read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        node = target_node(tree, name, cls)
        helpers = {n.name: n.end_lineno - n.lineno + 1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in BASE['functions'][path]}
        rows[path] = {
            'base_lines': BASE['lengths'][path],
            'new_lines': node.end_lineno - node.lineno + 1,
            'helpers': helpers,
            'sha256_lf': sha256(source.encode()).hexdigest(),
        }
    return rows


class FunctionLengthTests(unittest.TestCase):
    def test_five_targets_fit_eighty_lines(self):
        for path, (name, cls) in TARGETS.items():
            with self.subTest(target=f'{cls or path}.{name}'):
                node = target_node(ast.parse((ROOT / path).read_text(encoding='utf-8-sig')), name, cls)
                self.assertLessEqual(node.end_lineno - node.lineno + 1, 80)
                self.assertGreater(BASE['lengths'][path], 80, 'The same budget must reject the captured base')

    def test_extracted_stages_are_private_descriptive_and_bounded(self):
        stages = dict.fromkeys(TARGETS)
        stages.update(
            dict.fromkeys(('desktop_app/components/chart_geometry.py', 'desktop_app/components/chart_paint.py', 'desktop_app/components/chart_paint_footer.py'))
        )
        for path in stages:
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
            baseline = BASE['functions'].get(path, BASE['functions']['desktop_app/components/charts.py'])
            added = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name not in baseline]
            self.assertTrue(added, path)
            for node in added:
                with self.subTest(stage=node.name):
                    self.assertRegex(node.name, r'^_(?:register|mount|copy|build|prepare|paint|parse|validate|reconcile|collect|refresh|restore)_[a-z_]+$')
                    self.assertIsNone(re.search(r'(?:^|_)(?:part\d*|rest|helper|misc)(?:_|$)', node.name))
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 80)

    def test_paint_stages_do_not_introduce_qt_lifetime_work(self):
        paths = ('charts.py', 'chart_geometry.py', 'chart_paint.py', 'chart_paint_footer.py')
        nodes = [node for path in paths for node in ast.parse((ROOT / 'desktop_app/components' / path).read_text(encoding='utf-8-sig')).body]
        for node in nodes:
            if not isinstance(node, ast.FunctionDef) or node.name in BASE['functions']['desktop_app/components/charts.py']:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = child.func.attr if isinstance(child.func, ast.Attribute) else getattr(child.func, 'id', '')
                    self.assertNotIn(name, ('QTimer', 'findChildren', 'deleteLater'))
                if isinstance(child, ast.Assign):
                    self.assertFalse(any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self' for t in child.targets))


if __name__ == '__main__':
    print(json.dumps(measurements(), indent=2))
