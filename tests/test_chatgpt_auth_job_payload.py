"""The job manager admits the exact ChatGPT connection payloads the panel sends."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from quantlab.assistant.application.connection_contracts import ConnectionRequest
from quantlab.desktop_runtime import JobManager, RuntimeSafetyError

REF = 'a' * 32


class AuthJobPayloadTests(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager.__new__(JobManager)

    def prepare(self, request):
        return self.manager._prepare_other_job('ui_chatgpt_auth', {'request': request})

    def test_every_panel_request_shape_is_admitted(self):
        # Regression: ConnectionRequest gained `model` (connection test); sign-in could not start.
        requests = (
            ConnectionRequest(1, 'list'),
            ConnectionRequest(2, 'restore'),
            ConnectionRequest(3, 'first_sign_in', user_confirmed=True),
            ConnectionRequest(4, 'models', registration=REF, user_confirmed=True),
            ConnectionRequest(5, 'test', registration=REF, user_confirmed=True, model='gpt-fixture'),
        )
        for request in requests:
            with self.subTest(action=request.action):
                payload = request.payload()
                self.assertIn('model', payload)
                deadline, request_id, reconciliation = self.prepare(payload)
                self.assertIsNotNone(deadline)
                self.assertEqual((request_id, reconciliation), (request.request_id, False))

    def test_legacy_shape_without_model_still_admitted(self):
        payload = ConnectionRequest(1, 'list').payload()
        del payload['model']
        self.assertEqual(self.prepare(payload)[1], 1)

    def test_invalid_model_or_extra_fields_still_rejected(self):
        base = ConnectionRequest(1, 'list').payload()
        for bad in (
            {**base, 'model': 'bad model'},
            {**base, 'model': 7},
            {**base, 'model': 'x' * 129},
            {**base, 'extra': 1},
            {**base, 'max_runtime_seconds': 601},
        ):
            with self.subTest(bad=bad), self.assertRaises(RuntimeSafetyError):
                self.prepare(bad)


if __name__ == '__main__':
    unittest.main()
