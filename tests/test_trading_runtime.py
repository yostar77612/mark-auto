"""Real independent engine-process IPC, with no mocked server or transport."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import unittest
from uuid import uuid4

from quantlab.trading.application.codec import MAX_BYTES, dumps, loads
from quantlab.trading.application.contracts import SettingsForm, UiAction, UiCommand
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.ipc import IpcFacade, read_session
from quantlab.trading.runtime.protocol import Operation, Request, Response
import trading_runtime


WORKSPACE = Path(__file__).resolve().parents[2]


class IndependentEngineRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (WORKSPACE / 't').mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='v2-runtime-', dir=WORKSPACE / 't')
        cls.root = Path(cls.temp.name) / 'isolated'
        cls.facade = trading_runtime.ensure_engine(cls.root)
        cls.session = read_session(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        process = trading_runtime._STARTED.get(cls.root.resolve())
        try:
            if process is not None and process.poll() is None:
                trading_runtime.shutdown(cls.root)
            elif process is not None:
                process.wait(timeout=5)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            cls.temp.cleanup()

    def envelope(self, operation: Operation = Operation.SNAPSHOT, **values: object) -> Request:
        return Request(uuid4().hex, Environment.LOCAL, 'local-stock', datetime.now(timezone.utc) + timedelta(seconds=5), operation, **values)

    def exchange(self, payload: bytes) -> Response | None:
        session = read_session(self.root)
        with Client(session.address, family=session.family, authkey=session.key) as connection:
            try:
                connection.send_bytes(payload)
                self.assertTrue(connection.poll(5), 'engine failed to respond within the protocol deadline')
                value = loads(connection.recv_bytes(MAX_BYTES).decode('utf-8'))
            except (OSError, EOFError):
                return None
        self.assertIsInstance(value, Response)
        return value

    def healthy(self) -> None:
        self.assertEqual(read_session(self.root).process_id, self.session.process_id)
        self.assertEqual(self.facade.request(Operation.METRICS).metrics.process_id, self.session.process_id)

    def test_engine_is_independent_native_local_process_and_second_client_reuses_it(self) -> None:
        self.assertNotEqual(self.session.process_id, os.getpid())
        self.assertEqual(self.session.family, 'AF_PIPE' if os.name == 'nt' else 'AF_UNIX')
        second = trading_runtime.ensure_engine(self.root)
        independent_client = IpcFacade(self.root)
        self.assertEqual(second.snapshot().version, self.facade.snapshot().version)
        self.assertEqual(independent_client.snapshot().version, self.facade.snapshot().version)
        self.assertEqual(read_session(self.root).process_id, self.session.process_id)

    def test_wrong_hmac_key_is_rejected_without_crashing_engine(self) -> None:
        with self.assertRaises(AuthenticationError):
            Client(self.session.address, family=self.session.family, authkey=b'x' * 32)
        self.healthy()

    def test_malformed_utf8_json_duplicate_fields_and_unknown_schema_are_rejected(self) -> None:
        for payload in (b'\xff\xfe', b'{', b'{"x":1,"x":2}', b'{"@":"untrusted.runtime.Class","fields":{}}'):
            with self.subTest(payload=payload):
                response = self.exchange(payload)
                self.assertIsNotNone(response)
                self.assertIn(response.code, ('validation_failed', 'operation_failed'))
                self.healthy()

    def test_unknown_wire_fields_and_protocol_schema_cannot_be_ignored(self) -> None:
        body = json.loads(dumps(self.envelope()))
        for field, value in (('schema_version', 99), ('unrecognized', 'not-allowed')):
            body = json.loads(dumps(self.envelope()))
            body['fields'][field] = value
            response = self.exchange(json.dumps(body).encode())
            self.assertIsNotNone(response)
            self.assertEqual(response.code, 'validation_failed')
        self.healthy()

    def test_expired_deadline_future_deadline_and_foreign_account_rejected(self) -> None:
        body = json.loads(dumps(self.envelope()))
        changes = (
            ('deadline', {'@': 'datetime', 'value': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}, 'state_conflict'),
            ('deadline', {'@': 'datetime', 'value': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}, 'state_conflict'),
            ('account_ref', 'unavailable-account', 'capability_missing'),
            ('environment', {'@': 'quantlab.trading.domain.models.Environment', 'value': 'LIVE'}, 'capability_missing'),
        )
        for field, value, code in changes:
            with self.subTest(field=field, code=code):
                changed = json.loads(json.dumps(body))
                changed['fields'][field] = value
                response = self.exchange(json.dumps(changed).encode())
                self.assertIsNotNone(response)
                self.assertEqual(response.code, code)
        self.healthy()

    def test_state_version_conflict_does_not_execute_command(self) -> None:
        state = self.facade.snapshot()
        receipt = self.facade.execute(UiCommand(UiAction.STOP_NEW, state.version - 1))
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.code, 'state_conflict')
        self.assertEqual(self.facade.snapshot().version, state.version)

    def test_float_or_nonfinite_money_cannot_cross_wire_boundary(self) -> None:
        state = self.facade.snapshot()
        command = UiCommand(UiAction.SAVE_SETTINGS, state.version, settings=SettingsForm(Decimal('60000'), Decimal('40000'), Decimal('0.02')))
        for invalid in (60000.0, 'NaN', 'Infinity'):
            body = json.loads(dumps(self.envelope(Operation.COMMAND, command=command)))
            body['fields']['command']['fields']['settings']['fields']['stock_allocation'] = {'@': 'decimal', 'value': invalid}
            response = self.exchange(json.dumps(body).encode())
            self.assertIsNotNone(response)
            self.assertEqual(response.code, 'validation_failed')
            self.assertEqual(self.facade.snapshot().version, state.version)

    def test_oversize_message_is_closed_or_rejected_and_engine_stays_alive(self) -> None:
        response = self.exchange(b'x' * (MAX_BYTES + 1))
        if response is not None:
            self.assertTrue(response.code)
        self.healthy()

    def test_second_engine_process_cannot_steal_active_owner(self) -> None:
        command = [sys.executable, str(Path(trading_runtime.__file__).with_name('desktop.py')), '--trading-engine', str(self.root)]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        self.assertNotEqual(result.returncode, 0)
        self.healthy()

    def test_ui_client_process_can_close_without_shutting_down_engine(self) -> None:
        program = 'from pathlib import Path; from quantlab.trading.runtime.ipc import IpcFacade; import sys; IpcFacade(Path(sys.argv[1])).snapshot()'
        result = subprocess.run(
            [sys.executable, '-c', program, str(self.root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace'))
        self.healthy()

    def test_shutdown_separate_engine_releases_all_owned_handles(self) -> None:
        root = Path(self.temp.name) / 'shutdown-case'
        trading_runtime.ensure_engine(root)
        process = trading_runtime._STARTED[root.resolve()]
        trading_runtime.shutdown(root)
        self.assertEqual(process.poll(), 0)
        self.assertFalse((root / 'engine-session-v2.json').exists())
        # Actual rename validates that the owned SQLite and log handles closed.
        for path in root.glob('*.sqlite'):
            moved = path.with_suffix('.closed')
            path.rename(moved)
            moved.rename(path)

    def test_deep_engine_root_uses_private_native_transport_and_cleans_it(self) -> None:
        root = Path(self.temp.name) / ('deep-engine-' + 'x' * 110)
        self.assertGreater(len(os.fsencode(root.resolve())), 150)
        facade = trading_runtime.ensure_engine(root)
        session = read_session(root)
        private_directory = None
        try:
            self.assertEqual(facade.snapshot().environment, Environment.LOCAL)
            if os.name == 'nt':
                self.assertTrue(session.address.startswith('\\\\.\\pipe\\markauto-v2-'))
            else:
                private_directory = Path(session.address).parent
                self.assertLessEqual(len(os.fsencode(session.address)), 100)
                self.assertNotEqual(private_directory, root.resolve())
                self.assertEqual(stat.S_IMODE(private_directory.lstat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(Path(session.address).lstat().st_mode), 0o600)
                self.assertEqual(private_directory.lstat().st_uid, os.geteuid())
                foreign = Path(self.temp.name) / 'foreign-engine'
                foreign.mkdir()
                (foreign / 'engine-session-v2.json').write_bytes((root / 'engine-session-v2.json').read_bytes())
                with self.assertRaises(DomainError):
                    read_session(foreign)
                private_directory.chmod(0o755)
                try:
                    with self.assertRaises(DomainError):
                        read_session(root)
                finally:
                    private_directory.chmod(0o700)
                self.assertEqual(facade.snapshot().environment, Environment.LOCAL)
        finally:
            trading_runtime.shutdown(root)
        self.assertFalse((root / 'engine-session-v2.json').exists())
        if private_directory is not None:
            self.assertFalse(private_directory.exists(), 'owned private Unix endpoint must not remain after shutdown')


if __name__ == '__main__':
    unittest.main()
