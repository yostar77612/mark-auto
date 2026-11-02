"""Reference-only connection preferences; old optional forms never gate startup."""

from decimal import Decimal
from hashlib import sha256
from threading import RLock

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError, identity
from quantlab.trading.adapters.shioaji.account_discovery import account_digest, keyed_account_digest
from .sinopac_aliases import workspace_alias_key


class SinopacSettingsStore:
    def __init__(self, root):
        self.root = root
        self.store = SettingsStore(root / 'settings.json')
        self.lock = RLock()

    @property
    def alias_key(self):
        with self.lock:
            _, key = self._body()
            return key

    def _body(self):
        body = self.store.load()
        key = workspace_alias_key(self.root)
        key_id = sha256(b'MarkAuto/account-alias-key/v2\0' + key).hexdigest()
        self._parse_settings(body)  # Validate before a migration can rewrite preferences.
        previous = body.get('sinopac_alias_key_v2')
        legacy = body.get('sinopac_accounts_v1')
        if previous == key_id and legacy is None:
            return body, key
        if previous is None and 'sinopac_accounts_v2' not in body:
            rows = self._validate_accounts([] if legacy is None else legacy, 'identity_sha256')
            aliases, migrated = {}, []
            for row in rows:
                digest = keyed_account_digest(row['identity_sha256'], key)
                alias = 'sinopac-' + digest[:24]
                aliases[row['alias']] = alias
                migrated.append(
                    {
                        'alias': alias,
                        'label': row['label'].split('-***', 1)[0] + '-***' if '-***' in row['label'] else '***',
                        'market': row['market'],
                        'identity_hmac': digest,
                    }
                )
        else:
            # Lost/replaced key cannot identify prior accounts: never guess from
            # display labels, suffixes or a new key. Require explicit reselection.
            aliases, migrated = {}, []
        if (self.root / 'manual-trading-v2.sqlite').exists():
            body['sinopac_alias_reconciliation_v2'] = True
            aliases = {}
        raw = body.get('sinopac_connection_v1')
        if isinstance(raw, dict) and isinstance(raw.get('selected'), list):
            raw['selected'] = [aliases[value] for value in raw['selected'] if isinstance(value, str) and value in aliases]
        body.pop('sinopac_accounts_v1', None)
        body['sinopac_accounts_v2'] = migrated
        body['sinopac_alias_key_v2'] = key_id
        self.store.save(body)
        return body, key

    def load(self):
        with self.lock:
            body, _ = self._body()
            return self._parse_settings(body)

    @staticmethod
    def _parse_settings(body):
        raw = body.get('sinopac_connection_v1')
        if raw is None:
            # Legacy market preferences are optional hints, never credentials
            # or an instruction to connect during startup.
            legacy = body.get('market_data_v1', {})
            try:
                settings = SinopacConnectionSettings(Environment(legacy['environment']), legacy['secret_ref'])
            except (KeyError, ValueError, TypeError, DomainError):
                settings = SinopacConnectionSettings()
            return settings, ()
        if not isinstance(raw, dict) or set(raw) != {'environment', 'key_ref', 'certificate_path', 'certificate_secret_ref', 'fee_discount', 'selected'}:
            raise DomainError('validation_failed', 'connection preference schema')
        try:
            settings = SinopacConnectionSettings(
                Environment(raw['environment']), raw['key_ref'], raw['certificate_path'], raw['certificate_secret_ref'], Decimal(raw['fee_discount'])
            )
            selected = raw['selected']
            if type(selected) is not list or len(selected) > 100 or len(set(selected)) != len(selected):
                raise ValueError('selection')
            for alias in selected:
                identity(alias)
        except (ValueError, TypeError, ArithmeticError):
            raise DomainError('validation_failed', 'connection preference types') from None
        return settings, tuple(selected)

    def save(self, settings, selected):
        with self.lock:
            body, _ = self._body()
            if selected and body.get('sinopac_alias_reconciliation_v2', False):
                raise DomainError('reconciliation_required', 'account alias migration requires journal reconciliation')
            body['sinopac_connection_v1'] = {
                'environment': settings.environment.value,
                'key_ref': settings.key_ref,
                'certificate_path': settings.certificate_path,
                'certificate_secret_ref': settings.certificate_secret_ref,
                'fee_discount': str(settings.fee_discount),
                'selected': list(selected),
            }
            self.store.save(body)

    def check_selection(self, selected):
        with self.lock:
            body, _ = self._body()
            known = {row['alias'] for row in self._validate_accounts(body.get('sinopac_accounts_v2', []), 'identity_hmac')}
            if selected and (body.get('sinopac_alias_reconciliation_v2', False) or not set(selected) <= known):
                raise DomainError('reconciliation_required', 'account aliases changed; reconnect and reconcile')

    def advance_revision(self):
        with self.lock:
            body, _ = self._body()
            previous = body.get('sinopac_revision_v1', 0)
            if type(previous) is not int or previous < 0:
                raise DomainError('validation_failed', 'connection revision checkpoint')
            body['sinopac_revision_v1'] = previous + 1
            self.store.save(body)
            return previous + 1

    def save_accounts(self, accounts, environment):
        with self.lock:
            body, key = self._body()
            known = {item['alias']: item for item in self._validate_accounts(body.get('sinopac_accounts_v2', []), 'identity_hmac')}
            for account in accounts:
                digest = account_digest(account.native, environment, key)
                if account.alias != 'sinopac-' + digest[:24]:
                    raise DomainError('state_conflict', 'account alias key changed; reselect accounts')
                known[account.alias] = {
                    'alias': account.alias,
                    'label': account.label,
                    'market': account.market.value,
                    'identity_hmac': digest,
                }
            body['sinopac_accounts_v2'] = list(known.values())
            self.store.save(body)

    def known_accounts(self):
        with self.lock:
            body, _ = self._body()
            return self._validate_accounts(body.get('sinopac_accounts_v2', []), 'identity_hmac')

    @staticmethod
    def _validate_accounts(rows, digest_field):
        if type(rows) is not list or len(rows) > 500:
            raise DomainError('validation_failed', 'generated account metadata size')
        aliases = set()
        for row in rows:
            if type(row) is not dict or set(row) != {'alias', 'label', 'market', digest_field}:
                raise DomainError('validation_failed', 'generated account metadata schema')
            identity(row['alias'])
            if (
                row['alias'] in aliases
                or not isinstance(row['label'], str)
                or '*' not in row['label']
                or row['market'] not in (Market.STOCK.value, Market.INDEX_FUTURE.value)
            ):
                raise DomainError('validation_failed', 'generated account metadata identity')
            if not isinstance(row[digest_field], str) or len(row[digest_field]) != 64 or any(char not in '0123456789abcdef' for char in row[digest_field]):
                raise DomainError('validation_failed', 'generated account identity digest')
            if row['alias'] != 'sinopac-' + row[digest_field][:24]:
                raise DomainError('validation_failed', 'generated account alias mismatch')
            aliases.add(row['alias'])
        return tuple(rows)
