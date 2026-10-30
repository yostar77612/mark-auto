"""Fixed allowlisted model-fetch failure stages; invented errors, no network."""

import os
import sqlite3
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import desktop_app.features.assistant.connection as ui
from quantlab.assistant.adapters.chatgpt.auth import AuthError
from quantlab.assistant.adapters.chatgpt.provider import PlanError


class ModelErrorCodeTests(unittest.TestCase):
    def test_plan_error_codes_with_fixed_labels_pass_through(self):
        for code in (
            'http_transport_failed',
            'invalid_catalog',
            'credential_diagnosis',
            'grant_blocked',
            'redirect_rejected',
            'deadline_exceeded',
            'quota_paused',
        ):
            with self.subTest(code=code):
                self.assertEqual(ui._safe_error_code(PlanError(code)), code)
                self.assertIn(code, ui.ERROR_LABELS)

    def test_remote_error_maps_status_to_fixed_codes_without_remote_text(self):
        for status, expected in (
            (400, 'models_http_bad_request'),
            (404, 'models_http_not_found'),
            (429, 'models_http_rate_limited'),
            (502, 'models_http_server_error'),
            (418, 'models_http_other'),
            (None, 'models_http_other'),
        ):
            with self.subTest(status=status):
                exc = PlanError('remote_error', http_status=status, remote_code='SECRET_REMOTE_TEXT')
                self.assertEqual(ui._safe_error_code(exc), expected)
                self.assertIn(expected, ui.ERROR_LABELS)

    def test_unknown_codes_fall_back_to_coarse_fixed_classes(self):
        self.assertEqual(ui._safe_error_code(PlanError('SECRET_UNKNOWN')), 'operation_failed_plan')
        self.assertEqual(ui._safe_error_code(AuthError('SECRET_UNKNOWN')), 'operation_failed_auth')
        self.assertEqual(ui._safe_error_code(OSError('SECRET path')), 'operation_failed_local')
        self.assertEqual(ui._safe_error_code(sqlite3.Error('SECRET')), 'operation_failed_local')
        self.assertEqual(ui._safe_error_code(RuntimeError('Bearer SECRET')), 'operation_failed')
        for code in ('operation_failed_plan', 'operation_failed_auth', 'operation_failed_local'):
            self.assertIn(code, ui.ERROR_LABELS)

    def test_event_boundary_accepts_every_new_code_and_labels_have_no_secret_marker(self):
        for code, label in ui.ERROR_LABELS.items():
            ui.ConnectionEvent(1, 'error', 'unknown', error_code=code)
            self.assertNotIn('SECRET', label)


class ModelCatalogLimitTests(unittest.TestCase):
    def test_catalog_limit_is_bounded_and_larger_than_previous_cap(self):
        from quantlab.assistant.adapters.chatgpt.provider import MODELS_MAX_RESPONSE_BYTES

        self.assertGreater(MODELS_MAX_RESPONSE_BYTES, 262144)
        self.assertLessEqual(MODELS_MAX_RESPONSE_BYTES, 16 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
