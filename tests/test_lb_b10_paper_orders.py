"""Cheap synthetic paper amend, replay and offscreen gesture contracts."""

import ast
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D, localcontext, ROUND_UP
import inspect
import json
import re
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from desktop_app.components.charts import CandlestickChart
from desktop_app.components.chart_annotations import ChartTrace
from desktop_app.features.paper.order_lines import tick_price
from desktop_app.strings.catalog import ui_text
import desktop_app.shell.main_window as ui
from quantlab.core import Instrument, CostSpec, ValidationError, canonical_json
from quantlab.paper import PaperBroker, RiskLimits, RiskDecision, JournalConflict, ReconciliationError, LiveBroker, LiveTradingDisabled
from tests.test_chart_data import bar
import tests.test_paper as _paper_fixture
from tests.test_paper import NOW, CID
# Source scans below use current physical paths.


ROOT = Path(__file__).resolve().parents[1]


class AmendTests(unittest.TestCase):
    intent = _paper_fixture.PaperTests.intent
    quote = _paper_fixture.PaperTests.quote
    event = _paper_fixture.PaperTests.event

    def setUp(self):
        self.root = ROOT / ('.b10-test-' + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root))
        self.path = self.root / 'paper.sqlite3'
        self.kw = dict(
            instrument=Instrument(CID, expiry='2026-10-21'),
            costs=CostSpec(D('10'), D('.00002'), 0, 'half_up', '2026-01-01', 'synthetic-v1'),
            limits=RiskLimits(5, 3, D('500'), 5),
            risk_sessions=(
                {'open': NOW - timedelta(minutes=15), 'end': NOW + timedelta(hours=4), 'trade_date': '2026-10-09', 'source': 'synthetic', 'session': 'day'},
            ),
            margin_schedule=({'effective_from': '2026-01-01', 'margin_per_contract': D('10000'), 'version': 'synthetic'},),
        )
        self.broker = PaperBroker(self.path, **self.kw)
        self.broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        self.broker.submit(self.intent(order_type='limit', limit_price=D('20000')), quote=self.quote(), now=NOW)

    def amend(self, key='first', price=D('20001'), **changes):
        args = dict(price=price, amend_key=key, quote=self.quote(), now=NOW)
        args.update(changes)
        return self.broker.amend('a', **args)

    def ack(self, key='first'):
        order = self.broker.snapshot()['orders']['a']
        return self.broker.apply_event(self.event(typ='amend', seq=order['sequence'] + 1, amend_key=key))

    def assert_no_write(self, action):
        before = self.broker.journal_events()
        with self.assertRaises(ValidationError):
            action()
        self.assertEqual(self.broker.journal_events(), before)

    def test_restart_replays_price_and_requires_ack_before_reconcile(self):
        self.amend(price=D('20001.0'))
        event = self.broker.journal_events()[-1]
        self.assertEqual((event['operation'], event['payload']['price']), ('amend', '20001.0'))
        self.assertIn('"price":"20001.0"', canonical_json(event['payload']))
        self.broker = PaperBroker(self.path, **self.kw)
        state = self.broker.snapshot()
        self.assertEqual(state['orders']['a']['intent']['limit_price'], '20001.0')
        with self.assertRaisesRegex(ReconciliationError, 'pending amend'):
            self.broker.reconcile(state)
        self.assert_no_write(lambda: self.amend('during-reconcile'))
        self.assertEqual(self.ack()['status'], 'applied')
        self.assertTrue(self.broker.snapshot()['reconciliation_required'])
        self.broker.reconcile(self.broker.snapshot())
        self.assertFalse(self.broker.snapshot()['reconciliation_required'])

    def test_idempotent_keys_and_last_journal_writer(self):
        self.amend()
        count = len(self.broker.journal_events())
        self.amend()
        self.assertEqual(len(self.broker.journal_events()), count)
        with self.assertRaises(JournalConflict):
            self.amend(price=D('20002'))
        self.amend('second', D('19999'))
        self.amend()
        state = self.broker.snapshot()
        self.assertEqual(state['orders']['a']['intent']['limit_price'], '19999')
        self.assertEqual(state['orders']['a']['pending_amend'], 'second')
        self.assertEqual(state['orders']['a']['intent']['quantity'], 1)
        self.broker = PaperBroker(self.path, **self.kw)
        self.assertEqual(self.broker.snapshot()['orders'], state['orders'])
        self.amend('second', D('19999'))
        self.assertEqual(sum(e['operation'] == 'amend' for e in self.broker.journal_events()), 2)

    def test_strict_decimal_tick_time_and_quantity(self):
        for price in ('20001', 20001, 20001.0, True, D('NaN'), D('sNaN'), D('Infinity'), D('0'), D('-1'), D('20000.5')):
            with self.subTest(price=price):
                self.assert_no_write(lambda: self.amend(price=price))
        self.assert_no_write(lambda: self.amend(now=NOW - timedelta(seconds=1)))
        with self.assertRaises(TypeError):
            self.amend(quantity=2)
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 2, ROUND_UP
            result = self.amend()
        self.assertEqual(result['intent']['limit_price'], '20001')

    def test_inactive_states_and_risk_latches_write_nothing(self):
        original = self.broker.snapshot()
        for status in ('filled', 'cancelled', 'cancel_pending', 'rejected', 'unknown', 'submitting'):
            state = deepcopy(original)
            state['orders']['a']['status'] = status
            with self.subTest(status=status), patch.object(self.broker, '_restore', return_value=state):
                self.assert_no_write(self.amend)
        for name in ('kill_switch', 'reconciliation_required', 'consecutive_loss_halt'):
            state = deepcopy(original)
            state[name] = True
            with self.subTest(gate=name), patch.object(self.broker, '_restore', return_value=state):
                self.assert_no_write(self.amend)
        self.assert_no_write(lambda: self.broker.amend('missing', price=D('20001'), amend_key='x', quote=self.quote(), now=NOW))
        self.broker.set_kill_switch(True)
        self.assert_no_write(self.amend)

    def test_same_risk_entry_as_submit_without_bypass(self):
        with patch.object(self.broker, '_risk', return_value=RiskDecision(False, 'sentinel')) as risk:
            self.assert_no_write(self.amend)
            self.assertEqual(risk.call_count, 1)
            self.assertEqual(risk.call_args.kwargs['replace_order_id'], 'a')
            self.broker.submit(self.intent('blocked'), quote=self.quote(), now=NOW)
            self.assertEqual(risk.call_count, 2)

    def test_manual_lock_blocks_amend_before_other_latches_and_survives_restart(self):
        def assert_locked():
            events = self.broker.journal_events()
            with self.assertRaisesRegex(ValidationError, '^manual_order_lock$'):
                self.amend()
            self.assertEqual(self.broker.journal_events(), events)

        self.broker.set_manual_order_lock(True)
        before = self.broker.snapshot()
        assert_locked()
        self.assertEqual(self.broker.snapshot(), before)
        self.broker = PaperBroker(self.path, **self.kw)
        self.broker.set_kill_switch(True)
        assert_locked()
        self.broker.reconcile(self.broker.snapshot())
        self.broker.set_kill_switch(False)
        assert_locked()
        self.broker.set_manual_order_lock(False)
        self.assertEqual(self.amend()['intent']['limit_price'], '20001')

    def test_order_creation_append_sites_remain_submit_only(self):
        tree = ast.parse((ROOT / 'quantlab/paper.py').read_text(encoding='utf-8'))
        broker = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PaperBroker')
        creation_sites = []
        for method in broker.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for call in ast.walk(method):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != '_append':
                    continue
                if len(call.args) > 2 and isinstance(call.args[2], ast.Constant) and call.args[2].value in ('intent', 'risk_reject'):
                    creation_sites.append((method.name, call.args[2].value))
        self.assertEqual(sorted(creation_sites), [('submit', 'intent'), ('submit', 'risk_reject')])

    def test_21_amends_share_frequency_window_without_loss_changes(self):
        before = self.broker.snapshot()
        for i in range(21):
            if i < 19:
                self.amend(str(i), D(20001 + i))
            else:
                self.assert_no_write(lambda: self.amend(str(i), D(20001 + i)))
        state = self.broker.snapshot()
        self.assertEqual(sum(e['operation'] == 'amend' for e in self.broker.journal_events()), 19)
        self.assertEqual(len(state['order_send_timestamps']), 20)
        for field in ('lots', 'round_trips', 'consecutive_losses', 'consecutive_loss_halt'):
            self.assertEqual(state[field], before[field])
        later = NOW + timedelta(seconds=61)
        self.amend('after-window', quote=self.quote(timestamp=later), now=later)
        self.assertEqual(len(self.broker.snapshot()['order_send_timestamps']), 1)

    def test_partial_quantity_reservation_is_replaced_not_duplicated(self):
        self.broker.submit(self.intent('two', order_type='limit', limit_price=D('20000'), quantity=3), quote=self.quote(), now=NOW)
        self.broker.apply_event(self.event('two', quantity=1))
        result = self.broker.amend('two', price=D('20001'), amend_key='partial', quote=self.quote(), now=NOW)
        self.assertEqual((result['status'], result['intent']['quantity'], result['filled_quantity']), ('partial', 3, 1))

    def test_failed_append_rolls_back_and_price_has_canonical_string_form(self):
        before = self.broker.snapshot()
        with patch.object(self.broker, '_append', side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError):
                self.amend()
        self.assertEqual(self.broker.snapshot(), before)
        with patch.object(self.broker, '_append', wraps=self.broker._append) as append:
            self.amend()
        self.assertEqual(append.call_args.args[3]['price'], '20001')

    def test_frozen_pre_change_journal_replays_without_migration(self):
        golden = json.loads((ROOT / 'tests/fixtures/lb_b10_legacy_journal.json').read_text(encoding='utf-8'))
        path = self.root / 'legacy.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute(
                'CREATE TABLE journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT UNIQUE NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL, state_hash TEXT NOT NULL)'
            )
            db.execute('CREATE TABLE materialized (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)')
            db.executemany('INSERT INTO metadata VALUES (?,?)', golden['metadata'])
            db.executemany('INSERT INTO journal VALUES (?,?,?,?,?)', golden['journal'])
            db.executemany('INSERT INTO materialized VALUES (?,?)', golden['materialized'])
            db.commit()
        self.assertEqual(PaperBroker.read_snapshot(path), golden['snapshot'])
        restarted = PaperBroker(path, **self.kw)
        state = restarted.snapshot()
        self.assertTrue(state.pop('reconciliation_required'))
        expected = dict(golden['snapshot'])
        expected.pop('reconciliation_required')
        self.assertEqual(state, expected)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute('SELECT * FROM journal ORDER BY seq LIMIT ?', (len(golden['journal']),)).fetchall(), [tuple(r) for r in golden['journal']]
            )

    def test_existing_worker_envelope_and_preexisting_reconciliation_guard(self):
        payload = dict(
            action='amend',
            mode='paper',
            order_id='a',
            price='20001',
            amend_key='worker',
            now=NOW.isoformat(),
            quote=self.quote(),
            reconcile_confirmed=True,
            snapshot=self.broker.snapshot(),
        )
        with (
            patch.object(ui, '_prepare_paper_operation', side_effect=lambda *a: PaperBroker(self.path, **self.kw)),
            patch.object(ui, '_finish_paper_operation', side_effect=lambda root, broker: broker.snapshot()),
            patch('socket.socket', side_effect=AssertionError('offline only')),
        ):
            result = ui._handle_ui_paper_cancel(payload, None, self.root)
        self.assertEqual(result['orders']['a']['intent']['limit_price'], '20001')
        self.assertNotIn('pending_amend', result['orders']['a'])
        self.assertFalse(result['reconciliation_required'])
        self.broker = PaperBroker(self.path, **self.kw)
        payload['snapshot'] = self.broker.snapshot()
        with patch.object(ui, '_prepare_paper_operation') as prepare:
            with self.assertRaises(ValidationError):
                ui._handle_ui_paper_cancel(payload, None, self.root)
            prepare.assert_not_called()

    def test_drag_to_broker_with_failed_journal_preserves_snapshot(self):
        app = QApplication.instance() or QApplication([])
        chart = CandlestickChart()
        chart.resize(800, 500)
        chart.set_series((bar(0, 19990), bar(1, 20000), bar(2, 20010)))
        chart.set_paper_snapshot(self.broker.snapshot(), request=lambda oid, price: self.amend(price=price))
        self.addCleanup(chart.close)
        image = QImage(chart.size(), QImage.Format.Format_ARGB32)
        chart.render(image)
        point = QPointF(100, chart.paper_orders.hits[0][1])
        before = self.broker.journal_events()
        with patch.object(self.broker, '_append', side_effect=OSError('injected journal failure')) as append:
            chart.paper_orders.press(point, chart.price_rect)
            chart.paper_orders.release(point - QPointF(0, 40), chart.price_rect)
        self.assertIsNotNone(app)
        append.assert_called_once()
        self.assertEqual(self.broker.journal_events(), before)
        self.assertEqual(chart.paper_orders.lines(CID)[0][3], D('20000'))
        self.assertEqual(chart.paper_orders.notice, ui_text('orders.failed'))
        # Retrying the gesture can commit, but only a later snapshot moves it.
        chart.paper_orders.press(point, chart.price_rect)
        chart.paper_orders.release(point - QPointF(0, 40), chart.price_rect)
        payload = self.broker.journal_events()[-1]['payload']
        self.assertIsInstance(payload['price'], str)
        self.assertIn('"price":"' + payload['price'] + '"', canonical_json(payload))
        self.assertEqual(chart.paper_orders.lines(CID)[0][3], D('20000'))
        chart.set_paper_snapshot(self.broker.snapshot())
        self.assertEqual(chart.paper_orders.lines(CID)[0][3], D(payload['price']))


class OrderChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.snapshot = json.loads((ROOT / 'tests/fixtures/lb_b10_legacy_journal.json').read_text(encoding='utf-8'))['snapshot']
        self.chart = CandlestickChart()
        self.chart.resize(800, 500)
        self.chart.set_series((bar(0, 19990), bar(1, 20000), bar(2, 20010)))
        self.addCleanup(self.chart.close)

    def paint(self):
        image = QImage(self.chart.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        self.chart.render(image)
        return image

    def press(self):
        self.paint()
        point = QPointF(100, self.chart.paper_orders.hits[0][1])
        self.chart.mousePressEvent(
            QMouseEvent(QMouseEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        )
        return point

    def release(self, point):
        self.chart.mouseReleaseEvent(
            QMouseEvent(QMouseEvent.Type.MouseButtonRelease, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        )

    def test_qimage_active_and_terminal_lines(self):
        baseline = self.paint()
        for status in ('accepted', 'partial', 'filled', 'cancelled', 'rejected', 'cancel_pending', 'unknown', 'submitting'):
            snapshot = deepcopy(self.snapshot)
            snapshot['orders']['a']['status'] = status
            self.chart.set_paper_snapshot(snapshot)
            image = self.paint()
            active = status in ('accepted', 'partial')
            self.assertEqual(len(self.chart.paper_orders.hits), int(active))
            self.assertEqual(image != baseline, active)
        snapshot['orders']['a']['status'] = 'partial'
        snapshot['orders']['a']['filled_quantity'] = 1
        self.chart.set_paper_snapshot(snapshot)
        self.assertEqual(self.paint(), baseline)

    def test_snapshot_copy_and_paper_only_modes(self):
        callback = Mock()
        self.chart.set_paper_snapshot(self.snapshot, request=callback)
        self.snapshot['orders']['a']['intent']['limit_price'] = '1'
        self.assertEqual(self.chart.paper_orders.lines(CID)[0][3], D('20000'))
        for mode in ('live', 'backtest', 'replay', None):
            self.chart.set_paper_snapshot(self.snapshot, mode=mode, request=callback)
            self.paint()
            self.assertFalse(self.chart.paper_orders.hits)
        for value in (object(), [], {'orders': {}}, {'verification': 'live', 'orders': {}}):
            with self.assertRaises(ValueError):
                self.chart.set_paper_snapshot(value)
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()

    def test_drag_failure_keeps_old_line_and_displays_error(self):
        callback = Mock(side_effect=OSError('write failure'))
        self.chart.set_paper_snapshot(self.snapshot, request=callback)
        original = self.paint()
        point = self.press()
        self.release(point - QPointF(0, 40))
        callback.assert_called_once()
        self.assertIsInstance(callback.call_args.args[1], D)
        self.assertEqual(self.chart.paper_orders.lines(CID)[0][3], D('20000'))
        self.assertEqual(self.chart.paper_orders.notice, ui_text('orders.failed'))
        self.assertNotEqual(self.paint(), original)
        self.assertAlmostEqual(self.chart.paper_orders.hits[0][1], point.y())

    def test_esc_and_release_outside_write_nothing(self):
        callback = Mock()
        self.chart.set_paper_snapshot(self.snapshot, request=callback)
        point = self.press()
        self.chart.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.release(point - QPointF(0, 40))
        self.press()
        self.release(QPointF(-1, -1))
        callback.assert_not_called()

    def test_success_waits_for_snapshot_and_trace_clears_affordance(self):
        callback = Mock()
        self.chart.set_paper_snapshot(self.snapshot, request=callback)
        point = self.press()
        self.release(point - QPointF(0, 40))
        self.assertEqual(self.chart.paper_orders.lines(CID)[0][3], D('20000'))
        self.snapshot['orders']['a']['intent']['limit_price'] = str(callback.call_args.args[1])
        self.chart.set_paper_snapshot(self.snapshot, request=callback)
        self.assertEqual(self.chart.paper_orders.lines(CID)[0][3], callback.call_args.args[1])
        self.chart.set_series(self.chart.bars, trace=ChartTrace(CID, 'a' * 64, 'b' * 64, ui_text('charts.post_init.backtest')))
        self.paint()
        self.assertFalse(self.chart.paper_orders.hits)

    def test_async_worker_failure_clears_pending_notice_and_keeps_line(self):
        # Import the existing presentation adapter only for its failure event.
        from desktop_app.components.job_progress import failure_notice

        self.chart.set_paper_snapshot(self.snapshot, request=Mock())
        point = self.press()
        self.release(point - QPointF(0, 40))
        shell = SimpleNamespace(last_operation='ui_paper_cancel', market=SimpleNamespace(chart=self.chart))
        self.assertEqual(failure_notice(shell, {'type': 'error'}), ui_text('orders.failed'))
        self.assertEqual(self.chart.paper_orders.lines(CID)[0][3], D('20000'))

    def test_public_oracle_and_class_size_limits_unchanged(self):
        expected = json.loads((ROOT / 'tests/fixtures/desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in vars(ui) if not name.startswith('_')), expected)
        for path in [ROOT / 'desktop_app/shell/main_window.py', *(ROOT / 'desktop_app').rglob('*.py')]:
            for node in ast.parse(path.read_text(encoding='utf-8-sig'), feature_version=(3, 11)).body:
                if isinstance(node, ast.ClassDef) and (node.name == 'MainWindow' or node.name.endswith('Page')):
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 400 if node.name == 'MainWindow' else 500)

    def test_decimal_tick_conversion_isolated_from_ambient_rounding(self):
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 5, ROUND_UP
            result = tick_price(49.5, top=0.0, bottom=100.0, low=D('100'), high=D('200'), tick=D('1'))
        self.assertIsInstance(result, D)
        self.assertEqual(result, D('151'))
        self.assertEqual(tick_price(49.5, top=0, bottom=100, low=D('100'), high=D('200'), tick=D('0.25')), D('150.50'))

    def test_new_chart_path_has_no_execution_or_network_imports(self):
        source = (ROOT / 'desktop_app/features/paper/order_lines.py').read_text(encoding='utf-8')
        modules = [n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(m and ('paper' in m or 'network' in m or 'socket' in m) for m in modules))
        added = source + inspect.getsource(PaperBroker.amend) + (ROOT / 'quantlab/paper_amend.py').read_text(encoding='utf-8')
        for forbidden in ('shioaji', 'place_order', 'update_order', 'sendOrder', 'LiveBroker', 'apiPost'):
            self.assertIsNone(re.search(r'\b' + forbidden + r'\b', added))


if __name__ == '__main__':
    unittest.main()
