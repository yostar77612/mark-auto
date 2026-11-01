"""The facade's environment is explicit and cannot follow mutable SDK flags."""

from types import SimpleNamespace
import unittest

from quantlab.trading.adapters.shioaji.sdk_facade import ShioajiSDKFacade
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


class SinopacFacadeEnvironmentTests(unittest.TestCase):
    def test_environment_is_explicit_readonly_and_not_inferred_from_native_client(self):
        client = SimpleNamespace(simulation=False)
        facade = ShioajiSDKFacade(client, SimpleNamespace(__version__='1.7.9'), environment=Environment.BROKER_SIMULATION)
        self.assertIs(facade.environment, Environment.BROKER_SIMULATION)
        client.simulation = True
        with self.assertRaises(AttributeError):
            facade.environment = Environment.LIVE
        self.assertIs(facade.environment, Environment.BROKER_SIMULATION)

    def test_missing_or_untyped_environment_never_defaults_to_local(self):
        for value in (None, 'LIVE', Environment.LOCAL):
            with self.subTest(value=value), self.assertRaises(DomainError):
                ShioajiSDKFacade(object(), SimpleNamespace(__version__='1.7.9'), environment=value)
        with self.assertRaises(TypeError):
            ShioajiSDKFacade(object(), SimpleNamespace(__version__='1.7.9'))


if __name__ == '__main__':
    unittest.main()
