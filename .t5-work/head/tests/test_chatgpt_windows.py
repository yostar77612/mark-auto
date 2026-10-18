"""Native Windows acceptance: disposable current-user files, no OAuth/network.

Run with unittest on Windows. A Linux pass explicitly skips native evidence.
"""
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import desktop_chatgpt_auth as a

WAIT_SECONDS = 40  # Preserve the production lock's full 30-second deadline.


def _hold_lock(root, pipe):
    with a.DPAPIVault(root).lock():
        pipe.send('held')
        if pipe.recv() != 'release':
            raise AssertionError('unexpected command')
    pipe.send('released')


def _contend_lock(root, pipe):
    import msvcrt
    vault = a.DPAPIVault(root)
    # Prove contention before asking the production lock to wait; no sleep gate.
    with (vault.directory/'vault.lock').open('r+b') as stream:
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            pipe.send('blocked')
        else:
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            raise AssertionError('holder failed to exclude another process')
    with vault.lock():
        pipe.send('acquired')


def _private_dacl_matches_sid(descriptor, expected_sid):
    """Validate binary ACL identity; SDDL may abbreviate a trustee as LA."""
    import ctypes
    from ctypes import wintypes as w
    class AclSizeInformation(ctypes.Structure):
        _fields_ = [('AceCount', w.DWORD), ('AclBytesInUse', w.DWORD),
                    ('AclBytesFree', w.DWORD)]
    class AllowedAce(ctypes.Structure):
        _fields_ = [('AceType', w.BYTE), ('AceFlags', w.BYTE),
                    ('AceSize', w.WORD), ('Mask', w.DWORD), ('SidStart', w.DWORD)]
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p,
        ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p,
        ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    adv.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_int]
    adv.GetAce.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    adv.IsValidSid.argtypes = [ctypes.c_void_p]
    adv.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    control, revision = w.WORD(), w.DWORD()
    present, defaulted = w.BOOL(), w.BOOL()
    dacl, ace_pointer, expected = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    info = AclSizeInformation()
    if not adv.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not adv.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not control.value & 0x1000 or not present.value or not dacl.value:
        return False  # SE_DACL_PROTECTED; absent/null DACL grants broader access.
    if not adv.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.AceCount != 1:
        return False
    if not adv.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
        raise ctypes.WinError(ctypes.get_last_error())
    ace = ctypes.cast(ace_pointer, ctypes.POINTER(AllowedAce)).contents
    if ace.AceType != 0 or ace.Mask != 0x1f01ff or ace.AceFlags & 0x08:
        return False  # ACCESS_ALLOWED_ACE, FILE_ALL_ACCESS, not INHERIT_ONLY.
    trustee = ctypes.c_void_p(ace_pointer.value + AllowedAce.SidStart.offset)
    if not adv.IsValidSid(trustee):
        return False
    try:
        if not adv.ConvertStringSidToSidW(expected_sid, ctypes.byref(expected)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(adv.EqualSid(trustee, expected))
    finally:
        if expected:
            kernel.LocalFree(expected)


def _security_sddl(path, expected_sid):
    """Read actual kernel DACL, rather than mocking ACL installation."""
    import ctypes
    from ctypes import wintypes as w
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, ctypes.c_int, w.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    adv.GetNamedSecurityInfoW.restype = w.DWORD
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    text = w.LPWSTR()
    try:
        result = adv.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None,
                                           None, ctypes.byref(descriptor))
        if result:
            raise ctypes.WinError(result)
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return text.value, _private_dacl_matches_sid(descriptor, expected_sid)
    finally:
        if text:
            kernel.LocalFree(text)
        if descriptor:
            kernel.LocalFree(descriptor)


def _current_sid():
    import ctypes
    from ctypes import wintypes as w
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                      w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    handle, size, sid = w.HANDLE(), w.DWORD(), w.LPWSTR()
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        adv.GetTokenInformation(handle, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(handle, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not adv.ConvertSidToStringSidW(ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        return sid.value
    finally:
        if sid:
            kernel.LocalFree(sid)
        if handle:
            kernel.CloseHandle(handle)


class AuthImportBoundaryTests(unittest.TestCase):
    def test_fresh_source_import_and_constructor_are_network_inactive(self):
        code = '''
import socket, sys
from unittest.mock import patch
def denied(*args, **kwargs):
    raise AssertionError('network is forbidden during source import')
with patch.object(socket, 'socket', denied), patch.object(socket, 'create_connection', denied), patch.object(socket, 'getaddrinfo', denied):
    import quantlab
    assert not any(name in sys.modules for name in ('jwt', 'cryptography', 'desktop_chatgpt_auth'))
    import desktop_chatgpt_auth as auth
    session = auth.AuthSession(object())
    assert session.state == 'disconnected'
    assert not any(name in sys.modules for name in ('jwt', 'cryptography'))
'''
        result = subprocess.run([sys.executable, '-c', code],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=WAIT_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(sys.platform == 'win32', 'requires actual Windows DPAPI, DACL and msvcrt')
class WindowsAuthAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mark-auto-native-auth-')
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name).resolve()/'bootstrap')
        self.vault = a.DPAPIVault(self.root)
        self.session = a.AuthSession(self.vault)
        self.host = self.session.initialize_host()

    def _receive(self, pipe, expected):
        self.assertTrue(pipe.poll(WAIT_SECONDS), 'native lock handshake timed out')
        self.assertEqual(pipe.recv(), expected)

    def _spawn(self, target):
        ctx = multiprocessing.get_context('spawn')
        parent, child = ctx.Pipe()
        process = ctx.Process(target=target, args=(self.root, child))
        process.start()
        child.close()
        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(WAIT_SECONDS)
            parent.close()
            self.assertFalse(process.is_alive(), 'native child failed to stop')
        self.addCleanup(cleanup)
        return process, parent

    def test_encrypted_host_reload_private_dacl_and_no_reparse(self):
        other = a.AuthSession(a.DPAPIVault(self.root))
        self.assertEqual(other.initialize_host(), self.host)
        self.assertEqual(other.status_summary(), {'registrations': [],
            'active_registration': None, 'state': 'disconnected'})
        raw = self.vault.path.read_bytes()
        self.assertLessEqual(len(raw), a.MAX_RECORD)
        self.assertNotIn(self.host.encode(), raw)
        self.assertNotIn(b'"host_id"', raw)
        with self.vault.lock():
            self.assertEqual(self.vault.load()['host_id'], self.host)
        sid = _current_sid()
        for path in (self.vault.directory, self.vault.path, self.vault.directory/'vault.lock'):
            with self.subTest(path=path.name):
                sddl, private_current_user = _security_sddl(path, sid)
                self.assertTrue(sddl.startswith('D:P'), sddl)
                self.assertEqual(sddl.count('('), 1, sddl)
                ace = sddl[sddl.index('(')+1:sddl.index(')')].split(';')
                self.assertEqual(ace[0], 'A')
                self.assertEqual(ace[2], 'FA')
                self.assertTrue(private_current_user, sddl)
                for ancestor in (path, *path.parents):
                    info = ancestor.lstat()
                    self.assertFalse(stat.S_ISLNK(info.st_mode))
                    self.assertFalse(getattr(info, 'st_file_attributes', 0) & 0x400)

    def test_binary_dacl_identity_handles_admin_and_regular_sids(self):
        import ctypes
        from ctypes import wintypes as w
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        # Synthetic principals: no account creation, ACL installation or lookup.
        admin = 'S-1-5-21-101-202-303-500'
        regular = 'S-1-5-21-101-202-303-1001'
        other_admin = 'S-1-5-21-404-505-606-500'
        cases = [
            (f'D:P(A;OICI;FA;;;{admin})', admin, True),
            (f'D:P(A;OICI;FA;;;{regular})', regular, True),
            (f'D:P(A;OICI;FA;;;{admin})', regular, False),
            (f'D:P(A;OICI;FA;;;{regular})', admin, False),
            (f'D:P(A;OICI;FA;;;{other_admin})', admin, False),
            (f'D:(A;OICI;FA;;;{regular})', regular, False),
            (f'D:P(A;OICI;FR;;;{regular})', regular, False),
            (f'D:P(D;OICI;FA;;;{regular})', regular, False),
            (f'D:P(A;OICIIO;FA;;;{regular})', regular, False),
            (f'D:P(A;OICI;FA;;;{regular})(A;OICI;FA;;;WD)', regular, False),
            ('D:P', regular, False),
        ]
        for sddl, expected_sid, accepted in cases:
            with self.subTest(sddl=sddl, expected_sid=expected_sid):
                descriptor = ctypes.c_void_p()
                try:
                    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                            sddl, 1, ctypes.byref(descriptor), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.assertEqual(_private_dacl_matches_sid(descriptor, expected_sid), accepted)
                finally:
                    if descriptor:
                        kernel.LocalFree(descriptor)

    def test_actual_junction_ancestor_is_rejected(self):
        target = Path(self.temp.name)/'junction-target'
        target.mkdir()
        junction = Path(self.temp.name)/'junction'
        # Both target and junction are test-owned. mklink /J needs no symlink privilege.
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(target)],
                                capture_output=True, text=True, timeout=WAIT_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(lambda: os.rmdir(junction) if junction.exists() else None)
        self.assertTrue(junction.lstat().st_file_attributes & 0x400)
        with self.assertRaisesRegex(a.AuthError, 'vault_reparse_point'):
            a.AuthSession(a.DPAPIVault(str(junction/'bootstrap'))).initialize_host()
        self.assertEqual(list(target.iterdir()), [])

    def test_cross_process_lock_serialization(self):
        holder, held = self._spawn(_hold_lock)
        self._receive(held, 'held')
        contender, waiting = self._spawn(_contend_lock)
        self._receive(waiting, 'blocked')
        held.send('release')
        self._receive(held, 'released')
        self._receive(waiting, 'acquired')
        for process in (holder, contender):
            process.join(WAIT_SECONDS)
            self.assertEqual(process.exitcode, 0)

    def test_cross_process_lock_released_after_crash(self):
        holder, held = self._spawn(_hold_lock)
        self._receive(held, 'held')
        contender, waiting = self._spawn(_contend_lock)
        self._receive(waiting, 'blocked')
        holder.terminate()
        holder.join(WAIT_SECONDS)
        self.assertIsNotNone(holder.exitcode)
        self.assertNotEqual(holder.exitcode, 0)
        self._receive(waiting, 'acquired')
        contender.join(WAIT_SECONDS)
        self.assertEqual(contender.exitcode, 0)

    def test_durable_refresh_barrier_after_simulated_network_ambiguity(self):
        ref = 'a'*32
        tokens = dict(access_token='native-fixture-access-NOT-A-CREDENTIAL',
            refresh_token='native-fixture-refresh-NOT-A-CREDENTIAL',
            id_token='native-fixture-id-NOT-A-CREDENTIAL', scopes=a.SCOPES.split(),
            expires_at=time.time()-1, earliest_refresh_at=0)
        with self.vault.lock():
            record = self.vault.load()
            record['active'] = ref
            record['registrations'][ref] = dict(identity=dict(issuer=a.ISSUER,
                client_id='fixture-native-client', subject='fixture-native-subject'),
                tokens=tokens, generation=1, operation=None)
            self.vault.save(record)
        calls = []
        class AmbiguousTransport:
            def request(inner, *args, **kwargs):
                calls.append(1)
                # Same-thread read sees the actual atomic DPAPI write before send.
                self.assertEqual(self.vault.load()['registrations'][ref]['operation'], 'refresh')
                raise OSError('synthetic transport ambiguity; no network')
        with self.assertRaisesRegex(a.AuthError, 'reauthorization_required'):
            a.AuthSession(self.vault, AmbiguousTransport()).refresh(ref)
        restarted = a.AuthSession(a.DPAPIVault(self.root), AmbiguousTransport())
        self.assertEqual(restarted.status_summary()['state'], 'reauthorization_required')
        for action in (restarted.refresh, restarted.access_token):
            with self.assertRaisesRegex(a.AuthError, 'reauthorization_required'):
                action(ref)
        self.assertEqual(len(calls), 1)
        raw = self.vault.path.read_bytes()
        for fixture in tokens['access_token'], tokens['refresh_token'], tokens['id_token']:
            self.assertNotIn(fixture.encode(), raw)
        self.assertEqual(sorted(p.name for p in self.vault.directory.iterdir()),
                         ['accounts.dpapi', 'vault.lock'])


if __name__ == '__main__':
    unittest.main()
