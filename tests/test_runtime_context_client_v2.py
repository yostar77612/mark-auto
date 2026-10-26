"""Qt -> authenticated IPC -> real core with synthetic fault ports only.

These cases exercise the standard configuration/client path. They do not log
in to an SDK, resolve credentials, submit orders or establish broker readiness.
"""

from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from desktop_strings import ui_text
from desktop_trading import TradingWindow
from desktop_trading.wizard import StrategyWizard
from quantlab.trading.application.contextnavigation import CompositeFacade
from quantlab.trading.application.contracts import UiAction, UiCommand, UiReceipt
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.config import RuntimeLaunch, load_profile
from quantlab.trading.runtime.context_client import ContextIpcFacade, RuntimeContextManager, _STARTED, ensure_engine
from quantlab.trading.runtime.ipc import read_session
from test_trading_runtime_context import profile_fixture, serve_fixture


WORKSPACE = Path(__file__).resolve().parents[1]


def close_owned_test_context(client):
    """Only an explicit rejected CAS permits a fresh cleanup request.

    These are this fixture's synthetic hosts, not user engines. Unknown results
    and every other refusal retain the failure; no force-stop is acceptance.
    """
    for _ in range(3):
        state = client.snapshot()
        if state.engine_state == 'CLOSED':
            return
        result = client.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, state.version))
        if result.accepted:
            return
        if result.code != 'state_conflict':
            break
    raise DomainError(result.code)


class OwnedContextCleanupTests(unittest.TestCase):
    def test_explicit_version_refusal_requires_fresh_snapshot_before_new_request(self):
        client = Mock()
        client.snapshot.side_effect = [SimpleNamespace(engine_state='STOPPED', version=4), SimpleNamespace(engine_state='STOPPED', version=5)]
        client.execute.side_effect = [UiReceipt(False, 'state_conflict', ''), UiReceipt(True, 'completed', '')]
        close_owned_test_context(client)
        self.assertEqual(
            client.method_calls,
            [
                unittest.mock.call.snapshot(),
                unittest.mock.call.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, 4)),
                unittest.mock.call.snapshot(),
                unittest.mock.call.execute(UiCommand(UiAction.SHUTDOWN_ENGINE, 5)),
            ],
        )

    def test_unknown_or_other_refusal_is_not_replayed(self):
        for failure in ('outcome_unknown', 'journal_failed', 'capability_missing'):
            with self.subTest(failure=failure):
                client = Mock()
                client.snapshot.return_value = SimpleNamespace(engine_state='STOPPED', version=4)
                client.execute.return_value = UiReceipt(False, failure, '')
                with self.assertRaises(DomainError) as raised:
                    close_owned_test_context(client)
                self.assertEqual(raised.exception.code, failure)
                client.execute.assert_called_once()
        client = Mock()
        client.snapshot.return_value = SimpleNamespace(engine_state='STOPPED', version=4)
        client.execute.side_effect = EOFError('unknown transport outcome')
        with self.assertRaises(EOFError):
            close_owned_test_context(client)
        client.execute.assert_called_once()

    def test_repeated_conflict_remains_failure_with_bounded_requests(self):
        client = Mock()
        client.snapshot.return_value = SimpleNamespace(engine_state='STOPPED', version=4)
        client.execute.return_value = UiReceipt(False, 'state_conflict', '')
        with self.assertRaises(DomainError) as raised:
            close_owned_test_context(client)
        self.assertEqual(raised.exception.code, 'state_conflict')
        self.assertEqual(client.execute.call_count, 3)


class RuntimeContextRegistryTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='context-registry-', dir=WORKSPACE / 't')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_profile_registration_and_saved_selection_are_metadata_only(self):
        profile = profile_fixture(self.root / 'bundle', Environment.BROKER_SIMULATION)
        with patch('quantlab.trading.runtime.broker.ShioajiClientFactory.create', side_effect=AssertionError('no implicit SDK')):
            manager = RuntimeContextManager(self.root / 'base')
            added = manager.register_profile(str(profile), Environment.BROKER_SIMULATION)
            self.assertEqual(manager.selected_context, 'local')
            self.assertFalse((manager.base_root / 'context-engines' / added.context_id).exists())
            manager.persist_selection(added.context_id, 'test-stock')
            restored = RuntimeContextManager(manager.base_root)
            self.assertEqual((restored.selected_context, restored.selected_account), (added.context_id, 'test-stock'))
            self.assertEqual(restored.list_contexts(), manager.list_contexts())

    def test_changed_registry_cannot_be_overwritten_by_stale_navigation(self):
        manager = RuntimeContextManager(self.root / 'base')
        manager.persist_selection('local', 'local-stock')
        stale = RuntimeContextManager(manager.base_root)
        manager.persist_selection('local', 'local-futures')
        with self.assertRaises(DomainError) as raised:
            stale.persist_selection('local', 'local-stock')
        self.assertEqual(raised.exception.code, 'state_conflict')
        self.assertEqual(RuntimeContextManager(manager.base_root).selected_account, 'local-futures')

    def test_invalid_selected_profile_stays_explicitly_unavailable_without_local_fallback(self):
        profile = profile_fixture(self.root / 'bundle', Environment.LIVE)
        manager = RuntimeContextManager(self.root / 'base')
        option = manager.register_profile(str(profile), Environment.LIVE)
        manager.persist_selection(option.context_id, 'test-stock')
        profile.unlink()
        restored = RuntimeContextManager(manager.base_root)
        self.assertEqual(restored.selected_context, option.context_id)
        selected = next(item for item in restored.list_contexts() if item.context_id == option.context_id)
        self.assertEqual(selected.status, 'UNAVAILABLE')
        with patch('quantlab.trading.runtime.context_client.ensure_engine', side_effect=AssertionError('must not launch a fallback')):
            with self.assertRaises(DomainError):
                restored.open_context(option.context_id, 'test-stock')
        self.assertEqual(restored.selected_context, option.context_id)

    def test_changed_profile_cannot_relabel_a_running_context_or_overwrite_registry(self):
        profile = profile_fixture(self.root / 'bundle', Environment.BROKER_SIMULATION)
        manager = RuntimeContextManager(self.root / 'base')
        manager.register_profile(str(profile), Environment.BROKER_SIMULATION)
        before = manager.registry_path.read_bytes()
        options = manager.list_contexts()
        profile.write_bytes(profile.read_bytes() + b' ')
        with (
            patch('quantlab.trading.runtime.context_client.read_session', return_value=SimpleNamespace(process_id=1234)),
            patch('quantlab.trading.runtime.context_client._alive', return_value=True),
            self.assertRaises(DomainError) as raised,
        ):
            manager.register_profile(str(profile), Environment.BROKER_SIMULATION)
        self.assertEqual(raised.exception.code, 'startup_workspace_busy')
        self.assertEqual(manager.registry_path.read_bytes(), before)
        self.assertEqual(manager.list_contexts(), options)


class RuntimeContextClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        (WORKSPACE / 't').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='context-client-', dir=WORKSPACE / 't')
        self.root = Path(self.temp.name).resolve()
        self.processes = []
        self.launches = []
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.drain()
            self.window.setProperty('allow_close_for_tests', True)
            self.window.close()
            self.window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(self.window))
            self.app.processEvents()
        cleanup_errors = []
        for launch in reversed(self.launches):
            try:
                client = ContextIpcFacade(launch)
                close_owned_test_context(client)
            except DomainError as exc:
                cleanup_errors.append(exc.code)
            except (OSError, EOFError):
                pass  # A test may deliberately have closed its owned host.
        for process in self.processes:
            process.join(10)
            if process.is_alive():
                process.terminate()  # Only this test's explicitly created PID.
                process.join(5)
                cleanup_errors.append('owned synthetic host required forced cleanup')
        for launch in self.launches:
            process = _STARTED.pop(launch.root, None)
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()  # Only the Popen created by this case.
                    process.wait(timeout=5)
                    cleanup_errors.append('owned local host required forced cleanup')
        self.temp.cleanup()
        self.assertEqual(cleanup_errors, [])

    def drain(self):
        # Starting a new owned host has the existing 15s startup deadline;
        # ordinary UI operations retain the production IPC 10s deadline.
        deadline = time.monotonic() + 16
        while (self.window._operation is not None or self.window._priority_operation is not None) and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertIsNone(self.window._operation, self.window.notice.text())
        self.assertIsNone(self.window._priority_operation, self.window.notice.text())
        self.app.processEvents()

    def start_synthetic_host(self, environment, *, failure=False):
        folder = self.root / environment.value.lower()
        profile = profile_fixture(folder / 'bundle', environment)
        launch = RuntimeLaunch(folder / 'engine', environment, profile, 'test-stock')
        process = multiprocessing.get_context('spawn').Process(target=serve_fixture, args=(launch.root, environment, profile, failure))
        process.start()
        self.processes.append(process)
        self.launches.append(launch)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.exitcode is not None:
                self.fail(f'owned synthetic IPC host exited {process.exitcode}')
            try:
                if read_session(launch.root).process_id == process.pid:
                    ContextIpcFacade(launch, load_profile(profile).source_sha256).snapshot()
                    return launch
            except (OSError, EOFError):
                pass
            time.sleep(0.02)
        self.fail('owned synthetic IPC host did not publish a usable session')

    def manager_with(self, *launches):
        local = RuntimeLaunch(self.root / 'local')
        self.launches.append(local)
        path = self.root / 'contexts.json'
        entries = [('local', '', local)] + [(launch.environment.value.lower(), launch.environment.value, launch) for launch in launches]
        path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'selected_context': 'local',
                    'selected_account': 'local-stock',
                    'contexts': [
                        {
                            'context_id': key,
                            'label': label,
                            'root': str(launch.root),
                            'environment': launch.environment.value,
                            'account_ref': launch.account_ref,
                            'profile_path': str(launch.profile_path) if launch.profile_path else None,
                        }
                        for key, label, launch in entries
                    ],
                }
            ),
            encoding='utf-8',
        )
        return RuntimeContextManager(local.root, path)

    def show_manager(self, manager):
        current = manager.open_context(manager.selected_context, manager.selected_account)
        client = CompositeFacade(manager, manager.selected_context, current)
        self.window = TradingWindow(client, client.snapshot())
        self.window.poll.stop()
        self.window.show()
        self.app.processEvents()
        return client

    def choose_environment(self, environment):
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.environment.setCurrentIndex(self.window.environment.findData(environment))
        self.drain()

    def create_draft_in_visible_wizard(self, name, *, one_day=False):
        errors = []

        def accept_active():
            wizard = self.app.activeModalWidget()
            try:
                self.assertIsInstance(wizard, StrategyWizard)
                self.assertIs(wizard.parentWidget(), self.window)
                wizard.name.setText(name)
                if one_day:
                    wizard.policy.setCurrentIndex(4)
                    wizard.minimum.setValue(1)
                    wizard.maximum.setValue(1)
                wizard.accept()
                self.assertEqual(wizard.result(), StrategyWizard.DialogCode.Accepted)
            except BaseException as exc:
                errors.append(exc)
                if isinstance(wizard, StrategyWizard):
                    wizard.reject()

        def open_modal():
            QTimer.singleShot(0, accept_active)
            try:
                self.window.new_strategy()
            except BaseException as exc:
                errors.append(exc)
            finally:
                self.app.exit(0)

        QTimer.singleShot(0, open_modal)
        self.app.exec()
        if errors:
            raise errors[0]
        self.drain()
        self.assertIn(name, [item.name for item in self.window.state.strategies], self.window.notice.text())

    def wait_for_connected_core(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.window.refresh()
            self.drain()
            if self.window.state.engine_state != 'CONNECTING':
                break
            QTest.qWait(10)
        self.assertNotIn(self.window.state.engine_state, ('CONNECTING', 'DISCONNECTED'), self.window.notice.text())
        self.assertTrue(self.window.state.markets, 'actual injected core must supply the read model')

    def test_three_environments_use_real_ipc_and_never_mix_books_or_implicitly_connect(self):
        broker = self.start_synthetic_host(Environment.BROKER_SIMULATION)
        live = self.start_synthetic_host(Environment.LIVE)
        manager = self.manager_with(broker, live)
        client = self.show_manager(manager)
        self.create_draft_in_visible_wizard('LOCAL_ONLY_DRAFT')
        local_version = self.window.state.version
        self.choose_environment(Environment.BROKER_SIMULATION)
        self.assertEqual(self.window.state.environment, Environment.BROKER_SIMULATION)
        self.assertEqual(self.window.state.account_ref, 'test-stock')
        self.assertEqual(self.window.state.strategies, ())
        self.assertEqual(self.window.state.engine_state, 'DISCONNECTED')
        self.assertFalse((broker.root / 'fault-port.jsonl').exists(), 'opening a mode must not connect even its fake factory')
        self.assertIsNone(self.window.state.daily_pnl)
        self.assertFalse(self.window.state.financial_facts_verified)
        self.assertIn(ui_text('v2.context_facts_pending'), self.window.overview_status.text())
        self.assertIn('尚未核對', self.window.summary.text())
        with patch.object(self.window, '_confirm', return_value=True):
            self.window.connect_read_only_button.click()
        self.drain()
        self.assertNotEqual(self.window.notice.text(), ui_text('v2.completed'))
        self.wait_for_connected_core()
        self.create_draft_in_visible_wizard('BROKER_LABELLED_SYNTHETIC_DRAFT', one_day=True)
        self.assertEqual(self.window.state.strategies[0].environment, Environment.BROKER_SIMULATION)
        self.choose_environment(Environment.LIVE)
        self.assertEqual(self.window.state.strategies, ())
        self.assertFalse((live.root / 'fault-port.jsonl').exists())
        self.assertFalse(self.window.state.financial_facts_verified)
        self.choose_environment(Environment.LOCAL)
        self.assertEqual([s.name for s in self.window.state.strategies], ['LOCAL_ONLY_DRAFT'])
        self.assertGreaterEqual(self.window.state.version, local_version)
        restored = RuntimeContextManager(manager.base_root, manager.registry_path)
        self.assertEqual((restored.selected_context, restored.selected_account), ('local', 'local-stock'))
        self.assertEqual(client.snapshot().environment, Environment.LOCAL)
        trace = (broker.root / 'fault-port.jsonl').read_text(encoding='utf-8')
        self.assertIn('events_fault', trace)
        self.assertNotIn('FORBIDDEN_SUBMIT', trace)
        self.assertNotIn('FORBIDDEN_CANCEL', trace)

    def test_owned_cleanup_handles_real_ipc_version_change_without_bypassing_cas(self):
        manager = self.manager_with()
        client = manager.open_context('local', 'local-stock')
        original_execute = client.execute
        receipts = []

        def advance_once(command):
            if not receipts:
                stopped = original_execute(UiCommand(UiAction.STOP_NEW, command.expected_version))
                self.assertTrue(stopped.accepted)
            receipt = original_execute(command)
            receipts.append(receipt)
            return receipt

        with patch.object(client, 'execute', side_effect=advance_once):
            close_owned_test_context(client)
        self.assertEqual([(r.accepted, r.code) for r in receipts], [(False, 'state_conflict'), (True, 'completed')])

    def test_wrong_running_identity_is_not_relaunched_or_silently_local(self):
        launch = self.start_synthetic_host(Environment.BROKER_SIMULATION)
        session = read_session(launch.root)
        wrong = replace(launch, environment=Environment.LIVE)
        with patch('quantlab.trading.runtime.context_client.subprocess.Popen', side_effect=AssertionError('must retain running host')):
            with self.assertRaises(DomainError):
                ensure_engine(launch.root, launch=wrong, configuration_id=load_profile(launch.profile_path).source_sha256)
        self.assertEqual(read_session(launch.root).process_id, session.process_id)
        self.assertEqual(ContextIpcFacade(launch).snapshot().environment, Environment.BROKER_SIMULATION)

    def test_standard_disconnected_launch_without_profile_keeps_financial_facts_unknown(self):
        manager = self.manager_with()
        context_id = manager.configure_launch(Environment.LIVE, 'explicit-pending-account', None)
        pending = RuntimeLaunch(manager.base_root / 'context-engines' / context_id, Environment.LIVE, account_ref='explicit-pending-account')
        self.launches.append(pending)
        self.show_manager(manager)
        self.choose_environment(Environment.LIVE)
        state = self.window.state
        self.assertEqual((state.context_id, state.account_ref, state.environment), (context_id, pending.account_ref, Environment.LIVE))
        self.assertEqual(state.engine_state, 'DISCONNECTED')
        self.assertEqual(state.accounts, ())
        self.assertIsNone(state.daily_pnl)
        self.assertIsNone(state.remaining_risk)
        self.assertFalse(state.financial_facts_verified)
        self.assertEqual(state.configuration_id, 'UNCONFIGURED:LIVE:explicit-pending-account')
        self.assertEqual(state.quote_status, 'NO_DATA')
        self.assertIn('空表不代表沒有持倉', self.window.overview_status.text())
        self.window.command(UiAction.CHECK_READINESS)
        self.drain()
        self.assertIsNotNone(self.window.state.broker_readiness)
        self.assertFalse(self.window.state.broker_readiness.external_verified)
        self.assertEqual(self.window.state.positions, ())
        self.assertFalse((pending.root / 'engine-v2.sqlite').exists(), 'metadata readiness must not fabricate a trading engine')

    def test_failed_profile_target_retains_current_data_and_selector(self):
        launch = self.start_synthetic_host(Environment.BROKER_SIMULATION)
        manager = self.manager_with(launch)
        self.show_manager(manager)
        self.create_draft_in_visible_wizard('RETAINED_LOCAL_DRAFT')
        before = self.window.state
        # A changed pinned profile is a configuration mismatch, not permission
        # to replace the existing engine or erase the selected local book.
        launch.profile_path.write_bytes(launch.profile_path.read_bytes() + b' ')
        newer = RuntimeContextManager(manager.base_root, manager.registry_path)
        self.window.facade = CompositeFacade(newer, 'local', newer.open_context('local', 'local-stock'))
        self.window.apply_state(self.window.facade.snapshot())
        self.choose_environment(Environment.BROKER_SIMULATION)
        self.assertEqual(self.window.state.context_id, 'local')
        self.assertEqual(self.window.state.strategies, before.strategies)
        self.assertEqual(self.window.environment.currentData(), Environment.LOCAL)
        self.assertEqual(tuple(self.window.account.currentData()), ('local', 'local-stock'))
        self.assertIn(ui_text('v2.local'), self.window.notice.text())
        self.assertEqual(newer.selected_context, 'local')


if __name__ == '__main__':
    unittest.main()
