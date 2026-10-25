"""Application-only navigation races; these stubs make no broker claim."""

from dataclasses import replace
from decimal import Decimal
from threading import Event, Thread
import unittest

from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import AccountView, ContextOption, UiAction, UiCommand, UiReceipt, UiState
from quantlab.trading.domain.models import Environment, Market


class ViewStub:
    def __init__(self, environment, account, version, marker):
        local = environment is Environment.LOCAL
        self.state = UiState(
            environment,
            account,
            'STOPPED' if local else 'DISCONNECTED',
            '',
            Decimal('100000'),
            Decimal('0') if local else None,
            Decimal('2000') if local else None,
            'NO_DATA',
            version,
            '',
            local,
            accounts=(AccountView(account, environment, Market.STOCK, Decimal('100000'), 'EXTERNAL_REQUIRED'),),
            events=(marker,),
            financial_facts_verified=local,
        )
        self.commands = []

    def snapshot(self):
        return self.state

    def execute(self, command):
        self.commands.append(command)
        self.state = replace(self.state, version=self.state.version + 1)
        return UiReceipt(True, 'completed', '')


class NavigationStub:
    def __init__(self):
        self.options = (
            ContextOption('local', '', Environment.LOCAL, ('local-stock',)),
            ContextOption('broker', 'explicit-broker', Environment.BROKER_SIMULATION, ('test-stock',)),
        )
        self.facades = {
            'local': ViewStub(Environment.LOCAL, 'local-stock', 90, 'LOCAL_BOOK'),
            'broker': ViewStub(Environment.BROKER_SIMULATION, 'test-stock', 1, 'BROKER_BOOK'),
        }
        self.fail_open = self.fail_save = False
        self.entered = self.release = None
        self.opened = []
        self.selected = ('local', 'local-stock')

    def list_contexts(self):
        return self.options

    def open_context(self, context_id, account_ref):
        self.opened.append((context_id, account_ref))
        if self.entered:
            self.entered.set()
            if not self.release.wait(2):
                raise TimeoutError('owned fixture release missing')
        if self.fail_open:
            raise ConnectionError('synthetic target unavailable')
        return self.facades[context_id]

    def persist_selection(self, context_id, account_ref):
        if self.fail_save:
            raise OSError('synthetic registry disk error')
        self.selected = context_id, account_ref

    def register_profile(self, profile_ref, environment):
        return self.options[1]


class ContextNavigationTests(unittest.TestCase):
    def setUp(self):
        self.port = NavigationStub()
        self.client = CompositeFacade(self.port, 'local', self.port.facades['local'])

    def switch(self):
        return self.client.execute(
            UiCommand(UiAction.SWITCH_CONTEXT, 90, environment=Environment.BROKER_SIMULATION, account_ref='test-stock', context_id='broker', context_epoch=0)
        )

    def test_lower_target_version_is_a_new_epoch_without_book_data_union(self):
        result = self.switch()
        self.assertTrue(result.accepted, result)
        after = self.client.snapshot()
        self.assertEqual((after.context_id, after.context_epoch, after.version), ('broker', 1, 1))
        self.assertEqual(after.events, ('BROKER_BOOK',))
        self.assertIsNone(after.daily_pnl)
        self.assertFalse(after.financial_facts_verified)
        self.assertEqual(self.port.selected, ('broker', 'test-stock'))
        self.assertEqual(self.port.facades['local'].commands, [])

    def test_target_unavailable_or_wrong_mode_retains_original_context(self):
        before = self.client.snapshot()
        self.port.fail_open = True
        self.assertFalse(self.switch().accepted)
        self.assertEqual(self.client.snapshot(), before)
        self.port.fail_open = False
        self.port.facades['broker'].state = replace(self.port.facades['broker'].state, environment=Environment.LIVE)
        self.assertFalse(self.switch().accepted)
        self.assertEqual(self.client.snapshot(), before)

    def test_registry_commit_failure_does_not_replace_current(self):
        before = self.client.snapshot()
        self.port.fail_save = True
        self.assertFalse(self.switch().accepted)
        self.assertEqual(self.client.snapshot(), before)

    def test_old_account_epoch_cannot_mutate_current_book(self):
        self.assertTrue(self.switch().accepted)
        receipt = self.client.execute(UiCommand(UiAction.SAVE_SETTINGS, 1, context_id='broker', context_epoch=0))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertEqual(self.port.facades['broker'].commands, [])

    def test_stop_during_target_start_is_current_scoped_and_prevents_hiding_old_book(self):
        self.port.entered, self.port.release = Event(), Event()
        results = []
        worker = Thread(target=lambda: results.append(self.switch()))
        worker.start()
        try:
            self.assertTrue(self.port.entered.wait(1))
            stopped = self.client.execute(UiCommand(UiAction.STOP_NEW, 90, context_id='local', context_epoch=0))
            self.assertTrue(stopped.accepted)
        finally:
            self.port.release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(results[0].accepted)
        self.assertEqual((self.client.snapshot().context_id, self.client.snapshot().version), ('local', 91))
        self.assertEqual(self.port.selected, ('local', 'local-stock'))
        self.assertEqual(self.port.facades['broker'].commands, [])

    def test_legal_background_book_update_does_not_cancel_pure_navigation(self):
        self.port.entered, self.port.release = Event(), Event()
        results = []
        worker = Thread(target=lambda: results.append(self.switch()))
        worker.start()
        try:
            self.assertTrue(self.port.entered.wait(1))
            local = self.port.facades['local']
            local.state = replace(local.state, version=91, events=('LEGAL_BACKGROUND_REPORT',))
        finally:
            self.port.release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0].accepted, results)
        self.assertEqual(self.client.snapshot().context_id, 'broker')
        self.assertEqual(self.port.facades['local'].state.events, ('LEGAL_BACKGROUND_REPORT',))

    def test_second_switch_cannot_commit_while_first_target_is_opening(self):
        self.port.entered, self.port.release = Event(), Event()
        results = []
        worker = Thread(target=lambda: results.append(self.switch()))
        worker.start()
        try:
            self.assertTrue(self.port.entered.wait(1))
            self.assertFalse(self.switch().accepted)
        finally:
            self.port.release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0].accepted)
        self.assertEqual(self.client.snapshot().context_epoch, 1)
        self.assertEqual(self.port.opened, [('broker', 'test-stock')])


if __name__ == '__main__':
    unittest.main()
