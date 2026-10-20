"""Cheap AST regression checks for the T11 dependency seams."""

import ast
from functools import lru_cache
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOUCHED = (
    'desktop_pages/assistant_manifest.py',
    'quantlab/agent_manifest.py',
    'desktop_pages/assistant_models.py',
    'desktop_pages/assistant_completion.py',
    'desktop_pages/connection_test.py',
    'desktop_pages/assistant_permissions.py',
    'desktop_pages/assistant_details.py',
    'desktop_pages/assistant_runtime.py',
    'desktop_pages/assistant.py',
    'quantlab/assistant_chat.py',
    'quantlab/agent_skills.py',
    'quantlab/agent_return.py',
    'quantlab/agent_read_tools.py',
    'quantlab/agent_tool_contract.py',
    'quantlab/agent_tools.py',
    'desktop_pages/compare_table.py',
    'desktop_pages/log_table.py',
    'tests/test_table_readability_c9.py',
    'desktop_pages/widgets.py',
    'tests/test_panel_card_c3.py',
    'desktop_pages/async_status.py',
    'tests/test_async_status_c4.py',
    'desktop_pages/app_header.py',
    'tests/test_header_c1.py',
    'quantlab/replay_pacing.py',
    'quantlab/paper_replay.py',
    'desktop_pages/replay_controls.py',
    'tests/test_replay_b13.py',
    'quantlab/diagnostics.py',
    'desktop_pages/diagnostics.py',
    'desktop_pages/settings_layout.py',
    'tests/test_diagnostics_b12.py',
    'tests/test_paper_lock_b2.py',
    'quantlab/paper.py',
    'quantlab/desktop_feedback.py',
    'desktop_pages/paper.py',
    'quantlab/errors.py',
    'desktop_privacy.py',
    'desktop_theme.py',
    'desktop_pages/settings_layout.py',
    'desktop_pages/result_widgets.py',
    'desktop_order_lines.py',
    'quantlab/paper_amend.py',
    'quantlab/product_keys.py',
    'quantlab/chart_drawings.py',
    'desktop_market.py',
    'desktop_market_layout.py',
    'desktop_market_workspace.py',
    'tests/test_market_workspace_c5.py',
    'desktop_pages/market.py',
    'desktop_chatgpt_states.py',
    'desktop_pages/job_progress.py',
    'quantlab/payload_cleanup.py',
    'quantlab/update_check.py',
    'desktop_pages/maintenance.py',
    'quantlab/tls_trust.py',
    'quantlab/job_stages.py',
    'quantlab/wf_estimate.py',
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
    paths = sorted((ROOT / 'quantlab').glob('*.py')) + sorted(ROOT.glob('desktop*.py')) + sorted((ROOT / 'desktop_pages').glob('*.py'))
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
    def test_manifest_d12_has_only_contract_edges(self):
        graph = import_graph(self.sources)
        self.assertEqual(graph['quantlab.agent_manifest'], {'quantlab.agent_tool_contract'})
        self.assertIn('desktop_pages.assistant_manifest', graph['desktop_pages.assistant'])

    def test_d4_assistant_core_has_no_operator_or_ui_edges(self):
        graph = import_graph(self.sources)
        self.assertEqual(
            graph['quantlab.assistant_chat'],
            {'quantlab.agent_read_tools', 'quantlab.agent_tools', 'quantlab.agent_tool_contract'},
        )
        self.assertIn('desktop_pages.assistant_runtime', graph['desktop_pages.assistant'])
        self.assertNotIn('desktop_ui', graph['desktop_pages.assistant_runtime'])

    def test_d7_skills_have_only_permitted_edges(self):
        self.assertEqual(
            import_graph(self.sources)['quantlab.agent_skills'],
            {'quantlab.agent_return', 'quantlab.agent_tool_contract', 'quantlab.agent_tools'},
        )
        imports = module_imports('quantlab.agent_skills', self.sources['quantlab.agent_skills'])
        self.assertFalse(any(part.startswith(('desktop', 'PySide6', 'Qt')) for target in imports for part in target.split('.')))

    def test_d3_read_tools_have_only_permitted_edges(self):
        graph = import_graph(self.sources)
        self.assertEqual(
            graph['quantlab.agent_read_tools'],
            {
                'quantlab.agent_tool_contract',
                'quantlab.agent_tools',
                'quantlab.agent_return',
                'quantlab.agent_manifest',
                'quantlab.core',
                'quantlab.paper',
                'quantlab.reporting',
                'quantlab.research',
            },
        )
        imports = module_imports('quantlab.agent_read_tools', self.sources['quantlab.agent_read_tools'])
        self.assertFalse(any(part.startswith(('desktop', 'PySide6', 'Qt')) for target in imports for part in target.split('.')))

    def test_agent_tools_have_only_permitted_core_edges(self):
        graph = import_graph(self.sources)
        self.assertEqual(graph['quantlab.agent_tool_contract'], set())
        self.assertEqual(graph['quantlab.agent_tools'], {'quantlab.agent_tool_contract', 'quantlab.errors', 'quantlab.agent_return'})
        self.assertEqual(graph['quantlab.agent_return'], {'quantlab.agent_tool_contract'})
        for name in ('quantlab.agent_tool_contract', 'quantlab.agent_tools', 'quantlab.agent_return'):
            imports = module_imports(name, self.sources[name])
            self.assertFalse(any(part.startswith(('desktop', 'PySide6', 'Qt')) for target in imports for part in target.split('.')))

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
