"""Metadata transport failures and untrusted consent-dialog text boundaries."""

from http.client import BadStatusLine, IncompleteRead
import hashlib
import json
import unittest
from unittest.mock import Mock

from quantlab.update_check import RELEASE_DOWNLOAD_PREFIX, UpdateError, UpdateResult, check_for_update, release_source_url


class UpdateMetadataBoundaryTests(unittest.TestCase):
    def test_publication_timestamp_must_fit_both_utc_and_taipei(self):
        for published_at in ('0001-01-01T00:00:00+23:59', '9999-12-31T23:59:59Z'):
            raw = json.dumps(
                {
                    'version': '1.3',
                    'published_at': published_at,
                    'installer': {'url': RELEASE_DOWNLOAD_PREFIX + 'tag/MarkAuto.exe', 'sha256': 'a' * 64},
                }
            ).encode()
            with self.subTest(published_at=published_at):
                result = check_for_update('1.2', transport=lambda url: (raw, hashlib.sha256(raw).hexdigest()))
                self.assertEqual(result, UpdateResult('error', 'check_failed'))

    def test_truncated_http_metadata_returns_only_a_fixed_error(self):
        for error in (IncompleteRead(b'private partial body', 1), BadStatusLine('private server reply')):
            with self.subTest(error_type=type(error).__name__):
                result = check_for_update('1.2', transport=Mock(side_effect=error))
                self.assertEqual(result, UpdateResult('error', 'check_failed'))

    def test_source_url_rejects_html_whitespace_and_control_characters(self):
        for fragment in ('<b>setup</b>', 'setup file', 'setup\n', 'setup\r', 'setup\t', 'setup\x00', 'setup\x7f', 'setup"', "setup'"):
            with self.subTest(fragment=fragment), self.assertRaises(UpdateError) as caught:
                release_source_url(RELEASE_DOWNLOAD_PREFIX + 'tag/' + fragment + '.exe')
            self.assertEqual(caught.exception.code, 'update_source_rejected')
