"""Offscreen alert forms, validation, record navigation and local notification."""

import unittest
from PySide6.QtWidgets import QApplication, QPushButton

from desktop_app.features.trading.alert_panel import AlertPanel, AlertRuleDialog
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.alert_service import AlertService
from quantlab.trading.domain.alerts import RULE_KINDS, AlertKind
from tests.test_alert_rules import ID, NOW, fixtures


class MemoryStore:
    warning = ''

    def __init__(self):
        self.rules = ()
        self.events = ()

    def load_rules(self):
        return self.rules

    def save_rules(self, rules):
        self.rules = rules

    def load_events(self, now):
        return self.events

    def append_event(self, event):
        self.events = (*self.events, event)


class AlertUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exact_twelve_labels_order_and_dynamic_scope_fields(self):
        dialog = AlertRuleDialog(ID)
        self.addCleanup(dialog.deleteLater)
        expected = (
            '價格突破／跌破',
            '漲跌幅超過',
            '短時間急漲急跌',
            '創當日新高／新低',
            '突破前日高／跌破前日低',
            '量能放大',
            '均線交叉',
            'KD 黃金／死亡交叉',
            '漲停相關',
            '跌停相關',
            '1 秒急漲急跌',
            '爆量大單',
        )
        self.assertEqual(12, dialog.kind.count())
        self.assertEqual(expected, tuple(dialog.kind.itemText(i) for i in range(12)))
        self.assertEqual(list(RULE_KINDS), [dialog.kind.itemData(i) for i in range(12)])
        self.assertEqual({'price', 'direction'}, set(dialog.editors))
        self.assertEqual(2, dialog.scope.count())
        for index, kind in enumerate(RULE_KINDS):
            dialog.kind.setCurrentIndex(index)
            self.assertEqual(3 if index >= 8 else 2, dialog.scope.count())
            self.assertTrue(dialog.kind.accessibleName())
            self.assertTrue(dialog.scope.accessibleName())
            self.assertTrue(dialog.cooldown.accessibleName())
            for editor in dialog.editors.values():
                self.assertTrue(editor.accessibleName())
            if kind == AlertKind.VOLUME_SURGE:
                self.assertEqual(3, dialog.editors['period'].count())
            if kind == AlertKind.MA_CROSS:
                self.assertEqual(4, dialog.editors['period'].count())
        for button in dialog.findChildren(QPushButton):
            self.assertTrue(button.accessibleName())

    def test_validation_beside_field_and_creation(self):
        dialog = AlertRuleDialog(ID)
        self.addCleanup(dialog.deleteLater)
        dialog.editors['price'].setText('0')
        dialog.create_rule()
        self.assertIsNone(dialog.rule)
        self.assertEqual(ui_text('alert.invalid'), dialog.error.text())
        self.assertEqual(ui_text('alert.invalid'), dialog.field_errors['price'].text())
        dialog.editors['price'].setText('600.00')
        dialog.create_rule()
        self.assertEqual('600.00', str(dialog.rule.params['price']))
        self.assertEqual(60, dialog.rule.cooldown_seconds)
        self.assertEqual(ID, dialog.rule.instrument_id)

    def test_record_navigation_taipei_order_colors_notification_and_clear(self):
        service = AlertService(MemoryStore(), now=NOW)
        select, notify, status = [], [], []
        panel = AlertPanel(
            service,
            lambda: ID,
            lambda *args: select.append(args),
            instrument_name=lambda key: '台積電',
            notify=notify.append,
            rise_fall_colors=lambda: ('#ff0000', '#00ff00'),
        )
        self.addCleanup(panel.deleteLater)
        panel.latest_changed.connect(status.append)
        rule, observation = next(fixtures())
        service.add_rule(rule)
        service.observe(observation)
        panel.refresh()
        self.assertEqual('08:00:00', panel.table.item(0, 0).text())
        self.assertEqual('2330', panel.table.item(0, 1).text())
        self.assertEqual('台積電', panel.table.item(0, 2).text())
        self.assertEqual('#ff0000', panel.table.item(0, 4).foreground().color().name())
        panel.select_event(panel.table.item(0, 0))
        self.assertEqual([(ID, NOW)], select)
        self.assertEqual(1, len(notify))
        self.assertEqual(notify, status)
        panel.refresh()
        self.assertEqual(1, len(notify))
        panel.clear_events()
        self.assertEqual(0, panel.table.rowCount())

    def test_historical_events_are_not_announced_again(self):
        store = MemoryStore()
        service = AlertService(store, now=NOW)
        rule, observation = next(fixtures())
        service.add_rule(rule)
        service.observe(observation)
        notify = []
        panel = AlertPanel(service, lambda: ID, lambda *args: None, notify=notify.append)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(1, panel.table.rowCount())
        self.assertEqual([], notify)


if __name__ == '__main__':
    unittest.main()
