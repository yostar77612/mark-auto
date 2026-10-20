"""Cheap local D6 completion and reference isolation tests; no visible windows."""

import ast
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from desktop_pages.assistant_completion import MAX_COMPLETIONS, reference_catalog, resolve_references
from desktop_strings import ui_text
from quantlab import agent_skills
from quantlab.assistant_chat import ChatDispatcher
from quantlab.errors import ERROR_TABLE
from tests import test_assistant_d4 as safety
from tests.test_agent_harness_d1 import assert_no_protected_values
from tests.test_agent_skills_d7 import document


ROOT = Path(__file__).resolve().parents[1]


class AssistantD6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        safety.AssistantD4Tests.setUpClass()

    def setUp(self):
        self.fixture = safety.AssistantD4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.panel = self.fixture.panel
        self.menu = self.panel.completions
        self.dispatcher = self.fixture.dispatcher

    def labels(self):
        return [self.menu.list.item(i).text() for i in range(self.menu.list.count())]

    def test_local_skills_keyboard_accept_never_sends_or_runs(self):
        expected = {'/' + p.stem for p in agent_skills.SKILLS_DIRECTORY.glob('*.md')}
        self.assertEqual(len(expected), 4)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Tab):
            self.panel.input.clear()
            QTest.keyClicks(self.panel.input, '/')
            self.assertTrue(self.menu.open)
            self.assertEqual(set(self.labels()), expected)
            QTest.keyClick(self.panel.input, Qt.Key.Key_Down)
            self.assertEqual(self.menu.list.currentRow(), 1)
            QTest.keyClick(self.panel.input, Qt.Key.Key_Up)
            self.assertEqual(self.menu.list.currentRow(), 0)
            chosen = self.labels()[0]
            QTest.keyClick(self.panel.input, key)
            self.assertEqual(self.panel.input.text(), chosen + ' ')
            self.assertFalse(self.menu.open)
            self.assertEqual(self.panel.transcript.toPlainText(), '')
            self.fixture.worker.start.assert_not_called()
        self.assertEqual(self.menu.list.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.panel.input.setText('/')
        with patch.object(self.panel.input, 'setFocus') as focus:
            QTest.keyClick(self.panel.input, Qt.Key.Key_Escape)
            focus.assert_called_once()
        self.assertFalse(self.menu.open)

    def test_filtered_bounded_accessible_literal_list_and_midword_negative_controls(self):
        self.panel.input.setText('/check-d')
        self.assertEqual(self.labels(), ['/check-data-quality'])
        names = tuple('example-' + str(i) for i in range(60))
        with patch.object(self.menu.loader, 'completion_list', return_value=names):
            self.panel.input.setText('/')
            self.assertEqual(self.menu.list.count(), MAX_COMPLETIONS)
            self.panel.input.setText('/example-59')
            self.assertEqual(self.labels(), ['/example-59'])
        entries = {('result', format(i, '012x') + '0' * 52): self.fixture.storage.identity for i in range(60)}
        with patch('desktop_pages.assistant_completion.reference_catalog', return_value=entries):
            self.panel.input.setText('@result:')
            self.assertEqual(self.menu.list.count(), MAX_COMPLETIONS)
            self.panel.input.setText('@result:00000000003b')
            self.assertEqual(self.menu.list.count(), 1)
        partial = Mock()
        partial.call.return_value = {'ok': True, 'items': [], 'next_cursor': 'partial'}
        self.assertEqual(reference_catalog(partial), {})
        self.assertEqual(partial.call.call_count, 4)
        for text in ('a/b', 'a@b', 'word /check', 'mail a@b'):
            self.panel.input.setText(text)
            self.assertFalse(self.menu.open, text)
        self.panel.input.setText('@')
        self.assertTrue(self.menu.list.accessibleName())
        for i in range(self.menu.list.count()):
            item = self.menu.list.item(i)
            self.assertEqual(item.data(Qt.ItemDataRole.AccessibleTextRole), item.text())
            self.assertEqual(len(item.text().splitlines()), 1)
        self.panel.reply('<b>untrusted</b><script>alert(1)</script>')
        self.assertIn('<b>untrusted</b>', self.panel.transcript.toPlainText())

    def test_catalog_isolates_bad_skill_and_rejects_mutation_and_traversal_before_read(self):
        root = self.fixture.storage.root
        (root / 'valid.md').write_bytes(document(name='valid', tools=['get_data_quality_summary']))
        (root / 'malformed.md').write_bytes(b'not a skill')
        (root / 'mutation.md').write_bytes(document(name='mutation', tools=['run_backtest']))
        with patch.object(agent_skills, 'SKILLS_DIRECTORY', root):
            self.panel.input.setText('/')
            self.assertEqual(self.labels(), ['/valid'])
            self.assertTrue(self.menu.errors)
            self.assertTrue(set(self.menu.errors) <= set(ERROR_TABLE))
            self.assertIn('agent_tool_refused', self.menu.list.accessibleDescription())
            with patch.object(Path, 'open') as read:
                self.menu.loader.read('{"name":"../secret"}')
                read.assert_not_called()
            # Simulate a reparse-point escape; target bytes must never be read.
            original = agent_skills._link
            original_open = Path.open
            opened = []

            def confined_open(path, *args, **kwargs):
                self.assertEqual(path.parent, root)
                self.assertNotEqual(path.name, 'valid.md')
                opened.append(path)
                return original_open(path, *args, **kwargs)

            with patch.object(agent_skills, '_link', side_effect=lambda p: p.name == 'valid.md' or original(p)), patch.object(Path, 'open', confined_open):
                self.menu.loader.completion_list()
            self.assertTrue(opened)

    def test_missing_directory_empty_store_and_legacy_fail_closed(self):
        with patch.object(agent_skills, 'SKILLS_DIRECTORY', self.fixture.storage.root / 'missing'):
            self.panel.input.setText('/')
            self.assertFalse(self.menu.open)
            self.assertEqual(self.menu.errors, ('agent_tool_refused',))
        context = replace(self.fixture.storage.context, training=())
        legacy = ChatDispatcher(context)
        self.assertEqual(reference_catalog(legacy), {})
        with self.assertRaisesRegex(ValueError, 'agent_reference_not_found'):
            resolve_references('@result:' + self.fixture.storage.identity[:12], legacy)
        self.menu.dispatcher = legacy
        self.panel.input.setText('@')
        self.assertFalse(self.menu.open)

    def test_reference_summary_only_and_resolution_uses_d3_reads(self):
        self.panel.input.setText('@')
        self.assertTrue(any('@dataset:' in text for text in self.labels()))
        self.assertTrue(any('@result:' in text for text in self.labels()))
        for text in self.labels():
            self.assertTrue(text.endswith((ui_text('assistant.reference_result'), ui_text('assistant.reference_dataset'))))
            assert_no_protected_values(self, text)
            for forbidden in ('net_pnl', 'equity', 'ledger', '100000', '987654', '31337'):
                self.assertNotIn(forbidden, text)
        self.panel.input.setText('@dataset:')
        chosen = self.menu.list.currentItem().data(Qt.ItemDataRole.UserRole)
        QTest.keyClick(self.panel.input, Qt.Key.Key_Tab)
        self.assertEqual(self.panel.input.text(), chosen + ' ')
        self.assertFalse(self.menu.open)
        self.assertEqual(self.panel.transcript.toPlainText(), '')
        self.fixture.worker.start.assert_not_called()
        identity = self.fixture.storage.identity
        dataset = self.fixture.storage.payload['manifest']['data_hash']
        for kind, digest, tool in (('result', identity, 'get_backtest_summary'), ('dataset', dataset, 'get_data_quality_summary')):
            with patch.object(self.dispatcher, 'call', wraps=self.dispatcher.call) as call:
                resolved = resolve_references('@' + kind + ':' + digest[:12], self.dispatcher)
            self.assertEqual(
                resolved,
                '@' + kind + ':' + digest + ' ' + (ui_text('assistant.reference_result') if kind == 'result' else ui_text('assistant.reference_dataset')),
            )
            self.assertEqual([c.args[0] for c in call.call_args_list], ['list_saved_results', tool])
            assert_no_protected_values(self, resolved)
        with self.assertRaises(AssertionError):
            assert_no_protected_values(self, '\n'.join(self.labels()) + 'HOLDOUT_SENTINEL')

    def test_unknown_stale_ambiguous_and_protected_hash_never_fallback(self):
        identity = self.fixture.storage.identity
        for value in ('f' * 12, self.fixture.protected_id[:12], '../../secret', 'result:'):
            self.panel.input.setText('@result:' + value)
            self.panel.submit()
            self.assertIn(ERROR_TABLE['agent_reference_not_found'].explanation, self.panel.transcript.toPlainText())
            self.fixture.worker.start.assert_not_called()
        with patch('desktop_pages.assistant_completion.reference_catalog', return_value={('result', 'a' * 64): identity, ('result', 'a' * 63 + 'b'): identity}):
            with self.assertRaises(ValueError):
                resolve_references('@result:' + 'a' * 12, self.dispatcher)
        (self.fixture.storage.root / identity / 'result.json').unlink()
        with self.assertRaises(ValueError):
            resolve_references('@result:' + identity[:12], self.dispatcher)

    def test_remote_consent_denial_and_success_payload_contains_only_identity_and_fixed_summary(self):
        self.panel.mode.setCurrentIndex(1)
        prompt = '@result:' + self.fixture.storage.identity[:12]
        self.panel.input.setText(prompt)
        with patch.object(self.dispatcher, 'call', wraps=self.dispatcher.call) as read:
            self.panel.submit()
            read.assert_not_called()
        self.fixture.worker.start.assert_not_called()
        self.assertEqual(self.panel.transcript.toPlainText(), '')
        self.panel.ask_consent = Mock(return_value=True)
        self.panel.submit()
        request = self.fixture.worker.start.call_args.args[0]
        assert_no_protected_values(self, json.dumps(request) + self.panel.transcript.toPlainText())
        self.assertIn(self.fixture.storage.identity, request['prompt'])
        self.assertNotIn('metrics', request['prompt'])
        self.assertNotIn('DPAPI_SECRET_SENTINEL', str(request))

    def test_no_dynamic_execution_or_operator_route_and_existing_safety_oracles(self):
        source = (ROOT / 'desktop_pages/assistant_completion.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertFalse(calls & {'eval', 'exec', 'compile', 'open'})
        self.assertTrue(all(d['effect'] == 'read' for d in self.dispatcher.declarations.values()))
        self.fixture.test_operator_and_quota_entry_points_unreachable()
        self.fixture.test_exact_frozen_read_surface_and_unknown_names_never_dispatch()


if __name__ == '__main__':
    unittest.main()
