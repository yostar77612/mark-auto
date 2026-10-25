"""Query cache preserves failures, original timestamps and report disorder."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from quantlab.trading.domain.models import AccountSnapshot, CapabilitySnapshot, Environment, Market, OrderStatus, Quote
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.contracts import OrderEvent, RemoteSnapshot
from quantlab.trading.runtime.gateway_cache import ReadOnlyGatewayCache


class Clock:
    def __init__(self):
        self.current = datetime.now(timezone.utc)

    def now(self):
        return self.current


class QueryPort:
    def __init__(self, clock):
        self.clock, self.failure = clock, False
        self.calls = 0
        self.failure_code = 'outcome_unknown'
        self.remote_as_of = None
        self.capability = CapabilitySnapshot(
            'synthetic-stock',
            Environment.LIVE,
            frozenset((Market.STOCK,)),
            False,
            False,
            False,
            True,
            False,
            'SYNTHETIC_UNIT_TEST_NOT_BROKER',
            clock.now(),
            clock.now() + timedelta(days=1),
            'test-v1',
        )
        d = Decimal
        self.account = AccountSnapshot('synthetic-stock', Environment.LIVE, d('100000'), d('100000'), d('100000'), d('100000'), d('0'), d('0'), clock.now(), 0)
        self.reports = ()
        self.quote = Quote('TWSE:SYNTHETIC', d('10'), d('10.05'), d('10'), clock.now(), clock.now(), clock.now().date(), source='SYNTHETIC_TEST')

    def inspect(self, account):
        return self.capability

    def events(self, account, after_sequence=0):
        self.calls += 1
        if self.failure:
            raise DomainError(self.failure_code, 'injected disconnection')
        return self.reports

    def refresh(self, account):
        return RemoteSnapshot(self.account, (), (), max((r.sequence for r in self.reports), default=0), self.remote_as_of or self.clock.now())

    def latest(self, instrument):
        return self.quote


class QueryCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.port = QueryPort(self.clock)
        self.elapsed = 0.0
        self.cache = ReadOnlyGatewayCache(self.port, ('synthetic-stock',), Environment.LIVE, self.clock, elapsed=lambda: self.elapsed)

    def poll(self):
        self.elapsed += 6
        self.cache.poll(('TWSE:SYNTHETIC',), cancelled=lambda: False)

    def test_disconnected_query_raises_instead_of_zero_money_or_empty_report_success(self):
        for operation in (self.cache.snapshot, self.cache.refresh, self.cache.events):
            with self.assertRaises(DomainError):
                operation('synthetic-stock')
        self.poll()
        self.assertEqual(self.cache.snapshot('synthetic-stock').equity, Decimal('100000'))
        self.port.failure = True
        self.poll()
        for operation in (self.cache.snapshot, self.cache.refresh, self.cache.events):
            with self.assertRaises(DomainError) as raised:
                operation('synthetic-stock')
            self.assertEqual(raised.exception.code, 'outcome_unknown')
        self.port.failure = False
        self.poll()
        self.assertEqual(self.cache.refresh('synthetic-stock').account, self.port.account)

    def test_out_of_order_and_conflicting_duplicate_are_preserved_for_core_reducer(self):
        accepted = OrderEvent('accept', 'owned-order', 'broker-id', OrderStatus.ACCEPTED, 0, 0, Decimal('0'), self.clock.now(), 1, 'SYNTHETIC_TEST')
        filled = OrderEvent('fill', 'owned-order', 'broker-id', OrderStatus.FILLED, 1000, 1000, Decimal('10'), self.clock.now(), 2, 'SYNTHETIC_TEST')
        changed = replace(filled, last_fill_price=Decimal('11'))
        self.port.reports = (filled, accepted, filled, changed)
        self.poll()
        self.assertEqual(self.cache.events('synthetic-stock'), (filled, accepted, changed))
        self.poll()
        self.assertEqual(self.cache.events('synthetic-stock'), (filled, accepted, changed))

    def test_cache_never_retimes_old_account_or_quote_to_make_it_fresh(self):
        self.poll()
        self.assertEqual(self.cache.latest('TWSE:SYNTHETIC').source_at, self.port.quote.source_at)
        self.assertEqual(self.cache.snapshot('synthetic-stock').as_of, self.port.account.as_of)
        self.clock.current += timedelta(seconds=31)
        with self.assertRaises(DomainError):
            self.cache.snapshot('synthetic-stock')
        self.assertEqual(self.cache.latest('TWSE:SYNTHETIC').source_at, self.port.quote.source_at)

    def test_fresh_receipt_cannot_publish_stale_or_future_nested_account_or_envelope(self):
        for label, nested_age, envelope_age in (
            ('old-nested-account', -31, 0),
            ('future-nested-account', 1, 0),
            ('old-envelope', 0, -31),
            ('future-envelope', 0, 1),
        ):
            with self.subTest(case=label):
                port = QueryPort(self.clock)
                port.account = replace(port.account, as_of=self.clock.now() + timedelta(seconds=nested_age))
                port.remote_as_of = self.clock.now() + timedelta(seconds=envelope_age)
                cache = ReadOnlyGatewayCache(port, ('synthetic-stock',), Environment.LIVE, self.clock)
                cache.poll((), cancelled=lambda: False)
                for getter in (cache.snapshot, cache.refresh, cache.inspect, cache.events):
                    with self.assertRaises(DomainError) as raised:
                        getter('synthetic-stock')
                    self.assertEqual(raised.exception.code, 'reconciliation_required')

    def test_repolling_same_old_nested_timestamp_does_not_renew_fact_lifetime(self):
        self.poll()
        self.clock.current += timedelta(seconds=31)
        self.poll()  # Envelope is new; account fact is the same old T0 value.
        for getter in (self.cache.snapshot, self.cache.refresh, self.cache.inspect, self.cache.events):
            with self.assertRaises(DomainError):
                getter('synthetic-stock')

    def test_invalid_injected_naive_clock_is_a_typed_failure(self):
        self.poll()
        self.clock.current = self.clock.current.replace(tzinfo=None)
        with self.assertRaises(DomainError):
            self.cache.snapshot('synthetic-stock')

    def test_readonly_cache_never_forwards_any_asset_command(self):
        for operation, args in ((self.cache.submit, (None, 'owned')), (self.cache.cancel, ('owned',)), (self.cache.amend, ('owned', Decimal('10')))):
            with self.assertRaises(DomainError) as raised:
                operation(*args)
            self.assertEqual(raised.exception.code, 'capability_missing')

    def test_cancelled_query_result_does_not_become_confirmed_facts(self):
        self.cache.poll(('TWSE:SYNTHETIC',), cancelled=lambda: True)
        with self.assertRaises(DomainError):
            self.cache.refresh('synthetic-stock')

    def test_rate_limit_waits_without_requerying_or_fabricating_recovery(self):
        self.port.failure = True
        self.port.failure_code = 'rate_limited'
        self.cache.poll((), cancelled=lambda: False)
        self.assertEqual(self.port.calls, 1)
        self.port.failure = False
        for when in (0.5, 1, 5, 29.9):
            self.elapsed = when
            self.cache.poll((), cancelled=lambda: False)
            self.assertEqual(self.port.calls, 1)
            with self.assertRaises(DomainError) as raised:
                self.cache.refresh('synthetic-stock')
            self.assertEqual(raised.exception.code, 'rate_limited')
        self.elapsed = 30
        self.cache.poll((), cancelled=lambda: False)
        self.assertEqual(self.port.calls, 2)
        self.assertEqual(self.cache.refresh('synthetic-stock').account, self.port.account)
