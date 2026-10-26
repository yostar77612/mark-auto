"""Read-only context selection has its own generation fence, not a trading CAS."""

from dataclasses import replace
import unittest

from tests import test_context_navigation_v2 as navigation_support
from tests import test_trading_ui as support
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import ContextNavigationRequest, UiAction, UiCommand
from quantlab.trading.domain.models import Environment


class TracingFacade(CompositeFacade):
    def __init__(self, port):
        super().__init__(port, 'local', port.facades['local'])
        self.commands = []
        self.navigation_requests = []

    def execute(self, command):
        self.commands.append(command)
        return super().execute(command)

    def navigate_context(self, request):
        self.navigation_requests.append(request)
        return super().navigate_context(request)


class NavigationObservationTests(unittest.TestCase):
    setUpClass = support.TradingUiTests.__dict__['setUpClass']
    setUp = support.TradingUiTests.setUp
    tearDown = support.TradingUiTests.tearDown
    drain = support.TradingUiTests.drain

    def install_contexts(self, port):
        self.facade = TracingFacade(port)
        self.window.facade = self.facade
        self.window.apply_state(self.facade.snapshot())

    def navigate(self):
        self.window.command(UiAction.SWITCH_CONTEXT, context_id='broker', environment=Environment.BROKER_SIMULATION, account_ref='test-stock')
        self.drain()

    def test_read_only_navigation_survives_continuous_observation_changes(self):
        class AdvancingView(navigation_support.ViewStub):
            def snapshot(self):
                self.state = replace(self.state, version=self.state.version + 1)
                return self.state

        port = navigation_support.NavigationStub()
        port.facades['local'] = AdvancingView(Environment.LOCAL, 'local-stock', 90, 'LOCAL_BOOK')
        self.install_contexts(port)
        # The original version-bound command remains strict, even though this
        # new presentation request can tolerate observation-only journal changes.
        legacy = self.facade.execute(
            UiCommand(
                UiAction.SWITCH_CONTEXT,
                self.window.state.version,
                environment=Environment.BROKER_SIMULATION,
                account_ref='test-stock',
                context_id='broker',
                context_epoch=0,
            )
        )
        self.assertFalse(legacy.accepted)
        self.assertEqual(legacy.code, 'state_conflict')
        self.facade.commands.clear()
        self.navigate()
        self.assertEqual(len(self.facade.navigation_requests), 1)
        self.assertEqual(self.facade.commands, [])
        self.assertEqual(port.facades['local'].commands, [])
        self.assertEqual(port.facades['broker'].commands, [])
        self.assertEqual((self.window.state.context_id, self.window.state.context_epoch), ('broker', 1))
        self.assertIs(self.window.state.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(self.window.state.events, ('BROKER_BOOK',))
        self.assertFalse(self.window.state.financial_facts_verified)

    def test_wrong_source_epoch_or_target_never_changes_selected_book(self):
        port = navigation_support.NavigationStub()
        self.install_contexts(port)
        for source, epoch, environment, account in (
            ('local', 1, Environment.BROKER_SIMULATION, 'test-stock'),
            ('broker', 0, Environment.BROKER_SIMULATION, 'test-stock'),
            ('local', True, Environment.BROKER_SIMULATION, 'test-stock'),
            ('local', 0, Environment.LIVE, 'test-stock'),
            ('local', 0, Environment.BROKER_SIMULATION, 'wrong-account'),
        ):
            with self.subTest(source=source, epoch=epoch, environment=environment, account=account):
                receipt = self.facade.navigate_context(ContextNavigationRequest(source, epoch, 'broker', environment, account))
                self.assertFalse(receipt.accepted)
                self.assertEqual(port.selected, ('local', 'local-stock'))
                self.assertEqual(port.opened, [])
        self.assertFalse(self.facade.navigate_context(object()).accepted)

    def test_unknown_navigation_is_not_retried_and_financial_commands_keep_original_route(self):
        port = navigation_support.NavigationStub()
        port.fail_open = True
        self.install_contexts(port)
        self.navigate()
        self.assertEqual(len(self.facade.navigation_requests), 1)
        self.assertEqual(port.opened, [('broker', 'test-stock')])
        self.assertEqual(port.selected, ('local', 'local-stock'))
        self.assertIs(self.window.state.environment, Environment.LOCAL)
        self.assertEqual(self.facade.commands, [])
        # Synthetic facade only: no broker connector or real assets exist.
        self.window.command(UiAction.FLATTEN)
        self.drain()
        self.assertEqual([command.action for command in self.facade.commands], [UiAction.FLATTEN])
        self.assertEqual([command.action for command in port.facades['local'].commands], [UiAction.FLATTEN])
        self.assertEqual(port.facades['broker'].commands, [])
        self.assertEqual(len(self.facade.navigation_requests), 1)
