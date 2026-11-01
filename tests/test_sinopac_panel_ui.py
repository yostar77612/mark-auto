"""Reference-only three-step connection controls, using immutable fake facts."""

from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QLineEdit
import shiboken6

from desktop_app.features.trading.broker_panel import BrokerPanel
from desktop_app.strings.catalog import ui_text
from quantlab.trading.application.contracts import SinopacAccountView, SinopacConnectionSettings, SinopacConnectionView, SinopacReadiness
from quantlab.trading.domain.models import Environment, Market


def connected_view(revision=1):
    return SinopacConnectionView(
        revision=revision,
        generation='fixture-generation',
        environment=Environment.BROKER_SIMULATION,
        phase='CONNECTED',
        accounts=(
            SinopacAccountView('stock-1', '9A95-***4567', Market.STOCK, True, True),
            SinopacAccountView('future-1', 'F002000-***6789', Market.INDEX_FUTURE, False),
        ),
        readiness=(
            SinopacReadiness('market', 'READY', ''),
            SinopacReadiness('accounts', 'READY', ''),
            SinopacReadiness('simulation_orders', 'BLOCKED', 'implementation_pending'),
            SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
        ),
    )


class SinopacPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = BrokerPanel(confirm=lambda text: False)
        self.panel.resize(760, 740)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        shiboken6.delete(self.panel)

    def test_defaults_and_real_combo_save_emit_one_reference_only_typed_intent(self):
        self.assertEqual(self.panel.save_connect.property('role'), 'primary')
        for environment in (Environment.BROKER_SIMULATION, Environment.LIVE):
            self.panel.environment.setCurrentIndex(self.panel.environment.findData(environment))
            emitted = QSignalSpy(self.panel.save_connect_requested)
            self.panel.save_connect.click()
            self.assertEqual(emitted.count(), 1)
            settings, revision, generation = emitted.at(0)
            self.assertIsInstance(settings, SinopacConnectionSettings)
            self.assertIs(settings.environment, environment)
            self.assertEqual(settings.key_ref, 'MarkAuto/v2/broker/sinopac')
            self.assertEqual(settings.fee_discount, Decimal('1'))
            self.assertEqual((revision, generation), (0, ''))

    def test_signed_accounts_are_masked_and_keyboard_selection_uses_stable_aliases(self):
        self.panel.apply(connected_view())
        self.assertIn(ui_text('m2.connection.signed'), self.panel.account_boxes['stock-1'].text())
        self.assertIn(ui_text('m2.connection.unsigned'), self.panel.account_boxes['future-1'].text())
        emitted = QSignalSpy(self.panel.accounts_requested)
        self.panel.account_boxes['future-1'].setFocus()
        QTest.keyClick(self.panel.account_boxes['future-1'], Qt.Key.Key_Space)
        self.assertEqual(emitted.count(), 1)
        self.assertEqual(tuple(emitted.at(0)[0]), ('stock-1', 'future-1'))
        self.assertEqual(emitted.at(0)[1:], [1, 'fixture-generation'])
        for widget in self.panel.findChildren(QLabel) + self.panel.findChildren(QLineEdit):
            for value in (widget.text(), widget.toolTip(), widget.accessibleName(), widget.accessibleDescription()):
                self.assertNotIn('9A95-1234567', value)
                self.assertNotIn('A123456789', value)

    def test_poll_keeps_drafts_fee_and_newer_accepted_connection_status(self):
        self.panel.apply(connected_view(5))
        self.panel.key_ref.setFocus()
        self.panel.key_ref.selectAll()
        QTest.keyClicks(self.panel.key_ref, 'MarkAuto/v2/broker/new')
        self.panel.fee_group.setChecked(True)
        self.panel.fee_discount.setFocus()
        self.panel.fee_discount.selectAll()
        QTest.keyClicks(self.panel.fee_discount, '0.25')
        self.panel.apply(replace(connected_view(6), accounts=tuple(reversed(connected_view().accounts))))
        self.assertEqual(self.panel.settings().fee_discount, Decimal('0.25'))
        self.assertEqual(self.panel.key_ref.text(), 'MarkAuto/v2/broker/new')
        self.assertTrue(self.panel.dirty)
        self.panel.apply(SinopacConnectionView(revision=4))
        self.assertEqual(self.panel.view.revision, 6)
        self.assertIn(ui_text('m2.connection.connected'), self.panel.status.text())

    def test_four_readiness_reasons_never_infer_orders_from_login_or_signed(self):
        self.panel.apply(connected_view())
        self.assertEqual(set(self.panel.readiness_labels), {'market', 'accounts', 'simulation_orders', 'production_orders'})
        self.assertIn(ui_text('m2.connection.ready'), self.panel.readiness_labels['market'].text())
        self.assertIn(ui_text('m2.connection.execution_pending'), self.panel.readiness_labels['simulation_orders'].text())
        self.assertIn(ui_text('m2.connection.production_disabled'), self.panel.readiness_labels['production_orders'].text())
        unknown = replace(connected_view(2), accounts=(replace(connected_view().accounts[0], signed=None),))
        self.panel.apply(unknown)
        self.assertIn(ui_text('m2.connection.signed_unknown'), self.panel.account_boxes['stock-1'].text())

    def test_certificate_picker_cancel_and_selection_emit_reference_without_reading_file(self):
        self.assertFalse(self.panel.choose_certificate.isEnabled())
        self.panel.apply(connected_view())
        self.panel.certificate_group.setChecked(True)
        emitted = QSignalSpy(self.panel.certificate_requested)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.panel.choose_certificate.click()
        self.assertEqual(self.panel.certificate_path.text(), '')
        self.assertEqual(emitted.count(), 0)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('C:/fake/Sinopac.pfx', '')):
            self.panel.choose_certificate.click()
        self.assertTrue(self.panel.activate_certificate.isEnabled())
        self.panel.activate_certificate.click()
        self.assertEqual(emitted.count(), 1)
        self.assertEqual(emitted.at(0)[0].certificate_path, 'C:/fake/Sinopac.pfx')
        self.assertEqual(emitted.at(0)[0].certificate_secret_ref, 'MarkAuto/v2/certificate/sinopac')
        self.assertFalse(any(field.echoMode() == QLineEdit.EchoMode.Password for field in self.panel.findChildren(QLineEdit)))

    def test_disconnect_requires_confirmation_and_preserves_exact_connection_cas(self):
        self.panel.apply(connected_view())
        emitted = QSignalSpy(self.panel.disconnect_requested)
        self.panel.disconnect_button.click()
        self.assertEqual(emitted.count(), 0)
        self.panel.confirm = lambda text: True
        self.panel.disconnect_button.click()
        self.assertEqual(emitted.count(), 1)
        self.assertEqual(emitted.at(0), [1, 'fixture-generation'])

    def test_bad_fee_and_unknown_error_do_not_echo_fields_or_vendor_codes(self):
        self.panel.fee_discount.setText('NaN')
        emitted = QSignalSpy(self.panel.save_connect_requested)
        self.panel.save_connect.click()
        self.assertEqual(emitted.count(), 0)
        self.assertEqual(self.panel.status.text(), ui_text('m2.connection.invalid'))
        self.panel.apply(SinopacConnectionView(revision=1, error_code='VENDOR_UNSAFE_DETAIL'))
        self.assertNotIn('VENDOR_UNSAFE_DETAIL', self.panel.status.text())

    def test_production_readiness_is_always_blocked_even_for_inconsistent_snapshot(self):
        view = connected_view()
        self.panel.apply(
            replace(
                view, readiness=tuple(replace(item, state='READY', reason='ready') if item.code == 'production_orders' else item for item in view.readiness)
            )
        )
        label = self.panel.readiness_labels['production_orders']
        self.assertIn(ui_text('m2.connection.production_disabled'), label.text())
        self.assertEqual(label.property('sinopacStatus'), 'BLOCKED')

    def test_disconnect_refuses_if_a_new_connection_arrives_during_confirmation(self):
        self.panel.apply(connected_view())
        emitted = QSignalSpy(self.panel.disconnect_requested)

        def confirm(value):
            self.panel.apply(replace(connected_view(2), generation='replacement-generation'))
            return True

        self.panel.confirm = confirm
        self.panel.disconnect_button.click()
        self.assertEqual(emitted.count(), 0)
        self.assertEqual(self.panel.view.generation, 'replacement-generation')
        self.assertEqual(self.panel.status.text(), ui_text('m2.connection.state_conflict'))

    def test_final_backend_account_and_callback_failures_have_chinese_next_steps(self):
        self.panel.apply(
            SinopacConnectionView(
                revision=1,
                error_code='callback_failed',
                readiness=(
                    SinopacReadiness('market', 'UNKNOWN', 'callback_failed'),
                    SinopacReadiness('accounts', 'UNKNOWN', 'accounts_unavailable'),
                    SinopacReadiness('simulation_orders', 'BLOCKED', 'implementation_pending'),
                    SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
                ),
            )
        )
        self.assertIn(ui_text('m2.connection.outcome_unknown'), self.panel.status.text())
        self.assertIn(ui_text('m2.connection.outcome_unknown'), self.panel.readiness_labels['market'].text())
        self.assertIn(ui_text('m2.connection.account_unavailable'), self.panel.readiness_labels['accounts'].text())
        self.assertIn(ui_text('m2.connection.unknown'), self.panel.readiness_labels['accounts'].text())
        for label in self.panel.findChildren(QLabel):
            self.assertNotIn('callback_failed', label.text())
            self.assertNotIn('accounts_unavailable', label.text())
