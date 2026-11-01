"""Single native owner, independent callback consumers and subscription leases."""

from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.adapters.shioaji.shared_session import SharedSDKSession
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from test_trading_sdk_facade import QuoteType, QuoteVersion, contract


class SharedSessionTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.callbacks = [], {}
        client = SimpleNamespace(
            login=lambda **kw: self.calls.append(('login', kw)) or [],
            logout=lambda: self.calls.append(('logout',)),
            subscribe=lambda item, **kw: self.calls.append(('subscribe', item.code, kw)),
            unsubscribe=lambda item, **kw: self.calls.append(('unsubscribe', item.code, kw)),
            set_on_tick_stk_v1_callback=lambda cb, **kw: self.callbacks.setdefault('tick', []).append(cb),
            set_order_callback=lambda cb: self.callbacks.setdefault('order', []).append(cb),
        )
        module = SimpleNamespace(__version__='1.7.9', QuoteType=QuoteType, QuoteVersion=QuoteVersion)
        self.owner = SharedSDKSession(ShioajiSDKFacade(client, module, environment=Environment.BROKER_SIMULATION))
        self.owner.login(api_key='fake', secret_key='fake')
        self.market, self.engine = self.owner.consumer('market'), self.owner.consumer('engine')

    def test_one_native_callback_fans_out_and_detach_preserves_other(self):
        seen = []
        self.market.set_on_tick_stk_v1_callback(lambda *args: seen.append(('market', args)))
        self.engine.set_on_tick_stk_v1_callback(lambda *args: seen.append(('engine', args)))
        self.assertEqual(len(self.callbacks['tick']), 1)
        self.callbacks['tick'][0]('TSE', 'tick')
        self.assertEqual([item[0] for item in seen], ['market', 'engine'])
        self.market.logout()
        self.callbacks['tick'][0]('TSE', 'next')
        self.assertEqual([item[0] for item in seen], ['market', 'engine', 'engine'])
        self.assertFalse(any(call[0] == 'logout' for call in self.calls))

    def test_shared_market_and_engine_tick_subscription_has_one_remote_lease(self):
        item = contract()
        self.market.market_subscribe(item)
        self.engine.subscribe(item, quote_type='tick', version='v1')
        self.assertEqual(sum(call[0] == 'subscribe' for call in self.calls), 1)
        self.market.market_subscribe(item, remove=True)
        self.assertEqual(sum(call[0] == 'unsubscribe' for call in self.calls), 0)
        self.engine.logout()
        self.assertEqual(sum(call[0] == 'unsubscribe' for call in self.calls), 1)
        self.owner.close()
        self.owner.close()
        self.assertEqual(sum(call[0] == 'login' for call in self.calls), 1)
        self.assertEqual(sum(call[0] == 'logout' for call in self.calls), 1)

    def test_callback_failure_isolated_and_explicit_health_degradation(self):
        seen = []
        self.market.set_order_callback(lambda *args: (_ for _ in ()).throw(ValueError('private payload')))
        self.engine.set_order_callback(lambda *args: seen.append(args))
        self.callbacks['order'][0]('order')
        self.assertEqual(seen, [('order',)])
        self.assertEqual(self.owner.callback_errors, 1)
        with self.assertRaises(DomainError):
            self.engine.login(api_key='fake', secret_key='fake', subscribe_trade=True)
        self.owner.close()
        with self.assertRaises(DomainError):
            self.owner.consumer('late')


if __name__ == '__main__':
    unittest.main()
