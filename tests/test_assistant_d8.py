"""Offline permission menus, restart downgrade and immutable read boundary."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from desktop_pages.assistant_permissions import MODES, SETTING_KEY, ResearchPermission, install_menu
from desktop_strings import ui_text
from quantlab.agent_tools import Registry
from quantlab.desktop_runtime import SettingsStore
from tests import test_assistant_d4 as d4
from tests.test_agent_harness_d1 import REFUSAL, assert_no_protected_values, declaration


ROOT = Path(__file__).resolve().parents[1]


def mutation():
    value = declaration(name='fake_mutation', effect='mutation', capability='research.run')
    value['inputSchema'] = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['idempotency_key'],
        'properties': {'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 128}},
    }
    return value


class AssistantD8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d4.AssistantD4Tests.setUpClass()

    def setUp(self):
        self.fixture = d4.AssistantD4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.panel = self.fixture.panel

    def test_two_synchronized_keyboard_menus_and_release_scope(self):
        other = QWidget()
        self.addCleanup(other.deleteLater)
        mirror = install_menu(QVBoxLayout(other), self.panel.permissions, 'settings_research_permission')
        for menu in (self.panel.permission_menu, mirror):
            self.assertEqual(menu.count(), 2)
            self.assertEqual([menu.itemData(i) for i in range(2)], list(MODES))
            self.assertEqual([menu.itemText(i) for i in range(2)], [ui_text('assistant.permission_read'), ui_text('assistant.permission_confirm')])
            self.assertEqual(menu.currentData(), 'read_only')
            self.assertEqual(menu.accessibleName(), ui_text('assistant.permission_label'))
            self.assertIn('\u4ecd\u50c5\u5141\u8a31\u552f\u8b80\u5de5\u5177', menu.accessibleDescription())
            self.assertNotEqual(menu.focusPolicy(), Qt.FocusPolicy.NoFocus)
        QTest.keyClick(self.panel.permission_menu, Qt.Key.Key_Down)
        self.assertEqual(mirror.currentData(), 'confirm_each_time')
        self.assertEqual(self.panel.dispatcher.permission, 'confirm_each_time')
        QTest.keyClick(mirror, Qt.Key.Key_Up)
        self.assertEqual(self.panel.permission_menu.currentData(), 'read_only')
        # Both real installations remain inside already collapsed areas.
        source = (ROOT / 'desktop_pages/settings_layout.py').read_text(encoding='utf-8')
        self.assertIn("install_menu(management, page.assistant_panel.permissions, 'settings_research_permission')", source)
        self.assertIn('maintenance.addWidget(page.assistant_panel)', source)

    def test_real_persistence_restart_unknown_corrupt_and_legacy_keys(self):
        folder = ROOT / ('.tmp-d8-' + uuid4().hex)
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder)
        store = SettingsStore(folder / 'settings.json')
        legacy = {'persist_logs': False, 'market': {'existing': True}, 'provider': 'inert'}
        store.save(legacy)
        state = ResearchPermission(store)
        state.select('confirm_each_time')
        self.assertEqual(store.load(), {**legacy, SETTING_KEY: 'confirm_each_time'})
        self.assertEqual(state.mode, 'confirm_each_time')
        self.assertEqual(ResearchPermission(SettingsStore(store.path)).mode, 'read_only')
        for value in (None, {}, [], 1, 'unknown', 'confirm_each_time'):
            store.save({**legacy, SETTING_KEY: value})
            self.assertEqual(ResearchPermission(store).mode, 'read_only')
        store.path.write_text('{broken', encoding='utf-8')
        fresh = ResearchPermission(store)
        self.assertEqual(fresh.mode, 'read_only')
        fresh.select('confirm_each_time')
        self.assertEqual(fresh.mode, 'read_only')
        self.assertTrue(fresh.error)
        self.assertEqual(store.path.read_text(encoding='utf-8'), '{broken')
        for host in (None, SimpleNamespace(), SimpleNamespace(load=None, save=None)):
            bare = ResearchPermission(host)
            bare.select('confirm_each_time')
            self.assertEqual(bare.mode, 'confirm_each_time')
            bare.select({'unknown': True})
            self.assertEqual(bare.mode, 'read_only')

    def test_fake_mutation_never_runs_consent_is_per_attempt_and_registry_freezes(self):
        registry = Registry()
        handler = Mock()
        self.assertEqual(registry.register(mutation(), handler), {'ok': True})
        registry.freeze()
        self.assertEqual(registry.register({**mutation(), 'name': 'later_mutation'}, handler), REFUSAL)
        dispatcher = self.panel.dispatcher
        dispatcher._ChatDispatcher__registry = registry
        with patch('desktop_pages.assistant.QMessageBox.question') as dialog:
            from PySide6.QtWidgets import QMessageBox

            dialog.side_effect = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok]
            # Use the existing dialog, not a test-only consent route.
            self.panel.ask_consent = self.panel._consent
            self.assertEqual(dispatcher.call('fake_mutation', '{"idempotency_key":"once"}'), REFUSAL)
            dialog.assert_not_called()
            self.panel.permission_menu.setCurrentIndex(1)
            for attempt in range(3):
                self.assertEqual(dispatcher.call('fake_mutation', '{"idempotency_key":"once"}'), REFUSAL)
                self.assertEqual(dialog.call_count, attempt + 1)
                self.assertEqual(dialog.call_args.args[-1], QMessageBox.StandardButton.Cancel)
            self.panel.permission_menu.setCurrentIndex(0)
            self.assertEqual(dispatcher.call('fake_mutation', '{}'), REFUSAL)
            self.assertEqual(dialog.call_count, 3)
        for mode in MODES:
            dispatcher.permission = mode
            self.assertEqual(registry.call('fake_mutation', '{"idempotency_key":"once"}', capabilities=('research.run',)), REFUSAL)
        handler.assert_not_called()

    def test_existing_safety_oracles_in_each_permission_mode(self):
        for index in range(2):
            self.panel.permission_menu.setCurrentIndex(index)
            for oracle in (
                self.fixture.test_exact_frozen_read_surface_and_unknown_names_never_dispatch,
                self.fixture.test_operator_and_quota_entry_points_unreachable,
                self.fixture.test_all_d3_payloads_and_transcript_exclude_protected_values,
                self.fixture.test_network_payload_single_prompt_no_history_and_secret_scan,
            ):
                self.panel._transcript_entries.clear()
                oracle()
            self.panel._transcript_entries.clear()
            self.panel.refresh_transcript()
            self.fixture.test_cancel_consent_has_no_outgoing_request_or_transcript()

    def test_permission_log_has_only_fixed_event_and_mode(self):
        saved = {'credential': 'TOKEN_SENTINEL', 'protected': 'OOS_SENTINEL'}
        store = SimpleNamespace(load=lambda: deepcopy(saved), save=Mock())
        state = ResearchPermission(store)
        with self.assertLogs('desktop_pages.assistant_permissions', level='INFO') as logs:
            state.select('confirm_each_time')
            state.select('read_only')
        self.assertEqual(len(logs.output), 2)
        self.assertIn('assistant_permission_changed mode=confirm_each_time', logs.output[0])
        assert_no_protected_values(self, '\n'.join(logs.output))
        assert_no_protected_values(self, self.panel.transcript.toPlainText())
        self.assertEqual(store.save.call_args.args[0], {**saved, SETTING_KEY: 'read_only'})

    def test_permission_source_catalog_no_extra_authority_or_execution(self):
        forbidden = {'auto', 'always', 'allow-all', 'bypass'}
        paths = ('desktop_pages/assistant_permissions.py', 'desktop_pages/assistant.py', 'quantlab/assistant_chat.py')
        for name in paths:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            values = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            self.assertFalse(forbidden.intersection(value.casefold() for value in values))
            identifiers = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
            self.assertFalse(forbidden.intersection(identifiers))
            calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
            self.assertFalse({'eval', 'exec', 'compile'}.intersection(calls))
        from desktop_strings import ZH_TW

        catalog = {key: value for key, value in ZH_TW.items() if key.startswith('assistant.permission_')}
        self.assertEqual(len(catalog), 4)
        self.assertFalse(forbidden.intersection(catalog.keys()) | forbidden.intersection(catalog.values()))
        self.assertIn('\u672a\u9a57\u8b49', ui_text('assistant.permission_scope'))
        self.assertIn('\u4e0d\u662f\u771f\u5be6 AI', ui_text('assistant.fixture'))
        self.assertEqual(json.loads(json.dumps(list(MODES))), ['read_only', 'confirm_each_time'])


if __name__ == '__main__':
    unittest.main()
