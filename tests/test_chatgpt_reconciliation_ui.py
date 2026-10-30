"""Offline, explicit local reconciliation; no account, vault or network fixtures."""

from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports

from dataclasses import asdict, replace
from contextlib import ExitStack
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import shiboken6

import desktop_app.features.assistant.connection as ui
from quantlab.research_core.application.ui_operations.assistant import connection_event_from_payload
from quantlab.desktop_runtime import JobManager, RuntimeSafetyError

REF = 'a' * 32
OTHER = 'b' * 32
BOOTSTRAP = Path(__file__).resolve().parents[1] / 'fixture-bootstrap'


def inspection_event(request, inspection=('k1_resolvable', 1, 1, True), **kwargs):
    return ui.ReconciliationEvent(
        request.request_id,
        'result',
        reconciliation_action=request.action,
        reconciliation_registration=request.registration,
        inspection=inspection,
        **kwargs,
    )


class ReconciliationPayloadTests(unittest.TestCase):
    def prepare(self, payload):
        return JobManager.__new__(JobManager)._prepare_other_job('ui_chatgpt_auth', {'request': payload})

    def test_existing_and_new_request_shapes_round_trip_with_optional_version(self):
        requests = [
            ui.ConnectionRequest(1, 'list'),
            ui.ConnectionRequest(2, 'restore'),
            ui.ConnectionRequest(3, 'first_sign_in', user_confirmed=True),
            ui.ConnectionRequest(4, 'models', REF, user_confirmed=True),
            ui.ConnectionRequest(5, 'test', REF, user_confirmed=True, model='gpt-fixture'),
            ui.ConnectionRequest(6, 'inspect_unknown', REF),
            ui.ConnectionRequest(7, 'resolve_unknown', REF, user_confirmed=True, acknowledgement_version=1),
        ]
        for request in requests:
            with self.subTest(action=request.action):
                payload = json.loads(json.dumps(request.payload()))
                self.assertEqual(ui.ConnectionRequest(**payload), request)
                self.assertEqual(self.prepare(payload)[1:], (request.request_id, False))
                self.assertIn('model', payload)
                self.assertEqual(payload['acknowledgement_version'], 1 if request.action == 'resolve_unknown' else None)
        legacy = requests[0].payload()
        del legacy['model']
        del legacy['acknowledgement_version']
        self.assertEqual(self.prepare(legacy)[1], 1)

    def test_resolution_confirmation_and_registration_types_fail_closed_at_both_boundaries(self):
        base = ui.ConnectionRequest(1, 'resolve_unknown', REF, user_confirmed=True, acknowledgement_version=1).payload()
        changes = [
            *({'acknowledgement_version': value} for value in (None, False, True, 0, 2, 1.0, '1')),
            *({'user_confirmed': value} for value in (False, 1, 'true', None)),
            *({'registration': value} for value in (None, '', '../private', 'a' * 31, 1)),
            {'extra': 'untrusted'},
        ]
        for change in changes:
            payload = {**base, **change}
            with self.subTest(change=change):
                with self.assertRaises((TypeError, ValueError)):
                    ui.ConnectionRequest(**payload)
                with self.assertRaises(RuntimeSafetyError):
                    self.prepare(payload)
        for action in ('list', 'inspect_unknown'):
            payload = ui.ConnectionRequest(2, action, REF if action == 'inspect_unknown' else None).payload()
            with self.assertRaises(ValueError):
                ui.ConnectionRequest(**{**payload, 'acknowledgement_version': 1})
            with self.assertRaises(RuntimeSafetyError):
                self.prepare({**payload, 'acknowledgement_version': 1})
        for action in ('inspect_unknown', 'resolve_unknown'):
            with self.assertRaises(ValueError):
                ui.ConnectionRequest(
                    1, action, REF, user_confirmed=True, model='gpt-fixture', acknowledgement_version=1 if action == 'resolve_unknown' else None
                )

    def test_typed_events_round_trip_without_auth_or_private_detail_projection(self):
        request = ui.ConnectionRequest(1, 'inspect_unknown', REF)
        events = [
            inspection_event(request),
            *(inspection_event(request, (kind, None, None, False)) for kind in ('k1_other_registration', 'k2_unresolvable', 'none')),
            ui.ReconciliationEvent(
                2, 'result', reconciliation_action='resolve_unknown', reconciliation_registration=REF, account_status=('user_confirmed_consumed', False)
            ),
            ui.ReconciliationEvent(
                3, 'error', reconciliation_action='inspect_unknown', reconciliation_registration=REF, error_code='unknown_request_too_recent'
            ),
        ]
        for event in events:
            with self.subTest(event=event):
                decoded = connection_event_from_payload(_c_create_operation_ports(), json.loads(json.dumps(asdict(event))))
                self.assertIs(type(decoded), ui.ReconciliationEvent)
                self.assertEqual(decoded, event)
                self.assertEqual((decoded.state, decoded.registrations, decoded.models, decoded.authorization_url), ('unknown', (), (), None))
        valid = events[0]
        for changes in (
            {'inspection': ('k1_resolvable', True, 1, True)},
            {'inspection': ('k1_resolvable', 1, 2, True)},
            {'inspection': ('k1_resolvable', 1, 1, 1)},
            {'inspection': ('k1_resolvable', 101, 101, True)},
            {'inspection': ('k2_unresolvable', 1, 1, False)},
            {'inspection': ('private detail', None, None, False)},
            {'inspection': None},
            {'account_status': ('user_confirmed_consumed', False)},
            {'models': ('gpt-fixture',)},
            {'state': 'plan_ready'},
            {'registrations': ((REF, 'plan_ready'),)},
            {'kind': 'progress'},
            {'error_code': 'unknown_request_too_recent'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)
        for status in (('invented', False), ('user_confirmed_consumed', 0), ['user_confirmed_consumed', False]):
            with self.subTest(status=status), self.assertRaises(ValueError):
                replace(events[-2], account_status=status)

    def test_worker_inspection_and_resolution_never_construct_auth_or_vault(self):
        with ExitStack() as stack:
            forbidden = [
                stack.enter_context(patch(target, side_effect=AssertionError('unexpected external operation')))
                for target in (
                    'quantlab.assistant.adapters.chatgpt.auth.AuthSession',
                    'quantlab.assistant.adapters.chatgpt.auth.DPAPIVault',
                    'socket.socket',
                    'socket.create_connection',
                )
            ]
            inspect = stack.enter_context(
                patch(
                    'quantlab.assistant.adapters.chatgpt.provider.inspect_unknown_request',
                    return_value={
                        'kind': 'k1_resolvable',
                        'sequence': 2,
                        'calls': 2,
                        'max_age_ok': True,
                    },
                )
            )
            resolve = stack.enter_context(patch('quantlab.assistant.adapters.chatgpt.provider.resolve_unknown_request'))
            status = stack.enter_context(
                patch(
                    'quantlab.assistant.adapters.chatgpt.provider.read_account_status',
                    return_value={
                        'state': 'user_confirmed_consumed',
                        'pending': False,
                    },
                )
            )
            factory = Mock(side_effect=AssertionError('auth factory must not run'))
            emit = Mock()
            request = ui.ConnectionRequest(1, 'inspect_unknown', REF)
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=emit, cancelled=lambda: False, session_factory=factory)
            self.assertEqual(result.inspection, ('k1_resolvable', 2, 2, True))
            reference, controls = inspect.call_args.args
            self.assertEqual(reference.registration, REF)
            self.assertEqual(controls, BOOTSTRAP / 'control-v1')
            resolve.assert_not_called()
            status.assert_not_called()
            request = ui.ConnectionRequest(2, 'resolve_unknown', REF, user_confirmed=True, acknowledgement_version=1)
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=emit, cancelled=lambda: False, session_factory=factory)
            self.assertEqual(result.account_status, ('user_confirmed_consumed', False))
            self.assertEqual(resolve.call_args.kwargs, {'user_confirmed': True, 'acknowledgement_version': 1})
            self.assertEqual(resolve.call_args.args[1], controls)
            emit.assert_not_called()
            factory.assert_not_called()
            for guard in forbidden:
                guard.assert_not_called()

    def test_worker_cancel_and_private_errors_remain_bounded_and_local(self):
        request = ui.ConnectionRequest(1, 'inspect_unknown', REF)
        with patch('quantlab.assistant.adapters.chatgpt.provider.inspect_unknown_request') as inspect:
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: True)
            self.assertEqual(result.kind, 'error')
            inspect.assert_not_called()
        private = 'secret token user@example.invalid C:/private/account.sqlite'
        with patch('quantlab.assistant.adapters.chatgpt.provider.inspect_unknown_request', side_effect=ValueError(private)):
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
        self.assertEqual(result.kind, 'error')
        self.assertNotIn(private, json.dumps(asdict(result)))
        self.assertIn(result.error_code, ui.ERROR_LABELS)

    def test_successful_resolution_is_not_misreported_when_followup_status_fails_or_changes(self):
        request = ui.ConnectionRequest(1, 'resolve_unknown', REF, user_confirmed=True, acknowledgement_version=1)
        for observed in (None, ('quota_paused', False), ('reserved_unknown', True), ('ready', False)):
            kwargs = {'side_effect': OSError('private path')} if observed is None else {'return_value': {'state': observed[0], 'pending': observed[1]}}
            with (
                self.subTest(observed=observed),
                patch('quantlab.assistant.adapters.chatgpt.provider.resolve_unknown_request') as resolve,
                patch('quantlab.assistant.adapters.chatgpt.provider.read_account_status', **kwargs),
            ):
                result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
                resolve.assert_called_once()
                self.assertEqual(result.kind, 'result')
                self.assertEqual(result.account_status, observed)
                self.assertEqual(result.error_code, '')


class ReconciliationWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = ui.ConnectionController()
        self.panel = ui.ChatGPTConnectionPanel(self.controller)
        self.requests, self.quiesce, self.cancel = [], [], []
        self.controller.request_ready.connect(self.requests.append)
        self.controller.quiesce_requested.connect(self.quiesce.append)
        self.controller.cancel_requested.connect(self.cancel.append)
        self.panel.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_panel)

    def cleanup_panel(self):
        self.panel.reconciliation.abandon()
        self.panel.hide()
        shiboken6.delete(self.panel)
        self.app.processEvents()

    def pending(self):
        c = self.controller
        c.set_host_available(True)
        request = c.request('list')
        c.apply_event(
            ui.ConnectionEvent(request.request_id, 'result', 'plan_ready', ((REF, 'plan_ready'), (OTHER, 'plan_ready')), REF, models=('gpt-fixture',))
        )
        c.worker_joined(request.request_id, joined=True)
        c.set_usage(REF, [{'sequence': 1, 'status': 'reserved_unknown'}], account_status={'state': 'reserved_unknown', 'pending': True})
        self.requests.clear()
        return c

    def start(self):
        self.panel.buttons['inspect_unknown'].click()
        self.assertEqual(len(self.requests), 1)
        return self.requests[-1]

    def complete_inspection(self, inspection=('k1_resolvable', 1, 1, True)):
        request = self.start()
        self.controller.apply_event(inspection_event(request, inspection))
        self.controller.worker_joined(request.request_id, joined=True)
        self.app.processEvents()
        return self.panel.reconciliation.dialog

    def test_inspection_is_hidden_until_active_unknown_and_disabled_for_any_background_job(self):
        button = self.panel.buttons['inspect_unknown']
        self.assertTrue(button.isHidden())
        c = self.pending()
        self.assertTrue(button.isVisible())
        self.assertTrue(button.isEnabled())
        c.set_background_busy(True)
        self.assertFalse(button.isEnabled())
        with self.assertRaises(ValueError):
            c.request('inspect_unknown', REF)
        self.assertEqual((self.requests, self.quiesce, self.cancel), ([], [], []))
        c.set_background_busy(False)
        self.panel.account.setCurrentIndex(self.panel.account.findData(OTHER))
        self.assertFalse(button.isEnabled())
        with self.assertRaises(ValueError):
            c.request('inspect_unknown', OTHER)
        self.assertEqual((self.requests, self.quiesce, self.cancel), ([], [], []))
        for status in (
            {'state': 'ready', 'pending': False},
            {'state': 'user_confirmed_consumed', 'pending': False},
            {'state': 'quota_paused', 'pending': False},
        ):
            c.set_account_status(REF, status)
            self.assertTrue(button.isHidden())

    def test_inspection_result_needs_actual_join_before_dialog_and_retains_auth_models(self):
        c = self.pending()
        original = (c.state, c.registrations, c.active_registration, c.models)
        request = self.start()
        self.assertEqual(self.quiesce, [])
        c.apply_event(inspection_event(request))
        self.app.processEvents()
        self.assertTrue(c.busy)
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.assertFalse(c.worker_joined(request.request_id, joined=False))
        self.app.processEvents()
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.assertTrue(c.worker_joined(request.request_id, joined=True))
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.app.processEvents()
        self.assertIsNotNone(self.panel.reconciliation.dialog)
        self.assertEqual((c.state, c.registrations, c.active_registration, c.models), original)

    def test_three_fresh_acknowledgements_are_required_and_not_persisted(self):
        self.pending()
        dialog = self.complete_inspection()
        self.assertEqual(len(dialog.acknowledgements), 3)
        self.assertFalse(any(check.isChecked() for check in dialog.acknowledgements))
        self.assertTrue(dialog.cancel.isDefault())
        self.assertFalse(dialog.confirm.autoDefault())
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.accept()
        self.assertTrue(dialog.isVisible())
        for index, check in enumerate(dialog.acknowledgements):
            check.setChecked(True)
            self.assertEqual(dialog.confirm.isEnabled(), index == 2)
        dialog.acknowledgements[1].setChecked(False)
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.cancel.click()
        self.app.processEvents()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(set(self.panel.preferences()), {'version', 'max_calls', 'timeout_seconds'})
        self.requests.clear()
        fresh = self.complete_inspection()
        self.assertFalse(any(check.isChecked() for check in fresh.acknowledgements))
        QTest.keyClick(fresh, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.assertEqual(len(self.requests), 1)

    def test_confirm_sends_one_explicit_versioned_resolution_and_success_keeps_pause(self):
        c = self.pending()
        original = (c.state, c.registrations, c.active_registration, c.models)
        dialog = self.complete_inspection()
        for check in dialog.acknowledgements:
            check.setChecked(True)
        dialog.confirm.click()
        self.assertEqual([request.action for request in self.requests], ['inspect_unknown', 'resolve_unknown'])
        resolve = self.requests[-1]
        self.assertIs(resolve.user_confirmed, True)
        self.assertEqual(resolve.acknowledgement_version, 1)
        self.assertIs(type(resolve.acknowledgement_version), int)
        self.assertEqual(self.quiesce, [])
        c.apply_event(
            ui.ReconciliationEvent(
                resolve.request_id,
                'result',
                reconciliation_action=resolve.action,
                reconciliation_registration=REF,
                account_status=('user_confirmed_consumed', False),
            )
        )
        c.worker_joined(resolve.request_id, joined=True)
        self.assertEqual((c.state, c.registrations, c.active_registration, c.models), original)
        self.assertTrue(c.account_paused)
        self.assertFalse(c.account_pending)
        self.assertFalse(c.usage_known)
        self.assertIsNone(c.unknown_count)
        self.assertEqual(len(self.requests), 2)
        c.set_usage(REF, [{'sequence': 1, 'status': 'user_confirmed_consumed'}], account_status={'state': 'user_confirmed_consumed', 'pending': False})
        self.assertEqual((c.reserved_count, c.unknown_count), (1, 0))
        with self.assertRaises(ValueError):
            c.request('models', REF, confirmed=True)
        with self.assertRaises(ValueError):
            self.panel.build_plan_options()
        clear = c.request('clear_pause', REF, confirmed=True)
        self.assertEqual(clear.action, 'clear_pause')
        self.assertEqual(self.quiesce[-1], clear)

    def test_pending_after_resolution_blocks_clear_pause(self):
        c = self.pending()
        c.set_usage(REF, [{'sequence': 1, 'status': 'user_confirmed_consumed'}], account_status={'state': 'user_confirmed_consumed', 'pending': True})
        with self.assertRaises(ValueError):
            c.request('clear_pause', REF, confirmed=True)
        self.assertFalse(self.panel.buttons['clear_pause'].isEnabled())

    def test_unknown_followup_status_preserves_recorded_success_but_blocks_further_actions(self):
        c = self.pending()
        request = c.request('resolve_unknown', REF, confirmed=True, acknowledgement_version=1)
        c.apply_event(
            ui.ReconciliationEvent(request.request_id, 'result', reconciliation_action=request.action, reconciliation_registration=REF, account_status=None)
        )
        c.worker_joined(request.request_id, joined=True)
        self.assertFalse(c.account_status_known)
        self.assertFalse(c.usage_known)
        self.assertEqual(c.state, 'plan_ready')
        self.assertIn(ui.ui_text('chatgpt_reconciliation.resolved_unverified'), c.message)
        for action in ('inspect_unknown', 'resolve_unknown', 'clear_pause', 'models'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                c.request(action, REF, confirmed=True, acknowledgement_version=1 if action == 'resolve_unknown' else None)

    def test_changed_selection_hidden_panel_or_background_job_discards_dialog(self):
        c = self.pending()
        mutations = (
            lambda: self.panel.account.setCurrentIndex(self.panel.account.findData(OTHER)),
            self.panel.hide,
            lambda: c.set_background_busy(True),
            lambda: c.set_host_available(False),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.panel.show()
                c.set_host_available(True)
                c.set_background_busy(False)
                self.panel.account.setCurrentIndex(self.panel.account.findData(REF))
                self.requests.clear()
                dialog = self.complete_inspection()
                for check in dialog.acknowledgements:
                    check.setChecked(True)
                mutate()
                self.app.processEvents()
                self.assertIsNone(self.panel.reconciliation.dialog)
                self.assertEqual([r.action for r in self.requests], ['inspect_unknown'])

    def test_nonresolvable_recent_error_and_lost_terminal_never_open_confirmation(self):
        c = self.pending()
        for inspection in (
            ('k1_resolvable', 1, 1, False),
            ('k1_other_registration', None, None, False),
            ('k2_unresolvable', None, None, False),
            ('none', None, None, False),
        ):
            with self.subTest(inspection=inspection):
                self.requests.clear()
                self.assertIsNone(self.complete_inspection(inspection))
                self.assertEqual(len(self.requests), 1)
        self.requests.clear()
        request = self.start()
        c.apply_event(
            ui.ReconciliationEvent(
                request.request_id, 'error', reconciliation_action=request.action, reconciliation_registration=REF, error_code='unknown_request_too_recent'
            )
        )
        c.worker_joined(request.request_id, joined=True)
        self.app.processEvents()
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.requests.clear()
        request = self.start()
        c.worker_joined(request.request_id, joined=True, terminal_received=False)
        self.app.processEvents()
        self.assertIsNone(self.panel.reconciliation.dialog)
        self.assertFalse(c.account_status_known)
        self.assertEqual(c.state, 'plan_ready')

    def test_stale_mismatched_and_auth_events_cannot_drive_manual_flow(self):
        c = self.pending()
        request = self.start()
        self.assertFalse(c.apply_event(replace(inspection_event(request), request_id=request.request_id + 1)))
        for event in (
            replace(inspection_event(request), reconciliation_registration=OTHER),
            ui.ConnectionEvent(request.request_id, 'result', 'unknown'),
            ui.ReconciliationEvent(
                request.request_id,
                'result',
                reconciliation_action='resolve_unknown',
                reconciliation_registration=REF,
                account_status=('user_confirmed_consumed', False),
            ),
        ):
            with self.subTest(event=event), self.assertRaises(ValueError):
                c.apply_event(event)
        self.assertIsNone(c.reconciliation_inspection)
        self.assertTrue(c.account_pending)

    def test_dialog_accessibility_focus_plain_text_and_lazy_inventory(self):
        self.pending()
        self.assertEqual(self.panel.findChildren(QWidget, 'chatgpt_reconciliation_dialog'), [])
        dialog = self.complete_inspection()
        named = {widget.objectName() for widget in [dialog, *dialog.findChildren(QWidget)] if widget.objectName().startswith('chatgpt_reconciliation_')}
        self.assertEqual(
            named,
            {
                'chatgpt_reconciliation_' + name
                for name in ('dialog', 'summary', 'explanation', 'usage_checked', 'no_refund', 'no_other_tool', 'confirm', 'cancel')
            },
        )
        for widget in [dialog, *dialog.acknowledgements, dialog.confirm, dialog.cancel]:
            self.assertTrue(widget.accessibleName().strip(), widget.objectName())
            interface = QAccessible.queryAccessibleInterface(widget)
            self.assertTrue(interface.text(QAccessible.Text.Name).strip(), widget.objectName())
        self.assertIs(dialog.focusWidget(), dialog.cancel)
        dialog.acknowledgements[0].setFocus()
        for expected in [dialog.acknowledgements[1], dialog.acknowledgements[2], dialog.cancel]:
            QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
            self.assertIs(dialog.focusWidget(), expected)
        for name in ('summary', 'explanation'):
            self.assertEqual(dialog.findChild(QWidget, 'chatgpt_reconciliation_' + name).textFormat(), Qt.TextFormat.PlainText)
        self.assertFalse(dialog.grab().isNull())

    def test_host_race_refuses_reconciliation_without_cancelling_unrelated_work(self):
        from desktop_app.features.settings.settings import SettingsPage

        c = self.pending()
        request = c.request('inspect_unknown', REF)
        host = SimpleNamespace(
            jobs=SimpleNamespace(active=True), chatgpt_controller=c, status=Mock(), _quiesce_and_recover=Mock(), poll_jobs=Mock(), start_job=Mock()
        )
        SettingsPage._chatgpt_dispatch(host, request)
        self.assertFalse(c.busy)
        self.assertFalse(c.account_status_known)
        host._quiesce_and_recover.assert_not_called()
        host.poll_jobs.assert_not_called()
        host.start_job.assert_not_called()
        self.assertEqual(self.cancel, [])


def finished_inspection_event(request, inspection=('k2_resolvable', 1, 1, True), outcome='invalid_content_type', **kwargs):
    return ui.ReconciliationEvent(
        request.request_id,
        'result',
        reconciliation_action=request.action,
        reconciliation_registration=request.registration,
        inspection=inspection,
        inspection_outcome=outcome,
        **kwargs,
    )


class FinishedReconciliationPayloadTests(unittest.TestCase):
    """R2: the finished-unknown action, its bound target and the fixed outcome display."""

    def prepare(self, payload):
        return JobManager.__new__(JobManager)._prepare_other_job('ui_chatgpt_auth', {'request': payload})

    def finished(self, **kwargs):
        values = dict(user_confirmed=True, acknowledgement_version=1, expected_sequence=1, expected_calls=1, expected_outcome='invalid_content_type')
        values.update(kwargs)
        return ui.ConnectionRequest(9, 'resolve_finished_unknown', REF, **values)

    def test_finished_request_round_trips_and_every_payload_carries_the_null_target(self):
        request = self.finished()
        payload = json.loads(json.dumps(request.payload()))
        self.assertEqual(ui.ConnectionRequest(**payload), request)
        self.assertEqual(self.prepare(payload)[1:], (9, False))
        for other in (ui.ConnectionRequest(1, 'list'), ui.ConnectionRequest(2, 'inspect_unknown', REF)):
            payload = other.payload()
            self.assertEqual((payload['expected_sequence'], payload['expected_calls'], payload['expected_outcome']), (None, None, None))
            self.assertEqual(self.prepare(payload)[1], other.request_id)

    def test_finished_confirmation_and_target_fail_closed_at_both_boundaries(self):
        base = self.finished().payload()
        for change in (
            *({'acknowledgement_version': value} for value in (None, True, 0, 2, 1.0, '1')),
            {'user_confirmed': False},
            *({'expected_sequence': value} for value in (None, 0, 101, True, '1')),
            *({'expected_calls': value} for value in (None, 0, 1.0)),
            *({'expected_outcome': value} for value in (None, '', 'Invalid Content', 1)),
            {'registration': None},
        ):
            payload = {**base, **change}
            with self.subTest(change=change):
                with self.assertRaises((TypeError, ValueError)):
                    ui.ConnectionRequest(**payload)
                with self.assertRaises(RuntimeSafetyError):
                    self.prepare(payload)
        for action in ('list', 'inspect_unknown', 'resolve_unknown'):
            for key, value in (('expected_sequence', 1), ('expected_calls', 1), ('expected_outcome', 'cancelled')):
                confirmation = {'user_confirmed': True, 'acknowledgement_version': 1} if action == 'resolve_unknown' else {}
                payload = ui.ConnectionRequest(3, action, REF if action != 'list' else None, **confirmation).payload()
                payload[key] = value
                with self.subTest(action=action, key=key):
                    with self.assertRaises((TypeError, ValueError)):
                        ui.ConnectionRequest(**payload)
                    with self.assertRaises(RuntimeSafetyError):
                        self.prepare(payload)
        # A code outside the UI's frozen set is rejected by the typed request.
        with self.assertRaises(ValueError):
            self.finished(expected_outcome='quota_paused')

    def test_finished_outcomes_match_the_provider_set(self):
        import quantlab.assistant.adapters.chatgpt.provider

        self.assertEqual(ui.FINISHED_OUTCOMES, quantlab.assistant.adapters.chatgpt.provider._FINISHED_UNKNOWN_STATUSES)

    def test_finished_events_round_trip_and_outcome_is_only_for_k2_resolvable(self):
        request = ui.ConnectionRequest(1, 'inspect_unknown', REF)
        event = finished_inspection_event(request)
        self.assertEqual(connection_event_from_payload(_c_create_operation_ports(), json.loads(json.dumps(asdict(event)))), event)
        other = finished_inspection_event(request, ('k2_other_registration', None, None, False), None)
        self.assertEqual(connection_event_from_payload(_c_create_operation_ports(), json.loads(json.dumps(asdict(other)))), other)
        for inspection, outcome in (
            (('k2_resolvable', 1, 1, True), None),
            (('k2_resolvable', 1, 1, True), 'quota_paused'),
            (('k2_resolvable', 1, 2, True), 'cancelled'),
            (('k2_other_registration', 1, 1, False), None),
            (('k2_other_registration', None, None, False), 'cancelled'),
            (('k1_resolvable', 1, 1, True), 'cancelled'),
            (('k2_unresolvable', None, None, False), 'cancelled'),
        ):
            with self.subTest(inspection=inspection, outcome=outcome), self.assertRaises(ValueError):
                finished_inspection_event(request, inspection, outcome)

    def test_worker_consults_the_finished_inspector_only_after_an_r1_k2_refusal(self):
        request = ui.ConnectionRequest(1, 'inspect_unknown', REF)
        finished = {'kind': 'k2_resolvable', 'sequence': 1, 'calls': 1, 'max_age_ok': True, 'outcome': 'invalid_content_type'}
        with ExitStack() as stack:
            forbidden = [
                stack.enter_context(patch(target, side_effect=AssertionError('unexpected external operation')))
                for target in (
                    'quantlab.assistant.adapters.chatgpt.auth.AuthSession',
                    'quantlab.assistant.adapters.chatgpt.auth.DPAPIVault',
                    'socket.socket',
                    'socket.create_connection',
                )
            ]
            r1 = stack.enter_context(patch('quantlab.assistant.adapters.chatgpt.provider.inspect_unknown_request'))
            k2 = stack.enter_context(patch('quantlab.assistant.adapters.chatgpt.provider.inspect_finished_unknown_request', return_value=finished))
            for kind in ('k1_resolvable', 'k1_other_registration', 'none'):
                r1.return_value = {'kind': kind, 'sequence': 1 if kind == 'k1_resolvable' else None, 'calls': 1 if kind == 'k1_resolvable' else None,
                                   'max_age_ok': kind == 'k1_resolvable'}  # fmt: skip
                result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
                self.assertEqual(result.inspection[0], kind)
                self.assertIsNone(result.inspection_outcome)
            k2.assert_not_called()
            r1.return_value = {'kind': 'k2_unresolvable', 'sequence': None, 'calls': None, 'max_age_ok': False}
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
            self.assertEqual((result.inspection, result.inspection_outcome), (('k2_resolvable', 1, 1, True), 'invalid_content_type'))
            k2.side_effect = ValueError('private path C:/secret')
            result = ui.run_connection_request(request, bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
            self.assertEqual(result.kind, 'error')
            self.assertNotIn('secret', json.dumps(asdict(result)))
            for guard in forbidden:
                guard.assert_not_called()

    def test_worker_resolution_passes_the_bound_target(self):
        with (
            patch('quantlab.assistant.adapters.chatgpt.provider.resolve_finished_unknown_request') as resolve,
            patch('quantlab.assistant.adapters.chatgpt.provider.resolve_unknown_request') as r1,
            patch('quantlab.assistant.adapters.chatgpt.provider.read_account_status', return_value={'state': 'user_confirmed_consumed', 'pending': False}),
        ):
            result = ui.run_connection_request(self.finished(), bootstrap=BOOTSTRAP, emit=Mock(), cancelled=lambda: False)
        r1.assert_not_called()
        self.assertEqual(result.account_status, ('user_confirmed_consumed', False))
        self.assertEqual(
            resolve.call_args.kwargs,
            {'user_confirmed': True, 'acknowledgement_version': 1, 'expected_sequence': 1, 'expected_calls': 1, 'expected_outcome': 'invalid_content_type'},
        )

    def test_r2_refusal_codes_have_fixed_b1_text(self):
        from quantlab.errors import ERROR_LABELS

        for code in (
            'resolution_confirmation_required',
            'no_resolvable_unknown_request',
            'unknown_request_owned_by_another_registration',
            'finished_request_unmappable',
            'unknown_request_too_recent',
        ):
            self.assertIn(code, ERROR_LABELS)


class FinishedReconciliationWidgetTests(unittest.TestCase):
    """R2 reuses the R1 panel and dialog; only the copy and the sent action differ."""

    setUpClass = classmethod(ReconciliationWidgetTests.setUpClass.__func__)
    setUp = ReconciliationWidgetTests.setUp
    cleanup_panel = ReconciliationWidgetTests.cleanup_panel
    pending = ReconciliationWidgetTests.pending
    start = ReconciliationWidgetTests.start
    complete_inspection = ReconciliationWidgetTests.complete_inspection

    def complete_finished(self, inspection=('k2_resolvable', 1, 1, True), outcome='invalid_content_type'):
        request = self.start()
        self.controller.apply_event(finished_inspection_event(request, inspection, outcome))
        self.controller.worker_joined(request.request_id, joined=True)
        self.app.processEvents()
        return self.panel.reconciliation.dialog

    def test_k2_dialog_reuses_widgets_with_finished_copy_and_sends_the_bound_action(self):
        self.pending()
        k1 = self.complete_inspection()
        names = {child.objectName() for child in k1.findChildren(QWidget) if child.objectName()}
        k1.cancel.click()
        self.app.processEvents()
        self.requests.clear()
        dialog = self.complete_finished()
        self.assertEqual({child.objectName() for child in dialog.findChildren(QWidget) if child.objectName()}, names)
        summary = dialog.findChild(QWidget, 'chatgpt_reconciliation_summary').text()
        self.assertIn('invalid_content_type', summary)
        self.assertEqual(summary, ui.ui_text('chatgpt_reconciliation_k2.summary').format(1, 1, 'invalid_content_type'))
        self.assertTrue(
            dialog.findChild(QWidget, 'chatgpt_reconciliation_explanation').text().endswith(ui.ui_text('chatgpt_reconciliation_k2.not_sent_notice'))
        )
        self.assertEqual(dialog.acknowledgements[2].text(), ui.ui_text('chatgpt_reconciliation_k2.other_usage'))
        self.assertFalse(any(check.isChecked() for check in dialog.acknowledgements))
        self.assertTrue(dialog.cancel.isDefault())
        self.assertFalse(dialog.confirm.isEnabled())
        for check in dialog.acknowledgements:
            check.setChecked(True)
        dialog.confirm.click()
        resolve = self.requests[-1]
        self.assertEqual(resolve.action, 'resolve_finished_unknown')
        self.assertEqual((resolve.expected_sequence, resolve.expected_calls, resolve.expected_outcome), (1, 1, 'invalid_content_type'))
        self.assertIs(resolve.user_confirmed, True)
        self.assertEqual(resolve.acknowledgement_version, 1)
        c = self.controller
        c.apply_event(
            ui.ReconciliationEvent(
                resolve.request_id,
                'result',
                reconciliation_action=resolve.action,
                reconciliation_registration=REF,
                account_status=('user_confirmed_consumed', False),
            )
        )
        c.worker_joined(resolve.request_id, joined=True)
        self.assertTrue(c.account_paused)
        self.assertEqual(c.message.split(ui.ui_text('chatgpt_ui.apply_event.wait_for_host'))[0], ui.ui_text('chatgpt_reconciliation.resolved'))

    def test_recent_other_and_unmappable_k2_never_open_confirmation(self):
        cases = (
            (('k2_resolvable', 1, 1, False), 'invalid_content_type', 'chatgpt_reconciliation_k2.too_recent'),
            (('k2_other_registration', None, None, False), None, 'chatgpt_reconciliation_k2.other_registration'),
            (('k2_unresolvable', None, None, False), None, 'chatgpt_reconciliation_k2.unmappable'),
        )
        self.pending()
        for inspection, outcome, key in cases:
            with self.subTest(kind=inspection[0]):
                self.requests.clear()
                self.assertIsNone(self.complete_finished(inspection, outcome))
                self.assertEqual(self.requests[-1].action, 'inspect_unknown')
                self.assertTrue(self.controller.message.startswith(ui.ui_text(key)))


if __name__ == '__main__':
    unittest.main()
