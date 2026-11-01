"""Reference-only connection intents preserve old wire defaults and SDK isolation."""

from dataclasses import replace
from decimal import Decimal
import json
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import UiAction, UiCommand, UiState
from quantlab.trading.application.registry import initialize
from quantlab.trading.application.sinopac_contracts import (
    SinopacAccountView,
    SinopacConnectionSettings,
    SinopacConnectionView,
    SinopacReadiness,
)
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError


class SinopacContractTests(unittest.TestCase):
    def setUp(self):
        initialize()

    def test_reference_defaults_and_malformed_user_settings(self):
        settings = SinopacConnectionSettings()
        self.assertIs(settings.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(settings.key_ref, 'MarkAuto/v2/broker/sinopac')
        self.assertEqual(settings.certificate_secret_ref, 'MarkAuto/v2/certificate/sinopac')
        for fields in (
            {'environment': Environment.LOCAL},
            {'environment': 'LIVE'},
            {'key_ref': 'RAW_API_KEY_SENTINEL'},
            {'certificate_secret_ref': 'RAW_PASSWORD_SENTINEL'},
            {'certificate_path': 'relative.pfx'},
            {'fee_discount': Decimal('NaN')},
            {'fee_discount': Decimal('0')},
            {'fee_discount': Decimal('1.1')},
        ):
            with self.subTest(fields=tuple(fields)), self.assertRaises(DomainError):
                replace(settings, **fields)

    def test_all_connection_intents_roundtrip_separate_generation_and_revision(self):
        settings = SinopacConnectionSettings(Environment.LIVE)
        for action in (
            UiAction.SAVE_AND_CONNECT_SINOPAC,
            UiAction.SELECT_SINOPAC_ACCOUNTS,
            UiAction.ACTIVATE_SINOPAC_CA,
            UiAction.DISCONNECT_SINOPAC,
        ):
            command = UiCommand(
                action,
                91,
                sinopac_settings=settings,
                sinopac_accounts=('sinopac-stock-aabb',),
                connection_revision=7,
                connection_generation='generation-a',
            )
            self.assertEqual(loads(dumps(command)), command)

    def test_old_commands_and_states_decode_without_new_fields(self):
        command = UiCommand(UiAction.CHECK_READINESS, 8)
        body = json.loads(dumps(command))
        for name in ('sinopac_settings', 'sinopac_accounts', 'connection_revision', 'connection_generation'):
            body['fields'].pop(name)
        self.assertEqual(loads(json.dumps(body)), command)
        state = UiState(Environment.LOCAL, 'local-stock', 'STOPPED', '', Decimal('0'), None, None, '', 8, '', True)
        body = json.loads(dumps(state))
        body['fields'].pop('sinopac_connection')
        self.assertEqual(loads(json.dumps(body)), state)
        self.assertIsNone(state.sinopac_connection.environment)
        self.assertEqual(state.sinopac_connection.phase, 'DISCONNECTED')

    def test_redacted_accounts_and_four_readiness_facts_survive_wire(self):
        account = SinopacAccountView('sinopac-stock-aabb', '9A95-***1234', Market.STOCK, None, selected=True)
        view = SinopacConnectionView(
            revision=4,
            generation='generation-a',
            environment=Environment.BROKER_SIMULATION,
            phase='CONNECTED',
            accounts=(account,),
            readiness=(
                SinopacReadiness('market', 'READY', ''),
                SinopacReadiness('accounts', 'UNKNOWN', 'account_query_unavailable'),
                SinopacReadiness('simulation_orders', 'BLOCKED', 'implementation_pending'),
                SinopacReadiness('production_orders', 'BLOCKED', 'production_orders_disabled'),
            ),
        )
        self.assertEqual(loads(dumps(view)), view)
        self.assertIsNone(view.accounts[0].signed)
        with self.assertRaises(DomainError):
            replace(account, label='9A95-1234567')
        with self.assertRaises(DomainError):
            replace(view, readiness=view.readiness[:3])


if __name__ == '__main__':
    unittest.main()
