"""Window persistence uses frame position even without native window decorations."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QRect
from desktop_pages.market import MarketPage
from desktop_pages.settings import SettingsPage
from desktop_pages.data import DataPage
from desktop_pages.strategy import StrategyPage
from tests.t10_fixture import WindowFixture


class FramedWindow:
    def __init__(self):
        self.position = QPoint(120, 140)
        self.size = (900, 650)
        self.moves = []
        self.minimum_size = (1280, 720)

    def setMinimumSize(self, width, height):
        self.minimum_size = (width, height)

    def x(self):
        return self.position.x()

    def y(self):
        return self.position.y()

    def geometry(self):
        return QRect(self.x() + 8, self.y() + 31, *self.size)

    def resize(self, width, height):
        self.size = (width, height)

    def move(self, x, y):
        self.moves.append((x, y))
        self.position = QPoint(x, y)


class WindowPositionTests(unittest.TestCase):
    def setUp(self):
        self.window = FramedWindow()
        self.value = {'legacy': {'keep': True}}
        self.store = Mock()
        self.store.load.side_effect = lambda: deepcopy(self.value)
        self.store.save.side_effect = self.save
        self.screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        self.host = SimpleNamespace(
            window_position=lambda: QPoint(self.window.x(), self.window.y()),
            window_geometry=self.window.geometry, resize_window=self.window.resize,
            move_window=self.window.move, window_screen=lambda: self.screen,
            window_minimum_size=lambda: self.window.minimum_size)
        self.page = SimpleNamespace(
            host=self.host, settings=self.store, _section_toggles={},
            persist_logs=Mock(), local_notifications=Mock(), jobs=SimpleNamespace(),
            chatgpt_panel=Mock(), status=Mock(), read_logs=Mock(), market=Mock())
        self.page.persist_logs.isChecked.return_value = True
        self.page.local_notifications.isChecked.return_value = True
        self.page.market.preferences.return_value = {'contract': 'fixture'}
        self.page.state = SimpleNamespace(settings=self.store)

    def save(self, value):
        self.value = deepcopy(value)

    def load(self):
        with patch('desktop_pages.settings.QApplication.screens', return_value=[self.screen]):
            SettingsPage.load_settings(self.page)

    def test_both_save_paths_round_trip_without_frame_drift(self):
        self.window.setMinimumSize(0, 0)
        for save in (SettingsPage.save_settings, MarketPage.save_market_preferences):
            with self.subTest(save=save.__name__):
                save(self.page)
                expected = {'x': 120, 'y': 140, 'width': 900, 'height': 650}
                self.assertEqual(self.value['window'], expected)
                self.window.move(200, 220)
                self.load()
                self.assertEqual(self.window.moves[-1], (120, 140))
                save(self.page)
                self.assertEqual(self.value['window'], expected)
                self.assertEqual(self.value['legacy'], {'keep': True})

    def test_missing_position_defaults_to_frame_position(self):
        self.window.setMinimumSize(0, 0)
        self.load()
        self.assertEqual(self.window.moves, [(120, 140)])
        self.assertEqual(self.window.size, (900, 650))

    def test_restore_keeps_integer_conversion_and_screen_clamping(self):
        self.window.setMinimumSize(0, 0)
        self.value['window'] = {'x': '1900', 'y': '1050', 'width': '1000', 'height': '700'}
        self.load()
        self.assertEqual(self.window.size, (1000, 700))
        self.assertEqual(self.window.moves, [(920, 380)])

    def test_shell_position_binding_uses_x_y_not_client_geometry(self):
        # Exercise the actual shell lambda with a decorated window double.
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'desktop_ui.py').read_text(encoding='utf-8-sig'))
        constructor = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name) and n.func.id == 'PageHost')
        binding = next(k.value for k in constructor.keywords if k.arg == 'window_position')
        callback = eval(compile(ast.Expression(binding), '<window_position>', 'eval'),
                        {'self': self.window, 'QPoint': QPoint})
        self.assertEqual(callback(), QPoint(120, 140))

    def test_dialog_bindings_keep_shell_parent(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'desktop_ui.py').read_text(encoding='utf-8-sig'))
        constructor = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name) and n.func.id == 'PageHost')
        dialogs = Mock()
        for name, factory in (('question', 'question'), ('open_file', 'getOpenFileName'),
                              ('save_file', 'getSaveFileName'), ('market_history_dialog', None)):
            with self.subTest(binding=name):
                binding = next(k.value for k in constructor.keywords if k.arg == name)
                history = Mock()
                callback = eval(compile(ast.Expression(binding), '<dialog>', 'eval'),
                                {'self': self.window, 'QFileDialog': dialogs,
                                 'QMessageBox': dialogs, 'MarketHistoryDialog': history})
                if factory:
                    callback('title')
                    getattr(dialogs, factory).assert_called_once_with(self.window, 'title')
                else:
                    callback()
                    history.assert_called_once_with(self.window)

    def test_moved_dialog_calls_use_host_services(self):
        host = Mock()
        host.open_file.return_value = ('', '')
        host.save_file.return_value = ('', '')
        host.question.return_value = 0
        host.payload.return_value = {'max_improvements': 0}
        page = SimpleNamespace(host=host, state=SimpleNamespace(jobs=SimpleNamespace(active=False)),
                               campaign_config=Mock(), campaign_form=Mock())
        DataPage.import_market_file(page)
        StrategyPage.pick_walk_forward_original(page)
        StrategyPage.export_manual_request(page)
        MarketPage.refresh_market(page)
        DataPage.import_market_history(page)
        self.assertEqual(host.open_file.call_count, 2)
        host.save_file.assert_called_once()
        host.question.assert_called_once()
        host.market_history_dialog.assert_called_once_with()
        host.market_history_dialog.return_value.open.assert_called_once_with()
        host.start_job.assert_not_called()


class ProductionWindowMinimumTests(WindowFixture):
    def test_save_restore_respects_production_minimum_even_on_small_screen(self):
        w = self.window
        self.assertEqual((w.minimumWidth(), w.minimumHeight()), (1280, 720))
        self.assertEqual(w.page_host.window_minimum_size(), (1280, 720))
        for screen_size in ((1920, 1080), (800, 600)):
            screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, *screen_size))
            for saved_size in ((400, 300), (999999, 999999)):
                with self.subTest(screen=screen_size, saved=saved_size):
                    value = w.settings.load()
                    value['window'] = {'x': 0, 'y': 0, 'width': saved_size[0], 'height': saved_size[1]}
                    w.settings.save(value)
                    with patch('desktop_pages.settings.QApplication.screens', return_value=[screen]), patch.object(
                            w.page_host, 'window_screen', return_value=screen):
                        w.load_settings()
                        self.assertGreaterEqual(w.width(), 1280)
                        self.assertGreaterEqual(w.height(), 720)
                        w.save_settings()
                        saved = w.settings.load()['window']
                        self.assertEqual((saved['width'], saved['height']), (w.width(), w.height()))
                        w.load_settings()
                        self.assertEqual((w.width(), w.height()), (saved['width'], saved['height']))
