"""Cheap extraction contracts; real process coverage remains in smoke suites."""

import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import desktop
import desktop_app.smoke
from tests.test_import_graph import import_graph, reaches, source_map
from tests.layered_source_fixtures import physical_path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = {
    'parse_args',
    'acquire_instance_lock',
    'prepare_workspace',
    'run_gui',
    'main',
    '_prepare_startup_workspace',
    '_offer_workspace_after_recovery_block',
}
HARNESS = {
    '_SmokeSettingsView',
    '_auth_smoke_dependencies',
    '_smoke_steps',
    '_market_smoke_ui',
    '_market_smoke_response',
    '_check_market_worker_result',
    '_history_smoke_fixture',
    '_check_history_worker_result',
    '_history_smoke_ui',
    '_walk_forward_smoke_fixture',
    '_check_walk_forward_smoke_result',
    '_start_smoke_job',
    '_close_smoke_worker',
    '_retain_smoke_directory',
    'run_smoke',
}


class SmokePackageTests(unittest.TestCase):
    def test_entry_point_definitions_and_size(self):
        source = (ROOT / 'desktop.py').read_text(encoding='utf-8-sig')
        definitions = {node.name for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(definitions, PRODUCTION)
        self.assertLessEqual(len(source.splitlines()), 590)

    def test_compatibility_exports_are_identical(self):
        for name in HARNESS:
            with self.subTest(name=name):
                self.assertIs(getattr(desktop, name), getattr(desktop_app.smoke, name))

    def test_injections_reach_the_harness_globals(self):
        for name in ('_check_history_worker_result', '_history_smoke_fixture', '_close_smoke_worker', '_check_walk_forward_smoke_result'):
            sentinel = object()
            with self.subTest(name=name), patch.object(desktop_app.smoke, name, sentinel):
                self.assertIs(desktop.run_smoke.__globals__[name], sentinel)

    def test_all_package_modules_are_statically_reachable(self):
        graph = import_graph(source_map())
        modules = {
            path.relative_to(ROOT).with_suffix('').as_posix().replace('/', '.').removesuffix('.__init__')
            for path in (ROOT / physical_path('desktop_smoke')).rglob('*.py')
        }
        self.assertTrue(modules)
        for name in modules:
            with self.subTest(module=name):
                self.assertTrue(reaches(graph, 'desktop', name))

    def test_zero_difference_evidence_covers_all_definitions(self):
        evidence = json.loads((ROOT / 'docs/analysis/r2_ast_preservation.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['differing'], [])
        self.assertEqual(set(evidence['definitions']), PRODUCTION | HARNESS)
        self.assertTrue(all(record['equal'] for record in evidence['definitions'].values()))


if __name__ == '__main__':
    unittest.main()
