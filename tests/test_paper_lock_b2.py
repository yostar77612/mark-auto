"""Cheap offline B2 risk, persistence and order-entry regression evidence."""

import ast
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import desktop_ui
from desktop_strings import ui_text
from quantlab.core import canonical_json, content_hash
from quantlab.desktop_feedback import stop_presentation
from quantlab.paper import LiveBroker, LiveTradingDisabled, PaperBroker, ReconciliationError, ValidationError
from tests import test_paper as fixtures
from tests import test_paper_replay as replay_fixtures
from tests import test_ui_operations_registry as registry_fixtures


ROOT = Path(__file__).resolve().parents[1]
NOW = fixtures.NOW
CID = fixtures.CID


class ScratchDirectory:
    """Inherited ACLs keep SQLite fixtures usable in Windows sandbox runners."""

    def __init__(self):
        self.name = str(Path(tempfile.gettempdir()) / ('paper-b2-' + uuid4().hex))
        Path(self.name).mkdir(mode=0o777)

    def cleanup(self):
        shutil.rmtree(self.name)


class LockTests(unittest.TestCase):
    def setUp(self):
        with patch.object(fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixtures.PaperTests.setUp(self)

    intent = fixtures.PaperTests.intent
    quote = fixtures.PaperTests.quote
    submit = fixtures.PaperTests.submit
    event = fixtures.PaperTests.event

    # Run the original daily-loss assertions unchanged against this fixture.
    test_existing_daily_loss = fixtures.PaperTests.test_daily_loss_and_marked_margin
    test_existing_overnight_no_baseline = fixtures.PaperTests.test_overnight_profit_cannot_hide_new_day_loss
    test_existing_opening_reference = fixtures.PaperTests.test_versioned_opening_reference_measures_new_day_loss

    def assert_no_intents_since(self, count):
        self.assertFalse(any(e['operation'] == 'intent' for e in self.broker.journal_events()[count:]))

    def test_lock_survives_restart_reconcile_and_kill_off_until_explicit_unlock(self):
        self.submit('working')
        self.broker.apply_event(self.event('working'))
        self.submit('pending')
        before = self.broker.snapshot()
        self.broker.set_manual_order_lock(True)
        locked = self.broker.snapshot()
        for key in ('orders', 'positions', 'fills', 'cash', 'lots'):
            self.assertEqual(locked[key], before[key])
        # Broker connections close at every transaction boundary; discard the
        # entire broker object, then open a fresh execution session on the DB.
        del self.broker
        self.broker = PaperBroker(self.path, **self.kw)
        self.assertEqual(self.submit('restart-blocked')['reason'], 'manual_order_lock')
        with self.assertRaises(ReconciliationError):
            self.broker.set_manual_order_lock(False)
        self.broker.reconcile(self.broker.snapshot())
        self.broker.set_kill_switch(True)
        self.broker.set_kill_switch(False)
        count = len(self.broker.journal_events())
        self.assertEqual(self.submit('still-blocked')['reason'], 'manual_order_lock')
        self.assert_no_intents_since(count)
        self.broker.set_manual_order_lock(False)
        self.assertEqual(self.submit('unlocked')['status'], 'accepted')
        events = [e['payload'] for e in self.broker.journal_events() if e['operation'] == 'manual_order_lock']
        self.assertEqual(events, [{'active': True}, {'active': False}])
        self.assertFalse(PaperBroker.read_snapshot(self.path)['manual_order_lock'])

    def test_unknown_order_requires_explicit_reconciliation_before_unlock(self):
        self.submit()
        self.broker.apply_event(self.event(typ='unknown'))
        self.broker.set_manual_order_lock(True)
        with self.assertRaises(ReconciliationError):
            self.broker.set_manual_order_lock(False)
        state = self.broker.snapshot()
        with self.assertRaises(ReconciliationError):
            self.broker.reconcile(state)
        state['order_statuses'] = {'a': 'accepted'}
        self.broker.reconcile(state)
        self.assertTrue(self.broker.snapshot()['manual_order_lock'])
        self.broker.set_manual_order_lock(False)
        for invalid in (None, 0, 1, 'false'):
            with self.assertRaises(ValidationError):
                self.broker.set_manual_order_lock(invalid)

    def test_pre_lock_journal_restores_identically_without_snapshot_field(self):
        self.submit()
        self.broker.apply_event(self.event())
        old = self.broker.snapshot()
        self.assertNotIn('manual_order_lock', old)
        self.assertEqual(PaperBroker.read_snapshot(self.path), old)
        events = deepcopy(self.broker.journal_events())
        self.broker = PaperBroker(self.path, **self.kw)
        restored = self.broker.snapshot()
        self.assertEqual(restored, dict(old, reconciliation_required=True))
        self.assertEqual(self.broker.journal_events()[:-1], events)
        self.broker.reconcile(restored)
        self.assertEqual(self.submit('legacy-unlocked')['status'], 'accepted')

    def test_order_quantity_boundary_and_aggregate_pending_position(self):
        self.assertEqual(self.submit('cap', quantity=3)['status'], 'accepted')
        self.assertEqual(self.submit('over', quantity=4)['reason'], 'max_order_quantity')
        self.assertEqual(self.submit('pending', quantity=2)['status'], 'accepted')
        self.assertEqual(self.submit('aggregate', quantity=1)['reason'], 'max_position')
        self.assertEqual(self.broker.snapshot()['positions'], {})

    def test_decimal_daily_loss_realized_unrealized_and_combined(self):
        for label, cash_loss, mark_loss, allowed in (
            ('realized-limit-minus-one', D('499'), D('0'), True),
            ('realized-limit', D('500'), D('0'), False),
            ('unrealized-limit', D('0'), D('500'), False),
            ('combined', D('250'), D('250'), False),
        ):
            with self.subTest(label=label):
                # Separate journals use actual accepted/fill events. Commission
                # isolates exact Decimal realized loss without fractional ticks.
                broker = PaperBroker(Path(self.tmp.name) / (label + '.sqlite'), **self.kw)
                broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
                broker.submit(self.intent('entry'), quote=self.quote(), now=NOW)
                broker.apply_event(self.event('entry', commission=cash_loss if mark_loss else D('0'), tax=D('0')))
                if not mark_loss:
                    broker.submit(self.intent('exit', side='sell'), quote=self.quote(), now=NOW)
                    broker.apply_event(self.event('exit', commission=cash_loss, tax=D('0')))
                quote = self.quote(price=D('20000') - mark_loss / D('10'))
                result = broker.submit(self.intent('probe'), quote=quote, now=NOW)
                self.assertEqual(result['status'], 'accepted' if allowed else 'rejected')
                if not allowed:
                    self.assertEqual(result['reason'], 'max_daily_loss')
                state = broker.snapshot()
                self.assertEqual(D(state['cash']), D('100000') - cash_loss)
                self.assertEqual(D(state['daily_equity_baselines']['2026-10-09']['equity']), D('100000'))

    def test_new_trade_date_uses_fresh_flat_baseline(self):
        later = NOW + timedelta(days=1)
        session = dict(self.kw['risk_sessions'][0], open=later - timedelta(minutes=15), end=later + timedelta(hours=4), trade_date='2026-10-10')
        self.broker = PaperBroker(Path(self.tmp.name) / 'days.sqlite', **dict(self.kw, risk_sessions=self.kw['risk_sessions'] + (session,)))
        self.broker.reconcile(dict(account_id='synthetic', cash='100000', positions={}, orders={}, fills={}))
        self.submit('entry')
        self.broker.apply_event(self.event('entry', commission=D('499'), tax=D('0')))
        self.submit('exit', side='sell')
        self.broker.apply_event(self.event('exit', commission=D('1'), tax=D('0')))
        self.assertEqual(self.submit('today')['reason'], 'max_daily_loss')
        quote = self.quote(timestamp=later, **self.broker.quote_policy(later))
        result = self.broker.submit(self.intent('tomorrow', created_at=later), quote=quote, now=later)
        self.assertEqual(result['status'], 'accepted')
        baselines = self.broker.snapshot()['daily_equity_baselines']
        self.assertEqual(D(baselines['2026-10-09']['equity']), D('100000'))
        self.assertEqual(D(baselines['2026-10-10']['equity']), D('99500'))

    def test_ui_submit_and_explicit_lock_unlock_payloads(self):
        root = Path(self.tmp.name)
        common = patch.object(desktop_ui, '_prepare_paper_operation', return_value=self.broker)
        with common, patch.object(desktop_ui, '_finish_paper_operation', side_effect=lambda root, broker, replay: broker.snapshot()):
            desktop_ui._handle_ui_paper_kill({'manual_order_lock': True}, None, root)
            count = len(self.broker.journal_events())
            payload = dict(reconcile_confirmed=True, snapshot=self.broker.snapshot(), intent=self.intent('ui'), quote=self.quote(), now=NOW.isoformat())
            with patch.object(desktop_ui, 'load_selection', return_value={'strategy_hash': 'synthetic-strategy'}):
                account = desktop_ui._handle_ui_paper_submit(payload, None, root)
            self.assertEqual(account['orders']['ui']['reason'], 'manual_order_lock')
            self.assert_no_intents_since(count)
            account = desktop_ui._handle_ui_paper_reconcile({'snapshot': account}, None, root)
            self.assertTrue(account['manual_order_lock'])
            account = desktop_ui._handle_ui_paper_reconcile({'snapshot': account, 'manual_order_lock': False}, None, root)
            self.assertFalse(account['manual_order_lock'])

    def test_stop_text_and_live_disabled(self):
        self.assertEqual(stop_presentation({'manual_order_lock': True}), ('manual_order_lock', '#f1b65c'))
        self.assertEqual(
            stop_presentation({'manual_order_lock': True}, manual_lock_text=ui_text('paper.manual_locked')), (ui_text('paper.manual_locked'), '#f1b65c')
        )
        with self.assertRaises(LiveTradingDisabled):
            LiveBroker()


class ReplayLockTests(unittest.TestCase):
    def test_strategy_replay_start_stop_and_new_session_preserve_lock(self):
        fixture = replay_fixtures.ReplayTests()
        with patch.object(replay_fixtures.tempfile, 'TemporaryDirectory', ScratchDirectory):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.broker.set_manual_order_lock(True)
        fixture.broker = fixture.new_broker()
        fixture.broker.reconcile(fixture.broker.snapshot())
        replay = fixture.new_replay()
        # Reset/rebuild strategy targets and replay session never unlocks broker.
        replay.targets = {0: 1}
        replay.start()
        count = len(fixture.broker.journal_events())
        replay.step(max_bars=1)
        state = fixture.broker.snapshot()
        self.assertEqual(next(iter(state['orders'].values()))['reason'], 'manual_order_lock')
        self.assertFalse(state['positions'])
        self.assertFalse(state['fills'])
        self.assertFalse(any(e['operation'] == 'intent' for e in fixture.broker.journal_events()[count:]))
        replay.stop()
        replay.start()
        self.assertTrue(fixture.broker.snapshot()['manual_order_lock'])


class OrderEntryScanTests(unittest.TestCase):
    def test_existing_public_name_oracle_unchanged(self):
        registry_fixtures.RegistryTests('test_public_names_unchanged').test_public_names_unchanged()

    def test_class_limits_and_ui_lock_catalog_wiring(self):
        ui = ast.parse((ROOT / 'desktop_ui.py').read_text(encoding='utf-8-sig'))
        window = next(n for n in ui.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
        self.assertLessEqual(window.end_lineno - window.lineno + 1, 400)
        for path in (ROOT / 'desktop_pages').glob('*.py'):
            for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
                if isinstance(node, ast.ClassDef) and node.name.endswith('Page'):
                    self.assertLessEqual(node.end_lineno - node.lineno + 1, 500)
        page = ast.parse((ROOT / 'desktop_pages/paper.py').read_text(encoding='utf-8-sig'))
        presentation = ast.parse((ROOT / 'desktop_pages/paper_layout.py').read_text(encoding='utf-8-sig'))
        calls = [n for tree in (page, presentation) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == 'ui_text' and n.args[0].value == 'paper.manual_locked' for n in calls))
        lock_jobs = [
            n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == 'paper_job' and any(k.arg == 'manual_order_lock' for k in n.keywords)
        ]
        self.assertEqual(
            {(n.args[0].value, next(k.value.value for k in n.keywords if k.arg == 'manual_order_lock')) for n in lock_jobs},
            {('kill', True), ('reconcile', False)},
        )
        # Confirm/Observe persist the same explicit lock outside the job route.
        kill = next(n for n in ast.walk(page) if isinstance(n, ast.FunctionDef) and n.name == 'kill_paper')
        writes = [n for n in ast.walk(kill) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'set_manual_order_lock']
        self.assertEqual([n.args[0].value for n in writes], [True, True])

    def test_all_submit_callers_and_intent_writers_are_enumerated(self):
        paths = (
            sorted((ROOT / 'quantlab').rglob('*.py'))
            + sorted(ROOT.glob('desktop*.py'))
            + sorted((ROOT / 'desktop_pages').rglob('*.py'))
            + sorted((ROOT / 'desktop_trading').rglob('*.py'))
            + [ROOT / 'trading_runtime.py']
        )
        submits, v2_submits, writers, commits = set(), set(), set(), set()
        submit_function = None
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(function):
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                        continue
                    if call.func.attr == 'submit':
                        target = v2_submits if relative.startswith('quantlab/trading/') else submits
                        target.add((relative, function.name, ast.unparse(call.func.value)))
                    if call.func.attr == 'commit' and (call.args or call.keywords):
                        commits.add((relative, function.name, ast.unparse(call.func.value)))
                    if call.func.attr in ('_append', 'execute', 'executemany') and any(
                        isinstance(arg, ast.Constant) and isinstance(arg.value, str) and (arg.value == 'intent' or 'INSERT INTO journal' in arg.value)
                        for arg in call.args
                    ):
                        writers.add((relative, function.name))
                if relative == 'quantlab/paper.py' and function.name == 'submit' and function.args.kwonlyargs:
                    submit_function = function
        self.assertEqual(submits, {('quantlab/paper_replay.py', '_step', 'self.broker'), ('desktop_ui.py', '_handle_ui_paper_submit', 'broker')})
        # Owner-authorized v2 has an independently exhaustive execution contract;
        # it does not alter the original two callers or v1 intent writer oracle.
        self.assertEqual(
            v2_submits,
            {
                ('quantlab/trading/application/coordinator.py', '_entry_decision', 'engine'),
                ('quantlab/trading/application/engine.py', 'exit_lot', 'self'),
                ('quantlab/trading/application/execution.py', 'commit', 'self.broker'),
                ('quantlab/trading/application/lifecycle.py', '_progress_close', 'engine'),
                ('quantlab/trading/application/lifecycle.py', '_progress_open', 'engine'),
            },
        )
        self.assertEqual(commits, {('quantlab/trading/application/engine.py', 'submit', 'execution')})
        self.assertEqual(writers, {('quantlab/paper.py', 'submit'), ('quantlab/paper.py', '_append')})
        calls = [n for n in ast.walk(submit_function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        risks = [n for n in calls if n.func.attr == '_risk']
        self.assertEqual(len(risks), 1)
        intent_write = next(n for n in calls if n.func.attr == '_append' and any(isinstance(a, ast.Constant) and a.value == 'intent' for a in n.args))
        self.assertLess(risks[0].lineno, intent_write.lineno)
        guard = next(n for n in ast.walk(submit_function) if isinstance(n, ast.If) and ast.unparse(n.test) == 'not decision.allowed')
        self.assertTrue(any(isinstance(n, ast.Return) for n in guard.body))
        self.assertLess(guard.end_lineno, intent_write.lineno)

    def test_v2_unique_commit_requires_locked_risk_reservation_durable_intent_and_fence(self):
        engine = ast.parse((ROOT / 'quantlab/trading/application/engine.py').read_text(encoding='utf-8-sig'))
        submit = next(n for n in ast.walk(engine) if isinstance(n, ast.FunctionDef) and n.name == 'submit')
        locked = next(n for n in ast.walk(submit) if isinstance(n, ast.With) and ast.unparse(n.items[0].context_expr) == 'self.lock')
        calls = [n for n in ast.walk(locked) if isinstance(n, ast.Call)]
        preview = [n for n in calls if ast.unparse(n.func) == 'risk.preview']
        commit = [n for n in calls if ast.unparse(n.func) == 'execution.commit']
        self.assertEqual(len(preview), 1)
        self.assertEqual(len(commit), 1)
        guard = next(
            n for n in ast.walk(locked) if isinstance(n, ast.If) and ast.unparse(n.test) == 'not decision.allowed or decision.quantity != plan.quantity'
        )
        self.assertTrue(any(isinstance(n, ast.Raise) for n in guard.body))
        reservation = next(n for n in calls if ast.unparse(n.func) == 'Reservation')
        construction = next(n for n in calls if ast.unparse(n.func) == 'ExecutionService')
        self.assertLess(preview[0].lineno, guard.lineno)
        self.assertLess(guard.end_lineno, reservation.lineno)
        self.assertLess(reservation.lineno, construction.lineno)
        self.assertLess(construction.lineno, commit[0].lineno)
        self.assertEqual([ast.unparse(n) for n in construction.args[:4]], ['gateway', 'self._persist', 'self.fence', 'self.clock.now'])
        self.assertEqual(ast.unparse(commit[0].args[5]), 'lambda: self.fence()')
        execution = ast.parse((ROOT / 'quantlab/trading/application/execution.py').read_text(encoding='utf-8-sig'))
        execute = next(n for n in ast.walk(execution) if isinstance(n, ast.FunctionDef) and n.name == 'commit')
        calls = [n for n in ast.walk(execute) if isinstance(n, ast.Call)]
        validate = next(n for n in calls if ast.unparse(n.func) == 'validate')
        durable = next(
            n for n in calls if ast.unparse(n.func) == 'self.persist' and isinstance(n.args[0], ast.Constant) and n.args[0].value == 'order_submitting'
        )
        fence = next(n for n in calls if ast.unparse(n.func) == 'self.fence')
        broker = next(n for n in calls if ast.unparse(n.func) == 'self.broker.submit')
        self.assertLess(validate.lineno, durable.lineno)
        self.assertLess(durable.lineno, fence.lineno)
        self.assertLess(fence.lineno, broker.lineno)

    def test_v2_runtime_risk_and_ownership_reject_before_any_adapter_submission(self):
        from tests.test_trading_application import ApplicationLifecycleTests

        for name in (
            'test_second_writer_and_expired_owner_are_fenced_before_broker_call',
            'test_commit_revalues_existing_loss_before_accepting_new_entry',
        ):
            with self.subTest(case=name):
                fixture = ApplicationLifecycleTests(name)
                fixture.setUp()
                try:
                    getattr(fixture, name)()
                    self.assertEqual(fixture.engine.gateways['local-stock'].submission_count, 0)
                    expected = 0 if 'second_writer' in name else 2
                    self.assertEqual(sum(g.submission_count for g in fixture.engine.gateways.values()), expected)
                    if expected:
                        # The loss quote legitimately submitted the existing
                        # future's protective exit; the prohibited stock entry
                        # is still absent. Protection must not be suppressed.
                        self.assertEqual([o.plan.reduce_only for o in fixture.engine.state.orders], [False, True])
                        self.assertTrue(all(o.plan.account_ref == 'local-futures' for o in fixture.engine.state.orders))
                finally:
                    fixture.tearDown()
                    fixture.doCleanups()

    def test_v2_catalogue_composes_without_mutating_legacy_or_shadowing_codes(self):
        from quantlab.errors import ERROR_LABELS, ERROR_TABLE, ErrorCode
        from quantlab.trading.application.errors import ERROR_TABLE as V2_TABLE, V2_ERROR_TEXT

        self.assertFalse(V2_ERROR_TEXT.keys() & ERROR_TABLE.keys())
        self.assertEqual(set(V2_TABLE), set(ERROR_TABLE) | set(V2_ERROR_TEXT))
        self.assertEqual(set(ERROR_LABELS), set(ERROR_TABLE))
        self.assertEqual({v.value for v in ErrorCode}, set(ERROR_TABLE))
        self.assertNotIn('daily_baseline_required', ERROR_TABLE)
        self.assertIn('daily_baseline_required', V2_TABLE)
        self.assertTrue(all(V2_TABLE[code] is row for code, row in ERROR_TABLE.items()))
        with self.assertRaises(TypeError):
            V2_TABLE['new_code'] = V2_TABLE['operation_failed']

    def test_legacy_initial_state_checksum_is_pinned(self):
        # This hash pins the pre-B2 schema: adding a default lock field here
        # would invalidate every persisted old journal's checksums.
        from quantlab.paper import _initial  # Pure reducer schema fixture.

        state = _initial()
        self.assertNotIn('manual_order_lock', state)
        self.assertEqual(content_hash(state), '79e78d0d4683c94dfd6cfbc2e5a14a8bd71f3529d8e573ff67f54c3dcb7ebfb1')
        self.assertNotIn('manual_order_lock', canonical_json(state))
