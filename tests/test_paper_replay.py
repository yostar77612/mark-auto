from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing
from quantlab.core import Instrument, ValidationError
from quantlab.paper import PaperBroker, RiskLimits
from quantlab.paper_replay import PaperReplay
from quantlab.reporting import synthetic_dataset, demo_config
from quantlab.strategies import builtin_strategies


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = synthetic_dataset(120)
        self.spec = builtin_strategies()[0]
        self.broker = self.new_broker()
        self.broker.reconcile({'account_id': 'replay', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}})
        self.replay = self.new_replay()

    def new_broker(self):
        return PaperBroker(self.root / 'broker.sqlite3', instrument=Instrument('TAIFEX:TMF:202601'),
                           costs=demo_config().costs, limits=RiskLimits(1, 1, Decimal('100000'), 30),
                           risk_sessions=({'open': '2026-01-05T00:45:00Z', 'end': '2026-01-05T04:45:00Z', 'trade_date': '2026-01-05', 'session': 'day', 'contract_id': 'TAIFEX:TMF:202601', 'source': 'synthetic test'},),
                           margin_schedule=({'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-v1'},))

    def new_replay(self):
        return PaperReplay(self.root / 'replay.sqlite3', dataset=self.data, strategy=self.spec,
                           broker=self.broker, margin_per_contract=Decimal('100000'), margin_version='synthetic-v1')

    def test_start_stop_repeated_complete_and_next_bar(self):
        self.assertEqual(self.replay.step()['cursor'], 0)
        self.replay.start()
        self.replay.step(max_bars=30)
        self.replay.stop()
        self.assertEqual(self.replay.step()['cursor'], 30)
        self.replay.start()
        self.replay.step(max_bars=1000)
        state = self.broker.snapshot()
        self.assertTrue(state['fills'])
        self.assertTrue(self.replay.snapshot()['complete'])
        self.replay.start()
        self.replay.step(max_bars=1000)
        self.assertEqual(self.broker.snapshot()['fills'], state['fills'])
        from quantlab.strategies import generate_signals
        first_signal = generate_signals(self.data.bars, self.spec)[0]
        fill = next(iter(state['fills'].values()))
        self.assertGreaterEqual(fill['timestamp'], first_signal.timestamp.isoformat().replace('+00:00', 'Z'))

    def test_crash_after_fill_retry_no_duplicate(self):
        self.replay.start()
        def crash(point):
            if point == 'after_fill_before_cursor':
                raise RuntimeError('simulated interrupted process')
        self.replay._fault = crash
        with self.assertRaises(RuntimeError):
            self.replay.step(max_bars=120)
        fills = self.broker.snapshot()['fills']
        self.assertEqual(len(fills), 1)
        self.broker = self.new_broker()
        replay = self.new_replay()
        self.assertEqual(replay.step()['cursor'], self.replay.snapshot()['cursor'])
        with self.assertRaises(ValidationError):
            replay.start()
        self.broker.reconcile(self.broker.snapshot())
        replay.start()
        replay.step(max_bars=1)
        self.assertEqual(self.broker.snapshot()['fills'], fills)
        replay.step(max_bars=120)
        self.assertTrue(replay.snapshot()['complete'])

    def _reattach_after_boundary(self, boundary):
        self.replay.targets = {0: 1}
        self.replay.start()
        def crash(point):
            if point == boundary:
                raise TimeoutError('injected offline interruption: ' + point)
        self.replay._fault = crash
        with self.assertRaises(TimeoutError):
            self.replay.step(max_bars=1)
        pending = self.replay.snapshot()
        self.assertEqual(pending['cursor'], 0)
        self.assertTrue(pending['pending_plan'])
        self.assertFalse(self.broker.snapshot()['fills'])
        self.assertEqual(len(self.broker.snapshot()['orders']),
                         0 if boundary == 'after_plan_before_submit' else 1)
        self.broker = self.new_broker()
        resumed = self.new_replay()
        self.assertEqual(resumed.step()['cursor'], 0)
        with self.assertRaises(ValidationError):
            resumed.start()
        self.broker.reconcile(self.broker.snapshot())
        resumed.start()
        self.assertEqual(resumed.step(max_bars=1)['cursor'], 1)
        self.assertEqual(len(self.broker.snapshot()['orders']), 1)
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)
        self.assertEqual(len(self.broker.snapshot()['order_send_timestamps']), 1)

    def test_reattach_after_durable_plan_before_submit(self):
        self._reattach_after_boundary('after_plan_before_submit')

    def test_reattach_after_ack_before_fill(self):
        self._reattach_after_boundary('after_submit_before_fill')

    def test_cursor_write_failure_preserves_fill_and_idempotent_plan(self):
        self.replay.targets = {0: 1}
        self.replay.start()
        with closing(sqlite3.connect(self.replay.path)) as db, db:
            db.execute("CREATE TRIGGER fail_cursor BEFORE UPDATE ON replay WHEN NEW.cursor != OLD.cursor BEGIN SELECT RAISE(ABORT, 'injected cursor failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.replay.step(max_bars=1)
        before = self.broker.snapshot()
        self.assertEqual(len(before['fills']), 1)
        self.assertEqual(self.replay.snapshot()['cursor'], 0)
        self.assertTrue(self.replay.snapshot()['pending_plan'])
        with closing(sqlite3.connect(self.replay.path)) as db, db:
            db.execute('DROP TRIGGER fail_cursor')
        self.assertEqual(self.replay.step(max_bars=1)['cursor'], 1)
        after = self.broker.snapshot()
        for field in ('fills', 'orders', 'positions', 'cash', 'order_send_timestamps'):
            self.assertEqual(after[field], before[field])

    def test_empty_bars_commit_cursors_without_redundant_plans(self):
        from unittest.mock import patch
        self.replay.targets = {}
        self.replay.start()
        statements = []
        real_connect = sqlite3.connect
        def connect(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            if Path(args[0]) == self.replay.path:
                db.set_trace_callback(statements.append)
            return db
        with patch('quantlab.paper_replay.sqlite3.connect', side_effect=connect):
            self.assertTrue(self.replay.step(max_bars=120)['complete'])
        self.assertEqual(sum(s.startswith('UPDATE replay SET cursor=') for s in statements), 120)
        self.assertFalse(any(s.startswith('UPDATE replay SET plan=') for s in statements))
        self.assertTrue(self.new_replay().snapshot()['complete'])
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_empty_bar_interruption_and_cursor_failure_resume_without_orders(self):
        self.replay.targets = {2: 1}
        self.replay.start()
        def crash(point):
            if point == 'after_empty_cursor':
                raise RuntimeError('interrupted empty bar')
        self.replay._fault = crash
        with self.assertRaisesRegex(RuntimeError, 'interrupted empty bar'):
            self.replay.step(max_bars=1)
        self.assertEqual(self.replay.snapshot()['cursor'], 1)
        self.assertFalse(self.replay.snapshot()['pending_plan'])
        self.assertFalse(self.broker.snapshot()['orders'])
        self.replay._fault = lambda point: None
        with closing(sqlite3.connect(self.replay.path)) as db, db:
            db.execute("CREATE TRIGGER fail_empty_cursor BEFORE UPDATE ON replay WHEN NEW.cursor != OLD.cursor BEGIN SELECT RAISE(ABORT, 'empty cursor failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.replay.step(max_bars=1)
        self.assertEqual(self.replay.snapshot()['cursor'], 1)
        with closing(sqlite3.connect(self.replay.path)) as db, db:
            db.execute('DROP TRIGGER fail_empty_cursor')
        self.broker = self.new_broker()
        resumed = self.new_replay()
        resumed.targets = {2: 1}
        self.broker.reconcile(self.broker.snapshot())
        resumed.start()
        self.assertEqual(resumed.step(max_bars=1)['cursor'], 2)
        self.assertFalse(self.broker.snapshot()['orders'])
        self.assertEqual(resumed.step(max_bars=1)['cursor'], 3)
        self.assertEqual(len(self.broker.snapshot()['orders']), 1)
        self.assertEqual(len(self.broker.snapshot()['fills']), 1)
        self.assertEqual(len(self.broker.snapshot()['order_send_timestamps']), 1)

    def test_satisfied_empty_target_is_not_reinterpreted_after_restart(self):
        self.replay.targets = {0: 0}
        self.replay.start()
        def crash(point):
            if point == 'after_empty_cursor':
                raise RuntimeError('after durable empty decision')
        self.replay._fault = crash
        with self.assertRaises(RuntimeError):
            self.replay.step(max_bars=1)
        self.assertEqual(self.replay.snapshot()['cursor'], 1)
        # A separately reconciled account can change before the next replay.
        bar = self.data.bars[0]
        self.broker.submit({'client_order_id': 'external', 'strategy_hash': 'external',
            'contract_id': bar.contract_id, 'side': 'buy', 'quantity': 1,
            'order_type': 'market', 'created_at': bar.timestamp},
            quote={'account_id': 'replay', 'contract_id': bar.contract_id,
                   'timestamp': bar.timestamp, 'price': bar.open, **self.broker.quote_policy(bar.timestamp)},
            now=bar.timestamp)
        self.broker.apply_event({'event_id': 'external-fill', 'fill_id': 'external-fill',
            'order_id': 'external', 'sequence': 1, 'type': 'fill', 'timestamp': bar.timestamp,
            'quantity': 1, 'price': bar.open, 'commission': Decimal('0'), 'tax': Decimal('0')})
        self.broker = self.new_broker()
        resumed = self.new_replay()
        resumed.targets = {0: 0}
        self.broker.reconcile(self.broker.snapshot())
        resumed.start()
        self.assertEqual(resumed.step(max_bars=2)['cursor'], 3)
        self.assertEqual(set(self.broker.snapshot()['orders']), {'external'})
        self.assertEqual(self.broker.snapshot()['positions'][bar.contract_id], 1)

    def test_saved_legacy_empty_plan_consumes_without_reinterpretation(self):
        self.replay.targets = {0: 1}
        self.replay.start()
        with closing(sqlite3.connect(self.replay.path)) as db, db:
            db.execute("UPDATE replay SET plan='[]' WHERE id=1")
        self.assertEqual(self.replay.step(max_bars=1)['cursor'], 1)
        self.assertFalse(self.replay.snapshot()['pending_plan'])
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_empty_bars_observe_external_kill_before_next_bar(self):
        other = self.new_broker()
        other.reconcile(other.snapshot())
        self.replay.targets = {1: 1}
        self.replay.start()
        def kill(point):
            if point == 'after_empty_cursor':
                other.set_kill_switch(True)
        self.replay._fault = kill
        self.assertEqual(self.replay.step(max_bars=120)['cursor'], 1)
        self.assertTrue(self.broker.snapshot()['kill_switch'])
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_empty_bars_observe_external_reconciliation_barrier(self):
        self.replay.targets = {1: 1}
        self.replay.start()
        def restart(point):
            if point == 'after_empty_cursor':
                self.new_broker()
        self.replay._fault = restart
        self.assertEqual(self.replay.step(max_bars=120)['cursor'], 1)
        self.assertTrue(self.broker.snapshot()['reconciliation_required'])
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_empty_bars_observe_policy_change_before_next_bar(self):
        self.replay.targets = {1: 1}
        self.replay.start()
        def change_policy(point):
            if point == 'after_empty_cursor':
                self.broker._margin_schedule = [dict(self.broker._margin_schedule[0], version='changed')]
        self.replay._fault = change_policy
        with self.assertRaisesRegex(ValidationError, 'pinned broker policy changed'):
            self.replay.step(max_bars=120)
        self.assertEqual(self.replay.snapshot()['cursor'], 1)
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_binding_and_budget(self):
        with self.assertRaises(ValidationError):
            self.replay.step(max_bars=1001)
        self.spec = builtin_strategies()[1]
        with self.assertRaises(ValidationError):
            self.new_replay()

    def test_zero_volume_has_no_simulated_fills(self):
        from dataclasses import replace
        from quantlab.core import content_hash
        bars = tuple(replace(bar, volume=0) for bar in self.data.bars)
        manifest = {**self.data.manifest, 'data_hash': content_hash(bars)}
        manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('manifest_hash', 'imported_at')})
        dataset = replace(self.data, bars=bars, manifest=manifest)
        replay = PaperReplay(self.root / 'zero-volume.sqlite3', dataset=dataset, strategy=self.spec,
                             broker=self.broker, margin_per_contract=Decimal('100000'), margin_version='synthetic-v1')
        replay.start()
        replay.step(max_bars=120)
        self.assertTrue(replay.snapshot()['complete'])
        self.assertFalse(self.broker.snapshot()['orders'])
        self.assertFalse(self.broker.snapshot()['fills'])

    def test_protective_rules_explicitly_rejected(self):
        from dataclasses import replace
        protected = replace(self.spec, parameters={**self.spec.parameters, 'stop_ticks': 5})
        with self.assertRaisesRegex(ValidationError, 'protective stop/target'):
            PaperReplay(self.root / 'protected.sqlite3', dataset=self.data, strategy=protected,
                        broker=self.broker, margin_per_contract=Decimal('100000'), margin_version='synthetic-v1')
