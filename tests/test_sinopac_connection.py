"""Explicit fake-only unified connection intents, CAS and reference persistence."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from threading import Event
from unittest.mock import patch
import unittest

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.application.contracts import UiAction, UiCommand
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.runtime.sinopac_connection import SinopacConnection
from test_market_session import FakeApi, FakeSecrets


class UnifiedConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.api, self.secrets, self.creations = FakeApi(), FakeSecrets(), []
        self.account = SimpleNamespace(account_type='S', broker_id='9A95', account_id='1234567', signed=True, person_id='PRIVATE_PERSON')
        self.api.list_accounts = lambda: [self.account]
        self.api.list_positions = lambda **kw: []
        module = SimpleNamespace(__version__='1.7.9', QuoteType=lambda value: value, QuoteVersion=lambda value: value, Unit=lambda value: value)

        def factory(environment):
            self.creations.append(environment)
            return ShioajiSDKFacade(self.api, module, environment=environment)

        self.factory = factory
        self.clock = SimpleNamespace(now=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.owner = SinopacConnection(Path(self.temp.name), factory=factory, secrets=self.secrets, clock=self.clock)
        self.addCleanup(self.owner.close)

    def command(self, action, **kwargs):
        view = self.owner.snapshot()
        return UiCommand(action, 0, connection_revision=view.revision, connection_generation=view.generation, **kwargs)

    def connect(self):
        receipt = self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings()))
        self.assertTrue(receipt.accepted)
        self.owner.worker.join(2)
        self.assertFalse(self.owner.worker.is_alive())
        self.assertEqual(self.owner.snapshot().phase, 'CONNECTED')

    def test_startup_never_resolves_credentials_and_connect_does_not_select_accounts(self):
        self.assertEqual(self.creations, [])
        self.assertEqual(self.secrets.references, [])
        self.connect()
        view = self.owner.snapshot()
        self.assertEqual(len(view.accounts), 1)
        self.assertIn('***', view.accounts[0].label)
        self.assertNotIn(self.account.account_id, repr(view))
        self.assertNotIn(self.account.person_id, repr(view))
        self.assertTrue(view.accounts[0].signed)
        self.assertFalse(view.accounts[0].selected)
        self.assertEqual(len(self.secrets.references), 1)
        self.assertEqual(self.creations, [Environment.BROKER_SIMULATION])
        self.assertEqual(next(item.state for item in view.readiness if item.code == 'market'), 'READY')
        self.assertEqual(next(item.reason for item in view.readiness if item.code == 'accounts'), 'accounts_not_selected')

    def test_selection_cas_persisted_alias_and_single_native_logout(self):
        self.connect()
        before = self.owner.snapshot()
        alias = before.accounts[0].alias
        select = self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,))
        self.assertTrue(self.owner.execute(select).accepted)
        self.owner.worker.join(2)
        accepted = self.owner.snapshot()
        self.assertTrue(accepted.accounts[0].selected)
        self.assertGreater(accepted.revision, before.revision)
        self.assertEqual(accepted.revision, self.owner.snapshot().revision)
        self.assertFalse(self.owner.execute(select).accepted)
        self.assertTrue(self.owner.execute(self.command(UiAction.DISCONNECT_SINOPAC)).accepted)
        self.owner.worker.join(2)
        self.assertEqual(self.owner.snapshot().phase, 'DISCONNECTED')
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 1)
        reloaded = SinopacConnection(Path(self.temp.name), factory=self.factory, secrets=self.secrets, clock=self.clock)
        try:
            self.assertEqual(reloaded.selected, (alias,))
            self.assertEqual(reloaded.snapshot().phase, 'DISCONNECTED')
            self.assertEqual(len(self.creations), 1)
        finally:
            reloaded.close()

    def test_failed_logout_blocks_replacement_factory(self):
        self.connect()
        self.api.logout = lambda: False
        self.assertTrue(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings())).accepted)
        self.owner.worker.join(2)
        self.assertTrue(self.owner.cleanup_unconfirmed)
        self.assertEqual(len(self.creations), 1)
        self.assertEqual(self.owner.snapshot().error_code, 'logout_unconfirmed')
        self.assertFalse(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings())).accepted)

    def test_late_login_candidate_is_rejected_and_normally_logged_out(self):
        entered, release = Event(), Event()
        original_login = self.api.login

        def blocked_login(**kwargs):
            entered.set()
            release.wait(2)
            return original_login(**kwargs)

        self.api.login = blocked_login
        self.assertTrue(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings())).accepted)
        self.assertTrue(entered.wait(1))
        with patch('quantlab.trading.runtime.sinopac_connection.monotonic', return_value=self.owner.deadline + 1):
            self.assertEqual(self.owner.snapshot().error_code, 'connection_timeout')
        release.set()
        self.owner.worker.join(2)
        self.assertIsNone(self.owner.shared)
        self.assertIsNone(self.owner.session)
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 1)
        self.assertEqual(next(item.state for item in self.owner.snapshot().readiness if item.code == 'market'), 'BLOCKED')

    def test_failed_adoption_callback_releases_candidate_without_private_error(self):
        self.owner.on_connected = lambda session: (_ for _ in ()).throw(ValueError('PRIVATE_PERSON SECRET'))
        self.assertTrue(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings())).accepted)
        self.owner.worker.join(2)
        self.assertIsNone(self.owner.shared)
        self.assertIsNone(self.owner.session)
        self.assertEqual(sum(call[0] == 'logout' for call in self.api.calls), 1)
        self.assertNotIn('PRIVATE_PERSON', repr(self.owner.snapshot()))

    def test_late_account_query_cannot_persist_selection(self):
        self.connect()
        entered, release = Event(), Event()
        alias = self.owner.snapshot().accounts[0].alias

        def blocked_positions(**kwargs):
            entered.set()
            release.wait(2)
            return []

        self.api.list_positions = blocked_positions
        self.assertTrue(self.owner.execute(self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,))).accepted)
        self.assertTrue(entered.wait(1))
        with patch('quantlab.trading.runtime.sinopac_connection.monotonic', return_value=self.owner.deadline + 1):
            self.assertEqual(self.owner.snapshot().error_code, 'connection_timeout')
        release.set()
        self.owner.worker.join(2)
        self.assertEqual(self.owner.selected, ())
        self.assertTrue(self.owner.session.connected)
        self.assertFalse(self.owner.snapshot().accounts[0].selected)

    def test_factory_environment_mismatch_never_resolves_credentials_or_logs_in(self):
        self.owner.factory = lambda environment: self.factory(Environment.LIVE)
        self.assertTrue(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=SinopacConnectionSettings())).accepted)
        self.owner.worker.join(2)
        self.assertEqual(self.secrets.references, [])
        self.assertFalse(any(call[0] == 'login' for call in self.api.calls))

    def test_optional_fake_ca_uses_selected_person_id_and_password_reference(self):
        self.connect()
        alias = self.owner.snapshot().accounts[0].alias
        self.owner.execute(self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,)))
        self.owner.worker.join(2)
        path = Path(self.temp.name) / 'fake-only.pfx'
        path.write_bytes(b'not a certificate')
        references = []
        self.secrets.certificate_password = lambda reference: references.append(reference) or 'FAKE_PASSWORD'

        def activate(**kwargs):
            self.assertEqual(kwargs['person_id'], self.account.person_id)
            self.assertEqual(kwargs['ca_passwd'], 'FAKE_PASSWORD')
            return True

        self.api.activate_ca = activate
        settings = SinopacConnectionSettings(certificate_path=str(path))
        self.assertTrue(self.owner.execute(self.command(UiAction.ACTIVATE_SINOPAC_CA, sinopac_settings=settings)).accepted)
        self.owner.worker.join(2)
        self.assertEqual(self.owner.snapshot().certificate_status, 'READY')
        self.assertEqual(references, ['MarkAuto/v2/certificate/sinopac'])
        self.assertNotIn('FAKE_PASSWORD', repr(self.owner.snapshot()))

    def test_live_certificate_intent_and_executor_never_read_password_or_call_sdk(self):
        from unittest.mock import Mock
        from quantlab.trading.runtime.sinopac_certificate import activate_certificate
        from quantlab.trading.domain.validation import DomainError

        path = Path(self.temp.name) / 'fake-live-only.pfx'
        path.write_bytes(b'not a certificate')
        settings = SinopacConnectionSettings(Environment.LIVE, certificate_path=str(path))
        self.assertTrue(self.owner.execute(self.command(UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=settings)).accepted)
        self.owner.worker.join(2)
        self.assertEqual(self.owner.snapshot().phase, 'CONNECTED')
        alias = self.owner.snapshot().accounts[0].alias
        self.assertTrue(self.owner.execute(self.command(UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=(alias,))).accepted)
        self.owner.worker.join(2)
        self.secrets.certificate_password = Mock(return_value='FAKE_PASSWORD')
        self.api.activate_ca = Mock(return_value=True)
        before = self.owner.snapshot()
        receipt = self.owner.execute(self.command(UiAction.ACTIVATE_SINOPAC_CA, sinopac_settings=settings))
        if receipt.accepted:
            self.owner.worker.join(2)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'production_orders_disabled')
        self.assertEqual(self.owner.snapshot(), before)
        with self.assertRaises(DomainError) as error:
            activate_certificate(self.owner, settings, self.owner.ticket)
        self.assertEqual(error.exception.code, 'production_orders_disabled')
        self.secrets.certificate_password.assert_not_called()
        self.api.activate_ca.assert_not_called()


if __name__ == '__main__':
    unittest.main()
