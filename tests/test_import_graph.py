"""Cheap AST regression checks for the T11 dependency seams."""

import ast
from functools import lru_cache
import importlib
from pathlib import Path
import pickle
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOUCHED = (
    'quantlab/capital_scenario.py',
    'desktop_capital_scenario.py',
    'tests/test_capital_scenario_b5.py',
    'quantlab/verdict.py',
    'tests/test_verdict_b3.py',
    'tests/test_significance_b4.py',
    'quantlab/significance.py',
    'tests/test_significance_b2.py',
    'quantlab/trade_statistics.py',
    'tests/test_trade_statistics_b1.py',
    'desktop_pages/host.py',
    'tests/page_services_inventory.py',
    'tests/test_page_services_r1.py',
    'tests/test_r7_function_lengths.py',
    'tests/test_r7_characterization.py',
    'tests/r7_characterization.py',
    'desktop_chart_memory.py',
    'desktop_pages/backup_inspection.py',
    'quantlab/backup_inspection.py',
    'desktop_pages/compare_equity.py',
    'desktop_pages/data_gaps.py',
    'quantlab/data_gap_report.py',
    'desktop_pages/preferences.py',
    'quantlab/ui_preferences.py',
    'desktop_pages/quick_start.py',
    'desktop_pages/quick_start_chain.py',
    'desktop_pages/error_guidance.py',
    'desktop_pages/backtest_summary_card.py',
    'quantlab/backtest_summary.py',
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
    'desktop_pages/paper_tabs.py',
    'quantlab/paper_tab_data.py',
    'tests/test_paper_tab_data_c6.py',
    'tests/test_paper_tabs_c6.py',
    'tests/test_paper_timeline_u9.py',
    'desktop_pages/notifications.py',
    'desktop_pages/notification_log.py',
    'tests/test_notifications_c8.py',
    'desktop_pages/command_palette.py',
    'desktop_pages/palette_commands.py',
    'desktop_pages/shortcuts.py',
    'tests/test_command_palette_c7.py',
    'desktop_pages/onboarding.py',
    'tests/test_page_identity_r4.py',
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
    'desktop_chart_popout.py',
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
    'quantlab/analysis_recovery_windows.py',
    'quantlab/desktop_errors.py',
    'quantlab/reporting.py',
    'quantlab/strict_json.py',
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
    ('quantlab.analysis_recovery_windows', 'quantlab.desktop_runtime'),
    ('quantlab.desktop_errors', 'quantlab.desktop_runtime'),
    ('quantlab.__main__', 'quantlab.reporting'),
    ('desktop_pages.onboarding', 'desktop_pages.palette_commands'),
    ('desktop_pages.shortcuts', 'desktop_pages.palette_commands'),
    ('desktop_pages.command_palette', 'desktop_pages.palette_commands'),
    ('quantlab.desktop_runtime', 'quantlab.analysis_recovery'),
    ('quantlab.analysis_recovery', 'quantlab.research_analysis'),
    ('quantlab.research_analysis', 'quantlab.saved_candidate_pool'),
    ('quantlab.research_analysis', 'quantlab.walk_forward'),
    ('quantlab.saved_candidate_pool', 'quantlab.walk_forward'),
    ('desktop_ui', 'desktop_walk_forward'),
)


def source_map():
    paths = (
        sorted((ROOT / 'quantlab').glob('*.py'))
        + sorted(ROOT.glob('desktop*.py'))
        + sorted((ROOT / 'desktop_pages').glob('*.py'))
        + sorted((ROOT / 'desktop_smoke').glob('*.py'))
    )
    return {
        path.relative_to(ROOT).with_suffix('').as_posix().replace('/', '.').removesuffix('.__init__'): path.read_text(encoding='utf-8-sig') for path in paths
    }


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
    def test_a3_strict_json_dependencies(self):
        graph = import_graph(self.sources)
        self.assertEqual(graph['quantlab.strict_json'], {'quantlab.core'})
        self.assertEqual(
            graph['quantlab.reporting'],
            {'quantlab.core', 'quantlab.strict_json', 'quantlab.research_analysis', 'quantlab.configuration', 'quantlab.strategies', 'quantlab.data'},
        )
        self.assertEqual(module_imports('quantlab.strict_json', self.sources['quantlab.strict_json']), {'json', 'pathlib', 'quantlab.core'})

    def test_b2_significance_has_no_application_dependencies(self):
        self.assertEqual(import_graph(self.sources)['quantlab.significance'], set())

    def test_f5_inspection_uses_reader_without_shell_dependency(self):
        graph = import_graph(self.sources)
        self.assertIn('quantlab.backup_inspection', graph['desktop_pages.backup_inspection'])
        self.assertNotIn('desktop_ui', graph['desktop_pages.backup_inspection'])

    def test_r5_leaf_dependencies_and_compatibility_exports(self):
        graph = import_graph(self.sources)
        self.assertEqual(graph['quantlab.runtime_support'], set())
        self.assertNotIn('quantlab.desktop_runtime', graph['quantlab.analysis_recovery_windows'])
        self.assertNotIn('quantlab.desktop_runtime', graph['quantlab.desktop_errors'])
        self.assertNotIn('quantlab.__main__', graph['quantlab.reporting'])
        runtime = importlib.import_module('quantlab.desktop_runtime')
        support = importlib.import_module('quantlab.runtime_support')
        recovery = importlib.import_module('quantlab.analysis_recovery_windows')
        cli = importlib.import_module('quantlab.__main__')
        configuration = importlib.import_module('quantlab.configuration')
        self.assertIs(runtime.RuntimeSafetyError, support.RuntimeSafetyError)
        self.assertIs(runtime.WindowsAppMutex, support.WindowsAppMutex)
        self.assertIs(recovery.WindowsAppMutex, support.WindowsAppMutex)
        self.assertEqual(runtime.WINDOWS_APP_MUTEX, support.WINDOWS_APP_MUTEX)
        self.assertIs(cli.config_from_json, configuration.config_from_json)
        for module, name in (
            (runtime, 'WindowsAppMutex'),
            (runtime, '_job_worker'),
            (runtime, '_worker_recovery_guard'),
            (recovery, 'WindowsAnalysisRecoveryTree'),
        ):
            with self.subTest(name=name):
                obj = getattr(module, name)
                self.assertIs(pickle.loads(pickle.dumps(obj)), obj)
                self.assertIs(getattr(importlib.import_module(obj.__module__), obj.__qualname__), obj)
        # Existing module-qualified platform/ctypes patches still reach the moved class.
        with patch('quantlab.desktop_runtime.sys.platform', 'win32'), patch('quantlab.desktop_runtime.ctypes.WinDLL', create=True) as load:
            guard = runtime.WindowsAppMutex()
            kernel = load.return_value
            kernel.CreateMutexW.assert_called_once_with(None, False, runtime.WINDOWS_APP_MUTEX)
            guard.close()
            kernel.CloseHandle.assert_called_once_with(kernel.CreateMutexW.return_value)
            self.assertIsNone(guard.handle)

    def test_r5_startup_and_exception_codes_are_preserved(self):
        errors = importlib.import_module('quantlab.desktop_errors')
        support = importlib.import_module('quantlab.runtime_support')
        self.assertIs(errors.ERROR_TABLE, importlib.import_module('quantlab.errors').ERROR_TABLE)
        for message, code in (
            ('This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)', 'startup_sqlite_old'),
            ('Unsupported workspace version; original preserved', 'startup_workspace_incompatible'),
            ('Unsupported workspace pointer; original preserved', 'startup_workspace_incompatible'),
            ('Another MarkAuto instance is using this installation', 'startup_workspace_busy'),
            ('other', 'startup_failed'),
        ):
            with self.subTest(message=message):
                self.assertEqual(errors.startup_error_code(support.RuntimeSafetyError(message)), code)
                self.assertEqual(errors.startup_error_code(ValueError(message)), 'startup_failed')
        for exception, code in (
            (ValueError('invalid'), 'validation_failed'),
            (OSError('local'), 'operation_failed_local'),
            (RuntimeError('unknown'), 'operation_failed'),
            (support.RuntimeSafetyError('validation_failed'), 'validation_failed'),
        ):
            with self.subTest(code=code):
                self.assertEqual(errors.exception_code(exception), code)

    def test_paper_timeline_projection_has_no_application_dependencies(self):
        self.assertEqual(import_graph(self.sources)['quantlab.paper_tab_data'], set())

    def test_quick_start_sequencer_is_pure(self):
        self.assertEqual(module_imports('desktop_pages.quick_start_chain', self.sources['desktop_pages.quick_start_chain']), set())

    def test_error_guidance_u7_has_only_display_dependencies(self):
        self.assertEqual(
            import_graph(self.sources)['desktop_pages.error_guidance'],
            {'desktop_privacy', 'desktop_strings', 'quantlab.desktop_errors'},
        )

    def test_backtest_summary_u4_is_pure(self):
        self.assertEqual(module_imports('quantlab.backtest_summary', self.sources['quantlab.backtest_summary']), set())

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

    def test_u8_preferences_keep_serialization_qt_free(self):
        graph = import_graph(self.sources)
        self.assertEqual(graph['quantlab.ui_preferences'], set())
        imports = module_imports('quantlab.ui_preferences', self.sources['quantlab.ui_preferences'])
        self.assertFalse(any(target.startswith(('desktop', 'PySide6')) for target in imports))
        self.assertEqual(graph['desktop_pages.preferences'], {'quantlab.ui_preferences', 'quantlab.runtime_support'})

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
