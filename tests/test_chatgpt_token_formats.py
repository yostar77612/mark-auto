"""Invented token responses and in-memory accounts; no real OAuth or network."""

from copy import deepcopy
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import quantlab.assistant.adapters.chatgpt.auth as auth
from desktop_app.features.assistant.connection import ConnectionRequest, run_connection_request
from tests import test_chatgpt_auth as auth_fixtures


class TokenFormatAndStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_fixtures.AuthTests.setUpClass()

    def setUp(self):
        for target in ('socket.socket', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('offline fixture only'))
            guard.start()
            self.addCleanup(guard.stop)

    def attempt(self, changes=None, stage=None, existing=False):
        owner = auth_fixtures.AuthTests()
        owner.setUp()
        registration = None
        if existing:
            owner.begin()
            registration = owner.callback()
        else:
            owner.session.initialize_host()
        before = deepcopy(owner.vault.record)
        original_begin = owner.session.begin
        original_transport = owner.transport.request
        original_verify = owner.session.validator.verify
        original_save = owner.vault.save
        exchanges = []
        events = []

        def begin(*args, **kwargs):
            url = original_begin(*args, **kwargs)
            owner.query = parse_qs(urlsplit(url).query)
            return url

        def transport(method, endpoint, *, form=None):
            if endpoint == auth.TOKEN:
                exchanges.append(True)
                if stage == 'exchange':
                    raise RuntimeError('FIXTURE_PRIVATE_WIRE_DETAIL')
                if stage == 'cancel_exchange':
                    owner.session.cancel()
            response = original_transport(method, endpoint, form=form)
            if endpoint == auth.TOKEN and changes:
                response = auth.HttpResponse(response.status, json.dumps(json.loads(response.body) | changes).encode())
            return response

        def verify(*args, **kwargs):
            if stage == 'identity':
                raise RuntimeError('FIXTURE_PRIVATE_IDENTITY_DETAIL')
            return original_verify(*args, **kwargs)

        def save(record):
            if stage == 'storage':
                raise OSError('FIXTURE_PRIVATE_STORAGE_DETAIL')
            return original_save(record)

        def poll(timeout):
            try:
                owner.callback(scope=auth.SCOPES)
            except auth.AuthError:
                pass  # The existing listener catches rejected callbacks.

        owner.session.begin = begin
        owner.transport.request = transport
        owner.session.validator.verify = verify
        owner.session.poll = poll
        owner.vault.save = save
        result = run_connection_request(
            ConnectionRequest(1, 'begin', registration, user_confirmed=True),
            bootstrap='/fixture',
            emit=events.append,
            cancelled=lambda: False,
            session_factory=lambda: owner.session,
        )
        self.assertEqual(len(exchanges), 1)
        self.assertIsNone(result.authorization_url)
        return result, owner, before

    def test_case_insensitive_bearer_is_accepted(self):
        result, owner, _ = self.attempt({'token_type': 'bEaReR'})
        self.assertEqual((result.kind, result.state), ('result', 'plan_ready'))

    def test_iso_timestamp_string_is_normalized_to_unix_seconds(self):
        result, owner, _ = self.attempt({'earliest_refresh_at': '2026-10-15T00:00:00Z'})
        self.assertEqual((result.kind, result.state), ('result', 'plan_ready'))
        row = owner.vault.record['registrations'][result.active_registration]
        self.assertEqual(row['tokens']['earliest_refresh_at'], 1792022400)

    def test_four_failure_stages_are_fixed_safe_and_preserve_existing_accounts(self):
        cases = [
            ('exchange', None, 'authorization_exchange_failed'),
            ('identity', None, 'authorization_identity_failed'),
            ('tokens', {'expires_in': True}, 'authorization_tokens_failed'),
            ('storage', None, 'authorization_storage_failed'),
        ]
        for existing in (False, True):
            for stage, changes, expected in cases:
                with self.subTest(stage=stage, existing=existing):
                    result, owner, before = self.attempt(changes, stage=stage, existing=existing)
                    self.assertEqual((result.kind, result.state, result.error_code), ('error', 'authorization_failed', expected))
                    self.assertTrue(owner.vault.record == before, 'Existing synthetic account must be preserved')
                    self.assertTrue(result.active_registration == before['active'])
                    text = repr(result)
                    self.assertTrue(
                        all(
                            marker not in text
                            for marker in [
                                'FIXTURE_PRIVATE_',
                                'fixture-code',
                                owner.query['state'][0],
                                owner.query['nonce'][0],
                                'fixture-access-',
                                'fixture-refresh-',
                            ]
                        )
                    )

    def test_offsets_milliseconds_and_numeric_seconds_match_pinned_sdk(self):
        cases = [
            ('2026-10-15T08:00:00+08:00', 1792022400),
            ('2026-10-14T20:00:00-04:00', 1792022400),
            ('2026-10-15T00:00:00.123987654Z', 1792022400.123),
            (1792022400.125, 1792022400.125),
            (0, 0),
        ]
        for value, expected in cases:
            with self.subTest(case=type(value).__name__):
                result, owner, _ = self.attempt({'earliest_refresh_at': value})
                self.assertEqual(result.state, 'plan_ready')
                row = owner.vault.record['registrations'][result.active_registration]
                self.assertEqual(row['tokens']['earliest_refresh_at'], expected)

    def test_malformed_ambiguous_nonfinite_and_out_of_range_refresh_times_reject(self):
        cases = [
            None,
            True,
            -1,
            float('nan'),
            float('inf'),
            2**53 + 1,
            '',
            '1792022400',
            'not-a-date',
            '2026-02-30T00:00:00Z',
            '2026-10-15T00:00:00',
            '2026-10-15T00:00:00+99:00',
            '2026-10-15T00:00:00Z extra',
            '1969-12-31T23:59:59Z',
        ]
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                result, owner, before = self.attempt({'earliest_refresh_at': value})
                # NaN/Infinity are invalid JSON and fail before token-field validation.
                expected = 'authorization_exchange_failed' if index in (3, 4) else 'authorization_tokens_failed'
                self.assertEqual(result.error_code, expected)
                self.assertTrue(owner.vault.record == before, 'Invalid time must not commit credentials')

    def test_invalid_token_types_remain_rejected(self):
        for index, value in enumerate([None, True, 42, '', 'MAC', 'Bearer ', ' Bearer']):
            with self.subTest(case=index):
                result, owner, before = self.attempt({'token_type': value})
                self.assertEqual(result.error_code, 'authorization_tokens_failed')
                self.assertTrue(owner.vault.record == before)

    def test_original_expiry_limits_remain_enforced(self):
        for index, value in enumerate([None, True, 0, -1, 86401, float('nan'), float('inf')]):
            with self.subTest(case=index):
                result, owner, before = self.attempt({'expires_in': value})
                # Nonfinite JSON constants are rejected at exchange-response decoding.
                expected = 'authorization_exchange_failed' if index in (5, 6) else 'authorization_tokens_failed'
                self.assertEqual(result.error_code, expected)
                self.assertTrue(owner.vault.record == before)

    def test_identity_only_without_access_credentials_remains_explicitly_unverified(self):
        result, owner, before = self.attempt({'access_token': None, 'refresh_token': None, 'scope': 'openid profile email'})
        self.assertEqual((result.state, result.error_code), ('authorization_failed', 'authorization_tokens_failed'))
        self.assertTrue(owner.vault.record == before)

    def test_consumed_codes_are_never_exchanged_twice_after_any_stage_failure(self):
        for stage in ('exchange', 'identity', 'tokens', 'storage'):
            with self.subTest(stage=stage):
                changes = {'expires_in': True} if stage == 'tokens' else None
                result, owner, before = self.attempt(changes, stage=stage, existing=True)
                count = len(owner.transport.calls)
                with self.assertRaisesRegex(auth.AuthError, '^no_pending_authorization$'):
                    owner.callback()
                self.assertEqual(len(owner.transport.calls), count)
                self.assertTrue(owner.vault.record == before)

    def test_new_explicit_attempt_clears_only_the_transient_failure_category(self):
        result, owner, before = self.attempt(stage='identity', existing=True)
        self.assertEqual(owner.session.authorization_error_code, 'authorization_identity_failed')
        owner.session.begin(result.active_registration)
        self.assertIsNone(owner.session.authorization_error_code)
        self.assertTrue(owner.vault.record == before)
        owner.session.cancel()

    def test_unknown_stage_value_never_crosses_terminal_error_boundary(self):
        from tests import test_chatgpt_terminal_reporting as fixtures

        for value in ['FIXTURE_PRIVATE_UNKNOWN_STAGE', {'private': 'FIXTURE_PRIVATE_DETAIL'}]:
            session = fixtures.AttemptSession()
            session.authorization_error_code = value
            result = run_connection_request(
                ConnectionRequest(1, 'begin', user_confirmed=True),
                bootstrap='/fixture',
                emit=lambda event: None,
                cancelled=lambda: False,
                session_factory=lambda: session,
            )
            self.assertEqual(result.error_code, 'authorization_failed')
            self.assertTrue('FIXTURE_PRIVATE_' not in repr(result))

    def test_cancellation_during_exchange_keeps_prior_account_and_no_failure_stage(self):
        result, owner, before = self.attempt(stage='cancel_exchange', existing=True)
        self.assertEqual((result.kind, result.state, result.error_code), ('result', 'cancelled', ''))
        self.assertIsNone(owner.session.authorization_error_code)
        self.assertTrue(owner.vault.record == before)

    def test_invalid_offset_minutes_reject_and_preserve_existing_account(self):
        for offset in ('+00:60', '-00:60', '+01:99', '-01:99'):
            with self.subTest(offset=offset):
                result, owner, before = self.attempt({'earliest_refresh_at': '2026-10-15T00:00:00' + offset}, existing=True)
                self.assertEqual((result.kind, result.state, result.error_code), ('error', 'authorization_failed', 'authorization_tokens_failed'))
                self.assertTrue(owner.vault.record == before, 'Invalid offset must preserve the existing account')
                self.assertTrue(result.active_registration == before['active'])


if __name__ == '__main__':
    unittest.main()
