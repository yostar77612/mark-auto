"""Synthetic offline evidence only: no real broker compatibility is implied."""
import concurrent.futures
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, localcontext, ROUND_UP
from pathlib import Path
from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import Instrument, CostSpec, ValidationError
from quantlab.paper import PaperBroker, RiskLimits, JournalConflict, ReconciliationError, LiveBroker, LiveTradingDisabled

NOW = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
CID = 'TAIFEX:TMF:202610'


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'paper.sqlite'
        self.kw = dict(instrument=Instrument(CID, expiry='2026-10-21'),
                       costs=CostSpec(D('10'), D('.00002'), 0, 'half_up', '2026-01-01', 'synthetic-v1'),
                       limits=RiskLimits(5, 3, D('500'), 5),
                       risk_sessions=({'open': NOW-timedelta(minutes=15), 'end': NOW+timedelta(hours=4), 'trade_date': '2026-10-09', 'source': 'synthetic', 'session': 'day'},),
                       margin_schedule=({'effective_from':'2026-01-01','margin_per_contract':D('10000'),'version':'synthetic'},))
        self.broker = PaperBroker(self.path, **self.kw)
        self.broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))

    def intent(self, oid='a', **changes):
        value = dict(client_order_id=oid, strategy_hash='synthetic-strategy', contract_id=CID,
                     side='buy', quantity=1, order_type='market', created_at=NOW)
        value.update(changes)
        return value

    def quote(self, **changes):
        value = dict(account_id='synthetic', contract_id=CID, timestamp=NOW, price=D('20000'),
                     trade_date='2026-10-09', session_open=NOW-timedelta(minutes=15),
                     session_end=NOW+timedelta(hours=4), margin_per_contract=D('10000'))
        value.update(changes)
        return value

    def submit(self, oid='a', **changes):
        return self.broker.submit(self.intent(oid, **changes), quote=self.quote(), now=NOW)

    def event(self, oid='a', typ='fill', seq=1, **changes):
        value = dict(event_id=f'{oid}-{seq}', order_id=oid, sequence=seq, type=typ, timestamp=NOW)
        if typ == 'fill':
            value.update(fill_id=f'f-{oid}-{seq}', quantity=1, price=D('20000'), commission=D('10'), tax=D('4'))
        value.update(changes)
        return value

    def test_conflicting_event_latches_quarantine_across_restart(self):
        self.submit()
        original = self.event()
        self.broker.apply_event(original)
        before = self.broker.snapshot()
        with self.assertRaises(JournalConflict):
            self.broker.apply_event(dict(original, price='20001'))
        after = self.broker.snapshot()
        self.assertTrue(after['reconciliation_required'])
        self.assertTrue(after['quarantined'])
        self.assertEqual(after['fills'], before['fills'])
        self.assertEqual(after['cash'], before['cash'])
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        other = PaperBroker(self.path, **self.kw)
        with self.assertRaises(ReconciliationError):
            other.reconcile(other.snapshot())
        self.assertEqual(other.apply_event(original)['status'], 'duplicate')

    def test_truncated_event_freezes_without_manufacturing_fill(self):
        self.submit(quantity=2)
        event = self.event()
        del event['commission']
        with self.assertRaisesRegex(ValidationError, 'missing fill fields'):
            self.broker.apply_event(event)
        state = self.broker.snapshot()
        self.assertTrue(state['reconciliation_required'])
        self.assertFalse(state['fills'])
        self.assertFalse(state['positions'])
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        diagnostic = next(iter(state['quarantined'].values()))
        self.assertEqual(diagnostic['rejected_payload']['event_id'], event['event_id'])

    def test_simulated_transport_timeout_reattach_requires_resolution(self):
        # This is fault injection at the synthetic ACK boundary, not a socket/broker test.
        def timeout(point):
            if point == 'after_intent_commit':
                raise TimeoutError('simulated transport silence before ACK')
        self.broker._fault = timeout
        with self.assertRaises(TimeoutError):
            self.submit()
        self.broker._fault = lambda point: None
        self.assertEqual(self.submit()['status'], 'submitting')
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        self.broker = PaperBroker(self.path, **self.kw)
        state = self.broker.snapshot()
        self.assertEqual(state['orders']['a']['status'], 'unknown')
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(state)
        state['order_statuses'] = {'a': 'accepted'}
        self.broker.reconcile(state)
        self.assertEqual(self.submit()['status'], 'accepted')
        self.broker.apply_event(self.event())
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)
        self.assertEqual(len(self.broker.snapshot()['order_send_timestamps']), 1)

    def test_feed_silence_age_boundary_and_fresh_quote_recovery(self):
        boundary = NOW + timedelta(seconds=5)
        self.assertEqual(self.broker.submit(self.intent('boundary'), quote=self.quote(), now=boundary)['status'], 'accepted')
        stale = boundary + timedelta(microseconds=1)
        self.assertEqual(self.broker.submit(self.intent('stale'), quote=self.quote(), now=stale)['reason'], 'stale_or_future_quote')
        self.assertEqual(self.broker.submit(self.intent('fresh'), quote=self.quote(timestamp=stale), now=stale)['status'], 'accepted')
        self.assertFalse(self.broker.snapshot()['fills'])

    def test_sqlite_event_write_failure_atomic_and_reattach_retry(self):
        self.submit()
        before = self.broker.snapshot()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_event BEFORE UPDATE ON materialized BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.broker.apply_event(self.event())
        # Inspect raw persisted state while the synthetic storage fault is active.
        with closing(sqlite3.connect(self.path)) as db:
            import json
            self.assertEqual(json.loads(db.execute('SELECT state FROM materialized').fetchone()[0]), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER fail_event')
        self.assertEqual(self.submit('same-process-blocked')['reason'], 'reconciliation_required')
        self.broker = PaperBroker(self.path, **self.kw)
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        self.broker.reconcile(self.broker.snapshot())
        self.assertEqual(self.broker.apply_event(self.event())['status'], 'applied')
        self.assertEqual(self.broker.apply_event(self.event())['status'], 'duplicate')
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)

    def test_commit_failure_rolls_back_and_requires_reconciliation(self):
        self.submit()
        real_connect = sqlite3.connect
        class FailedCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError('injected commit I/O failure')
        def connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=FailedCommit)
        with patch('quantlab.paper.sqlite3.connect', side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError):
                self.broker.apply_event(self.event())
        state = self.broker.snapshot()
        self.assertFalse(state['fills'])
        self.assertEqual(state['cash'], '100000')
        self.assertTrue(state['reconciliation_required'])
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        self.broker.reconcile(self.broker.snapshot())
        self.assertEqual(self.broker.apply_event(self.event())['status'], 'applied')

    def test_unavailable_file_connection_latches_recovery(self):
        self.submit()
        with patch('quantlab.paper.sqlite3.connect', side_effect=sqlite3.OperationalError('unable to open database file')):
            with self.assertRaises(sqlite3.OperationalError):
                self.broker.apply_event(self.event())
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')
        self.assertFalse(self.broker.snapshot()['fills'])
        self.broker.reconcile(self.broker.snapshot())
        self.assertEqual(self.broker.apply_event(self.event())['status'], 'applied')

    def test_actual_process_death_at_fill_commit_boundaries(self):
        for point in ('before_event_commit', 'after_event_commit'):
            with self.subTest(point=point):
                path = Path(self.tmp.name) / (point + '.sqlite')
                script = """
import os
from pathlib import Path
from tests.test_paper import PaperTests
from quantlab.paper import PaperBroker
fixture = PaperTests()
fixture.setUp()
fixture.broker = PaperBroker(Path(PATH), **fixture.kw)
fixture.broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
fixture.submit()
def fail(point):
    if point == POINT:
        os._exit(73)
fixture.broker._fault = fail
fixture.broker.apply_event(fixture.event())
""".replace('PATH', repr(str(path))).replace('POINT', repr(point))
                result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stderr)
                other = PaperBroker(path, **self.kw)
                state = other.snapshot()
                self.assertTrue(state['reconciliation_required'])
                self.assertEqual(len(state['fills']), int(point == 'after_event_commit'))
                other.reconcile(state)
                status = other.apply_event(self.event())['status']
                self.assertEqual(status, 'duplicate' if point == 'after_event_commit' else 'applied')
                self.assertEqual(len(other.snapshot()['fills']), 1)
                self.assertEqual(other.snapshot()['cash'], '99986')

    def test_unknown_external_position_cannot_unblock_reattach(self):
        self.broker = PaperBroker(self.path, **self.kw)
        state = self.broker.snapshot()
        state['positions'][CID] = 1
        with self.assertRaisesRegex(ReconciliationError, 'positions discrepancy'):
            self.broker.reconcile(state)
        self.assertFalse(self.broker.snapshot()['positions'])
        self.assertFalse(self.broker.snapshot()['fills'])
        self.assertEqual(self.submit('blocked')['reason'], 'reconciliation_required')

    def test_durable_idempotence_and_conflicting_intent(self):
        first = self.submit()
        self.assertEqual(first['status'], 'accepted')
        self.assertEqual(first, self.submit())
        with self.assertRaises(JournalConflict):
            self.submit(quantity=2)
        other = PaperBroker(self.path, **self.kw)
        self.assertTrue(other.snapshot()['reconciliation_required'])
        self.assertEqual(other.submit(self.intent(), quote=self.quote(), now=NOW), first)
        self.assertEqual(other.submit(self.intent('b'), quote=self.quote(), now=NOW)['reason'], 'reconciliation_required')
        other.reconcile(other.snapshot())
        self.assertFalse(other.snapshot()['reconciliation_required'])

    def test_partial_fill_cancel_race_and_replay(self):
        self.submit(quantity=3)
        self.broker.apply_event(self.event())
        self.assertEqual(self.broker.snapshot()['orders']['a']['status'], 'partial')
        self.broker.cancel('a', now=NOW)
        self.broker.apply_event(self.event(typ='cancel', seq=2))
        self.broker.apply_event(self.event(seq=3))
        state = self.broker.snapshot()
        self.assertEqual(state['positions'], {CID: 2})
        self.assertEqual(state['orders']['a']['status'], 'cancelled')
        self.assertEqual(D(state['cash']), D('99972'))
        other = PaperBroker(self.path, **self.kw)
        self.assertEqual(other.snapshot()['fills'], state['fills'])
        self.assertEqual(other.snapshot()['cash'], state['cash'])

    def test_long_short_fifo_pnl(self):
        self.submit(quantity=2)
        self.broker.apply_event(self.event(quantity=2, commission='20', tax='8'))
        self.submit('b', side='sell', quantity=3)
        self.broker.apply_event(self.event('b', quantity=3, price='20010', commission='30', tax='12'))
        state = self.broker.snapshot()
        self.assertEqual(state['positions'], {CID: -1})
        self.assertEqual(D(state['cash']), D('100130'))  # 200 gross -70 fees/tax
        self.submit('c', side='buy')
        self.broker.apply_event(self.event('c', price='20000'))
        state = self.broker.snapshot()
        self.assertEqual(state['positions'], {})
        self.assertEqual(D(state['cash']), D('100216'))

    def test_event_duplicate_conflict_and_overfill(self):
        self.submit()
        e = self.event()
        self.assertEqual(self.broker.apply_event(e)['status'], 'applied')
        self.assertEqual(self.broker.apply_event(e)['status'], 'duplicate')
        with self.assertRaises(JournalConflict):
            self.broker.apply_event(dict(e, price='20001'))
        self.assertEqual(self.broker.apply_event(self.event(seq=2))['status'], 'quarantined')
        self.assertEqual(self.broker.snapshot()['positions'], {CID: 1})
        self.assertTrue(self.broker.snapshot()['reconciliation_required'])

    def test_gap_unknown_and_reconcile_never_overwrites(self):
        self.submit()
        self.broker.apply_event(self.event(typ='unknown'))
        self.assertEqual(self.submit('b')['reason'], 'reconciliation_required')
        state = self.broker.snapshot()
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(state)
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(dict(state, cash='99999', order_statuses={'a':'accepted'}))
        self.assertEqual(self.broker.snapshot()['cash'], '100000')
        state['order_statuses'] = {'a':'accepted'}
        self.broker.reconcile(state)
        self.assertEqual(self.submit('c')['status'], 'accepted')
        result = self.broker.apply_event(self.event('c', seq=2))
        self.assertEqual(result['status'], 'quarantined')
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(self.broker.snapshot())

    def test_restart_all_crash_boundaries(self):
        for point in ('before_intent_commit', 'after_intent_commit', 'before_ack_commit', 'after_ack_commit'):
            with self.subTest(point=point):
                path = Path(self.tmp.name) / (point + '.sqlite')
                b = PaperBroker(path, **self.kw)
                b.reconcile(dict(account_id='synthetic', cash='100000', orders={}, fills={}, positions={}))
                def fail(p):
                    if p == point:
                        raise RuntimeError('synthetic crash')
                b._fault = fail
                with self.assertRaises(RuntimeError):
                    b.submit(self.intent(), quote=self.quote(), now=NOW)
                b2 = PaperBroker(path, **self.kw)
                s = b2.snapshot()
                self.assertTrue(s['reconciliation_required'])
                self.assertFalse(s['fills'])
                self.assertEqual(len(s['orders']), 0 if point == 'before_intent_commit' else 1)
                if point in ('after_intent_commit', 'before_ack_commit'):
                    self.assertEqual(s['orders']['a']['status'], 'unknown')
                    with self.assertRaises(ReconciliationError):
                        b2.reconcile(s)
                    s['order_statuses'] = {'a':'accepted'}
                b2.reconcile(s)
                self.assertFalse(b2.snapshot()['reconciliation_required'])

    def test_crash_without_restart_blocks_new_orders(self):
        def fail(point):
            if point == 'after_intent_commit':
                raise RuntimeError('crash')
        self.broker._fault = fail
        with self.assertRaises(RuntimeError):
            self.submit()
        self.assertEqual(self.submit('b')['reason'], 'reconciliation_required')

    def test_event_rollback(self):
        self.submit()
        def fail(point):
            if point == 'before_event_commit':
                raise RuntimeError('crash')
        self.broker._fault = fail
        with self.assertRaises(RuntimeError):
            self.broker.apply_event(self.event())
        self.assertFalse(self.broker.snapshot()['fills'])
        self.broker._fault = lambda point: None
        self.assertEqual(self.broker.apply_event(self.event())['status'], 'applied')

    def test_concurrent_same_intent_and_event(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.submit(), range(20)))
            list(pool.map(lambda _: self.broker.apply_event(self.event()), range(20)))
        s = self.broker.snapshot()
        self.assertEqual(len(s['orders']), 1)
        self.assertEqual(len(s['fills']), 1)
        self.assertEqual(D(s['cash']), D('99986'))

    def test_risk_checks(self):
        cases = [({'account_id':'other'}, 'account_mismatch'),
                 ({'contract_id':'TAIFEX:TMF:202611'}, 'instrument_mismatch'),
                 ({'timestamp':NOW-timedelta(seconds=6)}, 'stale_or_future_quote'),
                 ({'timestamp':NOW+timedelta(seconds=1)}, 'stale_or_future_quote'),
                 ({'session_end':NOW}, 'outside_session'),
                 ({'margin_per_contract':'200000'}, 'risk_policy_mismatch'),
                 ({'trade_date':'2026-10-22'}, 'risk_policy_mismatch')]
        for i, (change, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                r = self.broker.submit(self.intent(str(i)), quote=self.quote(**change), now=NOW)
                self.assertEqual(r['reason'], reason)
        self.assertEqual(self.submit('large', quantity=4)['reason'], 'max_order_quantity')
        self.submit('pending', quantity=3)
        self.assertEqual(self.submit('exceed', quantity=3)['reason'], 'max_position')
        self.broker.set_kill_switch(True)
        self.assertEqual(self.submit('killed')['reason'], 'kill_switch')
        self.assertFalse(self.broker.snapshot()['fills'])
        restarted = PaperBroker(self.path, **self.kw)
        with self.assertRaises(ReconciliationError):
            restarted.set_kill_switch(False)
        restarted.reconcile(restarted.snapshot())
        restarted.set_kill_switch(False)
        self.assertFalse(restarted.snapshot()['kill_switch'])

    def test_daily_loss_and_marked_margin(self):
        self.submit()
        self.broker.apply_event(self.event())
        r = self.broker.submit(self.intent('loss'), quote=self.quote(price='19900'), now=NOW)
        self.assertEqual(r['reason'], 'max_daily_loss')

    def test_strict_values_and_tick(self):
        for value in (True, 1.0, '1', -1, 0):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.submit(quantity=value)
        for value in ('20000.5', 'NaN', 'Infinity', True, 20000.0, '-1'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.broker.submit(self.intent(), quote=self.quote(price=value), now=NOW)
        with self.assertRaises(ValidationError):
            self.broker.submit(self.intent(), quote=self.quote(), now=NOW.replace(tzinfo=None))
        with self.assertRaises(ValidationError):
            self.broker.set_kill_switch(1)
        with self.assertRaises(ValidationError):
            RiskLimits(True, 2, D('1'), 2)

    def test_fill_before_ack_and_limit_violation(self):
        self.submit(order_type='limit', limit_price=D('20000'))
        self.broker.apply_event(self.event())
        self.broker.apply_event(self.event(typ='ack', seq=2))
        self.assertEqual(self.broker.snapshot()['orders']['a']['status'], 'filled')
        self.submit('b', order_type='limit', limit_price=D('20000'))
        self.assertEqual(self.broker.apply_event(self.event('b', price='20001'))['status'], 'quarantined')

    def test_corrupted_snapshot_detected(self):
        self.submit()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE materialized SET state='{}'")
        with self.assertRaises(JournalConflict):
            self.broker.snapshot()

    def test_reconciliation_discrepancy_freezes_previously_ready_account(self):
        self.submit()
        state = self.broker.snapshot()
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(dict(state, cash='123'))
        self.assertEqual(self.broker.snapshot()['cash'], '100000')
        self.assertEqual(self.submit('b')['reason'], 'reconciliation_required')
        self.broker.reconcile(self.broker.snapshot())
        self.assertEqual(self.submit('c')['status'], 'accepted')

    def test_reconcile_rejects_bool_position_and_incomplete_views(self):
        self.submit()
        self.broker.apply_event(self.event())
        state = self.broker.snapshot()
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(dict(state, positions={CID: True}))
        missing = deepcopy(state)
        missing.pop('fills')
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(missing)
        self.assertTrue(self.broker.snapshot()['reconciliation_required'])

    def test_rejected_intent_persists_and_is_not_resubmitted(self):
        self.broker.set_kill_switch(True)
        first = self.submit()
        self.broker.set_kill_switch(False)
        self.assertEqual(self.submit(), first)
        records = self.broker.journal_events()
        self.assertEqual(sum(r['operation'] == 'risk_reject' for r in records), 1)
        self.assertFalse(self.broker.snapshot()['fills'])

    def test_unknown_freezes_all_other_instruments_and_orders(self):
        self.submit()
        self.submit('b')
        self.broker.apply_event(self.event(typ='unknown'))
        self.assertEqual(self.submit('c')['reason'], 'reconciliation_required')
        self.assertEqual(self.submit('d', contract_id='TAIFEX:TMF:202611')['reason'], 'reconciliation_required')
        # Cancel remains allowed and never liquidates while frozen.
        self.broker.cancel('b', now=NOW)
        self.assertFalse(self.broker.snapshot()['fills'])

    def test_unknown_order_event_quarantines_original_payload(self):
        event = self.event('never-submitted')
        self.assertEqual(self.broker.apply_event(event)['status'], 'quarantined')
        records = self.broker.journal_events()
        self.assertEqual(records[-1]['payload']['fill_id'], event['fill_id'])
        self.assertEqual(self.broker.apply_event(event)['status'], 'duplicate')
        self.assertFalse(self.broker.snapshot()['fills'])

    def test_duplicate_fill_id_under_new_event_is_quarantined(self):
        self.submit(quantity=2)
        self.broker.apply_event(self.event())
        e = self.event(seq=2, fill_id='f-a-1')
        self.assertEqual(self.broker.apply_event(e)['status'], 'quarantined')
        self.assertEqual(self.broker.snapshot()['positions'], {CID: 1})

    def test_cancel_and_late_ack_cannot_resurrect_filled_order(self):
        self.submit()
        self.broker.apply_event(self.event())
        self.broker.cancel('a', now=NOW)
        self.broker.apply_event(self.event(typ='cancel', seq=2))
        self.broker.apply_event(self.event(typ='ack', seq=3))
        self.assertEqual(self.broker.snapshot()['orders']['a']['status'], 'filled')

    def test_concurrent_different_orders_obey_reserved_position(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: self.submit(str(i)), range(20)))
        state = self.broker.snapshot()
        accepted = [o for o in state['orders'].values() if o['status'] == 'accepted']
        self.assertLessEqual(len(accepted), 5)
        self.assertTrue(accepted)
        self.assertEqual(len(state['orders']), 20)
        self.assertTrue(all(r['status'] in ('accepted', 'rejected') for r in results))

    def test_invalid_event_time_and_sequence_fail_closed(self):
        self.submit()
        self.assertEqual(self.broker.apply_event(self.event(timestamp=NOW-timedelta(seconds=1)))['status'], 'quarantined')
        self.assertFalse(self.broker.snapshot()['fills'])
        with self.assertRaises(ValidationError):
            self.broker.apply_event(self.event(seq=True))

    def test_cancel_unknown_does_not_erase_resolution_requirement(self):
        self.submit()
        self.broker.apply_event(self.event(typ='unknown'))
        self.broker.cancel('a', now=NOW)
        state = self.broker.snapshot()
        self.assertEqual(state['orders']['a']['status'], 'unknown')
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(state)

    def test_external_ack_after_submission_crash_still_requires_reconcile(self):
        def fail(point):
            if point == 'after_intent_commit':
                raise RuntimeError('crash')
        self.broker._fault = fail
        with self.assertRaises(RuntimeError):
            self.submit()
        self.broker.apply_event(self.event(typ='ack'))
        self.assertEqual(self.submit('b')['reason'], 'reconciliation_required')
        self.broker.reconcile(self.broker.snapshot())
        self.assertFalse(self.broker.snapshot()['reconciliation_required'])

    def test_actual_process_death_durability(self):
        for point in ('before_intent_commit', 'after_intent_commit', 'before_ack_commit', 'after_ack_commit'):
            with self.subTest(point=point):
                path = Path(self.tmp.name) / ('hard-' + point + '.sqlite')
                script = """
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D, localcontext, ROUND_UP
from pathlib import Path
from quantlab.core import Instrument, CostSpec
from quantlab.paper import PaperBroker, RiskLimits
b = PaperBroker(Path(PATH), instrument=Instrument('TAIFEX:TMF:202610', expiry='2026-10-21'), costs=CostSpec(D('10'), D('.00002'), 0, 'half_up', '2026-01-01', 'synthetic-v1'), limits=RiskLimits(5,3,D('500'),5), risk_sessions=({'open':'2026-10-09T00:45:00Z','end':'2026-10-09T05:00:00Z','trade_date':'2026-10-09','source':'synthetic','session':'day'},), margin_schedule=({'effective_from':'2026-01-01','margin_per_contract':'10000','version':'synthetic'},))
b.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
def fail(point):
    if point == POINT:
        os._exit(73)
b._fault = fail
now = datetime(2026,10,9,1,tzinfo=timezone.utc)
b.submit(dict(client_order_id='a', strategy_hash='synthetic', contract_id='TAIFEX:TMF:202610', side='buy', quantity=1, order_type='market', created_at=now), quote=dict(account_id='synthetic', contract_id='TAIFEX:TMF:202610', timestamp=now, price=D('20000'), trade_date='2026-10-09', session_open=now-timedelta(minutes=15), session_end=now+timedelta(hours=4), margin_per_contract=D('10000')), now=now)
""".replace('PATH', repr(str(path))).replace('POINT', repr(point))
                result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stderr)
                state = PaperBroker(path, **self.kw).snapshot()
                self.assertEqual(len(state['orders']), 0 if point == 'before_intent_commit' else 1)
                self.assertFalse(state['fills'])
                self.assertTrue(state['reconciliation_required'])
                if point in ('after_intent_commit', 'before_ack_commit'):
                    self.assertEqual(state['orders']['a']['status'], 'unknown')

    def test_pinned_policy_cannot_be_overridden_by_quote(self):
        for i, changed in enumerate(({'margin_per_contract':'1'}, {'trade_date':'2026-10-10'},
                                      {'session_open':NOW-timedelta(days=1)}, {'session_end':NOW+timedelta(days=1)})):
            result = self.broker.submit(self.intent('forged'+str(i)), quote=self.quote(**changed), now=NOW)
            self.assertEqual(result['reason'], 'risk_policy_mismatch')
        self.assertFalse(self.broker.snapshot()['fills'])
        policy = self.broker.quote_policy(NOW)
        policy['margin_per_contract'] = '1'
        self.assertEqual(D(self.broker.quote_policy(NOW)['margin_per_contract']), D('10000'))
        with self.assertRaises(JournalConflict):
            PaperBroker(self.path, **dict(self.kw, margin_schedule=({'effective_from':'2026-01-01','margin_per_contract':'1','version':'changed'},)))

    def test_caller_decimal_context_cannot_corrupt_replay(self):
        with localcontext() as context:
            context.prec = 4
            context.rounding = ROUND_UP
            self.submit()
            self.broker.apply_event(self.event())
        self.assertEqual(D(self.broker.snapshot()['cash']), D('99986'))
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(D(self.broker.snapshot()['cash']), D('99986'))

    def test_missing_policy_blocks_orders(self):
        kw = {k:v for k,v in self.kw.items() if k not in ('risk_sessions', 'margin_schedule')}
        broker = PaperBroker(Path(self.tmp.name)/'missing.sqlite', **kw)
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        result = broker.submit(self.intent(), quote=self.quote(), now=NOW)
        self.assertEqual(result['reason'], 'missing_risk_policy')

    def test_event_timestamp_regression_quarantines(self):
        self.submit(quantity=2)
        self.assertEqual(self.broker.apply_event(self.event(timestamp=NOW+timedelta(seconds=5)))['status'], 'applied')
        self.assertEqual(self.broker.apply_event(self.event(seq=2, timestamp=NOW+timedelta(seconds=1)))['status'], 'quarantined')
        self.assertEqual(self.broker.snapshot()['positions'], {CID:1})

    def test_new_intent_and_cancel_cannot_regress_account_clock(self):
        self.submit()
        self.broker.apply_event(self.event(timestamp=NOW+timedelta(seconds=1)))
        self.assertEqual(self.submit('backwards')['reason'], 'time_regression')
        with self.assertRaises(ValidationError):
            self.broker.cancel('a', now=NOW)

    def test_rod_fill_outside_pinned_session_quarantines(self):
        self.submit()
        result = self.broker.apply_event(self.event(timestamp=NOW+timedelta(days=1)))
        self.assertEqual(result['status'], 'quarantined')
        state = self.broker.snapshot()
        self.assertEqual(state['cash'], '100000')
        self.assertFalse(state['daily_pnl'])
        self.assertFalse(state['fills'])

    def test_pinned_margin_and_expiry_still_enforce(self):
        kw = dict(self.kw, margin_schedule=({'effective_from':'2026-01-01','margin_per_contract':'200000','version':'synthetic'},))
        broker = PaperBroker(Path(self.tmp.name)/'margin.sqlite', **kw)
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        result = broker.submit(self.intent(), quote=self.quote(margin_per_contract='200000'), now=NOW)
        self.assertEqual(result['reason'], 'insufficient_cash_or_margin')
        kw = dict(self.kw, instrument=Instrument(CID, expiry='2026-10-08'))
        broker = PaperBroker(Path(self.tmp.name)/'expiry.sqlite', **kw)
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        result = broker.submit(self.intent(), quote=self.quote(), now=NOW)
        self.assertEqual(result['reason'], 'expired_instrument')

    def test_overnight_profit_cannot_hide_new_day_loss(self):
        sessions = self.kw['risk_sessions'] + ({'open':NOW+timedelta(days=1, minutes=-15),
            'end':NOW+timedelta(days=1,hours=4), 'trade_date':'2026-10-10', 'source':'synthetic', 'session':'day'},)
        broker = PaperBroker(Path(self.tmp.name)/'overnight.sqlite', **dict(self.kw, risk_sessions=sessions))
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        broker.submit(self.intent(), quote=self.quote(), now=NOW)
        broker.apply_event(self.event(price='20000'))
        # Yesterday's mark could have been 20200 (+2000); today's 20100 is
        # a 1000 daily loss but still +1000 lifetime PnL. No baseline may be invented.
        now = NOW+timedelta(days=1)
        quote = self.quote(timestamp=now, price='20100', **broker.quote_policy(now))
        result = broker.submit(self.intent('new-day', created_at=now), quote=quote, now=now)
        self.assertEqual(result['reason'], 'overnight_daily_loss_baseline_required')
        self.assertEqual(broker.snapshot()['positions'], {CID:1})

    def test_versioned_opening_reference_measures_new_day_loss(self):
        now = NOW+timedelta(days=1)
        reference = {'price':'20200','known_at':now-timedelta(minutes=15),'version':'synthetic-opening-v1'}
        session = {'open':now-timedelta(minutes=15),'end':now+timedelta(hours=4),
                   'trade_date':'2026-10-10','source':'synthetic','session':'day','opening_reference':reference}
        broker = PaperBroker(Path(self.tmp.name)/'marked.sqlite', **dict(self.kw, risk_sessions=self.kw['risk_sessions']+(session,)))
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        broker.submit(self.intent(), quote=self.quote(), now=NOW)
        broker.apply_event(self.event())
        quote = self.quote(timestamp=now, price='20100', **broker.quote_policy(now))
        result = broker.submit(self.intent('daily-loss', created_at=now), quote=quote, now=now)
        self.assertEqual(result['reason'], 'max_daily_loss')
        baseline = broker.snapshot()['daily_equity_baselines']['2026-10-10']
        self.assertEqual(D(baseline['equity']), D('101986'))
        self.assertEqual(baseline['reference']['version'], 'synthetic-opening-v1')
        # A smaller daily loss allows closing; realized carry gains must not
        # reset the opening equity or double-count the reference gain.
        quote['price'] = '20160'
        self.assertEqual(broker.submit(self.intent('close', side='sell', created_at=now), quote=quote, now=now)['status'], 'accepted')
        broker.apply_event(self.event('close', timestamp=now, price='20160'))
        state = broker.snapshot()
        self.assertEqual(D(state['cash'])-D(baseline['equity']), D('-414'))
        self.assertEqual(broker.submit(self.intent('next', created_at=now), quote=quote, now=now)['status'], 'accepted')
        self.assertEqual(broker.snapshot()['daily_equity_baselines']['2026-10-10'], baseline)
        restarted = PaperBroker(broker.path, **dict(self.kw, risk_sessions=self.kw['risk_sessions']+(session,)))
        self.assertEqual(restarted.snapshot()['daily_equity_baselines']['2026-10-10'], baseline)

    def test_opening_reference_cannot_be_known_after_session_open(self):
        session = dict(self.kw['risk_sessions'][0], opening_reference={'price':'20000','known_at':NOW,'version':'future'})
        with self.assertRaises(ValidationError):
            PaperBroker(Path(self.tmp.name)/'future-ref.sqlite', **dict(self.kw,risk_sessions=(session,)))

    def test_cancel_late_fill_race_freezes_reserved_exposure_breach(self):
        broker = PaperBroker(Path(self.tmp.name)/'race.sqlite', **dict(self.kw, limits=RiskLimits(1,1,D('500'),5)))
        broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        broker.submit(self.intent(), quote=self.quote(), now=NOW)
        broker.apply_event(self.event(typ='cancel'))
        broker.submit(self.intent('b'), quote=self.quote(), now=NOW)
        broker.apply_event(self.event(seq=2))
        self.assertTrue(broker.snapshot()['reconciliation_required'])
        with self.assertRaises(ReconciliationError):
            broker.reconcile(broker.snapshot())
        # Actual fills remain authoritative/accounted even while further new orders freeze.
        broker.apply_event(self.event('b'))
        self.assertEqual(broker.snapshot()['positions'], {CID:2})
        self.assertEqual(broker.submit(self.intent('c'), quote=self.quote(), now=NOW)['reason'], 'reconciliation_required')

    def test_reported_fill_cost_margin_shortfall_freezes(self):
        self.submit()
        self.broker.apply_event(self.event(commission='90500', tax='0'))
        state = self.broker.snapshot()
        self.assertEqual(D(state['cash']), D('9500'))
        self.assertTrue(state['reconciliation_required'])
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(state)
        self.assertEqual(self.submit('new')['reason'], 'reconciliation_required')

    def test_consecutive_net_losses_latch_across_restart(self):
        kw = dict(self.kw, limits=RiskLimits(5,3,D('5000'),5,max_consecutive_losses=2))
        broker = PaperBroker(Path(self.tmp.name)/'streak.sqlite', **kw)
        broker.reconcile(dict(account_id='synthetic',cash='100000',positions={},orders={},fills={}))
        for i in range(2):
            for suffix,side in (('open','buy'),('close','sell')):
                oid = str(i)+suffix
                self.assertEqual(broker.submit(self.intent(oid,side=side),quote=self.quote(),now=NOW)['status'],'accepted')
                broker.apply_event(self.event(oid))
        state = broker.snapshot()
        self.assertEqual([D(r['net_pnl']) for r in state['round_trips']], [D('-28'),D('-28')])
        self.assertEqual(state['consecutive_losses'],2)
        self.assertTrue(state['consecutive_loss_halt'])
        self.assertEqual(broker.submit(self.intent('blocked'),quote=self.quote(),now=NOW)['reason'],'max_consecutive_losses')
        restarted = PaperBroker(broker.path, **kw)
        restarted.reconcile(restarted.snapshot())
        restarted.set_kill_switch(True)
        restarted.set_kill_switch(False)
        self.assertEqual(restarted.submit(self.intent('still-blocked'),quote=self.quote(),now=NOW)['reason'],'max_consecutive_losses')
        self.assertEqual(sum(e['operation']=='consecutive_loss_halt' for e in restarted.journal_events()),1)

    def test_partial_closes_count_only_completed_fifo_lot_net_fees(self):
        self.submit(quantity=3)
        self.broker.apply_event(self.event(quantity=3,commission='30',tax='12'))
        self.submit('close1',side='sell')
        self.broker.apply_event(self.event('close1',price='19999'))
        self.assertEqual(self.broker.snapshot()['consecutive_losses'],0)
        self.assertFalse(self.broker.snapshot()['round_trips'])
        self.submit('close2',side='sell',quantity=2)
        self.broker.apply_event(self.event('close2',quantity=2,price='20001',commission='20',tax='8'))
        state = self.broker.snapshot()
        self.assertEqual(state['consecutive_losses'],1)
        trip = state['round_trips'][0]
        self.assertEqual(trip['quantity'],3)
        self.assertEqual(D(trip['gross_pnl']),D('10'))
        self.assertEqual(D(trip['entry_cost']),D('42'))
        self.assertEqual(D(trip['exit_cost']),D('42'))
        self.assertEqual(D(trip['net_pnl']),D('-74'))

    def test_pending_winner_does_not_unlock_latched_loss_stop(self):
        kw = dict(self.kw,limits=RiskLimits(5,3,D('5000'),5,max_consecutive_losses=1))
        broker = PaperBroker(Path(self.tmp.name)/'pendingwin.sqlite', **kw)
        broker.reconcile(dict(account_id='synthetic',cash='100000',positions={},orders={},fills={}))
        for oid in ('a','b'):
            broker.submit(self.intent(oid),quote=self.quote(),now=NOW)
            broker.apply_event(self.event(oid))
        for oid in ('c','d'):
            broker.submit(self.intent(oid,side='sell'),quote=self.quote(),now=NOW)
        broker.apply_event(self.event('c',price='19999'))
        broker.apply_event(self.event('d',price='20010'))
        state=broker.snapshot()
        self.assertEqual(state['consecutive_losses'],0)
        self.assertTrue(state['consecutive_loss_halt'])
        self.assertEqual(broker.submit(self.intent('no-unlock'),quote=self.quote(),now=NOW)['reason'],'max_consecutive_losses')

    def test_order_frequency_reservations_idempotence_and_window_restart(self):
        kw=dict(self.kw,limits=RiskLimits(5,3,D('500'),5,max_orders_per_window=2,window_seconds=60))
        broker=PaperBroker(Path(self.tmp.name)/'frequency.sqlite',**kw)
        broker.reconcile(dict(account_id='synthetic',cash='100000',positions={},orders={},fills={}))
        for oid in ('a','b'):
            self.assertEqual(broker.submit(self.intent(oid),quote=self.quote(),now=NOW)['status'],'accepted')
        broker.submit(self.intent('a'),quote=self.quote(),now=NOW)
        broker.cancel('a',now=NOW)
        broker.snapshot();broker.journal_events();broker.reconcile(broker.snapshot())
        self.assertEqual(len(broker.snapshot()['order_send_timestamps']),2)
        self.assertEqual(broker.submit(self.intent('rate'),quote=self.quote(),now=NOW)['reason'],'max_orders_per_window')
        restarted=PaperBroker(broker.path,**kw)
        restarted.reconcile(restarted.snapshot())
        now=NOW+timedelta(seconds=59)
        self.assertEqual(restarted.submit(self.intent('early',created_at=now),quote=self.quote(timestamp=now),now=now)['reason'],'max_orders_per_window')
        now=NOW+timedelta(seconds=60)
        self.assertEqual(restarted.submit(self.intent('boundary',created_at=now),quote=self.quote(timestamp=now),now=now)['status'],'accepted')
        self.assertEqual(len(restarted.snapshot()['order_send_timestamps']),1)

    def test_frequency_counts_crashed_intent_and_bounded_limits(self):
        kw=dict(self.kw,limits=RiskLimits(5,3,D('500'),5,max_orders_per_window=1))
        broker=PaperBroker(Path(self.tmp.name)/'frequencycrash.sqlite',**kw)
        broker.reconcile(dict(account_id='synthetic',cash='100000',positions={},orders={},fills={}))
        def fail(point):
            if point=='after_intent_commit':raise RuntimeError('crash')
        broker._fault=fail
        with self.assertRaises(RuntimeError):broker.submit(self.intent(),quote=self.quote(),now=NOW)
        restarted=PaperBroker(broker.path,**kw)
        state=restarted.snapshot();state['order_statuses']={'a':'accepted'}
        restarted.reconcile(state)
        self.assertEqual(restarted.submit(self.intent('b'),quote=self.quote(),now=NOW)['reason'],'max_orders_per_window')
        for field,value in (('max_consecutive_losses',True),('max_consecutive_losses',1001),('max_orders_per_window',0),('max_orders_per_window',10001),('window_seconds',86401)):
            with self.assertRaises(ValidationError):RiskLimits(5,3,D('500'),5,**{field:value})

    def test_config_mismatch_and_live(self):
        with self.assertRaises(JournalConflict):
            PaperBroker(self.path, **dict(self.kw, limits=RiskLimits(6, 3, D('500'), 5)))
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker.submit(None)


if __name__ == '__main__':
    unittest.main()
