"""Revoked execution consumers cannot retain native financial authority."""

from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from test_trading_sdk_facade import StrictSDK, contract


class ConsumerExecutionTests(unittest.TestCase):
    def session(self, environment=Environment.BROKER_SIMULATION):
        native = StrictSDK()
        native.simulation = True
        native.signed = native.ca_activated = True
        owner = SharedSDKSession(ShioajiSDKFacade(native, SimpleNamespace(__version__='1.7.9'), environment=environment))
        owner.login(api_key='fake', secret_key='fake')
        return native, owner, owner.consumer('market'), owner.consumer('execution')

    def operations(self, execution):
        return (
            lambda: execution.place_order(contract(), object()),
            lambda: execution.update_order(object(), price=20.0, qty=1),
            lambda: execution.cancel_order(object()),
        )

    def assert_no_mutations(self, native):
        self.assertEqual([row for row in native._seen if row[0] in ('place_order', 'update_order', 'cancel_order')], [])

    def test_detached_execution_revokes_all_mutations_without_logging_out_market(self):
        native, owner, market, execution = self.session()
        execution.logout()
        for operation in self.operations(execution):
            with self.assertRaises(DomainError) as error:
                operation()
            self.assertEqual(error.exception.code, 'market_data_not_connected')
        self.assert_no_mutations(native)
        self.assertFalse(any(row[0] == 'logout' for row in native._seen))
        self.assertIs(owner._consumers['market'], market)

    def test_closed_owner_revokes_all_mutations(self):
        native, owner, _, execution = self.session()
        owner.close()
        for operation in self.operations(execution):
            with self.assertRaises(DomainError):
                operation()
        self.assert_no_mutations(native)
        self.assertEqual(sum(row[0] == 'logout' for row in native._seen), 1)

    def test_active_live_consumer_cannot_override_immutable_environment(self):
        native, _, _, execution = self.session(Environment.LIVE)
        for operation in self.operations(execution):
            with self.assertRaises(DomainError) as error:
                operation()
            self.assertEqual(error.exception.code, 'production_orders_disabled')
        self.assert_no_mutations(native)

    def test_active_sim_calls_hold_lifecycle_lock_and_keep_bounded_sdk_budget(self):
        native, owner, _, execution = self.session()
        original = native._record

        def record(name, *args, **kwargs):
            self.assertTrue(owner._operations.locked())
            self.assertEqual(kwargs['timeout'], 10000)
            return original(name, *args, **kwargs)

        native._record = record
        for operation in self.operations(execution):
            operation()
        self.assertEqual([row[0] for row in native._seen][-3:], ['place_order', 'update_order', 'cancel_order'])

    def test_price_only_amend_omits_quantity_for_base_and_shared_facades(self):
        native, owner, _, execution = self.session()
        seen = []

        def update(trade, *, price, timeout):
            seen.append((trade, price, timeout))
            return trade

        native.update_order = update
        trade = object()
        self.assertIs(owner.facade.update_order(trade, price=21.0), trade)
        self.assertIs(execution.update_order(trade, price=22.0), trade)
        self.assertEqual(seen, [(trade, 21.0, 10000), (trade, 22.0, 10000)])
        with self.assertRaises(DomainError):
            execution.update_order(trade)
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
