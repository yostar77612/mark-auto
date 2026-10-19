"""Cheap AST regression checks for the T11 dependency seams."""

import ast
from functools import lru_cache
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOUCHED = (
    'quantlab/tls_trust.py',
    'quantlab/job_stages.py',
    'quantlab/desktop_runtime.py',
    'quantlab/runtime_support.py',
    'quantlab/analysis_recovery.py',
    'quantlab/research_analysis.py',
    'quantlab/analysis_contracts.py',
    'quantlab/saved_candidate_pool.py',
    'quantlab/walk_forward.py',
    'quantlab/value_bounds.py',
    'quantlab/configuration.py',
    'quantlab/__main__.py',
    'desktop_ui.py',
    'desktop_walk_forward.py',
    'desktop_presentation.py',
)
PAIRS = (
    ('quantlab.desktop_runtime', 'quantlab.analysis_recovery'),
    ('quantlab.analysis_recovery', 'quantlab.research_analysis'),
    ('quantlab.research_analysis', 'quantlab.saved_candidate_pool'),
    ('quantlab.research_analysis', 'quantlab.walk_forward'),
    ('quantlab.saved_candidate_pool', 'quantlab.walk_forward'),
    ('desktop_ui', 'desktop_walk_forward'),
)


def source_map():
    paths = sorted((ROOT / 'quantlab').glob('*.py')) + sorted(ROOT.glob('desktop*.py'))
    return {path.relative_to(ROOT).with_suffix('').as_posix().replace('/', '.'): path.read_text(encoding='utf-8-sig') for path in paths}


@lru_cache(maxsize=256)
def module_imports(name, source):
    targets = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = name.rsplit('.', node.level)[0] + '.' if node.level else ''
            targets.update([prefix + node.module] if node.module else [prefix + alias.name for alias in node.names])
    return frozenset(targets)


def import_graph(sources):
    return {name: module_imports(name, source).intersection(sources) for name, source in sources.items()}


def reaches(graph, start, end):
    seen, pending = set(), [start]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for child in graph[current]:
            if child == end:
                return True
            pending.append(child)
    return False


def listed_cycles(sources):
    graph = import_graph(sources)
    return [(left, right) for left, right in PAIRS if reaches(graph, left, right) and reaches(graph, right, left)]


def uncommented_local_imports(source):
    lines = source.splitlines()
    tree = ast.parse(source)
    local = set()
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local.update(node.lineno for node in ast.walk(function) if isinstance(node, (ast.Import, ast.ImportFrom)))
    return sorted(line for line in local if '#' not in lines[line - 1] and (line < 2 or not lines[line - 2].lstrip().startswith('#')))


class ImportGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = source_map()

    def test_listed_cycles_are_absent(self):
        self.assertEqual(listed_cycles(self.sources), [])

    def test_each_in_memory_back_edge_is_detected(self):
        graph = import_graph(self.sources)
        for left, right in PAIRS:
            with self.subTest(pair=(left, right)):
                sources = dict(self.sources)
                # Inject both edges if no pre-existing path exists in either direction.
                if reaches(graph, left, right):
                    sources[right] += '\nimport ' + left + '\n'
                elif reaches(graph, right, left):
                    sources[left] += '\nimport ' + right + '\n'
                else:
                    sources[left] += '\nimport ' + right + '\n'
                    sources[right] += '\nimport ' + left + '\n'
                self.assertIn((left, right), listed_cycles(sources))

    def test_function_local_imports_have_adjacent_reasons(self):
        for name in TOUCHED:
            with self.subTest(module=name):
                self.assertEqual(uncommented_local_imports((ROOT / name).read_text(encoding='utf-8-sig')), [])

    def test_local_import_comment_scan_detects_missing_reason(self):
        self.assertEqual(uncommented_local_imports('def f():\n    import json\n'), [2])
        self.assertEqual(uncommented_local_imports('def f():\n    # Delay optional dependency until requested.\n    import json\n'), [])
