"""Cheap startup and error-contract checks; no subprocesses or disk fixtures."""

import ast
import copy
from contextlib import ExitStack
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import desktop
import desktop_app.strings.catalog
from quantlab import errors
from quantlab.saved_candidate_pool import SavedCandidatePoolError
from quantlab.desktop_errors import ERROR_LABELS, ERROR_TABLE, error_message, exception_code

ROOT = Path(__file__).resolve().parents[1]


class _NormalizeState(ast.NodeTransformer):
    def visit_Constant(self, node):
        # R3 changes only the catalog identifier in the pinned GUI handler.
        # Keep the original fingerprint and verify the identical message. The
        # earlier lock dialog uses the first alias; run_gui uses the last one.
        if node.value == 'desktop.main.startup_failed':
            aliases = [old for old, new in desktop_app.strings.catalog.TEXT_ALIASES.items() if new == node.value]
            assert len(aliases) == 2
            assert all(desktop_app.strings.catalog.ui_text(old) == desktop_app.strings.catalog.ui_text(node.value) for old in aliases)
            node.value = aliases[-1]
        return node

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == 'state':
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return self.generic_visit(node)

    def visit_Nonlocal(self, node):
        node.names = [name for name in node.names if name not in {'smoke_jobs', 'smoke_report', 'smoke_cleanup_verified'}]
        return node if node.names else None

    def visit_Pass(self, node):
        return None


def _canonical(node):
    """Python-version-independent AST fingerprint."""
    # ast.dump() differs between 3.11/3.12/3.13 (3.13 omits empty/None fields, 3.12 added type_params), so
    # the digest is built from node types and non-empty field values only.
    if isinstance(node, ast.AST):
        fields = []
        for name in node._fields:
            value = getattr(node, name, None)
            if value is None or value == []:
                continue
            fields.append(name + '=' + _canonical(value))
        return type(node).__name__ + '(' + ','.join(fields) + ')'
    if isinstance(node, list):
        return '[' + ','.join(_canonical(item) for item in node) + ']'
    return repr(node)


def _digest(nodes):
    tree = _NormalizeState().visit(copy.deepcopy(ast.Module(body=nodes, type_ignores=[])))
    return hashlib.sha256(_canonical(tree).encode()).hexdigest()


class StartupTests(unittest.TestCase):
    def _without_reviewed_access_metadata(self, nodes, *, expected_count):
        # Review the added evidence field independently; keep all original
        # control flow, time limits and cleanup under their historical hashes.
        tree = copy.deepcopy(ast.Module(body=nodes, type_ignores=[]))
        expected = ast.parse("'none' if getattr(state.args, 'smoke_isolated', False) else 'read_only'", mode='eval').body
        count = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            indexes = [i for i, key in enumerate(node.keys) if isinstance(key, ast.Constant) and key.value == 'user_state_access']
            self.assertLessEqual(len(indexes), 1, 'Duplicate smoke access metadata')
            if indexes:
                index = indexes[0]
                self.assertEqual(_canonical(node.values[index]), _canonical(expected))
                paired = [value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant) and key.value == 'user_state_read_only']
                self.assertEqual([_canonical(value) for value in paired], [_canonical(ast.Constant(value=True))])
                del node.keys[index]
                del node.values[index]
                count += 1
        self.assertEqual(count, expected_count)
        return tree.body

    def test_main_budget_and_named_seams(self):
        functions = {node.name: node for node in ast.parse((ROOT / 'desktop.py').read_text(encoding='utf-8-sig')).body if isinstance(node, ast.FunctionDef)}
        main = functions['main']
        self.assertLessEqual(main.end_lineno - main.lineno + 1, 80)
        for name in ('parse_args', 'acquire_instance_lock', 'prepare_workspace', 'run_smoke', 'run_gui'):
            self.assertTrue(callable(getattr(desktop, name)))

    def test_baseline_smoke_and_terminal_cleanup(self):
        # Original fingerprints retain control flow and cleanup. Only the exact
        # added access evidence is independently reviewed before comparison.
        functions = {node.name: node for node in ast.parse((ROOT / 'desktop.py').read_text(encoding='utf-8-sig')).body if isinstance(node, ast.FunctionDef)}
        lifecycle = next(node for node in functions['run_gui'].body if isinstance(node, ast.Try))
        functions.update(
            {
                node.name: node
                for node in ast.parse((ROOT / 'desktop_app/smoke/__init__.py').read_text(encoding='utf-8-sig')).body
                if isinstance(node, ast.FunctionDef)
            }
        )
        self.assertEqual(_digest(self._without_reviewed_access_metadata(functions['run_smoke'].body[3:], expected_count=2)), SMOKE_DIGEST)
        self.assertEqual(_digest(self._without_reviewed_access_metadata(lifecycle.handlers, expected_count=1)), HANDLERS_DIGEST)
        self.assertEqual(_digest(lifecycle.finalbody), FINALLY_DIGEST)

    def test_main_routes_tls_without_gui(self):
        report = Path(__file__).resolve()
        with patch('desktop_app.smoke.tls.write_report', return_value=17) as write, patch('desktop.run_gui') as gui:
            self.assertEqual(desktop.main(['--tls-smoke', str(report)]), 17)
        write.assert_called_once_with(report)
        gui.assert_not_called()

    def test_main_routes_normal_and_smoke(self):
        for argv in ([], ['--smoke-test', str(Path(__file__).resolve())]):
            with self.subTest(argv=argv), patch('desktop.run_gui', return_value=23) as gui:
                self.assertEqual(desktop.main(argv), 23)
                self.assertEqual(gui.call_args.args[0].smoke_test, None if not argv else Path(argv[1]))

    def test_lock_busy_retains_dialog_and_cleanup(self):
        lock = Mock()
        lock.tryLock.return_value = False
        directory = Mock()
        with patch('PySide6.QtCore.QLockFile', return_value=lock) as factory, patch('PySide6.QtWidgets.QMessageBox.information') as dialog:
            self.assertIsNone(desktop.acquire_instance_lock(SimpleNamespace(lock_path='lock-path'), directory))
        factory.assert_called_once_with('lock-path')
        lock.setStaleLockTime.assert_called_once_with(0)
        lock.tryLock.assert_called_once_with(0)
        directory.cleanup.assert_called_once_with()
        dialog.assert_called_once_with(None, desktop.ui_text('desktop.main.startup_failed'), error_message('startup_workspace_busy'))

    def test_lock_acquired_retains_handle(self):
        lock = Mock()
        lock.tryLock.return_value = True
        directory = Mock()
        with patch('PySide6.QtCore.QLockFile', return_value=lock):
            self.assertIs(desktop.acquire_instance_lock(SimpleNamespace(lock_path='lock-path'), directory), lock)
        directory.cleanup.assert_not_called()

    def test_normal_gui_lifecycle_order_without_workspace_io(self):
        events = []

        def event(name, result=None):
            def record(*args, **kwargs):
                events.append(name)
                return result

            return record

        app = Mock()
        app.exec.side_effect = event('exec', 19)
        app.installNativeEventFilter.side_effect = event('filter')
        window = Mock()
        window.show.side_effect = event('show')
        window.freeze_paper.side_effect = event('freeze')
        window.auto_restore_chatgpt.side_effect = event('restore')
        timer = Mock()
        timer.start.side_effect = event('timer')
        lock = Mock()
        lock.unlock.side_effect = event('unlock')

        def prepare(state):
            events.append('prepare')
            state.paths = Mock()
            state.settings = Mock()
            state.backups = Mock()
            state.previous_unclean = False
            state.jobs = Mock()
            state.jobs.close.side_effect = event('jobs.close')
            state.guard = Mock()
            state.guard.finish.side_effect = event('guard.finish')
            state.installation_guard = Mock()
            state.installation_guard.close.side_effect = event('mutex.close')
            return True

        with ExitStack() as stack:
            stack.enter_context(patch('PySide6.QtCore.QAbstractNativeEventFilter', object))
            stack.enter_context(patch('PySide6.QtCore.QTimer', return_value=timer))
            stack.enter_context(patch('PySide6.QtWidgets.QApplication', return_value=app))
            stack.enter_context(patch('desktop_app.components.icon.application_icon', return_value=None))
            stack.enter_context(patch('quantlab.desktop_runtime.AppPaths.discover', return_value=SimpleNamespace(root=MagicMock())))
            stack.enter_context(patch('quantlab.desktop_runtime.WorkspaceLocator'))
            stack.enter_context(patch('desktop.acquire_instance_lock', return_value=lock))
            stack.enter_context(patch('desktop.prepare_workspace', side_effect=prepare))
            stack.enter_context(patch.dict('sys.modules', {'desktop_app.shell.main_window': SimpleNamespace(MainWindow=Mock(return_value=window))}))
            self.assertEqual(desktop.main([]), 19)
        self.assertEqual(
            events, ['prepare', 'show', 'freeze', 'restore', 'filter', 'timer', 'exec', 'jobs.close', 'guard.finish', 'jobs.close', 'mutex.close', 'unlock']
        )
        window.freeze_paper.assert_called_once_with('Startup requires paper reconciliation')


class SharedErrorTests(unittest.TestCase):
    def test_exact_enum_coverage_and_chinese_messages(self):
        self.assertEqual({code.value for code in errors.ErrorCode}, set(ERROR_TABLE))
        self.assertEqual(set(ERROR_LABELS), set(ERROR_TABLE))
        for code in errors.ErrorCode:
            with self.subTest(code=code.value):
                text = ERROR_TABLE[code.value]
                self.assertTrue(text.explanation and text.action)
                self.assertTrue(any('\u4e00' <= char <= '\u9fff' for char in text.explanation))
                self.assertEqual(exception_code(SimpleNamespace(code=code.value)), code.value)

    def test_wrappers_preserve_exact_exception_contract(self):
        from quantlab import analysis_contracts, analysis_recovery, chart_data, market_history, saved_candidate_pool
        from quantlab.core import ValidationError
        from quantlab.market import MarketValidationError

        for module, error in (
            (analysis_contracts, ValidationError),
            (analysis_recovery, errors.RecoveryError),
            (chart_data, MarketValidationError),
            (market_history, MarketValidationError),
            (saved_candidate_pool, SavedCandidatePoolError),
        ):
            with self.subTest(module=module.__name__):
                with self.assertRaises(error) as raised:
                    module._fail('verbatim message \u4e2d\n')
                self.assertIs(type(raised.exception), error)
                self.assertEqual(raised.exception.args, ('verbatim message \u4e2d\n',))
                expected = {'reason_code': 'source_invalid_evidence'} if module is saved_candidate_pool else {}
                self.assertEqual(vars(raised.exception), expected)
        self.assertIs(analysis_recovery.RecoveryError, errors.RecoveryError)
        self.assertIs(saved_candidate_pool.SavedCandidatePoolError, SavedCandidatePoolError)
        self.assertEqual(errors.RecoveryError.__module__, 'quantlab.analysis_recovery')
        self.assertEqual(SavedCandidatePoolError.__module__, 'quantlab.saved_candidate_pool')

    def test_saved_reason_precedence(self):
        from quantlab.saved_candidate_pool import _fail, SavedCandidatePoolError

        for message, code in [
            ('strictly before producer protocol', 'source_temporal_overlap'),
            ('Source provider protocol', 'source_provider_unsupported'),
            ('Source provider receipt Missing', 'source_provider_receipt_invalid'),
            ('Missing evidence', 'source_missing_evidence'),
        ]:
            with self.subTest(message=message):
                with self.assertRaises(SavedCandidatePoolError) as raised:
                    _fail(message)
                self.assertEqual(raised.exception.reason_code, code)
                self.assertEqual(raised.exception.args, (message,))

    def test_exception_fallbacks(self):
        for exc, code in [
            (ValueError('history_date_invalid'), 'history_date_invalid'),
            (ValueError('unknown'), 'validation_failed'),
            (OSError('unknown'), 'operation_failed_local'),
            (RuntimeError('unknown'), 'operation_failed'),
        ]:
            self.assertEqual(exception_code(exc), code)
        self.assertEqual(error_message('unknown'), error_message('operation_failed'))


SMOKE_DIGEST = '7ceffca1b8b4cb9e77bf345bbe0161df84098cdacf8a4355f648ca06d67ba8ed'
HANDLERS_DIGEST = '538ec585bef484789b7e1bc9a05b942234dee1b82f84bacc2c849cf28ead39de'
FINALLY_DIGEST = '4ce33993e38dae10a54cda3424e0d354b09a4b8c460af84f4bd4883b6ae9a851'
