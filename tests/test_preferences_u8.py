"""U8: pre-change evidence and cheap display-state persistence regressions.

Before U8: advanced_sections, window x/y/width/height and market preferences
persisted. Last page and per-family parameters did not; navigation had a fixed
maximum width and no sidebar splitter. Market splitters had only layout hints.
"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.ui_preferences import page_row, bounded_size, splitter_sizes, family_parameters


class SerializationTests(unittest.TestCase):
    def test_identity_survives_reordering_and_invalid_falls_back(self):
        self.assertEqual(page_row('strategy', ['market', 'strategy']), 1)
        self.assertEqual(page_row('strategy', ['strategy', 'market']), 0)
        for value in (None, [], {}, 2, -1, 999, 'unknown'):
            self.assertEqual(page_row(value, ['market', 'strategy']), 0)

    def test_sizes_are_strict_and_bounded(self):
        self.assertEqual(bounded_size(-9, 120, 180, 180), 120)
        self.assertEqual(bounded_size(99999, 120, 180, 180), 180)
        self.assertEqual(bounded_size(True, 120, 180, 180), 180)
        self.assertEqual(splitter_sizes([-5, 99999], 2, 1000), [80, 1000])
        for value in (None, [1], ['1', 2], [True, 2]):
            self.assertIsNone(splitter_sizes(value, 2, 1000))

    def test_projection_discards_sensitive_and_unknown_fields(self):
        self.assertEqual(
            family_parameters({'trend': {'fast': 7, 'slow': 30, 'account': 'secret', 'quantity': 8, 'amount': 99}}, {'trend': {'fast': 5, 'slow': 20}}),
            {'trend': {'fast': 7, 'slow': 30}},
        )
        self.assertEqual(family_parameters(None, {}), {})


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def form(self):
        from desktop_app.components.forms import StrategyForm

        return StrategyForm()

    def test_family_values_round_trip_with_same_validation(self):
        form = self.form()
        form.fields['fast'].setText('7')
        form.fields['slow'].setText('31')
        form.family.setCurrentIndex(1)
        other = form.family.currentData()
        key = next(key for key in form.fields if key != 'family')
        form.fields[key].setText('25')
        saved = form.preference_parameters()
        self.assertEqual(saved['trend'], {'fast': 7, 'slow': 31})
        self.assertEqual(saved[other][key], 25)
        reopened = self.form()
        reopened.restore_preference_parameters(json.loads(json.dumps(saved)))
        self.assertEqual(reopened.fields['fast'].text(), '7')
        reopened.family.setCurrentIndex(1)
        self.assertEqual(reopened.fields[key].text(), '25')
        reopened.family.setCurrentIndex(0)
        self.assertEqual(reopened.fields['slow'].text(), '31')

    def test_invalid_saved_values_are_dropped(self):
        from quantlab.strategies import DEFAULTS

        for parameters in ({'fast': 50, 'slow': 2}, {'fast': 'NaN', 'slow': 30}, {'fast': '1e999', 'slow': 30}):
            form = self.form()
            form.restore_preference_parameters({'trend': parameters})
            self.assertEqual(form.fields['fast'].text(), str(DEFAULTS['trend']['fast']))
            self.assertNotIn('trend', form._family_preferences)
            form.build_payload()

    def test_invalid_inactive_family_is_also_dropped_on_restore(self):
        form = self.form()
        form.restore_preference_parameters({'trend': {'fast': 7, 'slow': 30}, 'mean_reversion': {'lookback': 'NaN', 'entry_bps': 10, 'max_holding_bars': 10}})
        self.assertNotIn('mean_reversion', form._family_preferences)
        self.assertEqual(form.fields['fast'].text(), '7')

    def shell(self, store):
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QListWidget, QStackedWidget
        from desktop_app.features.settings.preferences import install_sidebar

        class Market(QWidget):
            pass

        class Strategy(QWidget):
            pass

        window = QWidget()
        window.page_state = SimpleNamespace()
        window.navigation = QListWidget()
        window.navigation.setMaximumWidth(180)
        window.stack = QStackedWidget()
        for page in (Market(), Strategy()):
            window.navigation.addItem(type(page).__name__)
            window.stack.addWidget(page)
        install_sidebar(window, QHBoxLayout(window))
        window.navigation.currentRowChanged.connect(window.stack.setCurrentIndex)
        window.navigation.setCurrentRow(0)
        window.page_state.strategy_form = self.form()
        page = SimpleNamespace(host=SimpleNamespace(state=window.page_state), settings=store)
        return window, page

    def test_new_window_restore_sidebar_identity_unknown_and_privacy(self):
        from desktop_app.features.settings.preferences import save_preferences, restore_preferences

        window, page = self.shell(None)
        window.navigation.setCurrentRow(1)
        page.host.state.privacy_mode = True
        value = {'unknown': {'keep': True}, 'advanced_sections': {'a': True}, 'market': {'keep': True}}
        save_preferences(page, value)
        self.assertIsInstance(value['last_page'], str)
        second, reopened = self.shell(None)
        # Local classes have stable module/class identities across window creation.
        restore_preferences(reopened, deepcopy(value))
        self.assertEqual(second.navigation.currentRow(), 1)
        self.assertEqual(value['unknown'], {'keep': True})
        self.assertEqual(value['advanced_sections'], {'a': True})
        self.assertEqual(value['market'], {'keep': True})
        self.assertFalse(any(word in json.dumps(value) for word in ('account', 'amount', 'quantity')))
        for width, expected in ((-1, 120), (10000, 180)):
            restore_preferences(reopened, dict(value, sidebar_width=width))
            sizes = reopened.host.state.preference_sidebar.sizes()
            self.assertGreaterEqual(sizes[0], 120)
            self.assertLessEqual(sizes[0], 180)
        restore_preferences(reopened, dict(value, last_page=999))
        self.assertEqual(second.navigation.currentRow(), 0)
        window.close()
        second.close()

    def test_sidebar_width_and_market_splitter_round_trip(self):
        from PySide6.QtWidgets import QSplitter, QWidget
        from desktop_app.features.settings.preferences import save_preferences, restore_preferences

        window, page = self.shell(None)
        sidebar = page.host.state.preference_sidebar
        sidebar.setSizes([145, sidebar.width() - 145 - sidebar.handleWidth()])
        market = QSplitter(window)
        for _ in range(2):
            child = QWidget(market)
            child.setMinimumWidth(80)
        market.resize(800, 400)
        market.setSizes([250, 546])
        page.host.state.market = SimpleNamespace(main_splitter=market)
        value = {}
        save_preferences(page, value)
        self.assertEqual(value['sidebar_width'], 145)
        sidebar.setSizes([180, sidebar.width() - 180 - sidebar.handleWidth()])
        market.setSizes([400, 396])
        restore_preferences(page, value)
        self.assertEqual(sidebar.sizes()[0], 145)
        self.assertEqual(market.sizes(), value['splitter_sizes']['market'])
        restore_preferences(page, dict(value, splitter_sizes={'market': [-99, 999999]}))
        self.assertTrue(all(80 <= size <= market.screen().availableGeometry().width() for size in market.sizes()))
        window.close()

    def test_none_bare_host_and_corrupt_file(self):
        from desktop_app.features.settings.preferences import load_store, restore_preferences, save_preferences
        from desktop_app.features.settings.settings import SettingsPage
        from quantlab.desktop_runtime import SettingsStore

        page = SimpleNamespace(host=SimpleNamespace(), settings=None)
        restore_preferences(page, {})
        save_preferences(page, {})
        SettingsPage.load_settings(page)
        self.assertEqual(load_store(None), {})
        path = Path('corrupt-settings-fixture.json')
        with (
            patch('quantlab.desktop_runtime._read_json', side_effect=json.JSONDecodeError('invalid', '{broken', 1)),
            patch.object(Path, 'exists', return_value=True),
        ):
            self.assertEqual(load_store(SettingsStore(path)), {})

    def test_existing_settings_round_trip_and_corrupt_defaults(self):
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QCheckBox
        from desktop_app.features.settings.settings import SettingsPage
        from quantlab.runtime_support import RuntimeSafetyError

        saved = {'unknown': {'keep': True}, 'advanced_sections': {'detail': True}, 'market': {'fixture': True}}
        store = Mock()
        store.load.side_effect = lambda: deepcopy(saved)
        store.save.side_effect = lambda value: saved.update(deepcopy(value))
        window, page = self.shell(store)
        geometry = QRect(0, 0, 900, 650)
        page.host.window_position = lambda: QPoint(10, 20)
        page.host.window_geometry = lambda: geometry
        page.host.window_screen = lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        page.host.window_minimum_size = lambda: (0, 0)
        page.host.resize_window = Mock()
        page.host.move_window = Mock()
        page.persist_logs = QCheckBox()
        page.local_notifications = QCheckBox()
        page._section_toggles = {'detail': QCheckBox()}
        page.jobs = SimpleNamespace()
        page.chatgpt_panel = SimpleNamespace(consent=QCheckBox())
        page.status = Mock()
        page.read_logs = Mock()
        page.market = Mock()
        page.market.preferences.return_value = {'fixture': True}
        with patch('desktop_app.features.settings.settings.QApplication.screens', return_value=[]):
            SettingsPage.load_settings(page)
        self.assertTrue(page._section_toggles['detail'].isChecked())
        page.market.restore_preferences.assert_called_once_with({'fixture': True})
        window.navigation.setCurrentRow(1)
        page.chatgpt_panel.consent.setChecked(True)
        SettingsPage.save_settings(page)
        self.assertFalse(page.chatgpt_panel.consent.isChecked())
        self.assertEqual(saved['unknown'], {'keep': True})
        self.assertEqual(saved['window'], {'x': 10, 'y': 20, 'width': 900, 'height': 650})
        self.assertEqual(saved['advanced_sections'], {'detail': True})
        store.load.side_effect = RuntimeSafetyError('corrupt')
        with patch('desktop_app.features.settings.settings.QApplication.screens', return_value=[]):
            SettingsPage.load_settings(page)
        self.assertEqual(window.navigation.currentRow(), 0)
        self.assertFalse(page._section_toggles['detail'].isChecked())
        self.assertTrue(page.persist_logs.isChecked())
        window.close()

    def test_catalog_and_layout_scanners_cover_modules(self):
        from tests.test_no_hardcoded_ui_text import UI_PACKAGE_MODULES
        from tests.test_import_graph import TOUCHED

        self.assertIn('desktop_app/features/settings/preferences.py', UI_PACKAGE_MODULES)
        self.assertIn('desktop_app/features/settings/preferences.py', TOUCHED)
        self.assertIn('quantlab/ui_preferences.py', TOUCHED)
