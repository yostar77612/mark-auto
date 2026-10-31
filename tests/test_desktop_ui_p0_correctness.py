"""P0 presentation regressions; synthetic local data and offline sessions only."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services

import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from quantlab.desktop_errors import ERROR_TABLE, error_message, exception_code, startup_error_code
from quantlab.desktop_runtime import AppPaths, JobManager, SettingsStore, RuntimeSafetyError, RedactedEventLog
from quantlab.research_core.adapters.workspace_backup import BackupManager


class CorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Ordinary inherited permissions also work in restricted Windows test runners.
        self.root = Path(tempfile.gettempdir()) / ('markauto-t2-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def window(self):
        from desktop_app.shell.window import MainWindow

        paths = AppPaths(self.root).ensure()
        jobs = JobManager(paths)
        window = MainWindow(
            paths, jobs, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, jobs), services=_c_create_ui_services(_c_create_operation_ports())
        )
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        self.addCleanup(jobs.close)
        return window

    def test_reconciled_account_card_three_refreshes_are_read_only(self):
        from quantlab.research_core.application.paper_operations import _paper
        from quantlab.paper import PaperBroker

        w = self.window()
        policy = {'contract_id': 'TAIFEX:TMF:202610', 'risk_sessions': [], 'margin_schedule': []}
        (w.root / 'paper_policy.json').write_text(json.dumps(policy), encoding='utf8')
        broker = _paper(_c_create_operation_ports(), w.root)
        broker.reconcile({'account_id': 'synthetic', 'cash': '100000', 'positions': {}, 'orders': {}, 'fills': {}})
        before = broker.journal_events()
        with patch.object(w.paper_card, 'set_values', wraps=w.paper_card.set_values) as card:
            for _ in range(3):
                w.load_market_cache()
                self.assertIs(card.call_args.args[0]['reconciliation_required'], False)
                self.assertEqual(broker.journal_events(), before)
        self.assertEqual(sum(x['operation'] == 'restart' for x in broker.journal_events()), 0)
        self.assertFalse(PaperBroker.read_snapshot(broker.path)['reconciliation_required'])
        restarted = _paper(_c_create_operation_ports(), w.root)
        self.assertTrue(restarted.snapshot()['reconciliation_required'])
        self.assertEqual(sum(x['operation'] == 'restart' for x in restarted.journal_events()), 1)

    def test_read_snapshot_missing_or_corrupt_fails_closed_without_create(self):
        from quantlab.paper import PaperBroker, JournalConflict
        from quantlab.core import Instrument
        from quantlab.reporting import demo_config
        from quantlab.research_core.application.paper_operations import paper_risk_limits

        missing = self.root / 'missing.sqlite'
        with self.assertRaises(sqlite3.Error):
            PaperBroker.read_snapshot(missing)
        self.assertFalse(missing.exists())
        broker = PaperBroker(self.root / 'corrupt.sqlite', instrument=Instrument('TAIFEX:TMF:202610'), costs=demo_config().costs, limits=paper_risk_limits())
        with closing(sqlite3.connect(broker.path)) as db:
            with db:
                db.execute("UPDATE materialized SET state='{}' WHERE id=1")
        before = broker.path.read_bytes()
        with self.assertRaises(JournalConflict):
            PaperBroker.read_snapshot(broker.path)
        self.assertEqual(broker.path.read_bytes(), before)

    def test_unknown_exceptions_never_stringified_or_displayed(self):
        class SecretError(Exception):
            def __str__(self):
                raise AssertionError('must not stringify')

        w = self.window()

        def fail():
            raise SecretError('C:/private/token-secret')

        w._safe(fail)
        self.assertEqual(w.status.text(), error_message('operation_failed'))
        self.assertEqual(exception_code(ValueError('C:/private/token-secret')), 'validation_failed')
        from desktop_app.features.assistant.connection import ConnectionController, ChatGPTConnectionPanel

        panel = ChatGPTConnectionPanel(ConnectionController())
        self.addCleanup(panel.deleteLater)
        panel._safe(fail)
        from desktop_app.features.assistant.states import outcome_message

        self.assertEqual(panel.status.text(), outcome_message('operation_failed'))
        for text in (w.status.text(), panel.status.text(), error_message('C:/private/token-secret')):
            self.assertNotIn('private', text)
            self.assertNotIn('secret', text)
        self.assertTrue(all(row.explanation and row.action for row in ERROR_TABLE.values()))

    def test_startup_causes_are_distinct_fixed_chinese(self):
        cases = {
            'This workspace requires a WAL-safe SQLite runtime (3.51.3 or newer)': 'startup_sqlite_old',
            'Unsupported workspace version; original preserved': 'startup_workspace_incompatible',
        }
        for raw, code in cases.items():
            self.assertEqual(startup_error_code(RuntimeSafetyError(raw)), code)
            self.assertIn('請', error_message(code))
        self.assertEqual(startup_error_code(RuntimeSafetyError('C:/private/secret')), 'startup_failed')
        self.assertIn('另一個程序', error_message('startup_workspace_busy'))
        source = Path('desktop.py').read_text(encoding='utf8')
        self.assertIn("error_message('startup_workspace_busy')", source)
        self.assertIn('error_message(startup_error_code(exc))', source)

    def test_restore_and_cleanup_failures_record_fixed_stage_and_restore_signin(self):
        from quantlab.assistant.application.connection_contracts import ConnectionRequest, LOCAL_ACTIONS, STARTUP_ACTIONS
        from desktop_app.features.assistant.connection import ConnectionController, ChatGPTConnectionPanel
        from quantlab.assistant.adapters.chatgpt.connection_worker import run_connection_request
        from tests.test_desktop_chatgpt_ui import FixtureSession, REF

        self.assertNotIn('restore', LOCAL_ACTIONS)
        self.assertIn('restore', STARTUP_ACTIONS)
        session = FixtureSession()
        session.state = 'refresh_required'
        session.active_registration = REF
        session.rows = [{'registration': REF, 'state': 'refresh_required'}]

        def fail(*args, **kwargs):
            raise RuntimeError('C:/private/Bearer-secret')

        session.refresh = fail
        controller = ConnectionController()
        panel = ChatGPTConnectionPanel(controller)
        self.addCleanup(panel.deleteLater)
        controller.set_host_available(True)
        request = panel.start_auto_restore()
        result = run_connection_request(request, bootstrap=self.root, emit=lambda x: None, cancelled=lambda: False, session_factory=lambda: session)
        self.assertEqual(result.error_code, 'restore_refresh_failed')
        controller.apply_event(result)
        controller.worker_joined(request.request_id, joined=True)
        self.assertFalse(panel.primary_sign_in.isHidden())
        self.assertTrue(panel.primary_sign_in.isEnabled())
        from desktop_app.features.assistant.states import outcome_message

        self.assertEqual(controller.outcome, 'auth_expired')
        self.assertEqual(controller.message, outcome_message('restore_refresh_failed'))
        self.assertNotIn('restore_refresh_failed', controller.message)
        w = self.window()
        w._record_connection_error(result.error_code)
        session.state = 'authorizing'
        session.begin = fail
        session.cancel = fail
        emitted = []
        run_connection_request(
            ConnectionRequest(2, 'begin', user_confirmed=True),
            bootstrap=self.root,
            emit=emitted.append,
            cancelled=lambda: False,
            session_factory=lambda: session,
        )
        self.assertEqual(emitted[-1].error_code, 'authorization_cleanup_failed')
        w._record_connection_error(emitted[-1].error_code)
        records = RedactedEventLog(w.paths.logs / 'desktop-events.jsonl').tail()
        self.assertEqual([json.loads(x)['error_code'] for x in records], ['restore_refresh_failed', 'authorization_cleanup_failed'])
        self.assertNotIn('secret', ''.join(records))
        with self.assertRaises(RuntimeSafetyError):
            RedactedEventLog(self.root / 'invalid.jsonl').append('ui_chatgpt_auth', 'error', error_code='secret')


if __name__ == '__main__':
    unittest.main()
