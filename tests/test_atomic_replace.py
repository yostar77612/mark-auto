"""Windows rename contention must preserve bytes, atomicity and failure gates."""

import ctypes
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from quantlab import runtime_support as io


def denied(code=5):
    error = PermissionError('synthetic denial')
    error.winerror = code
    return error


class AtomicReplaceTests(unittest.TestCase):
    def test_transient_windows_errors_retry_only_identical_rename(self):
        for code in (5, 32, 33):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                source, target = Path(directory) / 'source', Path(directory) / 'target'
                source.write_bytes(b'new')
                target.write_bytes(b'old')
                real_replace = io.os.replace
                observed = []

                def replace(left, right):
                    observed.append((left, right, source.read_bytes(), target.read_bytes()))
                    if len(observed) == 1:
                        raise denied(code)
                    return real_replace(left, right)

                with patch.object(io.sys, 'platform', 'win32'), patch.object(io.os, 'replace', side_effect=replace), patch.object(io.time, 'sleep') as sleep:
                    io.replace_file(source, target)
                self.assertEqual(observed, [(source, target, b'new', b'old')] * 2)
                self.assertEqual(target.read_bytes(), b'new')
                self.assertFalse(source.exists())
                sleep.assert_called_once_with(0.001)

    def test_persistent_denial_is_bounded_and_preserves_old_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(b'old')
            error = denied()
            with (
                patch.object(io.sys, 'platform', 'win32'),
                patch.object(io.os, 'replace', side_effect=error) as replace,
                patch.object(io.time, 'sleep') as sleep,
            ):
                with self.assertRaises(PermissionError) as caught:
                    io.atomic_write(target, b'new')
            self.assertIs(caught.exception, error)
            self.assertEqual(replace.call_count, 7)
            self.assertEqual(sum(call.args[0] for call in sleep.call_args_list), 0.063)
            self.assertEqual(target.read_bytes(), b'old')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_deadline_expiry_never_starts_another_attempt(self):
        operation = Mock(side_effect=denied())
        with (
            patch.object(io.sys, 'platform', 'win32'),
            patch.object(io.time, 'monotonic', side_effect=[10, 10.0995, 10.101]),
            patch.object(io.time, 'sleep') as sleep,
        ):
            with self.assertRaises(PermissionError):
                io._retry_replace(operation)
        operation.assert_called_once_with()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.0005)

    def test_other_errors_and_other_platforms_are_not_retried(self):
        for platform, error in [('win32', denied(2)), ('win32', OSError('disk full')), ('linux', denied())]:
            with self.subTest(platform=platform, error=error):
                operation = Mock(side_effect=error)
                with patch.object(io.sys, 'platform', platform), patch.object(io.time, 'sleep') as sleep:
                    with self.assertRaises(OSError) as caught:
                        io._retry_replace(operation)
                self.assertIs(caught.exception, error)
                operation.assert_called_once_with()
                sleep.assert_not_called()

    def test_atomic_write_serializes_and_syncs_once_during_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(b'old')
            real_replace, real_sync = io.os.replace, io.os.fsync
            attempts = []

            def replace(source, destination):
                attempts.append((source, destination, Path(source).read_bytes()))
                if len(attempts) < 3:
                    raise denied()
                return real_replace(source, destination)

            with (
                patch.object(io.sys, 'platform', 'win32'),
                patch.object(io.os, 'replace', side_effect=replace),
                patch.object(io.os, 'fsync', wraps=real_sync) as sync,
                patch.object(io.time, 'sleep'),
            ):
                io.atomic_write(target, b'exact detached snapshot')
            sync.assert_called_once()
            self.assertEqual(attempts, [attempts[0]] * 3)
            self.assertEqual(target.read_bytes(), b'exact detached snapshot')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_wfo_snapshot_retries_no_database_work(self):
        from quantlab import walk_forward as wf
        from tests.test_walk_forward_snapshot_serialization import state_with

        with tempfile.TemporaryDirectory() as directory:
            root, db = Path(directory), Mock()
            real_replace = io.os.replace
            attempts = []

            def replace(source, destination):
                attempts.append((source, destination, Path(source).read_bytes()))
                if len(attempts) == 1:
                    raise denied()
                return real_replace(source, destination)

            with patch.object(io.sys, 'platform', 'win32'), patch.object(io.os, 'replace', side_effect=replace), patch.object(io.time, 'sleep'):
                wf._save_state(db, root, state_with({'synthetic': True}))
            db.execute.assert_called_once()
            db.commit.assert_called_once_with()
            self.assertEqual(attempts, [attempts[0]] * 2)
            self.assertEqual((root / 'walk_forward.json').read_bytes(), attempts[0][2])

    def test_reporting_retries_same_encoded_bytes_and_preserves_denial(self):
        from quantlab import reporting

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'report.json'
            target.write_bytes(b'old')
            canonical = reporting.canonical_json
            real_replace = io.os.replace
            attempts = []

            def replace(source, destination):
                attempts.append(Path(source).read_bytes())
                if len(attempts) == 1:
                    raise denied()
                return real_replace(source, destination)

            with (
                patch.object(io.sys, 'platform', 'win32'),
                patch.object(io.os, 'replace', side_effect=replace),
                patch.object(io.time, 'sleep'),
                patch.object(reporting, 'canonical_json', wraps=canonical) as encode,
            ):
                reporting.write_json(target, {'synthetic': True})
            encode.assert_called_once_with({'synthetic': True})
            self.assertEqual(attempts, [b'{"synthetic":true}' + io.os.linesep.encode()] * 2)
            self.assertEqual(target.read_bytes(), attempts[0])
            with patch.object(io.sys, 'platform', 'win32'), patch.object(io.os, 'replace', side_effect=denied()), patch.object(io.time, 'sleep'):
                with self.assertRaises(PermissionError):
                    reporting.write_json(target, {'synthetic': 'must not publish'})
            self.assertEqual(target.read_bytes(), attempts[0])
            self.assertEqual(list(target.parent.iterdir()), [target])


@unittest.skipUnless(sys.platform == 'win32', 'Native Windows sharing modes')
class NativeWindowsReplaceTests(unittest.TestCase):
    def test_real_reader_release_and_persistent_lock_keep_atomic_contract(self):
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        kernel.CreateFileW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        for durable in (False, True):
            for release in (False, True):
                with self.subTest(durable=durable, release=release), tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / 'target'
                    target.write_bytes(b'old complete snapshot')
                    handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
                    self.assertNotEqual(handle, w.HANDLE(-1).value)
                    ready, closed = threading.Event(), threading.Event()

                    def close_reader():
                        if ready.wait(2):
                            kernel.CloseHandle(handle)
                            closed.set()

                    thread = threading.Thread(target=close_reader)
                    thread.start()
                    failures = []
                    original = io._retry_replace

                    def inspect(operation):
                        def observed():
                            try:
                                return operation()
                            except OSError as error:
                                failures.append(error.winerror)
                                self.assertEqual(target.read_bytes(), b'old complete snapshot')
                                if release:
                                    ready.set()
                                    self.assertTrue(closed.wait(1))
                                raise

                        return original(observed)

                    try:
                        with patch.object(io, '_retry_replace', side_effect=inspect):
                            if release:
                                io.atomic_write(target, b'new complete snapshot', durable=durable)
                                self.assertEqual(target.read_bytes(), b'new complete snapshot')
                            else:
                                with self.assertRaises(PermissionError):
                                    io.atomic_write(target, b'new complete snapshot', durable=durable)
                                self.assertEqual(target.read_bytes(), b'old complete snapshot')
                        self.assertTrue(failures)
                        self.assertTrue(all(code in (5, 32, 33) for code in failures))
                        self.assertEqual(list(target.parent.iterdir()), [target])
                    finally:
                        ready.set()
                        thread.join(timeout=3)
                        self.assertFalse(thread.is_alive())
                        self.assertTrue(closed.is_set())
