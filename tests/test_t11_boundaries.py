"""No subprocesses, filesystem fixtures, Qt objects, or environment dependencies."""

from quantlab.research_core.application import job_requests
from quantlab.research_core.adapters import job_worker


import ast
from contextlib import nullcontext
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch

from quantlab import desktop_runtime as runtime
from tools.quality_gate import core_import_findings, python_findings, scan


ROOT = Path(__file__).resolve().parents[1]


class CoreBoundaryTests(unittest.TestCase):
    def test_clean_tree(self):
        for path in sorted((ROOT / 'quantlab').glob('*.py')):
            with self.subTest(module=path.name):
                self.assertEqual(core_import_findings(path.read_text(encoding='utf-8-sig'), path.name), [])
                self.assertEqual(python_findings(path.read_text(encoding='utf-8-sig'), path.name, research=True), [])

    def test_repository_scan_enforces_rule_independently_of_legacy_classifier(self):
        fake_path = Mock()
        fake_path.is_file.return_value = True
        fake_path.suffix = '.py'
        fake_path.read_bytes.return_value = b'def f():\n    from desktop_app.shell.main_window import MainWindow\n'
        root = MagicMock()
        root.__truediv__.return_value = fake_path
        with patch('tools.quality_gate.git', return_value=b'quantlab/desktop_runtime.py\0'):
            findings = scan(root)
        self.assertTrue(any('no desktop imports' in value for value in findings))

    def test_extracted_public_names_remain_reexported(self):
        from quantlab import analysis_contracts, configuration, runtime_support, value_bounds
        from quantlab import research_analysis, walk_forward
        from quantlab import __main__ as cli

        self.assertIs(runtime.RuntimeSafetyError, runtime_support.RuntimeSafetyError)
        self.assertIs(job_requests.validate_analysis_request, runtime_support.validate_analysis_request)
        self.assertIs(research_analysis.validate_analysis_plan, analysis_contracts.validate_analysis_plan)
        self.assertIs(research_analysis.analysis_request, analysis_contracts.analysis_request)
        self.assertIs(walk_forward._bounded_value, value_bounds._bounded_value)
        self.assertIs(cli.config_from_json, configuration.config_from_json)

    def test_static_imports_including_function_local_are_rejected(self):
        for source in (
            'import desktop_app.shell.main_window',
            'from desktop_app.connection_composition import execute_ui_operation',
            'def f():\n    import desktop_app.features.walk_forward.presenter',
            'def f():\n    from desktop_app.shell.main_window import MainWindow',
        ):
            self.assertTrue(core_import_findings(source, 'quantlab/fixture.py'))

    def test_negative_control_and_dynamic_literal(self):
        for source in (
            'from .desktop_errors import ERROR_TABLE',
            'from quantlab.desktop_runtime import JobManager',
            'import importlib\nimportlib.import_module(registrar)',
            'text = "import desktop_app.shell.main_window"',
        ):
            self.assertEqual(core_import_findings(source, 'quantlab/fixture.py'), [])
        self.assertTrue(core_import_findings('import importlib\nimportlib.import_module("desktop_app.shell.main_window")', 'quantlab/fixture.py'))
        # QA finding: the `from importlib import import_module` spelling must be caught as well.
        self.assertTrue(
            core_import_findings('from importlib import import_module' + chr(10) + 'import_module("desktop_app.shell.main_window")', 'quantlab/fixture.py')
        )
        self.assertEqual(core_import_findings('from importlib import import_module' + chr(10) + 'import_module(registrar)', 'quantlab/fixture.py'), [])

    def test_registry_is_fail_closed_and_identity_idempotent(self):
        registry = job_worker._OperationExecutorRegistry()
        with patch('quantlab.research_core.adapters.job_worker._executor_registry', registry):
            with self.assertRaises(runtime.RuntimeSafetyError):
                job_worker._operation_executor()
            executor = lambda *args, **kwargs: None
            job_worker.register_operation_executor(executor)
            job_worker.register_operation_executor(executor)
            self.assertIs(job_worker._operation_executor(), executor)
            for value in (None, lambda: None):
                with self.assertRaises(runtime.RuntimeSafetyError):
                    job_worker.register_operation_executor(value)
            self.assertIs(job_worker._operation_executor(), executor)

    def test_worker_resolves_injected_entry_point_before_execution(self):
        executor = lambda *args, **kwargs: 'result'

        class Module:
            execute = executor

        with patch.object(job_worker.importlib, 'import_module', return_value=Module) as load:
            resolved = job_worker._worker_operation_executor('fixture:execute')
            self.assertIs(resolved, executor)
            load.assert_called_once_with('fixture')
        with self.assertRaises(runtime.RuntimeSafetyError):
            job_worker._worker_operation_executor(None)
        with patch.object(job_worker.importlib, 'import_module', return_value=object()):
            with self.assertRaises(AttributeError):
                job_worker._worker_operation_executor('fixture:missing')

    def test_worker_uses_registered_executor_and_preserves_private_proof(self):
        for admitted in (False, True):
            sender, gate = Mock(), Mock()
            gate.wait.return_value = True
            executor = Mock(return_value={'reference': 'fixture'})
            with (
                patch.object(runtime.os, 'setsid', create=True),
                patch.object(job_worker, 'AppPaths', return_value=object()),
                patch('quantlab.research_core.adapters.job_worker._worker_recovery_guard', return_value=nullcontext()),
                patch('quantlab.research_core.adapters.job_worker._worker_operation_executor', return_value=executor),
            ):
                job_worker._job_worker(sender, gate, 'ui_walk_forward_reconcile', {'descendants_stopped': True}, 'unused', None, 'fixture', admitted)
            self.assertIs(executor.call_args.kwargs['descendants_stopped'], admitted)
            sender.close.assert_called_once_with()

    def test_worker_missing_registration_emits_error_without_execution(self):
        sender, gate = Mock(), Mock()
        gate.wait.return_value = True
        with (
            patch.object(runtime.os, 'setsid', create=True),
            patch.object(job_worker, 'AppPaths', return_value=object()),
            patch('quantlab.research_core.adapters.job_worker._worker_recovery_guard', return_value=nullcontext()),
            patch.object(job_worker.importlib, 'import_module') as load,
        ):
            job_worker._job_worker(sender, gate, 'ui_demo', {}, 'unused', None, 'fixture', operation_registrar=None)
        load.assert_not_called()
        self.assertIn(b'"type": "error"', sender.send_bytes.call_args.args[0])
        self.assertIn(b'"error_type": "RuntimeSafetyError"', sender.send_bytes.call_args.args[0])

    def test_registrar_duplicate_policy(self):
        with patch('quantlab.research_core.adapters.job_worker._executor_registrar', None):
            job_worker.register_operation_executor_factory('fixture:execute')
            job_worker.register_operation_executor_factory('fixture:execute')
            for target in ('other:execute', '', 'fixture', None):
                with self.assertRaises(runtime.RuntimeSafetyError):
                    job_worker.register_operation_executor_factory(target)

    def test_new_modules_are_statically_reachable_for_packaging(self):
        expected = {'runtime_support', 'value_bounds', 'analysis_contracts', 'configuration'}
        imported = set()
        for path in (ROOT / 'quantlab').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    imported.add(node.module)
        self.assertTrue(expected <= imported)
