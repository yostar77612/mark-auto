"""Strict JSON input regression coverage without external data or services."""

import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from desktop_pages.error_guidance import with_next_step
from desktop_pages.paper_tabs import existing_journal
from desktop_pages.widgets import WidgetTools
from quantlab import strict_json
from quantlab.core import ValidationError, canonical_json
from quantlab.desktop_errors import error_message
from quantlab.reporting import MAX_JSON_BYTES, read_json, write_json


@contextmanager
def fixture_folder():
    root = Path(tempfile.gettempdir()) / ('a3-' + uuid.uuid4().hex)
    root.mkdir(mode=0o755)
    try:
        yield root
    finally:
        shutil.rmtree(root)


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_keys_at_every_depth(self):
        for text, key in (
            ('{"margin_per_contract":1,"margin_per_contract":2}', 'margin_per_contract'),
            ('{"a":{"b":1,"b":2}}', 'b'),
            ('[{"nested":[{"item":1,"item":2}]}]', 'item'),
            ('{"a":1,"\\u0061":2}', 'a'),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValidationError, key):
                strict_json.loads(text)

    def test_invalid_inputs_are_validation_errors(self):
        for text in ('NaN', 'Infinity', '-Infinity', '{"a":NaN}', '[Infinity]', b'{}', None, '{', '{"a":1} trailing', '[' * 1100):
            with self.subTest(text=repr(text)[:60]), self.assertRaises(ValidationError):
                strict_json.loads(text)

    def test_canonical_roundtrip_and_standard_json_values(self):
        sample = {'unicode': '\u53f0\u7063', 'empty': [{}, []], 'big': 10**100, 'decimal': '123.4500', 'nested': {'a': [True, False, None, 1.25]}}
        text = canonical_json(sample)
        self.assertEqual(strict_json.loads(text), json.loads(text))
        self.assertEqual(strict_json.loads(text), sample)
        self.assertEqual(strict_json.loads('{"a":{"x":1},"b":{"x":2}}'), {'a': {'x': 1}, 'b': {'x': 2}})
        for text in ('null', '[]', '"hello"', '123', 'true'):
            self.assertEqual(strict_json.loads(text), json.loads(text))

    def test_file_bound_precedes_decode_and_parse(self):
        with fixture_folder() as folder:
            path = Path(folder) / 'input.json'
            data = canonical_json({'unicode': '\u53f0\u7063'}).encode('utf-8')
            path.write_bytes(data)
            self.assertEqual(strict_json.read(path, len(data)), {'unicode': '\u53f0\u7063'})
            with patch.object(Path, 'open', side_effect=AssertionError('oversize file opened')):
                with self.assertRaisesRegex(ValidationError, 'exceeds'):
                    strict_json.read(path, len(data) - 1)
            path.write_bytes(b'\xff')
            with self.assertRaisesRegex(ValidationError, 'UTF-8'):
                strict_json.read(path, 1)
            with self.assertRaisesRegex(ValidationError, 'exceeds'):
                strict_json.read(path, 0)
            path.write_text('{', encoding='utf-8')
            with self.assertRaises(ValidationError):
                strict_json.read(path, 1)

    def test_reporting_delegates_and_preserves_limit_and_constants(self):
        with patch('quantlab.strict_json.read', return_value={'ok': True}) as read:
            self.assertEqual(read_json('input.json'), {'ok': True})
            read.assert_called_once_with('input.json', MAX_JSON_BYTES)
        self.assertEqual(MAX_JSON_BYTES, 32 * 1024 * 1024)
        with fixture_folder() as folder:
            path = Path(folder) / 'input.json'
            for text, message in (('{"margin_per_contract":1,"margin_per_contract":2}', 'margin_per_contract'), ('{"x":NaN}', 'Invalid JSON constant: NaN')):
                path.write_text(text, encoding='utf-8')
                with self.assertRaisesRegex(ValidationError, message):
                    read_json(path)
            with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=MAX_JSON_BYTES + 1)):
                with self.assertRaisesRegex(ValidationError, '32 MiB'):
                    read_json(path)
            policy = {'account_id': 'paper-demo', 'instruments': [{'margin_per_contract': '100000.00'}]}
            write_json(Path(folder) / 'paper_policy.json', policy)
            self.assertEqual(read_json(Path(folder) / 'paper_policy.json'), policy)

    def test_existing_journal_rejects_duplicates_and_retains_bound(self):
        with fixture_folder() as folder:
            page = SimpleNamespace(root=folder)
            path = Path(folder) / 'paper_journal_export.json'
            path.write_text('{"events":[],"events":[]}', encoding='utf-8')
            self.assertIsNone(existing_journal(page))
            path.write_text('{"events":[]}', encoding='utf-8')
            self.assertEqual(existing_journal(page), {'events': []})
            with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=4 * 1024 * 1024 + 1)):
                self.assertIsNone(existing_journal(page))


class StrictJsonInlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bare_host_preserves_form_and_displays_existing_validation_feedback(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        field = QLineEdit('100000', page)
        editor = QPlainTextEdit('{"margin_per_contract":100000}', page)
        layout.addWidget(field)
        layout.addWidget(editor)
        failures = []

        def safe(callback):
            try:
                callback()
            except ValidationError as exc:
                failures.append(str(exc))

        host = SimpleNamespace(_advanced_values={editor: editor.toPlainText()}, _safe=safe, _confirm_button=lambda button, callback: callback(), actions=[])

        def apply():
            payload = WidgetTools._payload(host, editor, lambda: {'margin_per_contract': int(field.text())})
            field.setText(str(payload['margin_per_contract']))

        button = WidgetTools._button(host, layout, 'test', 'test_run', apply)
        editor.setPlainText('{"margin_per_contract":1,"margin_per_contract":2}')
        with self.assertRaisesRegex(ValidationError, 'margin_per_contract'):
            WidgetTools._payload(host, editor, lambda: self.fail('form builder called'))
        button.click()
        self.assertEqual(field.text(), '100000')
        self.assertIn('margin_per_contract', failures[0])
        self.assertEqual(button._error_guidance_label.text(), with_next_step(error_message('validation_failed'), 'validation_failed'))
        self.assertFalse(button._error_guidance_label.isHidden())
        editor.setPlainText('{"margin_per_contract":3}')
        button.click()
        self.assertEqual(field.text(), '3')
        self.assertTrue(button._error_guidance_label.isHidden())
