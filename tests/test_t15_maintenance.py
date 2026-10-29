"""T15 offline maintenance contracts; no socket, installer or real profile access."""

import ast
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QToolButton

from desktop_app.features.settings.maintenance import MaintenancePanel, installed_payload_root
from desktop_app.strings.catalog import ui_text
from quantlab.payload_cleanup import CleanupPlan, execute_payload_cleanup, plan_payload_cleanup
from quantlab.update_check import MAX_BODY, UpdateResult, _HTTPSRedirect, check_for_update
from tests.test_t9_onboarding import sandbox_ui


ROOT = Path(__file__).resolve().parents[1]


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket', side_effect=AssertionError('network forbidden')))
        self.stack.enter_context(sandbox_ui())

    def temp(self):
        # Resolve once: CI temp dirs use Windows 8.3 short spellings, which the cleanup (fail closed) treats as a different root spelling.
        return Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='t15-'))).resolve()


class PayloadCleanupTests(OfflineTest):
    def tree(self, names=('1.0', '1.1', '1.2')):
        parent = self.temp()
        root = parent / 'payloads'
        root.mkdir()
        for name in names:
            attempt = root / name / 'unique-attempt'
            attempt.mkdir(parents=True)
            (attempt / 'program.exe').write_bytes(b'payload')
        workspace = parent / 'MarkAuto'
        sibling = parent / 'payloads-other'
        for directory in (workspace, sibling):
            directory.mkdir()
            (directory / 'sentinel').write_bytes(b'keep')
        return root, workspace, sibling

    def test_only_oldest_deleted_and_sentinels_survive(self):
        root, workspace, sibling = self.tree()
        plan = plan_payload_cleanup(root, '1.2')
        self.assertEqual(plan.reason, '')
        self.assertEqual(plan.candidates, (root / '1.0',))
        self.assertEqual(execute_payload_cleanup(plan).deleted, (root / '1.0',))
        self.assertEqual(sorted(path.name for path in root.iterdir()), ['1.1', '1.2'])
        for directory in (workspace, sibling):
            self.assertEqual((directory / 'sentinel').read_bytes(), b'keep')

    def test_multiple_candidates_and_newer_versions(self):
        root, _, _ = self.tree(('0.8', '0.9', '1.0', '1.1', '1.2', '2.0'))
        plan = plan_payload_cleanup(root, '1.2')
        self.assertEqual([p.name for p in plan.candidates], ['0.8', '0.9', '1.0', '2.0'])
        result = execute_payload_cleanup(plan)
        self.assertEqual(result.reason, '')
        self.assertEqual(result.deleted, plan.candidates)
        self.assertEqual(sorted(p.name for p in root.iterdir()), ['1.1', '1.2'])

    def test_ambiguous_names_or_missing_current_refuse_everything(self):
        for extra in ('unknown', '1.0.0', '01.0', '1.2-other', '1..0', 'payloads-sibling'):
            with self.subTest(extra=extra):
                root, _, _ = self.tree()
                (root / extra).mkdir()
                plan = plan_payload_cleanup(root, '1.2')
                self.assertTrue(plan.reason)
                self.assertEqual(plan.candidates, ())
                self.assertEqual(execute_payload_cleanup(plan).deleted, ())
                self.assertTrue((root / '1.0').exists())
        root, _, _ = self.tree()
        for current in ('1.3', '../1.2', '1.2/../1.0', '1.02', ''):
            self.assertTrue(plan_payload_cleanup(root, current).reason)

    def test_forged_sibling_or_traversal_plan_and_wrong_root(self):
        root, workspace, sibling = self.tree()
        for path in (sibling, root / '..' / 'MarkAuto'):
            forged = CleanupPlan(root, '1.2', (path,))
            self.assertEqual(execute_payload_cleanup(forged).deleted, ())
        self.assertTrue(plan_payload_cleanup(workspace, '1.2').reason)
        self.assertTrue(plan_payload_cleanup(root / '..' / 'payloads', '1.2').reason)
        with patch.dict(os.environ, {'LOCALAPPDATA': str(workspace.parent)}):
            nested = workspace / 'payloads'
            nested.mkdir()
            self.assertEqual(plan_payload_cleanup(nested, '1.2').reason, 'user_workspace')

    def test_changed_plan_and_permission_error(self):
        root, _, _ = self.tree()
        plan = plan_payload_cleanup(root, '1.2')
        (root / '1.0' / 'new-file').write_bytes(b'changed')
        self.assertEqual(execute_payload_cleanup(plan).deleted, ())
        with patch('quantlab.payload_cleanup.Path.lstat', side_effect=PermissionError('denied')):
            refused = plan_payload_cleanup(root, '1.2')
        self.assertEqual(refused.candidates, ())
        self.assertEqual(refused.reason, 'filesystem_error')

    def test_links_and_simulated_windows_reparse_refuse_without_following(self):
        root, _, sibling = self.tree()
        original = Path.lstat

        def reparse(path):
            info = original(path)
            if path == root / '1.0':
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, 'lstat', reparse):
            self.assertEqual(plan_payload_cleanup(root, '1.2').reason, 'unsafe_link')
        # Windows symlink privilege may be absent; simulated reparse coverage above is unconditional.
        for path in (root / '1.0' / 'escape', root / '1.0' / 'unique-attempt' / 'escape'):
            try:
                path.symlink_to(sibling, target_is_directory=True)
            except OSError:
                continue
            try:
                self.assertEqual(plan_payload_cleanup(root, '1.2').reason, 'unsafe_link')
            finally:
                path.unlink()
        self.assertEqual((sibling / 'sentinel').read_bytes(), b'keep')

    def test_link_introduced_after_planning_and_rmtree_failure_stop(self):
        root, _, _ = self.tree(('0.8', '1.0', '1.1', '1.2'))
        plan = plan_payload_cleanup(root, '1.2')
        original = Path.lstat

        def reparse(path):
            info = original(path)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == root / '0.8' else info

        with patch.object(Path, 'lstat', reparse), patch('quantlab.payload_cleanup.shutil.rmtree') as removed:
            self.assertEqual(execute_payload_cleanup(plan).deleted, ())
            removed.assert_not_called()

        def fail(path, *, onerror):
            onerror(os.unlink, str(path), (PermissionError, PermissionError('denied'), None))

        with patch('quantlab.payload_cleanup.shutil.rmtree', side_effect=fail) as removed:
            result = execute_payload_cleanup(plan)
            self.assertEqual(result.reason, 'delete_failed')
            self.assertEqual(result.deleted, ())
            removed.assert_called_once()


class UpdateCheckTests(OfflineTest):
    def check(self, body, digest=None, **kwargs):
        return check_for_update('1.2', transport=lambda url: (body, hashlib.sha256(body).hexdigest() if digest is None else digest), **kwargs)

    def test_update_equal_and_older(self):
        for version, status in (('1.3', 'update_available'), ('1.2.0', 'up_to_date'), ('1.1', 'up_to_date')):
            result = self.check(json.dumps({'version': version}).encode())
            self.assertEqual(result, UpdateResult(status, status, version))
        body = b'{"version":"1.3"}'
        self.assertEqual(self.check(body, hashlib.sha256(body).hexdigest() + '  release-manifest.json\n').status, 'update_available')

    def test_missing_mismatched_hash_never_parses_json(self):
        for digest in ('', 'a' * 64, 'missing', b'a' * 64, 'a' * 257):
            with self.subTest(digest=digest), patch('quantlab.update_check.json.loads') as loads:
                self.assertEqual(self.check(b'{"version":"1.3"}', digest).status, 'error')
                loads.assert_not_called()

    def test_bad_json_versions_and_size(self):
        for body in (b'{', b'[]', b'null', b'{}', b'\xff', b'{"version":3}', b'{"version":"v1.3"}', b'{"version":"1.3-beta"}', b'x' * (MAX_BODY + 1)):
            with self.subTest(body=body[:32]):
                self.assertEqual(self.check(body).status, 'error')
        with patch('quantlab.update_check._default_transport') as transport:
            self.assertEqual(check_for_update('../1.2').status, 'error')
            self.assertEqual(check_for_update('1.2', url='http://example.com').status, 'error')
            transport.assert_not_called()

    def test_network_error_is_fixed_code_and_https_downgrade_is_refused(self):
        with patch('quantlab.update_check._default_transport', side_effect=OSError('private diagnostic')):
            self.assertEqual(check_for_update('1.2'), UpdateResult('error', 'check_failed'))
        with self.assertRaises(ValueError):
            _HTTPSRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com')

    def test_default_transport_two_bounded_https_requests_with_verified_context(self):
        body = b'{"version":"1.3"}'
        digest = hashlib.sha256(body).hexdigest().encode()
        calls = []

        class Response:
            def __init__(self, data, url):
                self.data, self.url = data, url

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return self.url

            def read(self, limit):
                calls.append(limit)
                return self.data[:limit]

        def fetch(opener, request, *, timeout):
            self.assertEqual(timeout, 8)
            self.assertEqual(opener.addheaders, [('User-Agent', 'ReleaseMetadataCheck/1.0')])
            return Response(digest if request.full_url.endswith('.sha256') else body, request.full_url)

        context = object()
        opener = SimpleNamespace(addheaders=[])
        with (
            patch('quantlab.update_check.build_trust_context', return_value=context) as trust,
            patch('quantlab.update_check.HTTPSHandler') as handler,
            patch('quantlab.update_check.build_opener', return_value=opener),
            patch('quantlab.update_check._fetch_response', side_effect=fetch),
        ):
            self.assertEqual(check_for_update('1.2').status, 'update_available')
            trust.assert_called_once_with()
            handler.assert_called_once_with(context=context)
        self.assertEqual(calls, [MAX_BODY + 1, 257])

    def test_ast_has_no_file_installer_browser_or_process_operations(self):
        tree = ast.parse((ROOT / 'quantlab/update_check.py').read_text(encoding='utf-8'))
        forbidden = {'open', 'write', 'write_text', 'write_bytes', 'startfile', 'system', 'Popen', 'run', 'urlretrieve'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
                self.assertNotIn(name, forbidden)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module]
                self.assertFalse({'subprocess', 'webbrowser', 'os'}.intersection(names))


class MaintenanceUITests(OfflineTest):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def panel(self):
        panel = MaintenancePanel()
        self.addCleanup(panel.deleteLater)
        return panel

    def test_page_and_window_construction_never_checks(self):
        from desktop_app.shell.main_window import MainWindow  # Exercise the actual settings mounting path.
        from quantlab.desktop_runtime import AppPaths, JobManager  # Disposable workspace only.

        paths = AppPaths(self.temp() / 'workspace').ensure()
        jobs = JobManager(paths)
        self.addCleanup(jobs.close)
        with patch('desktop_app.features.settings.maintenance.check_for_update') as checked:
            panel = self.panel()
            window = MainWindow(paths, jobs)
            for timer in window.findChildren(QTimer):
                timer.stop()
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
            self.assertIsInstance(window.settings_page.maintenance_panel, MaintenancePanel)
            page = window.settings_page
            window.navigation.setCurrentRow(6)
            window.show()
            self.app.processEvents()
            self.assertFalse(page.maintenance_panel.update_button.isVisibleTo(page))
            buttons = [button for button in page.findChildren(QPushButton) + page.findChildren(QToolButton) if button.isVisibleTo(page)]
            self.assertLessEqual(len(buttons), 8)
            page.maintenance_toggle.setChecked(True)
            self.assertTrue(page.maintenance_panel.update_button.isVisibleTo(page))
            self.assertTrue(page.maintenance_panel.cleanup_button.isVisibleTo(page))
            self.assertFalse(panel.timer.isActive())
            checked.assert_not_called()

    def test_user_click_disables_button_and_poll_renders_fixed_result(self):
        panel = self.panel()
        with patch('desktop_app.features.settings.maintenance.Thread') as thread:
            panel.update_button.click()
            thread.return_value.start.assert_called_once()
            self.assertFalse(panel.update_button.isEnabled())
            panel.check_updates()
            thread.return_value.start.assert_called_once()
        panel.results.put(UpdateResult('update_available', 'update_available', '9.0'))
        panel.poll_update()
        self.assertTrue(panel.update_button.isEnabled())
        self.assertEqual(panel.status.text(), ui_text('maintenance.available').format('9.0'))

    def test_cleanup_confirmation_is_default_no_and_required(self):
        parent = self.temp()
        root = parent / 'payloads'
        for version in ('0.1', '0.2', '0.2.2'):
            (root / version / 'unique').mkdir(parents=True)
        panel = self.panel()
        with patch('desktop_app.features.settings.maintenance.installed_payload_root', return_value=root):
            with patch('desktop_app.features.settings.maintenance.QMessageBox.question', return_value=QMessageBox.No) as question:
                panel.cleanup_button.click()
                self.assertEqual(question.call_args.args[-1], QMessageBox.No)
                self.assertIn('0.1', question.call_args.args[2])
                self.assertTrue((root / '0.1').exists())
            with patch('desktop_app.features.settings.maintenance.QMessageBox.question', return_value=QMessageBox.Yes):
                panel.cleanup_button.click()
                self.assertFalse((root / '0.1').exists())
                self.assertTrue((root / '0.2').exists())
                self.assertTrue((root / '0.2.2').exists())

    def test_development_and_wrong_executable_path_cannot_offer_deletion(self):
        with patch('desktop_app.features.settings.maintenance.sys.frozen', False, create=True):
            self.assertIsNone(installed_payload_root())
        with (
            patch('desktop_app.features.settings.maintenance.sys.frozen', True, create=True),
            patch.dict(os.environ, {'LOCALAPPDATA': str(self.temp())}),
        ):
            self.assertIsNone(installed_payload_root())


class DeveloperWorkspaceTests(unittest.TestCase):
    def test_notice_no_new_imports_and_packaging_exclusion(self):
        tree = ast.parse((ROOT / 'tools' / 'research_app.py').read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        notice = main.body[2]
        self.assertIsInstance(notice, ast.Expr)
        self.assertEqual(ast.unparse(notice.value.func), 'st.info')
        self.assertEqual(notice.value.args[0].value, 'This is a developer research workspace; the desktop app is the product.')
        imports = [ast.unparse(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual(
            imports,
            [
                'from pathlib import Path',
                'import json',
                'import os',
                'import sqlite3',
                'import streamlit as st',
                'from quantlab.core import canonical_json, content_hash, to_dict, ValidationError',
                'from quantlab.reporting import synthetic_dataset, demo_config, save_dataset, load_dataset, load_result, export_report, comparison_rows, read_json, write_json, save_selection, load_selection',
                'from quantlab.__main__ import config_from_json',
            ],
        )
        manifest = ast.parse((ROOT / 'packaging/build_manifest.py').read_text(encoding='utf-8'))
        patterns = next(
            node.iter
            for node in ast.walk(manifest)
            if isinstance(node, ast.comprehension) and isinstance(node.target, ast.Name) and node.target.id == 'pattern'
        )
        inventory = {path.name for pattern in ast.literal_eval(patterns) for path in ROOT.glob(pattern) if path.is_file()}
        self.assertNotIn('research_app.py', inventory)
        for name in ('packaging/markauto.spec', 'packaging/markauto.iss'):
            self.assertNotIn('research_app', (ROOT / name).read_text(encoding='utf-8').lower())
