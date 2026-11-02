"""Date/cost preferences without broker secrets; offline maintenance composition."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quantlab.research_core.adapters.settings_store import SettingsStore
from quantlab.taifex_expiries import load_expiries
from quantlab.trading.application.broker_settings import _secret_reference
from quantlab.trading.domain.costs import FeeSchedule
from quantlab.trading.domain.maintenance import ExpiryCoverage, key_expiry_status, maintenance_check
from quantlab.trading.domain.validation import DomainError, identity


@dataclass(frozen=True)
class StockMaintenanceSettings:
    discount: Decimal = Decimal('1')
    minimum_fee: Decimal = Decimal('20')
    tmf_fee_per_contract: Decimal = Decimal('30')
    slippage_ticks: int = 1

    def fees(self, *, stock_kind='STOCK', day_trade=False):
        return FeeSchedule.taiwan(
            discount=self.discount,
            minimum_fee=self.minimum_fee,
            futures_fee_per_contract=self.tmf_fee_per_contract,
            slippage_ticks=self.slippage_ticks,
            stock_kind=stock_kind,
            day_trade=day_trade,
        )


class StockMaintenanceStore:
    def __init__(self, root):
        self.store = SettingsStore(root / 'stock_maintenance.json')

    def load(self) -> StockMaintenanceSettings:
        raw = self.store.load().get('cost_inputs_v1')
        if raw is None:
            return StockMaintenanceSettings()
        try:
            if set(raw) != {'discount', 'minimum_fee', 'tmf_fee_per_contract', 'slippage_ticks'}:
                raise ValueError('schema')
            settings = StockMaintenanceSettings(
                Decimal(raw['discount']), Decimal(raw['minimum_fee']), Decimal(raw['tmf_fee_per_contract']), raw['slippage_ticks']
            )
            settings.fees()
            return settings
        except (ValueError, TypeError, ArithmeticError):
            raise DomainError('validation_failed', 'cost settings invalid; original preserved') from None

    def save(self, settings: StockMaintenanceSettings) -> FeeSchedule:
        fees = settings.fees()
        body = self.store.load()
        raw = {
            'discount': str(settings.discount),
            'minimum_fee': str(settings.minimum_fee),
            'tmf_fee_per_contract': str(settings.tmf_fee_per_contract),
            'slippage_ticks': settings.slippage_ticks,
        }
        body['cost_inputs_v1'] = raw
        # Append-only historical cost snapshots: research evidence is never rewritten.
        saved_versions = body.get('cost_versions_v1', {})
        if type(saved_versions) is not dict:
            raise DomainError('validation_failed', 'cost history invalid; original preserved')
        versions = dict(saved_versions)
        if fees.version in versions and versions[fees.version] != raw:
            raise DomainError('validation_failed', 'cost identity conflict')
        versions[fees.version] = raw
        body['cost_versions_v1'] = versions
        self.store.save(body)
        return fees

    def key_expiry(self, key_ref: str) -> date | None:
        identity(key_ref, 'key reference')
        if not _secret_reference(key_ref, 'broker'):
            raise DomainError('validation_failed', 'broker key reference required')
        dates = self.store.load().get('key_expiry_dates_v1', {})
        if type(dates) is not dict:
            raise DomainError('validation_failed', 'expiry settings invalid; original preserved')
        value = dates.get(key_ref)
        try:
            return date.fromisoformat(value) if value is not None else None
        except (ValueError, TypeError):
            raise DomainError('validation_failed', 'expiry date invalid; original preserved') from None

    def set_key_expiry(self, key_ref: str, expires_on: date | None) -> None:
        identity(key_ref, 'key reference')
        if not _secret_reference(key_ref, 'broker'):
            raise DomainError('validation_failed', 'broker key reference required')
        if expires_on is not None and type(expires_on) is not date:
            raise DomainError('validation_failed', 'expiry date required')
        body = self.store.load()
        saved_dates = body.get('key_expiry_dates_v1', {})
        if type(saved_dates) is not dict:
            raise DomainError('validation_failed', 'expiry settings invalid; original preserved')
        dates = dict(saved_dates)
        dates[key_ref] = expires_on.isoformat() if expires_on else None
        body['key_expiry_dates_v1'] = dates
        self.store.save(body)

    def key_status(self, key_ref, today):
        return key_expiry_status(self.key_expiry(key_ref), today)

    def pre_open(self, calendar, today, key_ref, *, expiries_path=None, futures_required=True):
        try:
            data = load_expiries() if expiries_path is None else load_expiries(expiries_path)
            expiries = ExpiryCoverage(
                data['data_version'], tuple(sorted((row['contract_month'], date.fromisoformat(row['expiry_date'])) for row in data['expiries']))
            )
        except (OSError, ValueError, TypeError):
            expiries = None
        return maintenance_check(calendar, today, expires_on=self.key_expiry(key_ref), expiries=expiries, futures_required=futures_required)
