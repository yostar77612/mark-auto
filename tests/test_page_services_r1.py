"""R1 additive contract: AST inventory, mock equivalence and real offscreen binding."""

import ast
from dataclasses import FrozenInstanceError, fields
import inspect
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton
import shiboken6

import desktop_ui as ui
from desktop_pages.bindings import HostMethod, PageContext, StateField
from desktop_pages.host import PageServices, _page_services
from desktop_pages import mount
from desktop_pages.mount import _register_shell_callbacks
from quantlab.core import ValidationError
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore
from tests.page_services_inventory import ROOT, FIXTURE, callback_reads, inventory, reviewed_inventory, tree
from tests.test_t9_onboarding import sandbox_ui

BASE = json.loads(FIXTURE.read_text(encoding='utf-8'))
SERVICES = BASE['services']
NAMES = [entry['name'] for entry in SERVICES]


class InventoryTests(unittest.TestCase):
    def test_complete_inventory_regenerates_exactly(self):
        delta = json.loads((ROOT / 'tests/fixtures/download_auto_import_ui_delta.json').read_text(encoding='utf-8'))
        self.assertEqual(inventory(), reviewed_inventory(BASE, delta['inventory']))
        self.assertEqual(len(NAMES), len(set(NAMES)))
        self.assertEqual(sum(s['origin'] == 'mount' for s in SERVICES), 66)
        self.assertEqual(sum(s['origin'] == 'page_services' for s in SERVICES), 14)
        self.assertEqual(len(BASE['aliases']), 130)
        self.assertEqual(len(BASE['state_copies']), 84)

    def test_type_members_and_annotations_match_source(self):
        node = next(n for n in tree('desktop_pages/host.py').body if isinstance(n, ast.ClassDef) and n.name == 'PageServices')
        declarations = [n.target.id for n in node.body if isinstance(n, ast.AnnAssign)]
        self.assertEqual(declarations, NAMES)
        self.assertEqual([field.name for field in fields(PageServices)], NAMES)
        for field in fields(PageServices):
            self.assertIsNotNone(field.type)

    def test_every_host_method_and_callback_read_has_a_service(self):
        for path in (ROOT / 'desktop_pages').glob('*.py'):
            for name, kind in callback_reads(path.relative_to(ROOT)):
                with self.subTest(module=path.name, name=name, kind=kind):
                    self.assertIn(name, NAMES)

    def test_no_desktop_pages_module_imports_desktop_ui(self):
        for path in (ROOT / 'desktop_pages').glob('*.py'):
            for node in ast.walk(tree(path.relative_to(ROOT))):
                if isinstance(node, ast.Import):
                    self.assertNotIn('desktop_ui', [alias.name for alias in node.names])
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'desktop_ui')

    def test_main_window_stays_within_budget(self):
        node = next(n for n in tree('desktop_ui.py').body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
        self.assertLessEqual(node.end_lineno - node.lineno + 1, 400)


class MockEquivalenceTests(unittest.TestCase):
    def test_every_service_has_identical_late_target_arguments_and_result(self):
        # All 80 keys; module services retain their actual MainWindow factory.
        shell = SimpleNamespace(page_host=SimpleNamespace(callbacks={}))
        shell.page_services = lambda: ui.MainWindow.page_services(shell)
        for entry in SERVICES:
            if entry['origin'] == 'mount':
                setattr(shell, entry['name'], Mock(side_effect=AssertionError('early target')))
        _register_shell_callbacks(shell)
        typed = _page_services(shell)
        self.assertEqual(list(shell.page_host.callbacks), NAMES)
        self.assertEqual(set(vars(typed)), set(shell.page_host.callbacks))
        self.assertIsInstance(typed, PageServices)
        with self.assertRaises(FrozenInstanceError):
            typed._safe = Mock()
        for entry in SERVICES:
            name = entry['name']
            with self.subTest(service=name):
                if not entry['variadic']:
                    self.assertIs(getattr(typed, name), shell.page_host.callbacks[name])
                    self.assertIs(getattr(typed, name), ui.UI_OPERATIONS)
                    continue
                result, first, second = object(), object(), object()
                receiver = shell if entry['origin'] == 'mount' else ui
                target = entry['target'].removeprefix('shell.')
                with patch.object(receiver, target, Mock(return_value=result)) as recording:
                    for callback in (shell.page_host.callbacks[name], getattr(typed, name)):
                        self.assertIs(callback(first, second, flag=first), result)
                    self.assertEqual(recording.call_count, 2)
                    self.assertEqual(recording.call_args_list[0], recording.call_args_list[1])
                    recording.assert_called_with(first, second, flag=first)

    def test_host_method_prefers_host_then_falls_back_and_preserves_key_error(self):
        direct, fallback = Mock(), Mock()
        page = PageContext()
        page.setup_context(SimpleNamespace(state=SimpleNamespace(), callbacks={'service': fallback}, service=direct))
        descriptor = HostMethod('service')
        self.assertIs(descriptor.__get__(page), direct)
        del page.host.service
        self.assertIs(descriptor.__get__(page), fallback)
        page.host.service = None
        self.assertIs(descriptor.__get__(page), fallback)
        with self.assertRaises(KeyError) as caught:
            HostMethod('unknown').__get__(page)
        self.assertEqual(caught.exception.args, ('unknown',))
        self.assertEqual(str(caught.exception), "'unknown'")

    def test_state_field_preserves_set_delete_and_class_access(self):
        class Page(PageContext):
            value = StateField()

        page = Page()
        page.setup_context(SimpleNamespace(state=SimpleNamespace(value=1)))
        self.assertIsInstance(Page.value, StateField)
        self.assertEqual(page.value, 1)
        page.value = 2
        self.assertEqual(page.state.value, 2)
        del page.value
        self.assertFalse(hasattr(page.state, 'value'))

    def test_bare_shell_state_copies_do_not_follow_later_alias_assignment(self):
        # Existing consumers also build namespace hosts without MainWindow's
        # StateField descriptors: their one-time copies must remain copies.
        shell = SimpleNamespace(page_host=SimpleNamespace(state=SimpleNamespace()))
        aliases = [a for a in BASE['aliases'] if a['page'] == 'data_page']
        page = SimpleNamespace(**{a['attribute']: Mock(name=a['attribute']) for a in aliases})
        with patch.object(mount, 'DataPage', return_value=page):
            mount._mount_data_page(shell)
        for alias in aliases:
            name = alias['name']
            with self.subTest(alias=name):
                original = getattr(shell.page_host.state, name)
                with patch.object(shell, name, object()):
                    self.assertIs(getattr(shell.page_host.state, name), original)
                    self.assertIs(getattr(page, alias['attribute']), original)


class RealWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.context = sandbox_ui()
        cls.context.__enter__()
        cls.temp = tempfile.TemporaryDirectory(prefix='page-services-r1-')
        cls.paths = AppPaths(Path(cls.temp.name) / 'workspace').ensure()
        cls.jobs = JobManager(cls.paths)
        cls.window = ui.MainWindow(cls.paths, cls.jobs, SettingsStore(cls.paths.state / 'settings.json'))
        # One startup walk, no recurring timer traversal or event loop.
        for timer in cls.window.findChildren(QTimer):
            timer.stop()
        cls.typed = _page_services(cls.window)

    @classmethod
    def tearDownClass(cls):
        cls.jobs.close()
        cls.window.close()
        shiboken6.delete(cls.window)
        del cls.typed, cls.window
        cls.temp.cleanup()
        cls.context.__exit__(None, None, None)

    def test_runtime_member_set_and_registry_identity(self):
        self.assertEqual(set(vars(self.typed)), set(self.window.page_host.callbacks))
        self.assertEqual(list(self.window.page_host.callbacks), NAMES)
        self.assertEqual([f.name for f in fields(type(self.typed))], NAMES)
        self.assertIs(self.typed.ui_operations, ui.UI_OPERATIONS)
        self.assertIs(self.typed.ui_operations, self.window.page_host.callbacks['ui_operations'])
        before = list(ui._UI_OPERATION_HANDLERS.items())
        _page_services(self.window)
        self.assertEqual(list(ui._UI_OPERATION_HANDLERS.items()), before)
        self.assertTrue(all(ui._UI_OPERATION_HANDLERS[key] is value for key, value in before))

    def test_each_patch_sensitive_service_is_observed_after_mount(self):
        page = self.window.paper_page
        for entry in SERVICES:
            if not entry['patch_sensitive'] or not entry['variadic']:
                continue
            name = entry['name']
            with self.subTest(service=name):
                receiver = self.window if entry['origin'] == 'mount' else ui
                target = entry['target'].removeprefix('shell.')
                with patch.object(receiver, target, Mock(return_value='patched')) as replacement:
                    # Exercise the same binding used by page code and the opt-in view.
                    observed = HostMethod(name).__get__(page) if entry['origin'] == 'mount' else page.host.callbacks[name]
                    self.assertEqual(observed('synthetic', flag=True), 'patched')
                    self.assertEqual(getattr(self.typed, name)('synthetic', flag=True), 'patched')
                    self.assertEqual(replacement.call_count, 2)

    def test_every_alias_keeps_base_ownership_and_statefield_patch_behavior(self):
        w = self.window
        for alias in BASE['aliases']:
            name = alias['name']
            with self.subTest(alias=name, patch_sensitive=alias['patch_sensitive']):
                page = getattr(w, alias['page'])
                original = getattr(w, name)
                page_value = getattr(page, alias['attribute']) if alias['attribute'] else page
                self.assertEqual(original, page_value)
                copied = [copy for copy in BASE['state_copies'] if copy['source'] == 'shell.' + name]
                before = {copy['name']: getattr(w.page_state, copy['name']) for copy in copied}
                replacement = Mock(name=name)
                with patch.object(w, name, replacement):
                    self.assertEqual(getattr(page, alias['attribute']) if alias['attribute'] else page, page_value)
                    for key, value in before.items():
                        follows = isinstance(inspect.getattr_static(type(w), name, None), StateField)
                        expected = replacement if follows else value
                        self.assertIs(getattr(w.page_state, key), expected)
                        if isinstance(getattr(PageContext, key, None), StateField):
                            self.assertIs(getattr(w.views_page, key), expected)

    def test_five_post_mount_patch_paths_from_page_code(self):
        w = self.window
        with patch.object(w, '_safe') as safe:
            w.findChild(QPushButton, 'create_demo').click()
            safe.assert_called_once()
        with patch.object(w, 'start_job', return_value='mock-job') as start:
            w.findChild(QPushButton, 'create_demo').click()
            start.assert_called_once_with('ui_demo', {'bars': w.data_page.bars.value()})
        with patch.object(w, 'freeze_paper') as freeze:
            w.views_page.freeze_paper('synthetic')
            freeze.assert_called_once_with('synthetic')
        with patch.object(w, '_button', return_value='mock-button') as button:
            self.assertEqual(w.compare_page._button('layout', 'label', 'name', 'callback'), 'mock-button')
            button.assert_called_once_with('layout', 'label', 'name', 'callback')
        with patch.object(w, '_busy') as busy:
            # _busy has no current page reader; test its registered host seam.
            HostMethod('_busy').__get__(w.views_page)(True)
            self.typed._busy(False)
            self.assertEqual(busy.call_count, 2)

    def test_single_job_slot_matches_base_with_real_manager_and_mock_launcher(self):
        w, jobs = self.window, self.jobs

        def launch(operation, payload, job_id, *args):
            jobs.process = Mock(name='offline-process')
            jobs.job_id = job_id

        # Actual MainWindow and JobManager gates; only process creation is mocked.
        for first, second in ((w.page_host.callbacks['start_job'], self.typed.start_job), (self.typed.start_job, w.page_host.callbacks['start_job'])):
            with self.subTest(first=first):
                with patch.object(jobs, '_launch_job_process', side_effect=launch) as launcher, patch.object(jobs, 'start', wraps=jobs.start) as start:
                    try:
                        first('ui_demo', {'bars': 100})
                        self.assertTrue(jobs.active)
                        with self.assertRaises(ValidationError) as refused:
                            second('ui_demo', {'bars': 100})
                        self.assertEqual(str(refused.exception), ui.ui_text('ui.start_job.job_busy'))
                        start.assert_called_once_with('ui_demo', {'bars': 100})
                        self.assertEqual(launcher.call_count, 1)
                    finally:
                        jobs.process = None
                        w._ui_job_id = None
                        w._busy(False)

    def test_state_has_no_shell_reference_or_new_shell_bound_method(self):
        for name, value in vars(self.window.page_state).items():
            with self.subTest(state=name):
                self.assertIsNot(value, self.window)
                self.assertFalse(inspect.ismethod(value) and value.__self__ is self.window)


if __name__ == '__main__':
    unittest.main()
