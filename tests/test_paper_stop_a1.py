"""Persistent user stops, reachable resume, and unchanged batch boundaries."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QCheckBox, QWidget

import desktop_app.shell.main_window as ui
from desktop_app.features.paper.paper import PaperPage
from desktop_app.strings.catalog import ui_text
from quantlab.core import ValidationError
from quantlab.desktop_errors import error_message, exception_code
from quantlab.desktop_feedback import stop_presentation
from quantlab.paper import PaperBroker
from quantlab.reporting import write_json
from tests import test_paper as paper_fixtures
from tests import test_paper_replay as replay_fixtures
from tests.test_paper_lock_b2 import ScratchDirectory


class StopResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = paper_fixtures.PaperTests()
        with patch.object(paper_fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = Path(self.fixture.tmp.name)
        self.broker = PaperBroker(self.root / 'paper.sqlite3', **self.fixture.kw)
        self.broker.reconcile(self.fixture.broker.snapshot())
        write_json(self.root / 'paper_policy.json', {})
        self.page = self.make_page()
        self.dialog = SimpleNamespace(confirm_button=object(), observe_button=object(), exec=Mock())
        self.dialog.clickedButton = Mock(return_value=self.dialog.confirm_button)
        dialog_patch = patch('desktop_app.features.paper.paper.stop_dialog', return_value=self.dialog)
        dialog_patch.start()
        self.addCleanup(dialog_patch.stop)
        prepare = patch.object(ui, '_prepare_paper_operation', side_effect=lambda *args: self.broker)
        finish = patch.object(ui, '_finish_paper_operation', side_effect=lambda root, broker, replay: broker.snapshot())
        prepare.start()
        finish.start()
        self.addCleanup(prepare.stop)
        self.addCleanup(finish.stop)

    def make_page(self):
        page = PaperPage.__new__(PaperPage)
        QWidget.__init__(page)
        self.addCleanup(page.close)
        state = SimpleNamespace(
            root=self.root,
            status=QLabel(),
            manual_order_lock=False,
            paper_confirm=QCheckBox(),
            paper_policy=Mock(),
            policy_form=Mock(),
            chatgpt_panel=SimpleNamespace(consent=QCheckBox()),
            _chatgpt_job_request=None,
            chatgpt_controller=Mock(),
            guard=None,
            market=Mock(),
            paper_card=SimpleNamespace(set_values=Mock(), label=QLabel()),
            jobs=SimpleNamespace(active=False),
        )
        state.market.chart.trace = None
        page.setup_context(
            SimpleNamespace(
                state=state,
                callbacks={
                    '_paper': Mock(side_effect=lambda root: self.broker),
                    'read_json': Mock(return_value={}),
                    'write_json': write_json,
                    '_quiesce_and_recover': Mock(),
                    '_payload': Mock(return_value={}),
                    'start_job': Mock(),
                },
            )
        )
        page.replay_controls = SimpleNamespace(cancel=Mock())
        page.kpis = Mock()
        page.positions_table = Mock()
        page.orders_table = Mock()
        page.account_fills_table = Mock()
        # Use real children: lock presentation must never disable their container.
        for name in ('paper_submit', 'paper_replay', 'paper_cancel', 'paper_reconcile', 'paper_manual_unlock'):
            button = QPushButton(ui_text('paper.manual_unlock'), page)
            button.setObjectName(name)
            button.setAccessibleName(button.text())
        return page

    def submit(self, oid):
        payload = dict(
            reconcile_confirmed=True,
            snapshot=self.broker.snapshot(),
            intent=self.fixture.intent(oid),
            quote=self.fixture.quote(),
            now=paper_fixtures.NOW.isoformat(),
        )
        with patch.object(ui, 'load_selection', return_value={'strategy_hash': 'synthetic-strategy'}):
            return ui._handle_ui_paper_submit(payload, None, self.root)

    def assert_stopped_submit(self):
        before = self.broker.snapshot()
        intents = sum(e['operation'] == 'intent' for e in self.broker.journal_events())
        account = self.submit('blocked')
        self.assertEqual(account['orders']['blocked']['status'], 'rejected')
        self.assertEqual(account['orders']['blocked']['reason'], 'manual_order_lock')
        for key in ('positions', 'cash', 'fills'):
            self.assertEqual(account[key], before[key])
        self.assertEqual(sum(e['operation'] == 'intent' for e in self.broker.journal_events()), intents)

    def test_confirm_reconcile_consent_submit_stays_locked_and_resume_in_same_process(self):
        self.page.kill_paper()
        events = self.broker.journal_events()
        locks = [e['payload'] for e in events if e['operation'] == 'manual_order_lock']
        self.assertEqual(locks, [{'active': True}])
        self.assertEqual([e['payload'] for e in events if e['operation'] == 'kill'], [{'active': True}])
        self.assertTrue(PaperBroker.read_snapshot(self.broker.path)['manual_order_lock'])
        self.assertEqual(stop_presentation(self.broker.snapshot(), 'user', manual_lock_text=ui_text('paper.manual_locked'))[0], ui_text('paper.manual_locked'))
        ui._handle_ui_paper_reconcile({'snapshot': self.broker.snapshot()}, None, self.root)
        self.assert_stopped_submit()
        self.assertTrue(self.page.page_state.manual_order_lock)

        def start(op, payload):
            self.assertEqual(op, 'ui_paper_reconcile')
            self.assertIs(payload['manual_order_lock'], False)
            self.page._show_account(ui._handle_ui_paper_reconcile(payload, None, self.root))

        self.page.host.callbacks['start_job'].side_effect = start
        self.page.paper_job('reconcile', snapshot=self.broker.snapshot(), manual_order_lock=False)
        self.assertFalse(self.page.page_state.manual_order_lock)
        self.assert_controls(self.page, False)
        self.assertEqual(self.submit('resumed')['orders']['resumed']['status'], 'accepted')

    def test_counterproof_omitting_manual_lock_allows_old_automatic_resume(self):
        # Mutation counter-test: the E2E rejection assertion detects the old bug.
        with patch.object(self.broker, 'set_manual_order_lock'):
            self.page.kill_paper()
        ui._handle_ui_paper_reconcile({'snapshot': self.broker.snapshot()}, None, self.root)
        with self.assertRaises(AssertionError):
            self.assert_stopped_submit()
        self.assertEqual(self.broker.snapshot()['orders']['blocked']['status'], 'accepted')

    def test_lock_whitelist_rejects_five_operations_except_explicit_unlock_or_lock_on(self):
        self.page.page_state.manual_order_lock = True
        for op in ('submit', 'replay', 'cancel', 'reconcile', 'kill'):
            with self.subTest(op=op):
                with self.assertRaises(ValidationError) as caught:
                    self.page.paper_job(op)
                self.assertEqual(str(caught.exception), ui_text('paper.lock.rejected'))
                self.assertIn(ui_text('paper.lock.rejected'), error_message(exception_code(caught.exception)))
        with self.assertRaises(ValidationError):
            self.page.paper_job('reconcile', manual_order_lock=False)
        self.page.paper_job('reconcile', snapshot=self.broker.snapshot(), manual_order_lock=False)
        self.page.paper_job('kill', manual_order_lock=True)
        self.assertEqual(self.page.host.callbacks['start_job'].call_count, 2)
        self.assertTrue(self.page.page_state.manual_order_lock)
        with self.assertRaises(ValidationError) as caught:
            self.page._amend_order('working', '20000')
        self.assertEqual(str(caught.exception), ui_text('paper.lock.rejected'))

    def assert_controls(self, page, locked):
        self.assertTrue(page.isEnabled())
        for name in ('paper_submit', 'paper_replay', 'paper_cancel', 'paper_reconcile', 'paper_manual_unlock'):
            button = page.findChild(QPushButton, name)
            self.assertEqual(button.isEnabled(), not locked or name in ('paper_reconcile', 'paper_manual_unlock'), name)
            self.assertTrue(button.accessibleName())

    def test_observe_and_restart_sync_controls_from_every_snapshot(self):
        self.dialog.clickedButton.return_value = self.dialog.observe_button
        self.page.paper_confirm.setChecked(True)
        self.page.chatgpt_panel.consent.setChecked(True)
        with patch.object(self.broker, 'set_manual_order_lock', wraps=self.broker.set_manual_order_lock) as lock:
            self.page.kill_paper()
        lock.assert_called_once_with(True)
        self.page.replay_controls.cancel.assert_called_once_with()
        self.page.host.callbacks['start_job'].assert_not_called()
        self.assertTrue(self.page.paper_confirm.isChecked())
        self.assertTrue(self.page.chatgpt_panel.consent.isChecked())
        self.assert_controls(self.page, True)
        self.broker = PaperBroker(self.root / 'paper.sqlite3', **self.fixture.kw)
        snapshot = PaperBroker.read_snapshot(self.root / 'paper.sqlite3')
        fresh = self.make_page()
        fresh._show_account(snapshot)
        self.assertTrue(fresh.page_state.manual_order_lock)
        self.assert_controls(fresh, True)
        self.assertEqual(fresh.kpis.set_values.call_args.args[0]['stop'], ui_text('paper.manual_locked'))
        self.assertIsNone(fresh.market.chart.set_paper_snapshot.call_args.kwargs['request'])
        for snapshot in ({'manual_order_lock': False}, {'manual_order_lock': True}, {}, None):
            fresh._show_account(snapshot)
            locked = bool((snapshot or {}).get('manual_order_lock', False))
            self.assertEqual(fresh.page_state.manual_order_lock, locked)
            self.assert_controls(fresh, locked)

    def test_absent_policy_still_freezes_without_constructing_broker(self):
        (self.root / 'paper_policy.json').unlink()
        before = deepcopy(self.broker.snapshot())
        self.page.kill_paper()
        self.page.host.callbacks['_paper'].assert_not_called()
        self.assertTrue((self.root / 'desktop_safety.json').exists())
        self.assertEqual(self.broker.snapshot(), before)
        self.assertFalse(self.page.paper_confirm.isChecked())

    def test_unreadable_journal_with_policy_does_not_construct_broker(self):
        with patch.object(PaperBroker, 'read_snapshot', side_effect=ValueError('invalid journal')):
            self.page.kill_paper()
        self.page.host.callbacks['_paper'].assert_not_called()
        self.assertTrue((self.root / 'desktop_safety.json').exists())

    def test_replay_handler_rejects_locked_batch_before_cursor_or_fills_change(self):
        fixture = replay_fixtures.ReplayTests()
        with patch.object(replay_fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.broker = fixture.broker
        self.page.kill_paper()
        before = deepcopy(self.broker.snapshot())
        cursor = fixture.replay.snapshot()['cursor']
        with patch.object(ui, '_dataset', return_value=fixture.data) as data:
            with self.assertRaises(ValidationError) as caught:
                ui._handle_ui_paper_replay(dict(snapshot=before, reconcile_confirmed=True), Mock(), self.root)
        self.assertEqual(str(caught.exception), ui_text('paper.lock.rejected'))
        data.assert_not_called()
        self.assertEqual(fixture.replay.snapshot()['cursor'], cursor)
        self.assertEqual(self.broker.snapshot()['fills'], before['fills'])
        self.assertTrue(self.broker.snapshot()['manual_order_lock'])

    def test_normal_replay_batches_need_no_manual_unlock(self):
        fixture = replay_fixtures.ReplayTests()
        with patch.object(replay_fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for cursor in (1, 2):
            fixture.replay.start()
            fixture.replay.step(max_bars=1)
            fixture.replay.stop()
            self.assertEqual(fixture.replay.snapshot()['cursor'], cursor)
            snapshot = fixture.broker.snapshot()
            self.assertTrue(snapshot['kill_switch'])
            self.assertFalse(snapshot.get('manual_order_lock', False))
            self.assertEqual(stop_presentation(snapshot, 'replay'), stop_presentation({'kill_switch': True}, 'replay'))
            self.assertNotEqual(stop_presentation(snapshot, 'replay', manual_lock_text=ui_text('paper.manual_locked'))[0], ui_text('paper.manual_locked'))
        self.assertFalse(any(e['operation'] == 'manual_order_lock' for e in fixture.broker.journal_events()))


if __name__ == '__main__':
    unittest.main()
