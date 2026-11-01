"""Real-process regressions for disposable engine fixture lifetime."""

from pathlib import Path
import json
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quantlab.trading.application.contracts import UiAction
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime import context_client
from quantlab.trading.runtime.context_client import _STARTED, ensure_engine, shutdown
from quantlab.trading.runtime.ipc import read_session
import test_trading_runtime as fixtures
from tools.owned_trading_engine import OwnedEngineProcesses


WORKSPACE = Path(__file__).resolve().parents[2]


class FixtureCleanupRegressionTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='owned-engine-cleanup-', dir=WORKSPACE / 't')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def assert_closed(self, owned):
        self.assertTrue(owned.owned)
        self.assertEqual([row['shutdown'] for row in owned.closed], ['NORMAL'] * len(owned.owned))
        for process, launch in owned.owned:
            self.assertEqual(process.poll(), 0)
            self.assertNotIn(launch.root, _STARTED)
            self.assertFalse((launch.root / 'engine-session-v2.json').exists())

    def test_setup_failure_releases_class_owned_engine(self):
        class FailsAfterStartup(fixtures.IndependentEngineRuntimeTests):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                cls.retained_process = _STARTED[cls.root.resolve()]
                raise RuntimeError('injected failure after actual engine readiness')

            def test_probe(self):
                self.fail('class setup must fail first')

        result = unittest.TestResult()
        try:
            unittest.TestSuite([FailsAfterStartup('test_probe')]).run(result)
            self.assertEqual(len(result.errors), 1)
            self.assertIn('injected failure after actual engine readiness', result.errors[0][1])
            self.assertEqual(FailsAfterStartup.retained_process.poll(), 0, 'failed setUpClass must not leave its engine running')
            self.assertNotIn(FailsAfterStartup.root.resolve(), _STARTED)
            self.assertFalse((FailsAfterStartup.root / 'engine-session-v2.json').exists())
        finally:
            # Red-phase containment only: a broken fixture still must not leak.
            process = getattr(FailsAfterStartup, 'retained_process', None)
            if process is not None and process.poll() is None:
                shutdown(Path(FailsAfterStartup.root))
            FailsAfterStartup.temp.cleanup()

    def test_success_closes_own_engine_but_retains_reused_host_and_files(self):
        with OwnedEngineProcesses() as foreign:
            other = ensure_engine(self.root / 'other')
            foreign_process = foreign.owned[0][0]
            sentinel = self.root / 'other' / 'keep-user-like-file.txt'
            sentinel.write_text('never delete or rewrite', encoding='utf-8')
            with OwnedEngineProcesses() as owned:
                self.assertEqual(ensure_engine(self.root / 'other').snapshot().environment, Environment.LOCAL)
                own = ensure_engine(self.root / 'own')
                process = owned.owned[0][0]
                self.assertEqual(read_session(self.root / 'own').process_id, process.pid)
                self.assertEqual(own.snapshot().environment, Environment.LOCAL)
            self.assert_closed(owned)
            self.assertIsNone(foreign_process.poll(), 'reused host belongs to the outer owner')
            self.assertEqual(other.snapshot().environment, Environment.LOCAL)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'never delete or rewrite')
        self.assert_closed(foreign)
        self.assertTrue(sentinel.exists(), 'engine cleanup never deletes fixture data')

    def test_body_failure_and_exception_normally_close_actual_engine(self):
        for failure in (AssertionError, RuntimeError):
            with self.subTest(failure=failure.__name__):
                with self.assertRaisesRegex(failure, 'injected body failure'):
                    with OwnedEngineProcesses() as owned:
                        ensure_engine(self.root / failure.__name__)
                        raise failure('injected body failure')
                self.assert_closed(owned)

    def test_startup_deadline_before_endpoint_publication_still_normally_closes_owned_engine(self):
        # Only the caller's clock is controlled. The real child still starts,
        # publishes its real authenticated endpoint and must exit normally.
        caller_clock = SimpleNamespace(monotonic=Mock(side_effect=(0, 16)))
        with self.assertRaisesRegex(DomainError, 'runtime startup deadline'):
            with OwnedEngineProcesses() as owned:
                with patch.object(context_client, 'time', caller_clock):
                    ensure_engine(self.root / 'deadline')
        self.assert_closed(owned)

    def test_test_setup_and_teardown_exceptions_do_not_bypass_registered_cleanup(self):
        import test_runtime_context_client_v2 as client_fixtures

        for phase in ('setup', 'teardown'):

            class BrokenFixture(client_fixtures.RuntimeContextClientTests):
                def setUp(self):
                    super().setUp()
                    self.manager_with().open_context('local', 'local-stock')
                    type(self).retained_root = self.root / 'local'
                    type(self).retained_process = _STARTED[type(self).retained_root]
                    if phase == 'setup':
                        raise RuntimeError('injected setup failure')

                def tearDown(self):
                    raise RuntimeError('injected teardown failure')

                def test_probe(self):
                    pass

            with self.subTest(phase=phase):
                result = unittest.TestResult()
                unittest.TestSuite([BrokenFixture('test_probe')]).run(result)
                self.assertEqual(len(result.errors), 1)
                self.assertIn('injected ' + phase + ' failure', result.errors[0][1])
                self.assertEqual(BrokenFixture.retained_process.poll(), 0)
                self.assertNotIn(BrokenFixture.retained_root, _STARTED)
                self.assertFalse((BrokenFixture.retained_root / 'engine-session-v2.json').exists())

    def test_load_probe_partial_initialization_uses_normal_shutdown(self):
        from tools import trading_load_probe

        root, report = self.root / 'load-failure', self.root / 'report.json'
        retained = []

        def fail_after_real_start(folder):
            ensure_engine(folder)
            retained.append(_STARTED[folder])
            raise RuntimeError('injected before facade is returned')

        with (
            patch('sys.argv', ['trading_load_probe', '--root', str(root), '--report', str(report), '--seconds', '1']),
            patch.object(trading_load_probe, 'os', SimpleNamespace(name='nt', environ={'QT_QPA_PLATFORM': ''})),
            patch.object(trading_load_probe.trading_runtime, 'ensure_engine', side_effect=fail_after_real_start),
            self.assertRaisesRegex(RuntimeError, 'injected before facade'),
        ):
            # LOCAL only, before Qt or preparation; source/IPC/engine are real.
            trading_load_probe.main()
        self.assertEqual(retained[0].poll(), 0)
        self.assertFalse((root / 'engine-session-v2.json').exists())
        saved = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'FAIL')
        self.assertFalse(saved['acceptance_30_minutes'])
        self.assertTrue(saved['shutdown_verified'])

    def test_synthetic_setup_and_another_cleanup_failure_still_close_owned_host(self):
        import test_trading_runtime_context as host_fixtures

        class BrokenHostFixture(host_fixtures.OwnedBrokerTagHostTests):
            def setUp(self):
                super().setUp()
                profile = host_fixtures.profile_fixture(self.root / 'bundle', Environment.BROKER_SIMULATION)
                process, _ = self.start(self.root / 'engine', Environment.BROKER_SIMULATION, profile)
                type(self).retained_process = process
                type(self).retained_root = self.root / 'engine'
                self.addCleanup(Mock(side_effect=RuntimeError('injected unrelated cleanup failure')))
                raise RuntimeError('injected synthetic host setup failure')

            def test_probe(self):
                self.fail('setup must fail first')

        result = unittest.TestResult()
        unittest.TestSuite([BrokenHostFixture('test_probe')]).run(result)
        self.assertEqual(len(result.errors), 2)
        self.assertTrue(BrokenHostFixture.retained_process._closed, 'Process.close refuses a live child')
        self.assertFalse((BrokenHostFixture.retained_root / 'engine-session-v2.json').exists())
        self.assertIn('injected synthetic host setup failure', result.errors[0][1])
        self.assertIn('injected unrelated cleanup failure', result.errors[1][1])


class OwnedEngineBoundaryTests(unittest.TestCase):
    def test_endpoint_removal_after_normal_shutdown_joins_retained_process(self):
        for phase in ('snapshot', 'execute'):
            with self.subTest(phase=phase):
                process = Mock(pid=123)
                process.poll.return_value = None
                process.wait.return_value = 0
                launch = RuntimeLaunch(Path.cwd() / 'normal-close-race')
                owner = OwnedEngineProcesses()
                owner.owned = [(process, launch)]
                facade = Mock()
                facade.snapshot.return_value = SimpleNamespace(engine_state='READY', version=1)

                def endpoint_removed(*_):
                    process.poll.return_value = 0
                    raise FileNotFoundError('endpoint removed by an earlier normal shutdown')

                getattr(facade, phase).side_effect = endpoint_removed
                with (
                    patch('tools.owned_trading_engine.read_session', return_value=SimpleNamespace(process_id=123)),
                    patch.object(context_client, 'ContextIpcFacade', return_value=facade),
                ):
                    owner.close()
                process.wait.assert_called_once_with(timeout=15)
                process.terminate.assert_not_called()
                self.assertEqual(owner.closed[0]['shutdown'], 'ALREADY_EXITED')
                self.assertEqual(owner.closed[0]['exit_code'], 0)
                if phase == 'snapshot':
                    facade.execute.assert_not_called()
                else:
                    self.assertEqual(facade.execute.call_args.args[0].action, UiAction.SHUTDOWN_ENGINE)

    def test_missing_endpoint_cannot_certify_live_or_abnormal_owned_exit(self):
        for failure in ('still-live', 'abnormal-exit'):
            with self.subTest(failure=failure):
                process = Mock(pid=123)
                process.poll.return_value = None if failure == 'still-live' else 1
                # The first retained-PID check occurs before the endpoint disappears.
                process.poll.side_effect = [None, process.poll.return_value, process.poll.return_value]
                process.wait.side_effect = [subprocess.TimeoutExpired('owned-fixture', 15), 0] if failure == 'still-live' else [1, 1]
                owner = OwnedEngineProcesses()
                owner.owned = [(process, RuntimeLaunch(Path.cwd() / failure))]
                facade = Mock()
                facade.snapshot.side_effect = FileNotFoundError('endpoint unavailable')
                with (
                    patch('tools.owned_trading_engine.read_session', return_value=SimpleNamespace(process_id=123)),
                    patch.object(context_client, 'ContextIpcFacade', return_value=facade),
                    self.assertRaisesRegex(RuntimeError, 'owned engine cleanup failed'),
                ):
                    owner.close()
                self.assertEqual(owner.closed[0]['shutdown'], 'FAILED')
                facade.execute.assert_not_called()
                if failure == 'still-live':
                    process.terminate.assert_called_once_with()

    def test_mismatched_session_never_receives_a_shutdown_command(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        owner = OwnedEngineProcesses()
        with (
            patch('tools.owned_trading_engine.read_session', return_value=SimpleNamespace(process_id=456)),
            patch.object(context_client, 'ContextIpcFacade') as facade,
            self.assertRaisesRegex(DomainError, 'different session owner'),
        ):
            owner._shutdown(process, RuntimeLaunch(Path.cwd()))
        facade.assert_not_called()
        process.terminate.assert_not_called()

    def test_cleanup_error_still_attempts_every_retained_child_and_remains_failure(self):
        first, second = Mock(pid=1), Mock(pid=2)
        first.poll.return_value = second.poll.return_value = 0
        owner = OwnedEngineProcesses()
        owner.owned = [(first, RuntimeLaunch(Path.cwd() / 'first')), (second, RuntimeLaunch(Path.cwd() / 'second'))]
        with patch.object(owner, '_shutdown', side_effect=[DomainError('outcome_unknown'), 'NORMAL']) as close:
            with self.assertRaisesRegex(RuntimeError, 'owned engine cleanup failed'):
                owner.close()
        self.assertEqual(close.call_count, 2)
        self.assertEqual([row['shutdown'] for row in owner.closed], ['FAILED', 'NORMAL'])
        first.terminate.assert_not_called()
        second.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
