"""Manual intents remain scoped untrusted input across the existing IPC codec."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import unittest

from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.contracts import UiAction, UiCommand, UiState
from quantlab.trading.application.manual_contracts import (
    ManualBookForm,
    ManualInstrumentView,
    ManualMutationForm,
    ManualOrderForm,
    ManualPendingView,
    ManualPreviewView,
    ManualPurpose,
    ManualScope,
    ManualTradingView,
)
from quantlab.trading.application.registry import initialize
from quantlab.trading.domain.models import Environment, Market, PriceBand, QuantityUnit, Side
from quantlab.trading.domain.validation import DomainError


class ManualContractTests(unittest.TestCase):
    def test_manual_intents_cross_typed_wire_with_scope_and_decimal_money(self):
        initialize()
        scope = ManualScope('sim-context', 3, Environment.BROKER_SIMULATION, 'future-alias', 'generation-a', 7)
        order = ManualOrderForm(scope, 'request-a', 'TMFK6', Side.BUY, 1, Decimal('24900'), Decimal('24800'))
        for action, fields in (
            (UiAction.ENABLE_MANUAL_BOOK, {'manual_book': ManualBookForm(scope, Decimal('40000'), True)}),
            (UiAction.PREVIEW_MANUAL, {'manual_order': order}),
            (UiAction.SUBMIT_MANUAL, {'manual_order': replace(order, confirmed=True, preview_id='preview-a')}),
            (UiAction.TEST_SIM_ORDER, {'manual_order': replace(order, purpose=ManualPurpose.DIAGNOSTIC_TMF, confirmed=True)}),
            (UiAction.CANCEL_MANUAL, {'manual_mutation': ManualMutationForm(scope, 'cancel-a', 'order-a', confirmed=True)}),
            (UiAction.AMEND_MANUAL, {'manual_mutation': ManualMutationForm(scope, 'amend-a', 'order-a', Decimal('24910'), 1, True)}),
        ):
            with self.subTest(action=action):
                command = UiCommand(action, 31, connection_generation='generation-a', connection_revision=7, **fields)
                self.assertEqual(loads(dumps(command)), command)

    def test_old_wire_defaults_remain_disabled_without_manual_fields(self):
        initialize()
        command = UiCommand(UiAction.RECONCILE, 4)
        body = json.loads(dumps(command))
        for name in ('manual_book', 'manual_order', 'manual_mutation'):
            body['fields'].pop(name)
        self.assertEqual(loads(json.dumps(body)), command)
        state = UiState(Environment.BROKER_SIMULATION, 'future-alias', 'STOPPED', '', Decimal('0'), None, None, '', 4, '', False)
        body = json.loads(dumps(state))
        body['fields'].pop('manual')
        decoded = loads(json.dumps(body))
        self.assertEqual(decoded, state)
        self.assertIsNone(decoded.manual.capital)
        self.assertTrue(decoded.manual.halted)
        self.assertFalse(decoded.manual.can_submit)
        self.assertFalse(decoded.manual.can_test)

    def test_malformed_user_intents_reject_before_engine_dispatch(self):
        scope = ManualScope('sim-context', 0, Environment.BROKER_SIMULATION, 'future-alias', 'generation-a', 1)
        order = ManualOrderForm(scope, 'request-a', 'TMFK6', Side.BUY, 1, Decimal('24900'), Decimal('24800'))
        for fields in (
            {'quantity': True},
            {'quantity': 1.0},
            {'quantity': 0},
            {'limit_price': 24900.0},
            {'stop_price': Decimal('NaN')},
            {'purpose': 'DIAGNOSTIC_TMF'},
            {'confirmed': 1},
            {'side': 'BUY'},
            {'preview_id': 0},
        ):
            with self.subTest(fields=fields), self.assertRaises(DomainError):
                replace(order, **fields)
        for fields in ({'connection_generation': 1}, {'context_epoch': True}, {'environment': 'LIVE'}, {'account_ref': ''}):
            with self.subTest(fields=fields), self.assertRaises(DomainError):
                replace(scope, **fields)
        with self.assertRaises(DomainError):
            ManualBookForm(scope, Decimal('-1'), True)

    def test_projection_keeps_virtual_funds_and_unprotected_estimate_explicit(self):
        initialize()
        scope = ManualScope('sim-context', 0, Environment.BROKER_SIMULATION, 'future-alias', 'generation-a', 1)
        now = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
        preview = ManualPreviewView(
            scope,
            'request-a',
            'preview-a',
            'TMFK6',
            Side.BUY,
            1,
            Decimal('24900'),
            Decimal('24800'),
            ManualPurpose.MANUAL,
            True,
            Decimal('35105'),
            Decimal('1090'),
            Decimal('55'),
            Decimal('40000'),
            'APP_VIRTUAL_SIMULATION',
            'NAMED_FEE_ASSUMPTION',
            now,
            now + timedelta(seconds=30),
            quantity_unit=QuantityUnit.CONTRACT,
            lot_size=1,
        )
        instrument = ManualInstrumentView('TMFK6', 'TMF fixture', Market.INDEX_FUTURE, QuantityUnit.CONTRACT, 1, 1, Decimal('1'))
        stock = ManualInstrumentView(
            'STOCK-FIXTURE',
            'stock fixture',
            Market.STOCK,
            QuantityUnit.SHARE,
            1000,
            1000,
            None,
            price_bands=(PriceBand(Decimal('0'), Decimal('50'), Decimal('0.01')), PriceBand(Decimal('50'), None, Decimal('0.05'))),
        )
        view = ManualTradingView(
            scope,
            'book-a',
            Decimal('40000'),
            Decimal('40000'),
            confirmed=True,
            suggested_capital=Decimal('40000'),
            instruments=(instrument, stock),
            preview=preview,
            pending=ManualPendingView(scope, 'request-a', 'SUBMIT', status='UNKNOWN', reason='outcome_unknown'),
        )
        decoded = loads(dumps(view))
        self.assertEqual(decoded, view)
        self.assertEqual(decoded.source, 'APP_VIRTUAL_SIMULATION')
        self.assertEqual(decoded.suggested_capital, Decimal('40000'))
        self.assertIsNone(decoded.instruments[1].price_tick)
        self.assertEqual(decoded.instruments[1].quantity_step, 1000)
        self.assertEqual(decoded.preview.protection, 'UNPROTECTED')
        self.assertEqual(decoded.preview.quantity_unit, QuantityUnit.CONTRACT)
        self.assertEqual(decoded.preview.lot_size, 1)
        self.assertFalse(decoded.pending.outcome_known)
        self.assertEqual(decoded.pending.request_id, 'request-a')
        self.assertFalse(decoded.can_submit)
