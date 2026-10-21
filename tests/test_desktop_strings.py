"""Catalog fallback and live widget lookup contracts for all desktop UI modules."""

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import desktop_strings as strings


class CatalogTests(unittest.TestCase):
    def test_every_registered_key_resolves_and_has_text(self):
        self.assertEqual(strings.DEFAULT_LOCALE, 'zh-TW')
        self.assertTrue(strings.LOCALES)
        for locale, catalog in strings.LOCALES.items():
            self.assertTrue(catalog, locale)
            for key, value in catalog.items():
                with self.subTest(locale=locale, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertEqual(strings.ui_text(key, locale), value)
                    self.assertEqual(strings.ui_text(key), strings.ZH_TW[key])

    def test_unknown_locale_and_partial_locale_fall_back(self):
        key = 'ui.advanced.default_title'
        expected = strings.ZH_TW[key]
        self.assertEqual(strings.ui_text(key, 'unknown-locale'), expected)
        with patch.dict(strings.LOCALES, {'stub': {'stub.only': 'Stub text'}}):
            self.assertEqual(strings.ui_text(key, 'stub'), expected)
            self.assertEqual(strings.ui_text('stub.only', 'stub'), 'Stub text')

    def test_unknown_key_raises_key_error(self):
        for locale in (None, 'zh-TW', 'unknown-locale'):
            with self.subTest(locale=locale), self.assertRaises(KeyError):
                strings.ui_text('missing.catalog.key', locale)

    def test_dynamic_templates_preserve_number_and_date_formatting(self):
        from decimal import Decimal
        from types import SimpleNamespace
        from desktop_presentation import result_name

        self.assertEqual(strings.ui_text('ui.paint_event.equity_range').format(1234, 5678), '權益 TWD  最低 1,234  最高 5,678 | 時間 →')
        result = SimpleNamespace(
            manifest={
                'strategy': {'family': 'trend', 'parameters': {'period': Decimal('3.123456')}},
                'dataset_manifest': {'coverage': {'start': '2026-01-01', 'end': '2026-01-02'}},
            },
            equity=[],
        )
        self.assertEqual(result_name(result, 0), '趨勢・period=3.1235・2026-01-01～2026-01-02・1970-01-01 08:00:00（台北）')

    def test_all_migrated_lookup_keys_exist_and_syntax_is_python_311(self):
        root = Path(__file__).resolve().parents[1]
        from tests.test_no_hardcoded_ui_text import UI_MODULES

        for name in ('desktop_strings.py', *UI_MODULES):
            tree = ast.parse((root / name).read_text(encoding='utf-8-sig'), filename=name, feature_version=(3, 11))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'ui_text':
                    self.assertIsInstance(node.args[0], ast.Constant)
                    self.assertTrue(strings.ui_text(node.args[0].value))

    def test_monkeypatching_registry_changes_rendered_widget_text(self):
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton
        from desktop_ui_polish import DisabledHint

        app = QApplication.instance() or QApplication([])
        button = QPushButton()
        label = QLabel()
        button.setEnabled(False)
        hint = DisabledHint(button, label, 'ready')
        original = label.text()
        stub = dict(strings.ZH_TW, **{'ui_polish.update.prerequisite_required': 'Stub prerequisite: {0}'})
        try:
            with patch.dict(strings.LOCALES, {strings.DEFAULT_LOCALE: stub}):
                hint.update()
                label.show()
                app.processEvents()
                self.assertEqual(label.text(), 'Stub prerequisite: ready')
                self.assertNotEqual(label.text(), original)
                self.assertFalse(label.grab().isNull())
            hint.update()
            self.assertEqual(label.text(), original)
        finally:
            label.close()
            button.close()
            label.deleteLater()
            button.deleteLater()

    def test_part_b_dynamic_text_preserves_validation_and_formatting(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from desktop_charts import _display_time
        from desktop_forms import number
        from quantlab.core import ValidationError

        self.assertEqual(number('3', '口數', 1, 5, integer=True), 3)
        for value, expected in (('', '口數：請輸入有效數字'), ('1.5', '口數：須為 1 至 5 的整數'), ('NaN', '口數：須為 1 至 5 的整數')):
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                number(value, '口數', 1, 5, integer=True)
            self.assertEqual(str(caught.exception), expected)
        self.assertEqual(_display_time(datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)), '2026/01/02 02:30 台北時間')
        self.assertEqual(_display_time(datetime(2026, 1, 1)), '時間未提供／未驗證')
        self.assertEqual(strings.ui_text('charts.paint_event.named_price').format('門檻', Decimal('1234.56789')), '門檻：1,234.5679')

    def test_part_b_form_uses_registry_at_widget_construction(self):
        from PySide6.QtWidgets import QApplication, QLabel
        from desktop_forms import StrategyForm

        app = QApplication.instance() or QApplication([])
        stub = dict(strings.ZH_TW, **{'forms.init.strategy_family': 'Stub field caption'})
        with patch.dict(strings.LOCALES, {strings.DEFAULT_LOCALE: stub}):
            form = StrategyForm()
            try:
                self.assertIn('Stub field caption', [label.text() for label in form.findChildren(QLabel)])
                app.processEvents()
            finally:
                form.close()
                form.deleteLater()


if __name__ == '__main__':
    unittest.main()
