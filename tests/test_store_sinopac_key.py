import unittest

from tools import store_sinopac_key as tool


class FakeVault:
    """Windows Credential Manager stand-in: one target may hold a roaming and a local-machine copy."""

    def __init__(self, copies):
        self.copies = list(copies)  # (persist, size); the first entry is the one CredReadW returns
        self.writes = []

    def CredDeleteW(self, target, kind, flags):
        if not self.copies:
            return 0
        self.copies.pop(0)
        return 1

    def CredWriteW(self, pointer, flags):
        cred = pointer._obj
        self.writes.append((cred.TargetName, cred.Persist, cred.CredentialBlobSize))
        self.copies.insert(0, (cred.Persist, cred.CredentialBlobSize))
        return 1

    def CredReadW(self, target, kind, flags, pointer):
        if not self.copies:
            return 0
        persist, size = self.copies[0]
        pointer._obj.contents = tool._Credential(Type=1, TargetName=target, Persist=persist, CredentialBlobSize=size)
        return 1

    def CredFree(self, pointer):
        pass


class StoreSinopacKeyTests(unittest.TestCase):
    def test_write_removes_a_stale_empty_roaming_copy_and_a_local_copy(self):
        vault = FakeVault([(3, 0), (2, 121)])

        tool._write(tool.TARGET, b'{"api_key": "a", "secret_key": "b"}', vault)

        self.assertEqual(vault.copies, [(2, 35)])
        self.assertEqual(vault.writes, [(tool.TARGET, 2, 35)])

    def test_write_into_an_empty_vault(self):
        vault = FakeVault([])

        tool._write(tool.TARGET, b'payload', vault)

        self.assertEqual(vault.copies, [(2, 7)])

    def test_write_fails_when_windows_returns_another_copy(self):
        class Shadowed(FakeVault):
            def CredReadW(self, target, kind, flags, pointer):
                pointer._obj.contents = tool._Credential(Type=1, TargetName=target, Persist=3, CredentialBlobSize=0)
                return 1

        with self.assertRaisesRegex(OSError, 'does not return the saved copy'):
            tool._write(tool.TARGET, b'payload', Shadowed([]))

    def test_write_refuses_when_copies_never_run_out(self):
        class Endless(FakeVault):
            def CredDeleteW(self, target, kind, flags):
                return 1

        vault = Endless([])
        with self.assertRaisesRegex(OSError, 'could not remove'):
            tool._write(tool.TARGET, b'payload', vault)
        self.assertEqual(vault.writes, [])


if __name__ == '__main__':
    unittest.main()
