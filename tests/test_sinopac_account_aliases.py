"""Fake-account privacy, persisted migration and key-loss fail-closed behavior."""

from hashlib import sha256
import hmac
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os
import subprocess
import unittest
from unittest.mock import patch

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.adapters.shioaji.account_discovery import account_identity, discover_accounts, keyed_account_digest
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.runtime.sinopac_aliases import KEY_FILE, workspace_alias_key
from quantlab.trading.runtime.sinopac_settings import SinopacSettingsStore

ENV = Environment.BROKER_SIMULATION


def fake_account(account_id='1234567'):
    return SimpleNamespace(account_type='S', broker_id='9A95', account_id=account_id, signed=True, person_id='PRIVATE_PERSON')


def old_digest(account, environment=ENV):
    return sha256('\0'.join((environment.value, *account_identity(account))).encode()).hexdigest()


class AccountAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SinopacSettingsStore(self.root)
        self.raw = fake_account()

    def discover(self, rows=None, environment=ENV):
        return discover_accounts(rows or [self.raw], environment, alias_key=self.store.alias_key)

    def legacy(self):
        digest = old_digest(self.raw)
        alias = 'sinopac-' + digest[:24]
        settings = SinopacConnectionSettings()
        body = {
            'unrelated': {'keep': True},
            'sinopac_connection_v1': {
                'environment': settings.environment.value,
                'key_ref': settings.key_ref,
                'certificate_path': settings.certificate_path,
                'certificate_secret_ref': settings.certificate_secret_ref,
                'fee_discount': str(settings.fee_discount),
                'selected': [alias],
            },
            'sinopac_accounts_v1': [{'alias': alias, 'label': '9A95-***567', 'market': 'STOCK', 'identity_sha256': digest}],
        }
        SettingsStore(self.root / 'settings.json').save(body)
        return body, digest, alias

    def test_fresh_empty_workspace_is_not_reconciliation_blocked(self):
        self.assertEqual(self.store.load(), (SinopacConnectionSettings(), ()))
        self.assertFalse(self.store.store.load().get('sinopac_alias_reconciliation_v2', False))
        accounts = self.discover()
        self.store.save_accounts(accounts, ENV)
        self.store.check_selection((accounts[0].alias,))
        self.store.save(SinopacConnectionSettings(), (accounts[0].alias,))
        self.assertEqual(self.store.load()[1], (accounts[0].alias,))

    def test_existing_ledger_without_identity_metadata_is_reconciliation_blocked(self):
        journal = self.root / 'manual-trading-v2.sqlite'
        journal.write_bytes(b'fake-existing-journal')
        self.assertEqual(self.store.load()[1], ())
        accounts = self.discover()
        with self.assertRaises(DomainError) as error:
            self.store.check_selection((accounts[0].alias,))
        self.assertEqual(error.exception.code, 'reconciliation_required')
        self.assertEqual(journal.read_bytes(), b'fake-existing-journal')

    def test_legacy_migrates_selection_and_removes_all_unkeyed_identities(self):
        _, digest, old_alias = self.legacy()
        settings, selected = self.store.load()
        discovered = self.discover()
        self.assertEqual(selected, (discovered[0].alias,))
        self.assertEqual(settings, SinopacConnectionSettings())
        migrated = self.store.store.load()
        self.assertEqual(migrated['unrelated'], {'keep': True})
        self.assertNotIn('sinopac_accounts_v1', migrated)
        contents = (self.root / 'settings.json').read_text()
        for private in (digest, old_alias, self.raw.account_id, self.raw.person_id, 'identity_sha256'):
            self.assertNotIn(private, contents)
        row = self.store.known_accounts()[0]
        expected = hmac.new(self.store.alias_key, b'MarkAuto/account-identity/v2\0' + bytes.fromhex(digest), sha256).hexdigest()
        self.assertEqual(row['identity_hmac'], expected)
        self.assertEqual(keyed_account_digest(digest, self.store.alias_key), expected)
        self.assertEqual(row['alias'], selected[0])
        self.store.save_accounts(discovered, ENV)
        self.assertEqual(len(self.store.known_accounts()), 1)
        self.assertEqual(SinopacSettingsStore(self.root).load()[1], selected)

    def test_same_account_stable_after_restart_and_different_account_environment_workspace_differ(self):
        first = self.discover()[0]
        self.assertEqual(first.alias, self.discover()[0].alias)
        reloaded = SinopacSettingsStore(self.root)
        self.assertEqual(first.alias, discover_accounts([self.raw], ENV, alias_key=reloaded.alias_key)[0].alias)
        self.assertNotEqual(first.alias, self.discover([fake_account('7654321')])[0].alias)
        self.assertNotEqual(first.alias, self.discover(environment=Environment.LIVE)[0].alias)
        other = SinopacSettingsStore(self.root / 'other')
        self.assertNotEqual(first.alias, discover_accounts([self.raw], ENV, alias_key=other.alias_key)[0].alias)
        self.assertNotEqual(first.alias, 'sinopac-' + old_digest(self.raw)[:24])
        self.assertNotIn(self.raw.account_id, repr(first))
        self.assertNotIn(self.raw.person_id, repr(first))

    def test_missing_key_requires_reselection_never_matches_old_alias_or_suffix(self):
        accounts = self.discover()
        self.store.save_accounts(accounts, ENV)
        self.store.save(SinopacConnectionSettings(), (accounts[0].alias,))
        (self.root / KEY_FILE).unlink()
        reloaded = SinopacSettingsStore(self.root)
        self.assertEqual(reloaded.load()[1], ())
        self.assertEqual(reloaded.known_accounts(), ())
        fresh = discover_accounts([self.raw, fake_account('9999567')], ENV, alias_key=reloaded.alias_key)
        reloaded.save_accounts(fresh, ENV)
        self.assertNotIn(accounts[0].alias, {row.alias for row in fresh})
        self.assertEqual(reloaded.load()[1], ())
        self.assertEqual(reloaded.store.load()['sinopac_connection_v1']['selected'], [])

    def test_replaced_key_also_clears_selection_and_rejects_stale_discovery(self):
        accounts = self.discover()
        self.store.save_accounts(accounts, ENV)
        self.store.save(SinopacConnectionSettings(), (accounts[0].alias,))
        (self.root / KEY_FILE).write_bytes(b'R' * 32)
        self.assertEqual(self.store.load()[1], ())
        self.assertEqual(self.store.known_accounts(), ())
        with self.assertRaises(DomainError) as error:
            self.store.save_accounts(accounts, ENV)
        self.assertEqual(error.exception.code, 'state_conflict')

    def test_corrupt_key_fails_closed_without_rewriting_preferences(self):
        self.discover()
        before = (self.root / 'settings.json').read_bytes()
        (self.root / KEY_FILE).write_bytes(b'incomplete')
        with self.assertRaises(DomainError) as error:
            self.store.load()
        self.assertEqual(error.exception.code, 'validation_failed')
        self.assertNotIn('incomplete', str(error.exception))
        self.assertEqual((self.root / 'settings.json').read_bytes(), before)

    def test_malformed_legacy_identity_preserves_original_settings(self):
        body, _, _ = self.legacy()
        body['sinopac_accounts_v1'][0]['identity_sha256'] = 'invalid'
        self.store.store.save(body)
        before = (self.root / 'settings.json').read_bytes()
        with self.assertRaises(DomainError):
            self.store.load()
        self.assertEqual((self.root / 'settings.json').read_bytes(), before)

    def test_malformed_legacy_selection_preserves_original_settings(self):
        body, _, _ = self.legacy()
        body['sinopac_connection_v1']['selected'] = ['same', 'same']
        self.store.store.save(body)
        before = (self.root / 'settings.json').read_bytes()
        with self.assertRaises(DomainError):
            self.store.load()
        self.assertEqual((self.root / 'settings.json').read_bytes(), before)

    def test_legacy_workspace_with_manual_ledger_is_reconciliation_blocked(self):
        self.legacy()
        journal = self.root / 'manual-trading-v2.sqlite'
        journal.write_bytes(b'fake-existing-journal-do-not-rewrite')
        self.assertEqual(self.store.load()[1], ())
        alias = self.discover()[0].alias
        with self.assertRaises(DomainError) as error:
            self.store.check_selection((alias,))
        self.assertEqual(error.exception.code, 'reconciliation_required')
        with self.assertRaises(DomainError):
            self.store.save(SinopacConnectionSettings(), (alias,))
        self.assertEqual(journal.read_bytes(), b'fake-existing-journal-do-not-rewrite')
        self.assertTrue(self.store.store.load()['sinopac_alias_reconciliation_v2'])
        # Reopening preferences or saving settings cannot clear the safety marker.
        self.store.save(SinopacConnectionSettings(), ())
        with self.assertRaises(DomainError):
            SinopacSettingsStore(self.root).check_selection((alias,))

    def test_key_is_private_ignored_and_absent_from_settings(self):
        key = self.store.alias_key
        self.assertEqual(len(key), 32)
        self.assertEqual(workspace_alias_key(self.root), key)
        self.assertNotIn(key.hex(), (self.root / 'settings.json').read_text())
        if os.name == 'posix':
            self.assertEqual((self.root / KEY_FILE).stat().st_mode & 0o777, 0o600)
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--', KEY_FILE], capture_output=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0)

    def test_exclusive_create_collision_uses_existing_key_without_overwrite(self):
        existing = workspace_alias_key(self.root)
        with patch('quantlab.trading.runtime.sinopac_aliases.token_bytes', side_effect=AssertionError('must not rotate')):
            self.assertEqual(workspace_alias_key(self.root), existing)

    def test_write_failure_cannot_migrate_legacy_settings(self):
        self.legacy()
        before = (self.root / 'settings.json').read_bytes()
        with patch('quantlab.trading.runtime.sinopac_aliases.os.fsync', side_effect=OSError('PRIVATE_PATH')):
            with self.assertRaises(DomainError) as error:
                self.store.load()
        self.assertNotIn('PRIVATE_PATH', str(error.exception))
        self.assertEqual((self.root / 'settings.json').read_bytes(), before)

    def test_short_native_identifiers_are_never_fully_exposed(self):
        for account_id in ('1', '12', '123'):
            with self.subTest(length=len(account_id)):
                row = self.discover([fake_account(account_id)])[0]
                self.assertNotIn(account_id, row.label)


if __name__ == '__main__':
    unittest.main()
