"""Offline SDK and gateway fixtures; no broker imports, IO or credentials."""

from dataclasses import replace
from types import SimpleNamespace

from quantlab.trading.adapters.shioaji import InstrumentBinding, ShioajiAdapter, SDK_VERSION
from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.domain.models import Environment, Market
from test_trading_adapters import MutableClock, instrument, NOW
from test_trading_sdk_facade import QuoteType, QuoteVersion, Unit


class TickSDK:
    def __init__(self, specs):
        self.callbacks = {}
        self.calls = []
        self.contracts = SimpleNamespace(get=self.get, info=self.info)
        self.specs = {str(i): spec for i, spec in enumerate(specs)}

    def get(self, code):
        return SimpleNamespace(code=code, security_type='FUT', exchange='TAIFEX', region='TW')

    def info(self, contract):
        spec = self.specs[contract.code]
        return SimpleNamespace(
            **vars(contract),
            delivery_month=spec.delivery_month,
            delivery_date=spec.expiry,
            multiplier=spec.multiplier,
            tick=spec.tick_size,
            tick_basis='fixed',
            tick_rule=None,
        )

    def set_on_tick_stk_v1_callback(self, callback, bind=False):
        self.calls.append(('stk', bind))
        self.callbacks['stk'] = callback

    def set_on_tick_fop_v1_callback(self, callback, bind=False):
        self.calls.append(('fop', bind))
        self.callbacks['fop'] = callback

    def subscribe(self, contract, *, quote_type, version):
        self.calls.append(('subscribe', contract.code, quote_type, version))

    def unsubscribe(self, contract, *, quote_type, version):
        self.calls.append(('unsubscribe', contract.code, quote_type, version))

    def set_session_down_callback(self, callback):
        self.callbacks['session_down'] = callback

    def list_accounts(self):
        return []

    def logout(self):
        return None

    def emit(self, code='0', *, kind='fop', **changes):
        raw = SimpleNamespace(**dict({'code': code, 'datetime': NOW, 'close': 100.25, 'volume': 1}, **changes))
        return self.callbacks[kind]('TAIFEX', raw)


class TickResolver:
    def session_at(self, instrument_id, timestamp):
        from datetime import timedelta

        return timestamp.date() + timedelta(days=1), 'NIGHT'


def tick_gateway(*, sdk_type=TickSDK, **kwargs):
    specs = tuple(replace(instrument(Market.INDEX_FUTURE), instrument_id=f'WATCH:{i}') for i in range(25))
    sdk, clock, resolver = sdk_type(specs), MutableClock(), TickResolver()
    module = SimpleNamespace(__version__=SDK_VERSION, Unit=Unit, QuoteType=QuoteType, QuoteVersion=QuoteVersion)
    facade = ShioajiSDKFacade(sdk, module)
    gateway = ShioajiAdapter(
        facade,
        clock,
        Environment.BROKER_SIMULATION,
        {},
        tuple(InstrumentBinding(spec, str(i)) for i, spec in enumerate(specs)),
        (),
        {},
        sdk_version=SDK_VERSION,
        session_resolver=resolver,
        quote_version='v1',
        **kwargs,
    )
    gateway.connected = True  # Explicit fake session; never authenticate.
    return gateway, sdk, clock, resolver
