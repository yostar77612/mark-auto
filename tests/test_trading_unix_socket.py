"""Socket isolation checks; actual POSIX transport branches execute on Unix CI."""

from multiprocessing.connection import Listener
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime import unix_socket
from quantlab.trading.runtime.server import serve


WORKSPACE = Path(__file__).resolve().parents[2]


class UnixSocketIsolationTests(unittest.TestCase):
    def setUp(self):
        (WORKSPACE / 't').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='v2-socket-', dir=WORKSPACE / 't')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_root_binding_is_canonical_and_independent_of_root_path_length(self):
        first = unix_socket._prefix(self.root / ('a' * 180), 12345)
        second = unix_socket._prefix(self.root / ('b' * 180), 12345)
        self.assertNotEqual(first, second)
        self.assertEqual(first, unix_socket._prefix(self.root / 'unused' / '..' / ('a' * 180), 12345))
        self.assertLessEqual(len(first), 50)

    def test_owner_permissions_and_file_type_fail_closed(self):
        def record(kind, mode, uid=42):
            return os.stat_result((kind | mode, 7, 3, 1, uid, 42, 0, 0, 0, 0))

        for directory, kind, mode in ((True, stat.S_IFDIR, 0o700), (False, stat.S_IFSOCK, 0o600)):
            with patch.object(Path, 'lstat', return_value=record(kind, mode)):
                self.assertEqual(unix_socket._checked(self.root, 42, mode, directory=directory).st_ino, 7)
            for value in (record(kind, 0o777), record(kind, mode, uid=43), record(stat.S_IFLNK, mode), record(stat.S_IFREG, mode)):
                with self.subTest(directory=directory, mode=value.st_mode, uid=value.st_uid):
                    with patch.object(Path, 'lstat', return_value=value), self.assertRaises(DomainError):
                        unix_socket._checked(self.root, 42, mode, directory=directory)
        for mode, uid, safe in ((0o1777, 0, True), (0o700, 42, True), (0o770, 0, False), (0o777, 0, False), (0o1777, 43, False)):
            with self.subTest(base_mode=mode, base_owner=uid):
                with patch.object(Path, 'resolve', return_value=self.root), patch.object(Path, 'stat', return_value=record(stat.S_IFDIR, mode, uid)):
                    if safe:
                        self.assertEqual(unix_socket._base(42), self.root)
                    else:
                        with self.assertRaises(DomainError):
                            unix_socket._base(42)

    def test_cleanup_never_recursively_removes_an_unexpected_file(self):
        directory = self.root / 'private'
        directory.mkdir()
        unexpected = directory / 'unrelated.txt'
        unexpected.write_text('preserve', encoding='utf-8')
        endpoint = unix_socket.UnixEndpoint(directory, str(directory / 'control.sock'), 42, 3, 7)
        with patch.object(unix_socket.UnixEndpoint, '_owned_directory'), self.assertRaises(OSError):
            endpoint.close()
        self.assertEqual(unexpected.read_text(encoding='utf-8'), 'preserve')

    def test_replaced_directory_cannot_be_removed(self):
        endpoint = unix_socket.UnixEndpoint(self.root, str(self.root / 'control.sock'), 42, 3, 7)
        replacement = os.stat_result((stat.S_IFDIR | 0o700, 8, 3, 1, 42, 42, 0, 0, 0, 0))
        with patch.object(unix_socket, '_checked', return_value=replacement), self.assertRaises(DomainError):
            endpoint._owned_directory()
        self.assertTrue(self.root.is_dir())

    def test_failed_listener_start_releases_private_endpoint_and_engine_owner(self):
        root = self.root / 'bind-failure'
        before = set()
        if os.name != 'nt':
            base, prefix = unix_socket._base(os.geteuid()), unix_socket._prefix(root, os.geteuid())
            before = set(base.glob(prefix + '*'))
        with patch('quantlab.trading.runtime.server.Listener', side_effect=OSError('synthetic bind failure')), self.assertRaises(OSError):
            serve(root)
        self.assertFalse((root / 'engine-session-v2.json').exists())
        if os.name != 'nt':
            self.assertEqual(set(base.glob(prefix + '*')), before)
        # A second real initialization must not be fenced by the failed owner.
        with patch('quantlab.trading.runtime.server.Listener', side_effect=OSError('second synthetic bind failure')), self.assertRaises(OSError):
            serve(root)

    def test_legacy_socket_session_remains_readable_without_relaxing_permissions(self):
        if os.name == 'nt':
            # Windows has no legacy AF_UNIX engine layout; its native pipe path
            # is exercised by the real independent-engine integration module.
            self.assertEqual(unix_socket._prefix(self.root, 42), unix_socket._prefix(self.root.resolve(), 42))
            return
        with tempfile.TemporaryDirectory(prefix='ma-legacy-', dir=unix_socket._base(os.geteuid())) as directory:
            root = Path(directory)
            address = str(root / ('engine-' + uuid4().hex + '.sock'))
            with Listener(address, family='AF_UNIX', authkey=None):
                Path(address).chmod(0o600)
                unix_socket.validate_unix_address(root, address)
                Path(address).chmod(0o660)
                with self.assertRaises(DomainError):
                    unix_socket.validate_unix_address(root, address)


if __name__ == '__main__':
    unittest.main()
