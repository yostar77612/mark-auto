"""Offline owner-tool behavior for the explicit reconciliation pause."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from quantlab.desktop_errors import error_message
from tools import validate_web_search as tool


class ReconciliationReadinessTests(unittest.TestCase):
    def test_confirmed_pause_has_recovery_guidance_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = {'registration': 'a' * 32, 'bootstrap': str(Path(directory))}
            transport, discover = Mock(), Mock()
            with (
                patch('quantlab.assistant.adapters.chatgpt.provider.read_account_status', return_value={'state': 'user_confirmed_consumed', 'pending': False}),
                patch('quantlab.assistant.adapters.chatgpt.auth.AuthSession', side_effect=AssertionError('No vault access')),
                patch('socket.socket', side_effect=AssertionError('No network')),
            ):
                search = tool.run('offline-model', transport=transport, **reference)
                models = tool.list_models(discover=discover, **reference)
            for result in (search, models):
                self.assertEqual(result['error_code'], 'account_not_ready')
                self.assertEqual(result['account_state'], 'user_confirmed_consumed')
                self.assertIs(result['pending_request'], False)
                self.assertEqual(result['message'], error_message('user_confirmed_consumed'))
            transport.stream.assert_not_called()
            discover.assert_not_called()

    def test_pending_or_other_pause_keeps_existing_fixed_status_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            for state, pending in (('reserved_unknown', True), ('user_confirmed_consumed', True), ('quota_paused', False)):
                with (
                    self.subTest(state=state, pending=pending),
                    patch('quantlab.assistant.adapters.chatgpt.provider.read_account_status', return_value={'state': state, 'pending': pending}),
                ):
                    reference, error = tool._reference('a' * 32, directory)
                self.assertIsNone(reference)
                self.assertEqual(error, {'error_code': 'account_not_ready', 'account_state': state, 'pending_request': pending})
