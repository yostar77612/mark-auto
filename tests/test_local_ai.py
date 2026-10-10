"""Small, inert local-AI fixtures; never download or execute a model/runtime."""
import copy
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import socket
import stat
import struct
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.request
import warnings
import zipfile

from quantlab import local_ai
from quantlab.core import ValidationError
from quantlab.provider import HTTPTransport
from quantlab.research import _provider_identity


def artifact(data, filename=None, url=None):
    value = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    if filename is not None:
        value['filename'] = filename
    if url is not None:
        value['url'] = url
    return value


def response_for(candidate):
    return {'choices': [{'message': {'content': json.dumps(candidate)}}]}


VALID_CANDIDATE = {'schema_version': 1, 'strategy_id': 'inert_local_fixture',
                   'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'rules': {}}
OWNER = {'pid': 123, 'created': 456}


class DownloadResponse(io.BytesIO):
    def __init__(self, data, *, url, status=200, headers=None):
        super().__init__(data)
        self.url = url
        self.status = status
        self.headers = {} if headers is None else headers

    def geturl(self):
        return self.url


class LocalAIFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.resources = self.base / 'resources'
        self.resources.mkdir()
        self.paths = SimpleNamespace(root=self.base / 'workspace', bootstrap=self.base / 'bootstrap')
        # These bytes deliberately are not real Windows executables or a model.
        self.members = {'llama-server.exe': b'INERT FIXTURE: must never execute',
                        'llama-server-impl.dll': b'INERT DLL',
                        'LICENSE-LLVM-OpenMP': b'inert bundled license'}
        self.model = self.base / 'model.gguf'
        self.model.write_bytes(b'GGUF INERT SMALL FIXTURE')
        self.archive = self.base / 'runtime.zip'
        self.licenses = {'runtime-MIT.txt': b'inert MIT fixture notice',
                         'model-Apache.txt': b'inert Apache fixture notice',
                         'openmp.txt': b'inert OpenMP fixture notice'}
        for name, raw in self.licenses.items():
            (self.resources / name).write_bytes(raw)
        self.spec = {'profile': local_ai.PROFILE,
                     'runtime': {},
                     'model': artifact(self.model.read_bytes(), self.model.name,
                                       'https://huggingface.co/fixture/model.gguf'),
                     'runtime_members': {name: artifact(raw) for name, raw in self.members.items()},
                     'licenses': {name: artifact(raw) for name, raw in self.licenses.items()}}
        self.pin_patch = patch.object(local_ai, 'MANIFEST_SHA256', '')
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        self.write_archive()
        self.resources_patch = patch.object(local_ai, 'resources', return_value=self.resources)
        self.resources_patch.start()
        self.addCleanup(self.resources_patch.stop)
        # Accidental external networking fails the test before opening a connection.
        self.network_guard = patch('socket.create_connection', side_effect=AssertionError('Unexpected network'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def write_manifest(self):
        target = self.resources / 'manifest.json'
        target.write_text(json.dumps(self.spec), encoding='utf-8')
        local_ai.MANIFEST_SHA256 = hashlib.sha256(target.read_bytes()).hexdigest()

    def write_archive(self, entries=None):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in (self.members.items() if entries is None else entries):
                    archive.writestr(name, raw)
        self.spec['runtime'] = artifact(self.archive.read_bytes(), self.archive.name,
                                       'https://github.com/fixture/runtime.zip')
        self.write_manifest()

    def install(self):
        return local_ai.install(self.paths, self.archive, self.model)

    def assert_error(self, code, callback, *args, **kwargs):
        with self.assertRaises(local_ai.LocalAIError) as caught:
            callback(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_cache_uses_bootstrap_and_is_outside_workspace_state(self):
        expected = self.paths.bootstrap / 'cache' / 'local-ai' / local_ai.PROFILE
        self.assertEqual(local_ai.cache_root(self.paths), expected)
        self.paths.bootstrap = None
        self.assertEqual(local_ai.cache_root(self.paths), self.paths.root / 'cache' / 'local-ai' / local_ai.PROFILE)

    def test_manifest_wrong_profile_fails_closed(self):
        self.spec['profile'] = 'unknown-profile'
        self.write_manifest()
        self.assert_error('artifact', local_ai.manifest)

    def test_manifest_tampering_is_rejected_before_using_changed_pins(self):
        target = self.resources / 'manifest.json'
        changed = json.loads(target.read_text())
        changed['runtime']['url'] = 'https://github.com/attacker/runtime.zip'
        target.write_text(json.dumps(changed), encoding='utf-8')
        self.assert_error('artifact', local_ai.manifest)

    def test_install_preserves_every_member_and_license_without_execution(self):
        with patch('subprocess.Popen', side_effect=AssertionError('Do not execute ZIP content')) as popen, \
             patch('os.system', side_effect=AssertionError('Do not execute shell')) as system:
            self.assertEqual(self.install(), {'status': 'installed', 'reused': False})
            exe, model = local_ai.verify_install(self.paths)
            self.assertEqual(exe.name, 'llama-server.exe')
            self.assertEqual(model.read_bytes(), self.model.read_bytes())
            root = local_ai.cache_root(self.paths)
            self.assertEqual({p.name for p in (root / 'runtime').iterdir()}, set(self.members))
            for name, raw in self.members.items():
                self.assertEqual((root / 'runtime' / name).read_bytes(), raw)
            for name, raw in self.licenses.items():
                self.assertEqual((root / 'licenses' / name).read_bytes(), raw)
            popen.assert_not_called()
            system.assert_not_called()
        self.assertFalse(list(root.parent.glob(local_ai.PROFILE + '.partial-*')))

    def test_valid_install_is_reused_without_changes(self):
        self.install()
        root = local_ai.cache_root(self.paths)
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(self.install(), {'status': 'installed', 'reused': True})
        self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_source_model_bad_digest_is_rejected_before_install(self):
        self.model.write_bytes(b'x' * self.spec['model']['bytes'])
        self.assert_error('artifact', self.install)
        self.assertFalse(local_ai.cache_root(self.paths).exists())

    def test_source_archive_bad_digest_is_rejected_before_extraction(self):
        self.archive.write_bytes(b'x' * self.spec['runtime']['bytes'])
        self.assert_error('artifact', self.install)
        self.assertFalse(local_ai.cache_root(self.paths).exists())

    def test_wrong_size_and_missing_file_are_rejected(self):
        self.model.write_bytes(b'short')
        self.assert_error('artifact', local_ai.verify_file, self.model, self.spec['model'])
        self.model.unlink()
        self.assert_error('missing', local_ai.verify_file, self.model, self.spec['model'])

    def test_expected_member_bad_digest_fails_and_cleans_stage(self):
        self.spec['runtime_members']['llama-server-impl.dll']['sha256'] = '0' * 64
        self.write_manifest()
        self.assert_error('artifact', self.install)
        root = local_ai.cache_root(self.paths)
        self.assertFalse(root.exists())
        self.assertFalse(list(root.parent.glob(local_ai.PROFILE + '.partial-*')))

    def test_unexpected_or_missing_archive_member_is_rejected(self):
        cases = [list(self.members.items()) + [('execute-me.cmd', b'bad')],
                 list(self.members.items())[:-1]]
        for entries in cases:
            with self.subTest(names=[name for name, _ in entries]):
                self.write_archive(entries)
                self.assert_error('archive', self.install)
                self.assertFalse(local_ai.cache_root(self.paths).exists())

    def test_archive_traversal_absolute_backslash_and_drive_names_are_rejected(self):
        for name in ('../escape.exe', '/absolute.exe', 'nested/file.dll', r'..\escape.exe',
                     'C:payload.exe', '.', '..', 'directory/'):
            with self.subTest(name=name):
                self.spec['runtime_members'] = {name: artifact(b'x')}
                self.write_archive([(name, b'x')])
                self.assert_error('archive', self.install)
        self.assertFalse((self.base / 'escape.exe').exists())

    def test_duplicate_case_alias_and_symlink_zip_entries_are_rejected(self):
        cases = [[('same.dll', b'x'), ('same.dll', b'x')],
                 [('same.dll', b'x'), ('SAME.dll', b'x')]]
        for entries in cases:
            with self.subTest(entries=entries):
                self.spec['runtime_members'] = {name: artifact(raw) for name, raw in entries}
                self.write_archive(entries)
                self.assert_error('archive', self.install)
        info = zipfile.ZipInfo('llama-server.exe')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.spec['runtime_members'] = {info.filename: artifact(b'target')}
        self.write_archive([(info, b'target')])
        self.assert_error('archive', self.install)

    def test_encrypted_and_nul_member_metadata_are_rejected(self):
        for encrypted, original in ((True, 'safe.dll'), (False, 'safe.dll\x00payload')):
            info = zipfile.ZipInfo('safe.dll')
            info.file_size = 1
            info.flag_bits = int(encrypted)
            info.orig_filename = original
            archive = Mock()
            archive.infolist.return_value = [info]
            with self.subTest(encrypted=encrypted, original=repr(original)):
                self.assert_error('archive', local_ai._members, archive, {'safe.dll': artifact(b'x')})

    def test_corrupt_existing_install_is_not_replaced(self):
        self.install()
        exe = local_ai.cache_root(self.paths) / 'runtime' / 'llama-server.exe'
        corrupt = b'x' * exe.stat().st_size
        exe.write_bytes(corrupt)
        self.assert_error('artifact', self.install)
        self.assertEqual(exe.read_bytes(), corrupt)

    def test_extra_installed_runtime_file_is_rejected_and_preserved(self):
        self.install()
        extra = local_ai.cache_root(self.paths) / 'runtime' / 'untrusted.dll'
        extra.write_bytes(b'never load')
        self.assert_error('archive', local_ai.verify_install, self.paths)
        self.assertEqual(extra.read_bytes(), b'never load')

    def test_installed_license_digest_is_required(self):
        self.install()
        name = next(iter(self.licenses))
        target = local_ai.cache_root(self.paths) / 'licenses' / name
        target.write_bytes(b'x' * len(self.licenses[name]))
        self.assert_error('artifact', local_ai.verify_install, self.paths)

    def test_installed_license_exact_inventory_is_required(self):
        self.install()
        notices = local_ai.cache_root(self.paths) / 'licenses'
        name, raw = next(iter(self.licenses.items()))
        (notices / name).unlink()
        with self.assertRaises(local_ai.LocalAIError):
            local_ai.verify_install(self.paths)
        (notices / name).write_bytes(raw)
        (notices / 'extra-license.txt').write_bytes(b'not pinned')
        with self.assertRaises(local_ai.LocalAIError):
            local_ai.verify_install(self.paths)

    def test_symlink_source_and_symlink_ancestor_are_rejected(self):
        link = self.base / 'linked.gguf'
        parent = self.base / 'linked-resources'
        try:
            link.symlink_to(self.model)
            parent.symlink_to(self.resources, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Symlinks unavailable: ' + str(exc))
        self.assert_error('unsafe_path', local_ai.verify_file, link, self.spec['model'])
        self.assert_error('unsafe_path', local_ai.safe_path, parent / 'future-file')

    def test_hardlinked_model_and_runtime_member_are_rejected(self):
        link = self.base / 'hardlink.gguf'
        try:
            os.link(self.model, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Hardlinks unavailable: ' + str(exc))
        self.assert_error('unsafe_path', self.install)
        link.unlink()
        self.install()
        exe = local_ai.cache_root(self.paths) / 'runtime' / 'llama-server.exe'
        os.link(exe, self.base / 'hardlink.exe')
        self.assert_error('unsafe_path', local_ai.verify_install, self.paths)

    def test_relative_unc_directory_and_reparse_paths_are_rejected(self):
        for name in ('relative.gguf', r'\\server\share\model.gguf', '//server/share/model.gguf'):
            with self.subTest(name=name):
                self.assert_error('unsafe_path', local_ai.safe_path, name)
        self.assert_error('unsafe_path', local_ai.safe_path, self.resources, file=True)
        original_lstat = Path.lstat
        target = self.model
        def reparse_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if path == target:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse_lstat):
            self.assert_error('unsafe_path', local_ai.safe_path, target)

    def test_setup_requires_literal_true_consent_before_any_download_or_install(self):
        with patch.object(local_ai, 'install') as install, patch.object(local_ai, 'download') as download:
            for consent in (None, False, 0, 1, 'true', [], {}):
                with self.subTest(consent=consent):
                    self.assert_error('consent', local_ai.setup, self.paths,
                                      {'action': 'download', 'consent': consent})
            self.assert_error('consent', local_ai.setup, self.paths, {'action': 'download'})
            install.assert_not_called()
            download.assert_not_called()

    def test_setup_rejects_unknown_action_missing_fields_and_extra_fields(self):
        payloads = [{'consent': True}, {'action': 'execute', 'consent': True},
                    {'action': 'install', 'consent': True},
                    {'action': 'download', 'consent': True, 'url': 'https://example.invalid'},
                    {'action': 'install', 'consent': True, 'runtime_archive': str(self.archive),
                     'model_file': str(self.model), 'command': 'execute'}]
        with patch.object(local_ai, 'install') as install, patch.object(local_ai, 'download') as download:
            for payload in payloads:
                with self.subTest(payload=payload):
                    self.assert_error('request', local_ai.setup, self.paths, payload)
            install.assert_not_called()
            download.assert_not_called()

    def test_setup_rejects_non_object_payload_without_side_effects(self):
        with patch.object(local_ai, 'install') as install, patch.object(local_ai, 'download') as download:
            for payload in (None, [], 'download', 1):
                with self.subTest(payload=payload):
                    self.assert_error('request', local_ai.setup, self.paths, payload)
            install.assert_not_called()
            download.assert_not_called()

    def test_setup_manual_install_accepts_only_pinned_artifacts(self):
        result = local_ai.setup(self.paths, {'action': 'install', 'consent': True,
                                             'runtime_archive': str(self.archive), 'model_file': str(self.model)})
        self.assertEqual(result['status'], 'installed')
        local_ai.verify_install(self.paths)

    def test_explicit_download_installs_then_removes_only_own_verified_duplicates(self):
        originals = {self.spec['runtime']['filename']: self.archive.read_bytes(),
                     self.spec['model']['filename']: self.model.read_bytes()}
        def inert_download(pin, destination, progress=None):
            destination.write_bytes(originals[pin['filename']])
            if progress:
                progress(pin['bytes'], pin['bytes'])
            return destination
        events = []
        with patch.object(local_ai, 'download', side_effect=inert_download) as downloader:
            result = local_ai.setup(self.paths, {'action': 'download', 'consent': True},
                                    lambda event, **payload: events.append((event, payload)))
            self.assertEqual(result, {'status': 'installed', 'reused': False})
            self.assertEqual(downloader.call_count, 2)
            root = local_ai.cache_root(self.paths)
            self.assertEqual(list((root.parent / 'downloads').iterdir()), [])
            self.assertEqual(self.archive.read_bytes(), originals[self.spec['runtime']['filename']])
            self.assertEqual(self.model.read_bytes(), originals[self.spec['model']['filename']])
            local_ai.verify_install(self.paths)
            self.assertEqual(local_ai.setup(self.paths, {'action': 'download', 'consent': True}),
                             {'status': 'installed', 'reused': True})
            self.assertEqual(downloader.call_count, 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event == 'progress' and payload['progress'] == 100 for event, payload in events))

    def test_fixed_endpoint_rejects_remote_aliases_credentials_paths_and_queries(self):
        self.assertEqual(local_ai.validate_local_endpoint(local_ai.ENDPOINT), local_ai.ENDPOINT)
        endpoints = ['http://localhost:18765/v1/chat/completions', 'http://127.0.0.1:1/v1/chat/completions',
                     'https://example.invalid/v1/chat/completions', local_ai.ENDPOINT + '?key=x',
                     local_ai.ENDPOINT + '#fragment', 'http://u:p@127.0.0.1:18765/v1/chat/completions',
                     'http://127.0.0.1:18765/health', None]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assert_error('request', local_ai.validate_local_endpoint, endpoint)

    def test_download_urls_and_redirects_are_https_publisher_only(self):
        invalid = ['http://github.com/a', 'file:///tmp/file', 'https://github.com.evil.invalid/a',
                   'https://user:secret@github.com/a', 'https://github.com:444/a',
                   'https://github.com/a#fragment', 'https://127.0.0.1/a']
        request = urllib.request.Request('https://github.com/fixture/runtime.zip')
        handler = local_ai._PinnedRedirect()
        for url in invalid:
            with self.subTest(url=url):
                self.assert_error('network', local_ai._download_url, url)
                self.assert_error('network', handler.redirect_request, request, None, 302, 'Found', {}, url)
        target = 'https://release-assets.githubusercontent.com/inert-fixture?signature=fixture'
        self.assertEqual(handler.redirect_request(request, None, 302, 'Found', {}, target).full_url, target)

    def fake_download(self, data, *, spec=None, headers=None, status=200, url=None):
        spec = artifact(data, 'small.bin', 'https://github.com/fixture/small.bin') if spec is None else spec
        destination = self.base / 'downloaded.bin'
        response = DownloadResponse(data, url=url or spec['url'], status=status, headers=headers)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener) as build:
            result = local_ai.download(spec, destination)
        return result, opener, build

    def test_download_checks_bytes_hash_and_disables_environment_proxies(self):
        raw = b'tiny pinned artifact'
        result, opener, build = self.fake_download(raw, headers={'Content-Length': str(len(raw))})
        self.assertEqual(result.read_bytes(), raw)
        self.assertFalse(result.with_suffix(result.suffix + '.partial').exists())
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler) and h.proxies == {} for h in handlers))
        self.assertTrue(any(isinstance(h, local_ai._PinnedRedirect) for h in handlers))
        self.assertEqual(opener.open.call_args.args[0].full_url, 'https://github.com/fixture/small.bin')

    def test_download_does_not_accept_bad_hash_short_or_oversized_response(self):
        pin = artifact(b'good', 'small.bin', 'https://github.com/fixture/small.bin')
        for raw in (b'evil', b'bad', b'oversized'):
            with self.subTest(raw=raw):
                self.assert_error('artifact', self.fake_download, raw, spec=pin)
                self.assertFalse((self.base / 'downloaded.bin').exists())

    def test_download_rejects_encoding_status_size_header_and_final_url(self):
        cases = [({'headers': {'Content-Encoding': 'gzip'}}, 'network'),
                 ({'status': 206}, 'network'), ({'headers': {'Content-Length': '999'}}, 'artifact'),
                 ({'url': 'https://example.invalid/artifact'}, 'network')]
        for options, code in cases:
            with self.subTest(options=options):
                self.assert_error(code, self.fake_download, b'good', **options)
                self.assertFalse((self.base / 'downloaded.bin').exists())

    def test_download_network_error_is_sanitized(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError('secret-query-token-must-not-leak')
        pin = artifact(b'good', 'small.bin', 'https://github.com/fixture/small.bin')
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(local_ai.LocalAIError) as caught:
                local_ai.download(pin, self.base / 'downloaded.bin')
        self.assertEqual(caught.exception.code, 'network')
        self.assertNotIn('secret-query-token', str(caught.exception))

    def test_download_existing_file_must_still_match_pin_and_never_connects(self):
        path = self.base / 'existing.bin'
        path.write_bytes(b'good')
        pin = artifact(b'good', path.name, 'https://github.com/fixture/existing.bin')
        with patch.object(local_ai.urllib.request, 'build_opener') as build:
            self.assertEqual(local_ai.download(pin, path), path)
            path.write_bytes(b'evil')
            self.assert_error('artifact', local_ai.download, pin, path)
            build.assert_not_called()

    def test_download_uses_bounded_read1_and_never_blocking_read(self):
        pin = artifact(b'good', 'small.bin', 'https://github.com/fixture/small.bin')
        class OneReadResponse(DownloadResponse):
            sizes = []
            def read(self, *args):
                raise AssertionError('Use read1 so trickled traffic cannot hold a full-buffer read')
            def read1(self, size=-1):
                self.sizes.append(size)
                return super().read1(size)
        response = OneReadResponse(b'good', url=pin['url'])
        opener = Mock()
        opener.open.return_value = response
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener):
            result = local_ai.download(pin, self.base / 'downloaded.bin')
        self.assertEqual(result.read_bytes(), b'good')
        self.assertTrue(response.sizes)
        self.assertTrue(all(0 < size <= 65536 for size in response.sizes))

    def test_download_stops_trickled_body_at_overall_deadline(self):
        pin = artifact(b'good', 'small.bin', 'https://github.com/fixture/small.bin')
        clock = [0.0]
        class TrickleResponse(DownloadResponse):
            calls = 0
            def read(self, *args):
                raise AssertionError('Blocking read is forbidden')
            def read1(self, size=-1):
                self.calls += 1
                clock[0] = 901.0
                return super().read1(1)
        response = TrickleResponse(b'good', url=pin['url'])
        opener = Mock()
        opener.open.return_value = response
        destination = self.base / 'downloaded.bin'
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener), \
             patch.object(local_ai.time, 'monotonic', side_effect=lambda: clock[0]):
            self.assert_error('network', local_ai.download, pin, destination)
        self.assertEqual(response.calls, 1)
        self.assertFalse(destination.exists())

    def test_download_refuses_linked_partial_without_touching_target(self):
        destination = self.base / 'downloaded.bin'
        partial = destination.with_suffix(destination.suffix + '.partial')
        target = self.base / 'protected.bin'
        target.write_bytes(b'protected existing bytes')
        try:
            partial.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Symlinks unavailable: ' + str(exc))
        pin = artifact(b'good', 'small.bin', 'https://github.com/fixture/small.bin')
        with patch.object(local_ai.urllib.request, 'build_opener') as build:
            self.assert_error('unsafe_path', local_ai.download, pin, destination)
            build.assert_not_called()
        self.assertEqual(target.read_bytes(), b'protected existing bytes')

    def test_failed_probe_and_new_provider_share_persistent_budget(self):
        controls = self.base / 'controls'
        seen = []
        def transport(endpoint, request, timeout):
            seen.append((endpoint, copy.deepcopy(request), timeout))
            if len(seen) == 1:
                raise ValidationError('inert simulated transport failure')
            return response_for(VALID_CANDIDATE)
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), \
             patch.object(local_ai, 'health', return_value=True), patch.object(local_ai, 'MAX_CALLS', 2), \
             patch.object(local_ai, 'verify_owner'):
            self.assertEqual(local_ai.usage(controls)['calls'], 0)
            self.assert_error('probe', local_ai.probe, controls, OWNER)
            self.assertEqual(local_ai.usage(controls)['calls'], 1)
            # Recreate the provider and reopen its on-disk ledger, as after restart.
            restarted = local_ai.provider(controls, OWNER)
            candidate = restarted.generate({'family': 'trend', 'task': 'inert_campaign_fixture'})
            self.assertEqual(candidate, VALID_CANDIDATE)
            self.assertEqual(local_ai.usage(controls)['calls'], 2)
            self.assert_error('probe', local_ai.probe, controls, OWNER)
            self.assertEqual(local_ai.usage(controls)['calls'], 2)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(endpoint == local_ai.ENDPOINT for endpoint, _, _ in seen))
        with sqlite3.connect(controls / 'local-ai-v1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT status FROM calls ORDER BY sequence').fetchall(),
                             [('failed_or_interrupted',), ('transport_returned_not_verified',)])

    def test_probe_request_contains_no_market_data_and_does_not_claim_validation(self):
        seen = []
        def transport(endpoint, request, timeout):
            seen.append(copy.deepcopy(request))
            return response_for(VALID_CANDIDATE)
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), \
             patch.object(local_ai, 'health', return_value=True), patch.object(local_ai, 'verify_owner'):
            result = local_ai.probe(self.base / 'controls', OWNER)
        self.assertEqual(result['status'], 'schema_probe_pass')
        self.assertEqual(result['real_model_status'], 'not_verified')
        self.assertEqual(result['research_evaluations'], 0)
        self.assertEqual(result['usage']['calls'], 1)
        self.assertEqual(len(seen), 1)
        request = seen[0]
        self.assertEqual(request['model'], local_ai.MODEL)
        self.assertEqual(request['response_format']['type'], 'json_schema')
        context = json.loads(request['messages'][-1]['content'])
        self.assertEqual(context['training'], {'bar_count': 240})
        self.assertEqual(context['task'], 'technical_schema_probe')
        self.assertEqual(set(context), {'family', 'task', 'training', 'instruction', 'output_contract'})
        self.assertNotIn('bars', context)
        self.assertNotIn('dataset', context)

    def test_bad_schema_probe_consumes_budget_without_fixture_fallback(self):
        controls = self.base / 'controls'
        transport = Mock(return_value=response_for({'not': 'a strategy'}))
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), \
             patch.object(local_ai, 'health', return_value=True), patch.object(local_ai, 'verify_owner'):
            self.assert_error('probe', local_ai.probe, controls, OWNER)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(local_ai.usage(controls)['calls'], 1)

    def test_unhealthy_probe_does_not_create_or_consume_budget(self):
        controls = self.base / 'controls'
        with patch.object(local_ai, 'health', return_value=False), \
             patch.object(local_ai, 'HTTPTransport') as transport, patch.object(local_ai, 'verify_owner'):
            self.assert_error('loading', local_ai.probe, controls, OWNER)
            transport.assert_not_called()
        self.assertFalse((controls / 'local-ai-v1.sqlite3').exists())


class LocalAIOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controls = Path(self.temp.name).resolve() / 'controls'
        self.listener = (2, '127.0.0.1', local_ai.PORT, '0.0.0.0', 0, OWNER['pid'])

    def assert_ownership_error(self, callback, *args, **kwargs):
        with self.assertRaises(local_ai.LocalAIError) as caught:
            callback(*args, **kwargs)
        self.assertEqual(caught.exception.code, 'ownership')

    def test_listener_matches_pid_address_port_and_creation_time(self):
        with patch.object(local_ai, 'process_creation_time', return_value=OWNER['created']) as creation, \
             patch.object(local_ai, '_tcp_owners', return_value=[self.listener]):
            local_ai.verify_owner(**OWNER)
            self.assertEqual(creation.call_count, 2)
        invalid_rows = [(), [(2, '0.0.0.0', local_ai.PORT, '0.0.0.0', 0, OWNER['pid'])],
                        [(2, '127.0.0.1', local_ai.PORT + 1, '0.0.0.0', 0, OWNER['pid'])],
                        [(2, '127.0.0.1', local_ai.PORT, '0.0.0.0', 0, 999)],
                        [(5, '127.0.0.1', local_ai.PORT, '0.0.0.0', 0, OWNER['pid'])]]
        for rows in invalid_rows:
            with self.subTest(rows=rows), \
                 patch.object(local_ai, 'process_creation_time', return_value=OWNER['created']), \
                 patch.object(local_ai, '_tcp_owners', return_value=rows):
                self.assert_ownership_error(local_ai.verify_owner, **OWNER)

    def test_recycled_pid_before_or_during_table_snapshot_is_rejected(self):
        for creation_times in ([457], [456, 457]):
            with self.subTest(creation_times=creation_times), \
                 patch.object(local_ai, 'process_creation_time', side_effect=creation_times), \
                 patch.object(local_ai, '_tcp_owners', return_value=[self.listener]):
                self.assert_ownership_error(local_ai.verify_owner, **OWNER)

    def test_connected_peer_requires_exact_reversed_established_tuple(self):
        sock = Mock()
        sock.getpeername.return_value = ('127.0.0.1', local_ai.PORT)
        sock.getsockname.return_value = ('127.0.0.1', 53001)
        server_row = (5, '127.0.0.1', local_ai.PORT, '127.0.0.1', 53001, OWNER['pid'])
        with patch.object(local_ai, 'process_creation_time', return_value=456), \
             patch.object(local_ai, '_tcp_owners', return_value=[server_row]):
            local_ai.verify_owner(**OWNER, sock=sock)
        wrong_rows = [[self.listener],
                      [(5, '127.0.0.1', 53001, '127.0.0.1', local_ai.PORT, OWNER['pid'])],
                      [(5, '127.0.0.1', local_ai.PORT, '127.0.0.1', 53002, OWNER['pid'])],
                      [(5, '127.0.0.1', local_ai.PORT, '127.0.0.1', 53001, 999)],
                      [(8, '127.0.0.1', local_ai.PORT, '127.0.0.1', 53001, OWNER['pid'])]]
        for rows in wrong_rows:
            with self.subTest(rows=rows), \
                 patch.object(local_ai, 'process_creation_time', return_value=456), \
                 patch.object(local_ai, '_tcp_owners', return_value=rows):
                self.assert_ownership_error(local_ai.verify_owner, **OWNER, sock=sock)

    def test_foreign_socket_endpoint_is_rejected_even_with_matching_table(self):
        sock = Mock()
        sock.getsockname.return_value = ('127.0.0.1', 53001)
        for peer in (('127.0.0.2', local_ai.PORT), ('127.0.0.1', local_ai.PORT + 1)):
            sock.getpeername.return_value = peer
            with self.subTest(peer=peer), \
                 patch.object(local_ai, 'process_creation_time', return_value=456), \
                 patch.object(local_ai, '_tcp_owners') as table:
                self.assert_ownership_error(local_ai.verify_owner, **OWNER, sock=sock)
                table.assert_not_called()

    def test_listener_mismatch_prevents_budget_creation_and_transport(self):
        cases = [(457, [self.listener]),
                 (456, [(2, '127.0.0.1', local_ai.PORT, '0.0.0.0', 0, 999)])]
        for created, rows in cases:
            with self.subTest(created=created, rows=rows), \
                 patch.object(local_ai, 'process_creation_time', return_value=created), \
                 patch.object(local_ai, '_tcp_owners', return_value=rows), \
                 patch.object(local_ai, 'HTTPTransport') as transport, patch.object(local_ai, 'health') as health:
                provider = local_ai.provider(self.controls, OWNER)
                self.assert_ownership_error(provider.generate, {'family': 'trend'})
                self.assert_ownership_error(local_ai.probe, self.controls, OWNER)
                self.assertFalse((self.controls / 'local-ai-v1.sqlite3').exists())
                transport.return_value.assert_not_called()
                health.assert_not_called()

    def test_listener_mismatch_does_not_change_existing_budget(self):
        transport = Mock(return_value=response_for(VALID_CANDIDATE))
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), patch.object(local_ai, 'verify_owner'):
            provider = local_ai.provider(self.controls, OWNER)
            provider.generate({'family': 'trend'})
        ledger = self.controls / 'local-ai-v1.sqlite3'
        original = ledger.read_bytes()
        with patch.object(local_ai, 'verify_owner', side_effect=local_ai.LocalAIError('ownership')):
            self.assert_ownership_error(provider.generate, {'family': 'trend'})
        self.assertEqual(ledger.read_bytes(), original)
        self.assertEqual(local_ai.usage(self.controls)['calls'], 1)
        self.assertEqual(transport.call_count, 1)

    def test_owner_changes_do_not_change_campaign_identity_or_reset_budget(self):
        other = {'pid': 789, 'created': 999999}
        transport = Mock(return_value=response_for(VALID_CANDIDATE))
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), patch.object(local_ai, 'verify_owner'):
            first = local_ai.provider(self.controls, OWNER)
            second = local_ai.provider(self.controls, other)
            self.assertEqual(_provider_identity(first), _provider_identity(second))
            encoded_identity = json.dumps(_provider_identity(first))
            self.assertNotIn('"pid"', encoded_identity)
            self.assertNotIn('"created"', encoded_identity)
            first.generate({'family': 'trend'})
            with sqlite3.connect(first.path) as db:
                first_binding = db.execute('SELECT binding FROM budget').fetchone()[0]
            second.generate({'family': 'trend'})
            with sqlite3.connect(second.path) as db:
                self.assertEqual(db.execute('SELECT binding,calls FROM budget').fetchone(), (first_binding, 2))
        self.assertEqual(transport.call_count, 2)

    def test_provider_attaches_owned_peer_verifier_without_networking(self):
        with patch('socket.create_connection', side_effect=AssertionError('No network during construction')):
            provider = local_ai.provider(self.controls, OWNER)
        self.assertIsInstance(provider.transport.connection_verifier, local_ai.OwnedPeerVerifier)
        self.assertEqual(provider.transport.connection_verifier, local_ai.OwnedPeerVerifier(**OWNER))
        self.assertFalse((self.controls / 'local-ai-v1.sqlite3').exists())
        sock = Mock()
        with patch.object(local_ai, 'verify_owner') as verify:
            provider.transport.connection_verifier(sock)
            verify.assert_called_once_with(OWNER['pid'], OWNER['created'], sock)

    def test_missing_or_extra_owner_identity_fields_fail_closed(self):
        for owner in (None, {}, {'pid': 123}, {'created': 456}, {**OWNER, 'host': 'foreign'}, []):
            with self.subTest(owner=owner):
                self.assert_ownership_error(local_ai.provider, self.controls, owner)
                self.assert_ownership_error(local_ai.probe, self.controls, owner)
        self.assertFalse(self.controls.exists())

    def test_tcp_table_decodes_windows_dword_rows_and_32_bit_bool(self):
        addr = int.from_bytes(socket.inet_aton('127.0.0.1'), 'little')
        rows = [(2, addr, socket.htons(local_ai.PORT) | 0xABCD0000, 0, 0, 123),
                (5, addr, socket.htons(local_ai.PORT), addr, socket.htons(53001), 123)]
        raw = struct.pack('<I', len(rows)) + b''.join(struct.pack('<6I', *row) for row in rows)
        def table(buffer, size, ordered, family, table_class, reserved):
            self.assertEqual((family, table_class, reserved), (socket.AF_INET, 5, 0))
            size._obj.value = len(raw)
            if buffer is None:
                return 122
            ctypes.memmove(buffer, raw, len(raw))
            return 0
        api = SimpleNamespace(GetExtendedTcpTable=Mock(side_effect=table))
        with patch.object(local_ai.sys, 'platform', 'win32'), \
             patch.object(local_ai.ctypes, 'WinDLL', return_value=api, create=True):
            result = local_ai._tcp_owners()
        self.assertEqual(result, [self.listener,
                                  (5, '127.0.0.1', local_ai.PORT, '127.0.0.1', 53001, 123)])
        self.assertEqual(ctypes.sizeof(api.GetExtendedTcpTable.argtypes[2]), 4,
                         'Win32 BOOL must be 32 bits, not ctypes.c_bool')

    def test_tcp_table_rejects_truncated_or_oversized_table(self):
        for raw, size_value in ((struct.pack('<I', 2), 4), (b'', 1024 * 1024 + 1)):
            def table(buffer, size, *args):
                size._obj.value = size_value
                if buffer is None:
                    return 122
                ctypes.memmove(buffer, raw, len(raw))
                return 0
            api = SimpleNamespace(GetExtendedTcpTable=Mock(side_effect=table))
            with self.subTest(size=size_value), patch.object(local_ai.sys, 'platform', 'win32'), \
                 patch.object(local_ai.ctypes, 'WinDLL', return_value=api, create=True):
                self.assert_ownership_error(local_ai._tcp_owners)

    def test_process_creation_filetime_and_full_width_handle_are_preserved(self):
        handle = (1 << 40) + 17
        def times(actual_handle, created, exited, kernel, user):
            self.assertEqual(actual_handle, handle)
            created._obj.low = 0x89ABCDEF
            created._obj.high = 0x01234567
            return 1
        api = SimpleNamespace(OpenProcess=Mock(return_value=handle),
                              GetProcessTimes=Mock(side_effect=times), CloseHandle=Mock())
        with patch.object(local_ai.sys, 'platform', 'win32'), \
             patch.object(local_ai.ctypes, 'WinDLL', return_value=api, create=True):
            self.assertEqual(local_ai.process_creation_time(123), 0x0123456789ABCDEF)
        self.assertEqual(ctypes.sizeof(api.OpenProcess.restype), ctypes.sizeof(ctypes.c_void_p))
        api.OpenProcess.assert_called_once_with(0x1000, False, 123)
        api.CloseHandle.assert_called_once_with(handle)

    def test_process_time_failure_closes_handle_and_invalid_pid_does_not_open(self):
        api = SimpleNamespace(OpenProcess=Mock(return_value=12345),
                              GetProcessTimes=Mock(return_value=0), CloseHandle=Mock())
        with patch.object(local_ai.sys, 'platform', 'win32'), \
             patch.object(local_ai.ctypes, 'WinDLL', return_value=api, create=True) as dll:
            self.assert_ownership_error(local_ai.process_creation_time, 123)
            api.CloseHandle.assert_called_once_with(12345)
            dll.reset_mock()
            for pid in (True, 0, -1, '123', None):
                with self.subTest(pid=pid):
                    self.assert_ownership_error(local_ai.process_creation_time, pid)
            dll.assert_not_called()


class OwnedTransportLoopbackTests(unittest.TestCase):
    """Actual HTTP on an ephemeral loopback port, never an external service."""
    def setUp(self):
        self.seen = []
        self.request_received = threading.Event()
        seen = self.seen
        event = self.request_received
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                seen.append(body)
                event.set()
                raw = json.dumps({'fixture': 'inert-loopback'}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1/chat/completions'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_owned_peer_verifier_runs_before_any_request_body(self):
        observations = []
        def verify(pid, created, sock=None):
            self.assertIsNotNone(sock)
            self.assertEqual((pid, created), (123, 456))
            self.assertEqual(sock.getpeername(), ('127.0.0.1', self.server.server_port))
            observations.append(len(self.seen))
            self.assertFalse(self.request_received.is_set())
        transport = HTTPTransport(allow_network=True, connection_verifier=local_ai.OwnedPeerVerifier(**OWNER))
        with patch.object(local_ai, 'verify_owner', side_effect=verify):
            result = transport(self.endpoint, {'fixture_market_data': [1, 2, 3]}, 2)
        self.assertEqual(observations, [0])
        self.assertEqual(result, {'fixture': 'inert-loopback'})
        self.assertEqual(len(self.seen), 1)

    def test_verifier_rejection_sends_no_market_body_or_http_request(self):
        transport = HTTPTransport(allow_network=True, connection_verifier=local_ai.OwnedPeerVerifier(**OWNER))
        with patch.object(local_ai, 'verify_owner', side_effect=local_ai.LocalAIError('ownership')) as verify:
            with self.assertRaises(local_ai.LocalAIError) as caught:
                transport(self.endpoint, {'fixture_market_data': ['must-not-transmit']}, 2)
        self.assertEqual(caught.exception.code, 'ownership')
        self.assertEqual(verify.call_count, 1)
        self.assertFalse(self.request_received.wait(0.05))
        self.assertEqual(self.seen, [])


class PackagedLocalAIManifestTests(unittest.TestCase):
    def test_real_manifest_is_small_pinned_inventory_and_licenses_only(self):
        spec = local_ai.manifest()
        self.assertEqual(spec['profile'], 'llamacpp-b11429-qwen15-v1')
        self.assertEqual(spec['runtime']['bytes'], 19398918)
        self.assertEqual(spec['runtime']['sha256'], '1283323272b04cd07905816a597a0da810918102de958f4ff6f7bbaa70ed2efe')
        self.assertEqual(spec['model']['bytes'], 1117320736)
        self.assertEqual(spec['model']['sha256'], '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e')
        self.assertEqual(len(spec['runtime_members']), 51)
        self.assertEqual(sum(item['bytes'] for item in spec['runtime_members'].values()), 49497373)
        self.assertEqual(len(spec['licenses']), 3)
        for name, item in spec['licenses'].items():
            local_ai.verify_file(local_ai.resources() / name, item)
        self.assertFalse((local_ai.resources() / spec['runtime']['filename']).exists())
        self.assertFalse((local_ai.resources() / spec['model']['filename']).exists())


if __name__ == '__main__':
    unittest.main()
