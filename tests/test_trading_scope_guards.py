"""Commit-time observations and current evidence protect owned positions."""

from dataclasses import replace
from decimal import Decimal
import unittest

import test_trading_application as lifecycle
from quantlab.trading.application.contracts import UiAction
from quantlab.trading.application.events import reconcile
from quantlab.trading.application.workflows import fill_local_pending
from quantlab.trading.domain.models import Market, Side
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import BrokerPosition


class ScopeGuardTests(unittest.TestCase):
    setUp = lifecycle.ApplicationLifecycleTests.setUp
    tearDown = lifecycle.ApplicationLifecycleTests.tearDown
    close_engine = lifecycle.ApplicationLifecycleTests.close_engine
    restart = lifecycle.ApplicationLifecycleTests.restart
    command = lifecycle.ApplicationLifecycleTests.command
    deploy = lifecycle.ApplicationLifecycleTests.deploy
    order_plan = lifecycle.ApplicationLifecycleTests.order_plan
    submit = lifecycle.ApplicationLifecycleTests.submit

    def test_unobserved_mobile_direction_flip_cannot_expand_short(self):
        reference = self.deploy(Market.INDEX_FUTURE)
        self.submit(reference)
        fill_local_pending(self.engine)
        lot = next(p for p in self.engine.state.positions if p.quantity)
        broker = self.engine.gateways[lot.account_ref]
        spec = self.engine.catalog.resolve(lot.instrument_id)
        broker.external_position(BrokerPosition(lot.account_ref, lot.instrument_id, -1, 1, spec.unit, lot.entry_price))
        before = broker.submission_count
        with self.assertRaises(DomainError) as caught:
            self.engine.exit_lot(lot.lot_id, protective=True)
        self.assertEqual(caught.exception.code, 'reconciliation_required')
        self.assertEqual(broker.submission_count, before)
        self.assertEqual(broker.refresh(lot.account_ref).positions[0].quantity, -1)
        self.assertEqual(self.engine.state.positions[0].sellable_quantity, 0)
        self.assertTrue(self.facade.snapshot().reconciliation)

    def test_new_version_cannot_net_old_policy_owned_lot(self):
        reference = self.deploy(Market.INDEX_FUTURE)
        self.submit(reference)
        fill_local_pending(self.engine)
        successor = self.deploy(Market.INDEX_FUTURE, parent=reference.split(':')[0], direction=Side.SELL)
        broker = self.engine.gateways['local-futures']
        before = broker.submission_count
        with self.assertRaises(DomainError) as caught:
            self.submit(successor, key='opposing-new-version')
        self.assertEqual(caught.exception.code, 'risk_rejected')
        self.assertEqual(broker.submission_count, before)
        self.assertEqual(self.engine.state.positions[0].direction, Side.BUY)
        self.assertEqual(self.engine.state.positions[0].strategy_version, 1)

    def test_current_cost_increase_revalues_owned_reservation(self):
        reference = self.deploy(Market.INDEX_FUTURE)
        self.submit(reference)
        fill_local_pending(self.engine)
        before = self.engine.reservations()[0]
        self.engine.fees = replace(self.engine.fees, futures_fee_per_contract=Decimal('800'))
        after = self.engine.reservations()[0]
        self.assertEqual(after.quantity, before.quantity)
        self.assertGreater(after.risk, before.risk)
        self.assertEqual(after.cash, before.cash)
        reconcile(self.engine)
        self.assertEqual(self.engine.reservations()[0].risk, after.risk)

    def test_changed_cost_values_with_same_version_require_new_research(self):
        reference = self.deploy()
        record = self.engine.strategy(reference)
        self.engine.update_strategy(replace(record, state='RESEARCHED'), 'test_stage_researched')
        self.engine.fees = replace(self.engine.fees, minimum_fee=Decimal('100'))
        receipt = self.command(UiAction.DEPLOY, target_id=reference, accepted=False)
        self.assertEqual(self.engine.strategy(reference).state, 'RESEARCHED')
        self.assertEqual(receipt.code, 'strategy_evidence_stale')
        self.assertIn('重新研究', receipt.message)

    def test_source_upgrade_preserves_lot_but_requires_new_entry_research(self):
        reference = self.deploy()
        self.submit(reference)
        fill_local_pending(self.engine)
        lot = self.engine.state.positions[0]
        self.close_engine()
        from unittest.mock import patch
        from quantlab.trading.application.provenance import ProducerProfile
        import hashlib
        import json
        import quantlab.trading.runtime.build as build

        profile = build.compute_profile()
        manifest = tuple((name, '0' * 64 if index == 0 else digest) for index, (name, digest) in enumerate(profile.source_manifest))
        digest = hashlib.sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        changed = ProducerProfile(profile.profile_id, 2, manifest, digest)
        with patch.object(build, 'compute_profile', return_value=changed):
            self.engine = build.create_engine(self.root / 'platform')
        self.facade = lifecycle.LocalFacade(self.engine)
        self.assertEqual(self.engine.state.positions[0], lot)
        self.assertEqual(self.engine.strategy(reference).state, 'RULE_VALID')
        self.assertIn('重新研究', self.facade.snapshot().strategies[0].evidence)
        self.assertTrue(self.engine.state.stopped)

    def test_delayed_terminal_ack_cannot_release_split_position_reservation(self):
        import test_trading_lifecycle as corporate
        from quantlab.trading.application.events import apply_event
        from quantlab.trading.application.lifecycle import schedule_corporate_action

        fixture = corporate.DurableLifecycleTests()
        fixture.fixture = self
        original = fixture.stock_position()
        _, spec, action = fixture.action()
        schedule_corporate_action(self.engine, original.instrument_id, spec, action)
        before = self.engine.reservations()[0]
        event = self.engine.gateways[original.account_ref].remote_state.events[-1]
        delayed = replace(event, event_id='late-filled-confirmation', sequence=event.sequence + 1, last_fill_quantity=0, last_fill_price=Decimal('0'))
        apply_event(self.engine, delayed)
        self.assertEqual(self.engine.reservations()[0], before)
        self.assertEqual(self.engine.reservations()[0].quantity, original.quantity * 2)


if __name__ == '__main__':
    unittest.main()
