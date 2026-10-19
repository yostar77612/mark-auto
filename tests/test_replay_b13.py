"""Offline B13 pacing, durable pause and UI controller regressions."""

import ast
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

import desktop_ui as ui
from desktop_pages.paper import PaperPage
from desktop_pages.replay_controls import ReplayControls
from desktop_strings import ui_text
from quantlab.core import ValidationError, content_hash, to_dict
from quantlab.replay_pacing import ReplayPacer, SPEEDS, TICK_BARS, control
from quantlab.reporting import synthetic_dataset
from quantlab.strategies import builtin_strategies
from tests import test_paper_replay as fixtures
from tests.test_t9_onboarding import sandbox_ui
from quantlab.desktop_runtime import AppPaths


ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ReplayB13Tests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ('.tmp-b13-' + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.fixture = fixtures.ReplayTests()
        self.fixture.root = self.root
        self.fixture.data = synthetic_dataset(20)
        self.fixture.spec = builtin_strategies()[0]

    def fresh(self):
        for path in self.root.iterdir():
            path.unlink()
        f = self.fixture
        f.broker = f.new_broker()
        f.broker.reconcile({'account_id': 'replay', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}})
        replay = f.new_replay()
        replay.targets = {1: 1, 6: 0, 12: 1, 18: 0}
        return replay

    def run_replay(self, speed, *, pause=False):
        replay = self.fresh()
        clock = FakeClock()
        pacer = ReplayPacer(speed, clock=clock)
        replay.start()
        while not replay.snapshot()['complete']:
            if replay.snapshot()['cursor'] == 10 and pause:
                journal = replay.broker.journal_events()
                replay.pause()
                clock.advance(600)
                self.assertEqual(replay.step(max_bars=1000)['cursor'], 10)
                self.assertEqual(replay.broker.journal_events(), journal)
                replay.resume()
            self.assertTrue(pacer.ready())
            control(replay, 'tick')
            pacer.defer()
            clock.advance(1 / speed)
        replay.stop()
        return replay.snapshot(), replay.broker.snapshot(), content_hash(replay.broker.journal_events())

    def test_every_speed_has_identical_identity_snapshot_fills_cursor_and_journal(self):
        expected = self.run_replay(1)
        self.assertTrue(expected[1]['fills'])
        for speed in SPEEDS:
            with self.subTest(speed=speed):
                self.assertEqual(self.run_replay(speed), expected)

    def test_step_ten_pause_wait_resume_equals_uninterrupted(self):
        self.assertEqual(self.run_replay(100, pause=True), self.run_replay(100))

    def test_pause_guards_no_writes_and_exact_durable_cursor(self):
        r = self.fresh()
        with self.assertRaises(ValidationError):
            r.resume()
        with self.assertRaises(ValidationError):
            r.pause()
        r.start()
        r.step(max_bars=10)
        before = r.broker.journal_events()
        paused = r.pause()
        self.assertTrue(paused['paused'])
        self.assertFalse(paused['active'])
        self.assertFalse(r.broker.snapshot()['kill_switch'])
        for action in (r.pause, r.start, lambda: control(r, 'tick')):
            with self.assertRaises(ValidationError):
                action()
        self.assertEqual(r.step(max_bars=10), paused)
        self.assertEqual(r.broker.journal_events(), before)
        restored = self.fixture.new_replay()
        self.assertEqual(restored.snapshot(), paused)
        self.assertEqual(restored.binding, r.binding)
        self.assertEqual(restored.resume()['cursor'], 10)
        restored.step(max_bars=10)
        with self.assertRaises(ValidationError):
            restored.pause()
        with self.assertRaises(ValidationError):
            restored.resume()
        restored.stop()
        self.assertTrue(r.broker.snapshot()['kill_switch'])

    def test_old_replay_schema_fixture_and_original_binding_are_unchanged(self):
        r = self.fresh()
        expected_binding = content_hash(
            dict(
                data=self.fixture.data.manifest['data_hash'],
                strategy=self.fixture.spec,
                broker_journal=str(r.broker.path.resolve()),
                costs=r.broker.costs,
                limits=r.broker.limits,
                margin=Decimal('100000'),
                margin_version='synthetic-v1',
            )
        )
        self.assertEqual(r.binding, expected_binding)
        r.path.unlink()
        with closing(sqlite3.connect(r.path)) as db, db:
            db.executescript((ROOT / 'tests/fixtures/paper_replay_legacy_b13.sql').read_text())
            db.execute('INSERT INTO replay VALUES (1, ?, 10, 0, NULL)', (expected_binding,))
            columns = db.execute('PRAGMA table_info(replay)').fetchall()
        restored = self.fixture.new_replay()
        self.assertEqual(restored.binding, expected_binding)
        self.assertEqual(restored.snapshot()['cursor'], 10)
        restored.start()
        restored.pause()
        with closing(sqlite3.connect(r.path)) as db:
            self.assertEqual(db.execute('PRAGMA table_info(replay)').fetchall(), columns)
        self.assertTrue(self.fixture.new_replay().snapshot()['paused'])

    def test_validation_and_safety_latches_still_block(self):
        r = self.fresh()
        r.start()
        for value in (True, False, 0, -1, 1001, '10', 1.0, None):
            with self.assertRaises(ValidationError):
                r.step(max_bars=value)
        r.broker.set_kill_switch(True)
        self.assertEqual(r.step(max_bars=1)['cursor'], 0)
        r.pause()
        with self.assertRaises(ValidationError):
            r.resume()
        r.stop()
        r.start()
        self.fixture.broker = self.fixture.new_broker()
        restored = self.fixture.new_replay()
        self.assertEqual(restored.step(max_bars=1)['cursor'], 0)
        restored.pause()
        with self.assertRaises(ValidationError):
            restored.resume()

    def test_highest_speed_single_op_bound_with_fake_clock(self):
        clock = FakeClock()
        pacer = ReplayPacer(max(SPEEDS), clock=clock)
        replay = Mock()
        replay.snapshot.return_value = {'paused': False, 'active': True}
        replay.step.side_effect = lambda **kwargs: clock.advance(kwargs['max_bars'] * 0.1)
        for _ in range(50):
            before = clock()
            control(replay, 'tick')
            self.assertLess(clock() - before, 30)
            replay.step.assert_called_with(max_bars=TICK_BARS)
            self.assertEqual(TICK_BARS, 1)
            pacer.defer()
            self.assertFalse(pacer.ready())
            clock.advance(0.011)
            self.assertTrue(pacer.ready())
        replay.start.assert_not_called()
        for speed in (True, 0, 3, 101, 100.0, '100', None):
            with self.assertRaises(ValidationError):
                pacer.set_speed(speed)

    def test_worker_adapter_preserves_original_smoke_and_short_controls(self):
        self.fixture.data = synthetic_dataset(30)
        r = self.fresh()
        paths = SimpleNamespace(require_replay_wal=Mock())
        selection = {'strategy': to_dict(self.fixture.spec), 'strategy_hash': content_hash(self.fixture.spec)}
        with (
            patch.object(ui, '_prepare_paper_operation', return_value=r.broker),
            patch.object(ui, '_dataset', return_value=self.fixture.data),
            patch.object(ui, 'load_selection', return_value=selection),
        ):
            payload = {'snapshot': r.broker.snapshot(), 'reconcile_confirmed': True, 'max_bars': 25}
            result = ui._handle_ui_paper_replay(payload, paths, self.root)
            self.assertNotIn('paused', result['replay'])
            self.assertNotIn('replay_action', payload)
            self.assertEqual(result['replay']['processed_bars'], 25)
            self.assertEqual(result['replay']['cursor'], 25)
            self.assertTrue(result['account']['kill_switch'])
            payload['snapshot'] = result['account']
            for action, cursor, paused in (('tick', 26, False), ('pause', 26, True), ('inspect', 26, True), ('resume', 26, False), ('tick', 27, False)):
                result = ui._handle_ui_paper_replay(dict(payload, replay_action=action), paths, self.root)
                self.assertEqual(result['replay']['cursor'], cursor)
                self.assertEqual(result['replay'].get('paused', False), paused)
                self.assertFalse(result['account']['kill_switch'])
                payload['snapshot'] = result['account']
            result = ui._handle_ui_paper_replay(dict(payload, replay_action='stop'), paths, self.root)
            self.assertTrue(result['account']['kill_switch'])
            self.assertEqual(result['replay']['cursor'], 27)


class ReplayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = QWidget()
        self.page.host = SimpleNamespace(safe=lambda callback: callback())
        self.page.jobs = SimpleNamespace(active=False)
        self.page.start_job = Mock()
        self.controls = ReplayControls(self.page, QVBoxLayout(self.page))
        self.addCleanup(self.page.close)
        self.addCleanup(self.controls.cancel)
        self.controls.pacer = ReplayPacer(clock=FakeClock())

    def reply(self, *, paused=False, complete=False):
        self.controls.result({'replay': {'paused': paused, 'complete': complete}, 'account': {'kill_switch': False, 'reconciliation_required': False}})

    def test_speed_pause_resume_and_no_step_while_paused(self):
        c = self.controls
        self.assertEqual([c.speed.itemData(i) for i in range(c.speed.count())], [None, *SPEEDS])
        for widget in (c.speed, c.button, c.label):
            self.assertTrue(widget.accessibleName())
        self.assertTrue(c.speed.toolTip())
        self.assertTrue(c.button.toolTip())
        c.begin({'max_bars': 20, 'snapshot': {}, 'reconcile_confirmed': True})
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'inspect')
        self.reply()
        c.pacer.clock.advance(1)
        c.tick()
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'tick')
        c.toggle()  # Queue pause while the one-bar worker is still in flight.
        self.reply()
        c.tick()
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'pause')
        self.reply(paused=True)
        self.assertEqual(c.label.text(), ui_text('replay.paused'))
        self.assertEqual(c.button.text(), ui_text('replay.resume'))
        before = self.page.start_job.call_count
        c.pacer.clock.advance(600)
        c.tick()
        c.begin({'max_bars': 20})
        self.assertEqual(self.page.start_job.call_count, before)
        c.toggle()
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'resume')
        self.reply()
        self.assertEqual(c.label.text(), ui_text('replay.running'))
        c.speed.setCurrentIndex(c.speed.count() - 1)
        self.assertEqual(c.pacer.speed, 100)
        self.assertFalse(c.pacer.ready())
        c.pacer.clock.advance(0.011)
        c.tick()
        self.reply(complete=True)
        c.tick()
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'stop')
        self.reply(complete=True)
        self.assertFalse(c.running)
        self.assertFalse(c.timer.isActive())

    def test_durable_paused_inspection_requires_resume_and_cancel_cancels_timer(self):
        c = self.controls
        c.begin({'max_bars': 20})
        self.reply(paused=True)
        c.pacer.clock.advance(600)
        c.tick()
        self.assertEqual(self.page.start_job.call_count, 1)
        self.assertEqual(c.label.text(), ui_text('replay.paused'))
        c.cancel()
        c.tick()
        self.assertEqual(self.page.start_job.call_count, 1)

    def test_stop_from_paused_and_job_submission_failure_end_session(self):
        c = self.controls
        c.begin({'max_bars': 20})
        self.reply(paused=True)
        c.stop()
        self.assertEqual(self.page.start_job.call_args.args[1]['replay_action'], 'stop')
        self.reply()
        self.assertFalse(c.running)
        self.page.start_job.side_effect = RuntimeError('offline fake worker failure')
        with self.assertRaises(RuntimeError):
            c.begin({'max_bars': 20})
        self.assertFalse(c.running)
        self.assertFalse(c.timer.isActive())

    def test_real_page_defaults_to_original_worker_and_hides_controls(self):
        root = ROOT / ('.tmp-b13-ui-' + uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        with sandbox_ui():
            jobs = SimpleNamespace(active=False, poll=lambda: [], start=Mock(), close=Mock())
            window = ui.MainWindow(AppPaths(root).ensure(), jobs)
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
            for timer in window.findChildren(QTimer):
                timer.stop()
            page = window.findChild(PaperPage)
            controls = page.replay_controls
            self.assertIsNone(controls.speed.currentData())
            for widget in (controls.speed, controls.button, controls.stop_button, controls.label):
                self.assertFalse(widget.isVisibleTo(page))
            button = window.findChild(QPushButton, 'paper_replay')
            with patch.object(page, 'paper_job') as submit:
                button.clicked.emit()
                submit.assert_called_once_with('replay', max_bars=100, _paced=False)
                controls.speed.setCurrentIndex(1)
                button.clicked.emit()
                self.assertEqual(submit.call_args.kwargs, {'max_bars': 100, '_paced': True})
            page.paper_policy.setPlainText('{"synthetic_test_policy": true}')
            page.paper_confirm.setChecked(True)
            with patch.object(page, 'start_job') as start, patch.object(controls, 'begin') as begin:
                page.paper_job('replay', max_bars=25, _paced=False)
                begin.assert_not_called()
                self.assertEqual(start.call_args.args[0], 'ui_paper_replay')
                self.assertEqual(set(start.call_args.args[1]), {'max_bars', 'snapshot', 'reconcile_confirmed', 'policy'})
                self.assertEqual(start.call_args.args[1]['max_bars'], 25)

    def test_public_oracle_and_page_size(self):
        expected = json.loads((ROOT / 'tests/fixtures/desktop_ui_public_names.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(name for name in vars(ui) if not name.startswith('_')), expected)
        for path in [ROOT / 'desktop_ui.py', *(ROOT / 'desktop_pages').glob('*.py')]:
            for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
                if isinstance(node, ast.ClassDef) and (node.name == 'MainWindow' or node.name.endswith('Page')):
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 400 if node.name == 'MainWindow' else 500)


if __name__ == '__main__':
    unittest.main()
