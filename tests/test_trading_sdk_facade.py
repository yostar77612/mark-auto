"""Strict documented SDK shapes, without importing or constructing Shioaji.

These controls verify delegation/enum/timeout behavior, not a broker session.
The real 1.7.9 pure-model/wheel audit remains a separately identified evidence
level and never implies login, permissions or actual execution success.
"""

from datetime import date
from enum import Enum
from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.domain.validation import DomainError


class Unit(Enum):
    Common = 'Common'
    Share = 'Share'


class QuoteType(Enum):
    Tick = 'tick'
    BidAsk = 'bid_ask'
    Quote = 'quote'


class QuoteVersion(Enum):
    v1 = 'v1'


def contract(code='2330', *, futures=False, **changes):
    return SimpleNamespace(
        **dict(
            {'code': code, 'security_type': 'FUT' if futures else 'STK', 'exchange': 'TAIFEX' if futures else 'TSE', 'region': 'TW', 'target_code': None},
            **changes,
        )
    )


class StrictContractV2:
    def __init__(self, seen):
        self._seen = seen
        self._base = {'2330': contract(), 'TXFL6': contract('TXFL6', futures=True), 'CDFL6': contract('CDFL6', futures=True)}
        self._info = {
            code: SimpleNamespace(
                **{
                    **vars(base),
                    **(
                        {'unit': 1000.0, 'trading_suspended': False}
                        if code == '2330'
                        else {'delivery_month': '202612', 'delivery_date': date(2026, 12, 16), 'multiplier': 200.0, 'tick': 1.0}
                    ),
                }
            )
            for code, base in self._base.items()
        }

    # Contract V2 has no documented timeout keyword. The strict signatures make
    # invented timeout/fallback/legacy-category calls observable failures.
    def get(self, code):
        self._seen.append(('get', code))
        return self._base[code]

    def info(self, item):
        self._seen.append(('info', item.code))
        return self._info[item.code]


class StrictSDK:
    """Only documented signatures; every call is observed and may fail."""

    def __init__(self):
        self._seen = []
        self._contracts = StrictContractV2(self._seen)
        self._failure = {}
        self._accounts = [SimpleNamespace(account_type='S', broker_id='synthetic', account_id='offline', signed=False)]

    @property
    def contracts(self):
        self._seen.append(('contracts_access',))
        return self._contracts

    def _record(self, name, *args, **kwargs):
        self._seen.append((name, args, kwargs))
        if name in self._failure:
            raise self._failure[name]
        return SimpleNamespace(kind=name)

    def login(self, api_key, secret_key, subscribe_trade=True):
        self._record('login', subscribe_trade=subscribe_trade)
        return self._accounts

    def logout(self):
        self._record('logout')

    def activate_ca(self, ca_path, ca_passwd, person_id=None):
        self._record('activate_ca')
        return True

    def list_accounts(self):
        self._record('list_accounts')
        return self._accounts

    def account_balance(self, account=None, timeout=30000, cb=None):
        return self._record('account_balance', account=account, timeout=timeout)

    def trading_limits(self, account=None, timeout=30000, cb=None):
        return self._record('trading_limits', account=account, timeout=timeout)

    def margin(self, account=None, timeout=30000, cb=None):
        return self._record('margin', account=account, timeout=timeout)

    def settlements(self, account=None, timeout=30000, cb=None):
        self._record('settlements', account=account, timeout=timeout)
        return []

    def list_positions(self, account=None, unit=None, timeout=30000, cb=None):
        self._record('list_positions', account=account, unit=unit, timeout=timeout)
        return []

    def kbars(self, contract, start=None, end=None, timeout=30000, cb=None):
        return self._record('kbars', contract, start=start, end=end, timeout=timeout)

    def snapshots(self, contracts, timeout=30000, cb=None):
        self._record('snapshots', contracts, timeout=timeout)
        return []

    def subscribe(self, contract, quote_type=QuoteType.Tick, intraday_odd=False, version=None):
        self._record('subscribe', contract, quote_type=quote_type, version=version)

    def unsubscribe(self, contract, quote_type=QuoteType.Tick, intraday_odd=False, version=None):
        self._record('unsubscribe', contract, quote_type=quote_type, version=version)

    def place_order(self, contract, order, timeout=30000, cb=None):
        return self._record('place_order', contract, order, timeout=timeout)

    def update_order(self, trade, price=None, qty=None, timeout=30000, cb=None):
        return self._record('update_order', trade, price=price, qty=qty, timeout=timeout)

    def cancel_order(self, trade, timeout=30000, cb=None):
        return self._record('cancel_order', trade, timeout=timeout)

    def update_status(self, account=None, *, trade=None, timeout=30000, cb=None):
        self._record('update_status', account=account, timeout=timeout)

    def list_trades(self):
        self._record('list_trades')
        return []

    def set_on_tick_stk_v1_callback(self, callback, bind=False):
        self._record('set_on_tick_stk_v1_callback', callback, bind=bind)

    def set_on_bidask_stk_v1_callback(self, callback, bind=False):
        self._record('set_on_bidask_stk_v1_callback', callback, bind=bind)

    def set_on_tick_fop_v1_callback(self, callback, bind=False):
        self._record('set_on_tick_fop_v1_callback', callback, bind=bind)

    def set_on_bidask_fop_v1_callback(self, callback, bind=False):
        self._record('set_on_bidask_fop_v1_callback', callback, bind=bind)

    def set_order_callback(self, callback):
        self._record('set_order_callback', callback)

    def set_event_callback(self, callback):
        self._record('set_event_callback', callback)

    def set_session_down_callback(self, callback):
        self._record('set_session_down_callback', callback)


class SDKFacadeTests(unittest.TestCase):
    def setUp(self):
        self.vendor = StrictSDK()
        self.models = []

        def order(**values):
            self.models.append(values)
            return SimpleNamespace(**values)

        self.sdk_module = SimpleNamespace(__version__='1.7.9', Unit=Unit, QuoteType=QuoteType, QuoteVersion=QuoteVersion, Order=order)
        self.bridge = ShioajiSDKFacade(self.vendor, self.sdk_module)

    def test_construction_is_inert_and_does_not_even_access_lazy_contracts(self):
        self.assertEqual(self.vendor._seen, [])
        self.assertEqual(self.models, [])
        self.assertEqual(self.bridge.query_timeout_ms, 2500)
        self.assertEqual(self.bridge.order_timeout_ms, 10000)

    def test_contract_v2_real_codes_and_original_typed_info_are_preserved_for_three_markets(self):
        for code in ('2330', 'TXFL6', 'CDFL6'):
            base = self.bridge.contracts.get(code)
            info = self.bridge.contracts.info(base)
            self.assertIs(base, self.vendor._contracts._base[code])
            self.assertIs(info, self.vendor._contracts._info[code])
        self.assertIs(type(self.vendor._contracts._info['TXFL6'].delivery_date), date)

    def test_continuous_redirected_wrong_region_and_mismatched_results_fail_closed(self):
        with self.assertRaises(DomainError):
            self.bridge.contracts.get('TXFR1')
        self.assertEqual(self.vendor._seen, [])
        for replacement in (contract('TXFR1', futures=True), contract('2330', target_code='2317'), contract('2330', region='US')):
            self.vendor._contracts._base['2330'] = replacement
            with self.assertRaises(DomainError):
                self.bridge.contracts.get('2330')
        self.vendor._contracts._base['2330'] = contract()
        self.vendor._contracts._info['2330'] = contract('2317')
        with self.assertRaises(DomainError):
            self.bridge.contracts.info(self.bridge.contracts.get('2330'))

    def test_query_budgets_and_explicit_accounts_reach_only_supported_signatures(self):
        explicit = self.vendor._accounts[0]
        for method in ('account_balance', 'trading_limits', 'margin', 'settlements', 'update_status'):
            getattr(self.bridge, method)(account=explicit)
            self.assertEqual(self.vendor._seen[-1][2], {'account': explicit, 'timeout': 2500})
        for method in ('account_balance', 'trading_limits', 'margin', 'settlements', 'update_status'):
            before = len(self.vendor._seen)
            with self.assertRaises(DomainError):
                getattr(self.bridge, method)(account=None)
            self.assertEqual(len(self.vendor._seen), before)

    def test_share_common_units_and_quote_enums_are_actual_sdk_enum_values(self):
        explicit = self.vendor._accounts[0]
        for value in ('Share', Unit.Share, 'Common', Unit.Common):
            self.bridge.list_positions(account=explicit, unit=value)
            self.assertIsInstance(self.vendor._seen[-1][2]['unit'], Unit)
        self.bridge.subscribe(contract(), quote_type='tick', version='v1')
        self.assertEqual(self.vendor._seen[-1][2], {'quote_type': QuoteType.Tick, 'version': QuoteVersion.v1})
        self.bridge.unsubscribe(contract(), quote_type='bid_ask', version=QuoteVersion.v1)
        self.assertEqual(self.vendor._seen[-1][2], {'quote_type': QuoteType.BidAsk, 'version': QuoteVersion.v1})
        for value in (None, 'v0', 'v2'):
            with self.assertRaises(DomainError):
                self.bridge.subscribe(contract(), quote_type='tick', version=value)

    def test_bounded_history_snapshot_and_order_routes_have_injected_budgets(self):
        custom = ShioajiSDKFacade(self.vendor, self.sdk_module, query_timeout_ms=1700, order_timeout_ms=8000)
        base = contract()
        custom.kbars(contract=base, start='2026-10-01', end='2026-10-02')
        self.assertEqual(self.vendor._seen[-1][2]['timeout'], 1700)
        custom.snapshots([base])
        self.assertEqual(self.vendor._seen[-1][2]['timeout'], 1700)
        model = custom.Order(action='Buy', quantity=1, price=100.0, price_type='LMT', order_type='ROD')
        for method, args, kwargs in (
            ('place_order', (base, model), {}),
            ('update_order', (model,), {'price': 99.0, 'qty': 1}),
            ('cancel_order', (model,), {}),
        ):
            getattr(custom, method)(*args, **kwargs)
            self.assertEqual(self.vendor._seen[-1][2]['timeout'], 8000)
        self.assertEqual(len(self.models), 1)

    def test_methods_without_documented_timeout_never_receive_invented_keyword(self):
        accounts = self.bridge.login(api_key='synthetic-offline', secret_key='synthetic-offline', subscribe_trade=True)
        self.assertIs(accounts[0], self.vendor._accounts[0])
        self.assertIs(self.bridge.list_accounts()[0], accounts[0])
        self.assertEqual(self.bridge.list_trades(), [])
        self.assertTrue(self.bridge.activate_ca(ca_path='synthetic-only', ca_passwd='synthetic-only', person_id='synthetic-only'))
        self.bridge.logout()

    def test_timeout_exception_is_not_retried_or_changed_into_a_success(self):
        unknown = TimeoutError('synthetic vendor timeout')
        self.vendor._failure['place_order'] = unknown
        with self.assertRaises(TimeoutError) as caught:
            self.bridge.place_order(contract(), object())
        self.assertIs(caught.exception, unknown)
        self.assertEqual(sum(row[0] == 'place_order' for row in self.vendor._seen), 1)

    def test_callbacks_use_exact_documented_registration_and_keep_original_callable(self):
        def callback(*args):
            return None

        for name in ('set_on_tick_stk_v1_callback', 'set_on_bidask_stk_v1_callback', 'set_on_tick_fop_v1_callback', 'set_on_bidask_fop_v1_callback'):
            getattr(self.bridge, name)(callback, bind=False)
            self.assertIs(self.vendor._seen[-1][1][0], callback)
            self.assertEqual(self.vendor._seen[-1][2], {'bind': False})
        for name in ('set_order_callback', 'set_event_callback', 'set_session_down_callback'):
            getattr(self.bridge, name)(callback)
            self.assertIs(self.vendor._seen[-1][1][0], callback)
            self.assertEqual(self.vendor._seen[-1][2], {})

    def test_wrong_version_and_noninteger_or_unbounded_budgets_are_rejected(self):
        wrong = SimpleNamespace(__version__='1.5.0')
        with self.assertRaises(DomainError):
            ShioajiSDKFacade(self.vendor, wrong)
        for value in (None, False, 0, -1, 30001, 2.5, '2500'):
            for field in ('query_timeout_ms', 'order_timeout_ms'):
                with self.subTest(field=field, value=value), self.assertRaises(DomainError):
                    ShioajiSDKFacade(self.vendor, self.sdk_module, **{field: value})


if __name__ == '__main__':
    unittest.main()
