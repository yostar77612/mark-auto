"""Pinned replay margins; invented offline fixtures, never a live broker/feed."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from quantlab.core import Instrument, ValidationError, content_hash
from quantlab.paper import PaperBroker, RiskLimits
from quantlab.paper_replay import PaperReplay
from quantlab.reporting import demo_config, synthetic_dataset
from quantlab.strategies import builtin_strategies


def policy_fixture():
    return {
        'risk_sessions': [
            {'open': '2026-01-05T00:45:00Z', 'end': '2026-01-05T04:45:00Z',
             'trade_date': '2026-01-05', 'session': 'day', 'source': 'invented day source'},
            {'open': '2026-01-05T17:00:00Z', 'end': '2026-01-05T18:00:00Z',
             'trade_date': '2026-01-06', 'session': 'night', 'source': 'invented night source',
             'opening_reference': {'price': '20000', 'known_at': '2026-01-05T17:00:00Z', 'version': 'invented-opening-v1'}},
        ],
        # Deliberately not sorted, with an unused future row included in identity.
        'margin_schedule': [
            {'effective_from': '2026-01-07', 'margin_per_contract': '180000', 'version': 'future-v3'},
            {'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'past-v0'},
            {'effective_from': '2026-01-06', 'margin_per_contract': '150000', 'version': 'night-v2'},
            {'effective_from': '2026-01-05', 'margin_per_contract': '120000', 'version': 'day-v1'},
        ],
    }


def with_bars(data, bars):
    manifest = {**data.manifest, 'data_hash': content_hash(bars)}
    manifest['manifest_hash'] = content_hash({k: v for k, v in manifest.items() if k not in ('manifest_hash', 'imported_at')})
    return replace(data, bars=tuple(bars), manifest=manifest)


class ReplayPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = synthetic_dataset(2)
        night = datetime(2026, 1, 5, 17, tzinfo=timezone.utc)
        self.data = with_bars(self.data, [self.data.bars[0], replace(self.data.bars[1],
            timestamp=night, end=night + timedelta(minutes=1), trade_date='2026-01-06', session='night')])
        self.policy = policy_fixture()
        self.spec = builtin_strategies()[0]
        self.broker = self.new_broker()
        self.broker.reconcile({'account_id': 'policy-replay', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}})

    def new_broker(self, policy=None):
        return PaperBroker(self.root / 'broker.sqlite3', instrument=Instrument('TAIFEX:TMF:202601'),
            costs=demo_config().costs, limits=RiskLimits(1, 1, Decimal('100000'), 30), **(policy or self.policy))

    def new_replay(self, path='replay.sqlite3', **kwargs):
        return PaperReplay(self.root / path, dataset=kwargs.pop('dataset', self.data), strategy=self.spec,
            broker=self.broker, margin_schedule=self.broker._margin_schedule, **kwargs)

    def test_effective_dates_use_session_trade_date_including_night(self):
        replay = self.new_replay()
        self.assertEqual(replay._quote_policy(self.data.bars[0])['margin_per_contract'], '120000')
        self.assertEqual(replay._quote_policy(self.data.bars[1])['margin_per_contract'], '150000')
        replay.targets = {0: 1, 1: 0}
        with patch.object(self.broker, 'submit', wraps=self.broker.submit) as submit:
            replay.start(); replay.step(max_bars=2); replay.stop()
        self.assertEqual([call.kwargs['quote']['margin_per_contract'] for call in submit.call_args_list], ['120000', '150000'])
        self.assertEqual(len(self.broker.snapshot()['fills']), 2)
        self.assertTrue(replay.snapshot()['complete'])
        self.assertTrue(self.broker.snapshot()['kill_switch'])

    def test_complete_future_schedule_versions_and_session_sources_bound(self):
        replay = self.new_replay()
        expected = replay.binding
        variants = []
        for key, field, index, value in [
            ('margin_schedule', 'version', 0, 'changed-unused-version'),
            ('margin_schedule', 'margin_per_contract', 0, '180001'),
            ('margin_schedule', 'effective_from', 0, '2026-01-08'),
            ('risk_sessions', 'source', 0, 'different-session-source'),
        ]:
            changed = deepcopy(self.policy); changed[key][index][field] = value; variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed):
                # A stub with the same path/config isolates replay identity from
                # the broker's independently enforced journal configuration.
                from copy import copy
                altered = copy(self.broker)
                altered._risk_sessions = changed['risk_sessions']; altered._margin_schedule = changed['margin_schedule']
                with self.assertRaisesRegex(ValidationError, 'bound to a different'):
                    PaperReplay(replay.path, dataset=self.data, strategy=self.spec, broker=altered,
                                margin_schedule=changed['margin_schedule'])
        self.assertEqual(self.new_replay().binding, expected)

    def test_policy_aliases_are_detached_and_frozen(self):
        replay = self.new_replay()
        self.policy['margin_schedule'][0]['version'] = 'caller-mutated'
        self.assertEqual(replay.policy['margin_schedule'][0]['version'], 'future-v3')
        with self.assertRaises(TypeError): replay.policy['margin_schedule'][0]['version'] = 'tampered'
        self.assertEqual(self.new_replay().binding, replay.binding)

    def test_supplied_schedule_mismatch_rejected(self):
        changed = deepcopy(self.policy['margin_schedule']); changed[-1]['margin_per_contract'] = '100000'
        with self.assertRaisesRegex(ValidationError, 'schedule does not match'):
            PaperReplay(self.root / 'bad.sqlite3', dataset=self.data, strategy=self.spec,
                        broker=self.broker, margin_schedule=changed)
        self.assertFalse((self.root / 'bad.sqlite3').exists())
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_missing_future_coverage_preflights_before_any_plan_or_order(self):
        no_session = deepcopy(self.policy); no_session['risk_sessions'].pop()
        from copy import copy
        broker = copy(self.broker); broker._risk_sessions = no_session['risk_sessions']
        with self.assertRaisesRegex(ValidationError, 'outside pinned risk sessions'):
            PaperReplay(self.root / 'missing.sqlite3', dataset=self.data, strategy=self.spec,
                        broker=broker, margin_schedule=broker._margin_schedule)
        self.assertFalse((self.root / 'missing.sqlite3').exists())
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_no_effective_margin_and_empty_policy_are_rejected(self):
        from copy import copy
        for schedule in ([], [self.policy['margin_schedule'][0]]):
            broker = copy(self.broker); broker._margin_schedule = schedule
            with self.subTest(schedule=schedule), self.assertRaises(ValidationError):
                PaperReplay(self.root / 'missing.sqlite3', dataset=self.data, strategy=self.spec,
                            broker=broker, margin_schedule=schedule)
        self.assertFalse((self.root / 'missing.sqlite3').exists())
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_wrong_dataset_trade_date_rejected_even_without_signals(self):
        data = with_bars(self.data, [self.data.bars[0], replace(self.data.bars[1], trade_date='2026-01-05')])
        with self.assertRaisesRegex(ValidationError, 'trade date does not match'):
            self.new_replay(dataset=data)
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_quote_amount_mismatch_fails_before_plan(self):
        replay = self.new_replay(); replay.targets = {0: 1}
        good = self.broker.quote_policy(self.data.bars[0].timestamp)
        replay.start()
        with patch.object(self.broker, 'quote_policy', return_value={**good, 'margin_per_contract': '100000'}):
            with self.assertRaisesRegex(ValidationError, 'margin does not match'):
                replay.step(max_bars=1)
        self.assertEqual(replay.snapshot()['cursor'], 0)
        self.assertFalse(replay.snapshot()['pending_plan'])
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_runtime_policy_reassignment_fails_closed(self):
        replay = self.new_replay(); replay.targets = {0: 1}; replay.start()
        changed = deepcopy(self.policy['margin_schedule']); changed[0]['version'] = 'changed'
        self.broker._margin_schedule = changed
        with self.assertRaisesRegex(ValidationError, 'pinned broker policy changed'):
            replay.step(max_bars=1)
        self.assertEqual(replay.snapshot()['cursor'], 0)
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_broker_restart_rejects_configuration_tampering(self):
        before = (self.root / 'broker.sqlite3').read_bytes()
        changed = deepcopy(self.policy); changed['margin_schedule'][0]['version'] = 'changed'
        with self.assertRaisesRegex(ValidationError, 'configuration mismatch'):
            self.new_broker(changed)
        self.assertEqual((self.root / 'broker.sqlite3').read_bytes(), before)

    def test_scalar_legacy_hash_and_ledger_preserved_but_not_adopted(self):
        data = with_bars(self.data, [self.data.bars[0]])
        scalar = PaperReplay(self.root / 'legacy.sqlite3', dataset=data, strategy=self.spec, broker=self.broker,
                             margin_per_contract=Decimal('120000'), margin_version='day-v1')
        old_hash = content_hash({'data': data.manifest['data_hash'], 'strategy': self.spec,
            'broker_journal': str(self.broker.path.resolve()), 'costs': self.broker.costs,
            'limits': self.broker.limits, 'margin': Decimal('120000'), 'margin_version': 'day-v1'})
        self.assertEqual(scalar.binding, old_hash)
        scalar.targets = {0: 1}; scalar.start(); scalar.step(max_bars=1); scalar.stop()
        before = scalar.path.read_bytes(); orders = self.broker.snapshot()['orders']
        resumed = PaperReplay(scalar.path, dataset=data, strategy=self.spec, broker=self.broker,
                             margin_per_contract=Decimal('120000'), margin_version='day-v1')
        self.assertTrue(resumed.snapshot()['complete'])
        with self.assertRaisesRegex(ValidationError, 'Preserve this workspace and its orders'):
            self.new_replay(path='legacy.sqlite3', dataset=data)
        self.assertEqual(scalar.path.read_bytes(), before)
        self.assertEqual(self.broker.snapshot()['orders'], orders)

    def test_scalar_margin_and_version_must_match_applicable_policy(self):
        data = with_bars(self.data, [self.data.bars[0]])
        for amount, version in [('100000', 'day-v1'), ('120000', 'other-v1')]:
            with self.subTest(amount=amount, version=version), self.assertRaisesRegex(ValidationError, 'scalar margin or version'):
                PaperReplay(self.root / 'bad.sqlite3', dataset=data, strategy=self.spec, broker=self.broker,
                            margin_per_contract=Decimal(amount), margin_version=version)
        with self.assertRaisesRegex(ValidationError, 'either'):
            self.new_replay(margin_per_contract=Decimal('120000'), margin_version='day-v1')
        self.assertFalse(self.broker.snapshot()['orders'])

    def test_schedule_restart_crash_retry_and_completed_repeat_no_extra_orders(self):
        replay = self.new_replay(); replay.targets = {0: 1}; replay.start()
        def crash(point):
            if point == 'after_fill_before_cursor': raise RuntimeError('synthetic interruption')
        replay._fault = crash
        with self.assertRaises(RuntimeError): replay.step(max_bars=1)
        original = self.broker.snapshot()
        self.broker = self.new_broker()
        resumed = self.new_replay(); resumed.targets = {0: 1}
        with self.assertRaisesRegex(ValidationError, 'Reconcile'): resumed.start()
        self.broker.reconcile(self.broker.snapshot()); resumed.start(); resumed.step(max_bars=1)
        for field in ('orders', 'fills', 'cash', 'positions', 'order_send_timestamps'):
            self.assertEqual(self.broker.snapshot()[field], original[field])
        resumed.step(max_bars=1); resumed.stop()
        final = self.broker.snapshot(); resumed.start(); resumed.step(max_bars=2); resumed.stop()
        for field in ('orders', 'fills', 'cash', 'positions', 'order_send_timestamps'):
            self.assertEqual(self.broker.snapshot()[field], final[field])
        self.assertTrue(resumed.snapshot()['complete'])
        with self.assertRaises(ValidationError): resumed.step(max_bars=1001)


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(HAS_QT, 'Pinned Qt required for actual typed form / process worker')
class TypedReplayWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_typed_120000_normal_worker_and_repeat_are_safe(self):
        from tests.test_desktop_ui import NativeDesktopTests
        from quantlab.reporting import read_json
        from desktop_ui import paper_risk_limits
        self.cleanup_window = NativeDesktopTests.cleanup_window.__get__(self)
        self.click = NativeDesktopTests.click.__get__(self)
        self.wait_job = NativeDesktopTests.wait_job.__get__(self)
        NativeDesktopTests.setUp(self)
        self.click('create_demo'); self.wait_job()
        self.click('run_backtest'); self.wait_job()
        self.click('select_strategy'); self.wait_job()
        self.click('demo_policy')
        # Ordinary typed policy table, not advanced JSON or a patched backend.
        self.window.policy_form.margins.table.item(0, 1).setText('120000')
        self.window.policy_form.margins.table.item(0, 2).setText('typed-synthetic-120000-v1')
        typed = self.window.policy_form.build_payload()
        self.assertEqual(typed['margin_schedule'][0]['margin_per_contract'], '120000')
        self.click('paper_snapshot'); self.wait_job()
        self.click('paper_reconcile'); self.wait_job()
        self.window.replay_bars.setValue(1000)
        self.window.paper_confirm.setChecked(True)
        self.click('paper_replay'); self.wait_job()
        result = json.loads(self.window.paper_detail.toPlainText())
        self.assertTrue(result['replay']['complete'])
        self.assertTrue(result['account']['fills'])
        self.assertTrue(result['account']['kill_switch'])
        self.assertFalse(self.window.paper_confirm.isChecked())
        self.assertEqual(read_json(self.paths.state / 'paper_policy.json'), typed)
        self.assertEqual(paper_risk_limits().max_position, 1)
        self.assertEqual(paper_risk_limits().max_order_quantity, 1)
        self.assertEqual(paper_risk_limits().max_daily_loss, Decimal('1000'))
        # Repeated worker action still requires an explicit up-to-date reference.
        self.window.snapshot_form.from_payload(result['account'])
        self.window.paper_confirm.setChecked(True)
        self.click('paper_replay'); self.wait_job()
        repeated = json.loads(self.window.paper_detail.toPlainText())
        self.assertEqual(repeated['replay']['binding'], result['replay']['binding'])
        for field in ('fills', 'orders', 'positions', 'cash', 'order_send_timestamps'):
            self.assertEqual(repeated['account'][field], result['account'][field])
        self.evidence = {'typed_margin': typed['margin_schedule'][0], 'replay': result['replay'],
                         'orders': len(result['account']['orders']), 'fills': len(result['account']['fills']),
                         'repeat_no_extra_orders': True, 'kill_switch': repeated['account']['kill_switch'],
                         'scope': 'invented synthetic normal typed Qt controls and isolated worker; no network/model/OOS/holdout'}


if __name__ == '__main__': unittest.main()
