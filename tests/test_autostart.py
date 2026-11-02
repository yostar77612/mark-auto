"""Startup registration uses private HKCU test keys, never the user's Run key."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from quantlab import autostart
from quantlab.autostart import AutostartError, RunAutostart


@unittest.skipIf(autostart.winreg is None, 'Windows registry required')
class RunAutostartTests(unittest.TestCase):
    def setUp(self):
        self.registry = autostart.winreg
        self.key_path = rf'Software\MarkAuto\Tests\Autostart\{uuid4().hex}'
        self.controller = RunAutostart(Path('C:/Mark Auto/payloads/current/MarkAuto.exe'), key_path=self.key_path)
        self.addCleanup(self.remove_test_key)

    def remove_test_key(self):
        try:
            self.registry.DeleteKey(self.registry.HKEY_CURRENT_USER, self.key_path)
        except FileNotFoundError:
            pass

    def test_default_off_does_not_create_key(self):
        self.assertNotEqual(self.key_path, autostart.RUN_KEY_PATH)
        self.assertFalse(self.controller.enabled())
        self.assertFalse(self.controller.repair_enabled())
        with self.assertRaises(FileNotFoundError):
            self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, self.key_path)

    def test_enable_quotes_only_executable_under_hkcu(self):
        with patch.object(self.registry, 'CreateKeyEx', wraps=self.registry.CreateKeyEx) as create:
            self.controller.set_enabled(True)
        self.assertEqual(create.call_args.args[0], self.registry.HKEY_CURRENT_USER)
        self.assertEqual(create.call_args.args[1], self.key_path)
        with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, self.key_path) as key:
            value, kind = self.registry.QueryValueEx(key, 'MarkAuto')
        self.assertEqual(value, f'"{self.controller.executable}"')
        self.assertEqual(kind, self.registry.REG_SZ)
        self.assertTrue(self.controller.enabled())

    def test_disable_removes_only_owned_value(self):
        self.controller.set_enabled(True)
        with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, self.key_path, 0, self.registry.KEY_SET_VALUE) as key:
            self.registry.SetValueEx(key, 'OtherApp', 0, self.registry.REG_SZ, 'preserve')
        self.controller.set_enabled(False)
        self.assertFalse(self.controller.enabled())
        with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, self.key_path) as key:
            self.assertEqual(self.registry.QueryValueEx(key, 'OtherApp')[0], 'preserve')
        self.controller.set_enabled(False)

    def test_disable_missing_key_is_idempotent(self):
        self.controller.set_enabled(False)
        self.assertFalse(self.controller.enabled())

    def test_repair_follows_updated_or_moved_executable(self):
        self.controller.set_enabled(True)
        replacement = RunAutostart(Path('C:/Moved Mark Auto/payloads/new/MarkAuto.exe'), key_path=self.key_path)
        self.assertTrue(replacement.repair_enabled())
        with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, self.key_path) as key:
            self.assertEqual(self.registry.QueryValueEx(key, 'MarkAuto'), (replacement.command, self.registry.REG_SZ))

    def test_correct_registration_has_no_write(self):
        self.controller.set_enabled(True)
        with patch.object(self.registry, 'SetValueEx') as write:
            self.assertTrue(self.controller.repair_enabled())
        write.assert_not_called()

    def test_read_access_error_is_specific(self):
        with patch.object(self.registry, 'OpenKey', side_effect=PermissionError('private detail')):
            with self.assertRaises(AutostartError) as caught:
                self.controller.enabled()
        self.assertEqual(caught.exception.code, 'autostart_read_failed')
        self.assertNotIn('private detail', str(caught.exception))

    def test_query_error_is_not_treated_as_disabled(self):
        self.controller.set_enabled(True)
        with patch.object(self.registry, 'QueryValueEx', side_effect=OSError('query denied')):
            with self.assertRaises(AutostartError) as caught:
                self.controller.repair_enabled()
        self.assertEqual(caught.exception.code, 'autostart_read_failed')

    def test_create_error_is_specific(self):
        with patch.object(self.registry, 'CreateKeyEx', side_effect=PermissionError('denied')):
            with self.assertRaises(AutostartError) as caught:
                self.controller.set_enabled(True)
        self.assertEqual(caught.exception.code, 'autostart_write_failed')

    def test_write_error_is_specific(self):
        with patch.object(self.registry, 'SetValueEx', side_effect=PermissionError('denied')):
            with self.assertRaises(AutostartError) as caught:
                self.controller.set_enabled(True)
        self.assertEqual(caught.exception.code, 'autostart_write_failed')

    def test_delete_error_preserves_registration(self):
        self.controller.set_enabled(True)
        with patch.object(self.registry, 'DeleteValue', side_effect=PermissionError('denied')):
            with self.assertRaises(AutostartError) as caught:
                self.controller.set_enabled(False)
        self.assertEqual(caught.exception.code, 'autostart_remove_failed')
        self.assertTrue(self.controller.enabled())


class InstalledAutostartTests(unittest.TestCase):
    def test_source_run_never_registers_python(self):
        with patch.object(autostart.sys, 'frozen', False, create=True):
            self.assertIsNone(autostart.installed_autostart())

    def test_non_windows_has_no_registry_side_effect(self):
        with patch.object(autostart, 'winreg', None), patch.object(autostart.sys, 'frozen', True, create=True):
            self.assertIsNone(autostart.installed_autostart())

    def test_frozen_other_executable_is_not_registered(self):
        with (
            patch.object(autostart, 'winreg', object()),
            patch.object(autostart.sys, 'frozen', True, create=True),
            patch.object(autostart.sys, 'executable', 'C:/App/python.exe'),
        ):
            self.assertIsNone(autostart.installed_autostart())

    def test_frozen_markauto_points_to_running_installation(self):
        with (
            patch.object(autostart, 'winreg', object()),
            patch.object(autostart.sys, 'frozen', True, create=True),
            patch.object(autostart.sys, 'executable', 'C:/App/MarkAuto.exe'),
        ):
            controller = autostart.installed_autostart()
        self.assertEqual(controller.executable, Path('C:/App/MarkAuto.exe').resolve())
        self.assertEqual(controller.key_path, r'Software\Microsoft\Windows\CurrentVersion\Run')

    def test_startup_repairs_only_existing_opt_in(self):
        controller = Mock()
        with patch.object(autostart, 'installed_autostart', return_value=controller):
            self.assertIsNone(autostart.repair_autostart())
        controller.repair_enabled.assert_called_once_with()
        controller.set_enabled.assert_not_called()

    def test_startup_failure_returns_fixed_code_without_breaking_startup(self):
        controller = SimpleNamespace(repair_enabled=Mock(side_effect=AutostartError('autostart_write_failed')))
        with patch.object(autostart, 'installed_autostart', return_value=controller):
            self.assertEqual(autostart.repair_autostart(), 'autostart_write_failed')


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt required')
class AutostartPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def panel(self, *, enabled=False, error=None):
        from desktop_app.features.settings.autostart_panel import AutostartPanel

        controller = Mock()
        controller.repair_enabled.return_value = enabled
        if error:
            controller.repair_enabled.side_effect = AutostartError(error)
        panel = AutostartPanel(controller=controller)
        self.addCleanup(panel.deleteLater)
        return panel, controller

    def test_checkbox_defaults_off_and_does_not_enable(self):
        panel, controller = self.panel()
        self.assertFalse(panel.enabled.isChecked())
        controller.set_enabled.assert_not_called()
        self.assertIn('睡眠', panel.hint.text())
        self.assertIn('關機', panel.hint.text())

    def test_toggle_writes_and_removes_only_on_user_action(self):
        panel, controller = self.panel()
        panel.enabled.setChecked(True)
        controller.set_enabled.assert_called_once_with(True)
        panel.enabled.setChecked(False)
        self.assertEqual(controller.set_enabled.call_args_list[-1].args, (False,))

    def test_existing_opt_in_is_repaired_and_shown(self):
        panel, controller = self.panel(enabled=True)
        self.assertTrue(panel.enabled.isChecked())
        controller.repair_enabled.assert_called_once_with()
        controller.set_enabled.assert_not_called()

    def test_write_error_reverts_checkbox_with_specific_error(self):
        panel, controller = self.panel()
        controller.set_enabled.side_effect = AutostartError('autostart_write_failed')
        panel.enabled.setChecked(True)
        self.assertFalse(panel.enabled.isChecked())
        self.assertIn('autostart_write_failed', panel.async_status.label.text())

    def test_remove_error_preserves_checked_state(self):
        panel, controller = self.panel(enabled=True)
        controller.set_enabled.side_effect = AutostartError('autostart_remove_failed')
        panel.enabled.setChecked(False)
        self.assertTrue(panel.enabled.isChecked())
        self.assertIn('autostart_remove_failed', panel.async_status.label.text())

    def test_read_error_disables_control_with_specific_error(self):
        panel, _ = self.panel(error='autostart_read_failed')
        self.assertFalse(panel.enabled.isEnabled())
        self.assertIn('autostart_read_failed', panel.async_status.label.text())

    def test_source_preview_cannot_register(self):
        from desktop_app.features.settings.autostart_panel import AutostartPanel

        self.app.setProperty('autostartController', None)
        panel = AutostartPanel()
        self.addCleanup(panel.deleteLater)
        self.assertFalse(panel.enabled.isEnabled())
        self.assertFalse(panel.enabled.isChecked())

    def test_offline_preview_toggle_has_no_side_effect(self):
        panel, controller = self.panel()
        panel.setProperty('offlinePreview', True)
        panel.enabled.setChecked(True)
        self.assertFalse(panel.enabled.isChecked())
        controller.set_enabled.assert_not_called()
