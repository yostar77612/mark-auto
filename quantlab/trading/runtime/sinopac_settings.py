"""Reference-only connection preferences; old optional forms never gate startup."""

from decimal import Decimal
from hashlib import sha256
from threading import RLock

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.trading.application.sinopac_contracts import SinopacConnectionSettings
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.validation import DomainError, identity


class SinopacSettingsStore:
    def __init__(self, root):
        self.store = SettingsStore(root / 'settings.json')
        self.lock = RLock()

    def load(self):
        body = self.store.load()
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
            body = self.store.load()
            body['sinopac_connection_v1'] = {
                'environment': settings.environment.value,
                'key_ref': settings.key_ref,
                'certificate_path': settings.certificate_path,
                'certificate_secret_ref': settings.certificate_secret_ref,
                'fee_discount': str(settings.fee_discount),
                'selected': list(selected),
            }
            self.store.save(body)

    def advance_revision(self):
        with self.lock:
            body = self.store.load()
            previous = body.get('sinopac_revision_v1', 0)
            if type(previous) is not int or previous < 0:
                raise DomainError('validation_failed', 'connection revision checkpoint')
            body['sinopac_revision_v1'] = previous + 1
            self.store.save(body)
            return previous + 1

    def save_accounts(self, accounts, environment):
        from quantlab.trading.adapters.shioaji.account_discovery import account_identity

        with self.lock:
            body = self.store.load()
            known = {item['alias']: item for item in self.known_accounts()}
            rows = [
                {
                    'alias': account.alias,
                    'label': account.label,
                    'market': account.market.value,
                    'identity_sha256': sha256('\0'.join((environment.value, *account_identity(account.native))).encode('utf-8')).hexdigest(),
                }
                for account in accounts
            ]
            known.update({item['alias']: item for item in rows})
            body['sinopac_accounts_v1'] = list(known.values())
            self.store.save(body)

    def known_accounts(self):
        rows = self.store.load().get('sinopac_accounts_v1', [])
        if type(rows) is not list or len(rows) > 500:
            raise DomainError('validation_failed', 'generated account metadata size')
        aliases = set()
        for row in rows:
            if type(row) is not dict or set(row) != {'alias', 'label', 'market', 'identity_sha256'}:
                raise DomainError('validation_failed', 'generated account metadata schema')
            identity(row['alias'])
            if (
                row['alias'] in aliases
                or not isinstance(row['label'], str)
                or '*' not in row['label']
                or row['market'] not in (Market.STOCK.value, Market.INDEX_FUTURE.value)
            ):
                raise DomainError('validation_failed', 'generated account metadata identity')
            if (
                not isinstance(row['identity_sha256'], str)
                or len(row['identity_sha256']) != 64
                or any(char not in '0123456789abcdef' for char in row['identity_sha256'])
            ):
                raise DomainError('validation_failed', 'generated account identity hash')
            aliases.add(row['alias'])
        return tuple(rows)
