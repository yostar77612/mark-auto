"""Installer trust/download guards against a loopback HTTP server, never GitHub."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

from quantlab.update_check import (
    RELEASE_DOWNLOAD_PREFIX,
    ReleaseInfo,
    UpdateError,
    _HTTPSRedirect,
    check_for_update,
    release_source_url,
)
from quantlab.update_download import CHUNK_SIZE, discard_download, download_installer


PAYLOAD = b'MZ' + bytes(range(256)) * 1000
ASSET_URL = RELEASE_DOWNLOAD_PREFIX + 'desktop-preview-123/MarkAuto-1.3-windows-x64-setup.exe'


def release(**changes):
    values = dict(
        version='1.3',
        commit='a' * 40,
        published_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        installer_url=ASSET_URL,
        installer_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
    )
    values.update(changes)
    return ReleaseInfo(**values)


@contextmanager
def http_fixture(mode='ok'):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if mode == 'timeout':
                time.sleep(0.1)
            try:
                self.send_response(503 if mode == 'unavailable' else 200)
                if mode not in ('unbounded', 'timeout'):
                    length = len(PAYLOAD) + (1 if mode == 'truncated' else 0)
                    self.send_header('Content-Length', str(length))
                self.end_headers()
                self.wfile.write(PAYLOAD)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        # The injected network adapter connects to the fixture. The public entry
        # point still validates the production release URL before invoking it.
        yield lambda url, timeout: urlopen('http://127.0.0.1:' + str(server.server_port) + '/installer', timeout=timeout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ReleaseMetadataTests(unittest.TestCase):
    def manifest(self, **changes):
        document = {
            'version': '1.3',
            'commit': 'a' * 40,
            'published_at': '2026-11-01T01:02:03Z',
            'signature_verified': False,
            'installer': {'url': ASSET_URL, 'sha256': hashlib.sha256(PAYLOAD).hexdigest()},
        }
        document.update(changes)
        raw = json.dumps(document).encode()
        return check_for_update('1.2', transport=lambda url: (raw, hashlib.sha256(raw).hexdigest()))

    def test_verified_manifest_contains_install_metadata(self):
        result = self.manifest()
        self.assertEqual(result.status, 'update_available')
        self.assertEqual(result.release.installer_url, ASSET_URL)
        self.assertEqual(result.release.installer_sha256, hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual(result.release.published_at, datetime(2026, 11, 1, 1, 2, 3, tzinfo=timezone.utc))
        self.assertFalse(result.release.signature_verified)

    def test_each_install_metadata_guard_rejects_its_own_invalid_value(self):
        cases = (
            {'published_at': '2026-11-01'},
            {'published_at': 'not-a-time'},
            {'published_at': 0},
            {'installer': None},
            {'installer': {}},
            {'installer': {'url': ASSET_URL, 'sha256': 'a' * 63}},
            {'installer': {'url': ASSET_URL, 'sha256': 'z' * 64}},
            {'installer': {'url': ASSET_URL, 'sha256': 123}},
            {'installer': {'url': ASSET_URL.replace('https:', 'http:'), 'sha256': 'a' * 64}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.manifest(**changes).status, 'error')


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='m4a-download-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sentinel = self.root / 'workspace-settings.json'
        self.sentinel.write_bytes(b'original settings')

    def assert_clean(self):
        self.assertEqual(list(self.root.iterdir()), [self.sentinel])
        self.assertEqual(self.sentinel.read_bytes(), b'original settings')

    def test_complete_download_is_verified_in_its_own_unique_directory(self):
        with http_fixture() as transport:
            first = download_installer(release(), Event(), temp_root=self.root, transport=transport)
            second = download_installer(release(), Event(), temp_root=self.root, transport=transport)
        self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(first.read_bytes(), PAYLOAD)
        self.assertEqual(list(first.parent.iterdir()), [first])
        discard_download(first)
        discard_download(second)
        self.assert_clean()

    def test_hash_compares_all_256_bits_and_removes_rejected_download(self):
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        wrong_last_digit = digest[:-1] + ('0' if digest[-1] != '0' else '1')
        with http_fixture() as transport, self.assertRaises(UpdateError) as caught:
            download_installer(release(installer_sha256=wrong_last_digit), Event(), temp_root=self.root, transport=transport)
        self.assertEqual(caught.exception.code, 'update_hash_mismatch')
        self.assert_clean()

    def test_source_is_validated_before_network_or_temp_file_creation(self):
        for url in (
            ASSET_URL.replace('https:', 'http:'),
            ASSET_URL.replace('github.com/', 'github.com.evil.example/'),
            ASSET_URL.replace('github.com/', 'user@github.com/'),
            ASSET_URL.replace('github.com/', 'github.com:444/'),
            ASSET_URL + '#fragment',
            ASSET_URL + '?unexpected=1',
            ASSET_URL.replace('/desktop-preview-123/', '/../'),
            ASSET_URL.replace('/desktop-preview-123/', '/%2e%2e/'),
            'https://release-assets.githubusercontent.com/github-production-release-asset/123/file.exe',
            'https://github.com/another/repo/releases/download/tag/setup.exe',
        ):
            with self.subTest(url=url):
                transport = Mock()
                with self.assertRaises(UpdateError) as caught:
                    download_installer(release(installer_url=url), Event(), temp_root=self.root, transport=transport)
                self.assertEqual(caught.exception.code, 'update_source_rejected')
                transport.assert_not_called()
                self.assert_clean()

    def test_declared_content_length_enforces_limit_before_read(self):
        with http_fixture() as transport, self.assertRaises(UpdateError) as caught:
            download_installer(release(), Event(), temp_root=self.root, max_bytes=len(PAYLOAD) - 1, transport=transport)
        self.assertEqual(caught.exception.code, 'update_too_large')
        self.assert_clean()

    def test_unknown_content_length_cannot_bypass_stream_limit(self):
        with http_fixture('unbounded') as transport, self.assertRaises(UpdateError) as caught:
            download_installer(release(), Event(), temp_root=self.root, max_bytes=CHUNK_SIZE, transport=transport)
        self.assertEqual(caught.exception.code, 'update_too_large')
        self.assert_clean()

    def test_socket_timeout_has_specific_code_and_cleans_partial_directory(self):
        with http_fixture('timeout') as transport, self.assertRaises(UpdateError) as caught:
            download_installer(release(), Event(), temp_root=self.root, timeout=0.02, transport=transport)
        self.assertEqual(caught.exception.code, 'update_download_timeout')
        self.assert_clean()

    def test_total_deadline_is_checked_after_a_response_chunk(self):
        with http_fixture() as transport, patch('quantlab.update_download.monotonic', side_effect=[0, 0, 0, 2]):
            with self.assertRaises(UpdateError) as caught:
                download_installer(release(), Event(), temp_root=self.root, timeout=1, transport=transport)
        self.assertEqual(caught.exception.code, 'update_download_timeout')
        self.assert_clean()

    def test_cancel_before_request_never_downloads(self):
        cancel = Event()
        cancel.set()
        transport = Mock()
        with self.assertRaises(UpdateError) as caught:
            download_installer(release(), cancel, temp_root=self.root, transport=transport)
        self.assertEqual(caught.exception.code, 'update_download_cancelled')
        transport.assert_not_called()
        self.assert_clean()

    def test_cancel_during_a_real_response_read_removes_partial_file(self):
        cancel = Event()
        with http_fixture() as request:

            def transport(url, timeout):
                response = request(url, timeout)
                read = response.read1

                def cancelling_read(size):
                    data = read(size)
                    cancel.set()
                    return data

                response.read1 = cancelling_read
                return response

            with self.assertRaises(UpdateError) as caught:
                download_installer(release(), cancel, temp_root=self.root, transport=transport)
        self.assertEqual(caught.exception.code, 'update_download_cancelled')
        self.assert_clean()

    def test_http_failure_and_truncated_transfer_preserve_settings(self):
        for mode in ('unavailable', 'truncated'):
            with self.subTest(mode=mode), http_fixture(mode) as transport, self.assertRaises(UpdateError) as caught:
                download_installer(release(), Event(), temp_root=self.root, transport=transport)
            self.assertEqual(caught.exception.code, 'update_download_failed')
            self.assert_clean()

    def test_redirects_reject_downgrade_credentials_and_unrelated_https(self):
        for url in (
            'http://github.com/file',
            'https://evil.example/file.exe',
            'https://user@release-assets.githubusercontent.com/github-production-release-asset/x/y',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _HTTPSRedirect().redirect_request(Request(ASSET_URL), None, 302, '', {}, url)

    def test_official_release_cdn_is_only_a_redirect_destination(self):
        url = 'https://release-assets.githubusercontent.com/github-production-release-asset/123/hash?sig=signature'
        request = _HTTPSRedirect().redirect_request(Request(ASSET_URL), None, 302, '', {}, url)
        self.assertEqual(request.full_url, url)
        with self.assertRaises(UpdateError):
            release_source_url(url)

    def test_live_transport_rechecks_final_url_and_closes_a_rejected_response(self):
        class Response:
            headers = {}
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.closed = True

            def geturl(self):
                return 'https://unrelated.example/installer.exe'

        response = Response()
        opener = SimpleNamespace(open=Mock(return_value=response))
        with patch('quantlab.update_download.build_trust_context'), patch('quantlab.update_download.build_opener', return_value=opener):
            with self.assertRaises(UpdateError) as caught:
                download_installer(release(), Event(), temp_root=self.root)
        self.assertEqual(caught.exception.code, 'update_source_rejected')
        self.assertTrue(response.closed)
        self.assert_clean()
