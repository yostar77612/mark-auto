"""Retain only masked account markets and bindings needed by manual obligations."""

from dataclasses import dataclass
from datetime import datetime, timezone

from quantlab.trading.adapters.shioaji.sdk import InstrumentBinding
from quantlab.trading.adapters.storage.ledger import Ledger
from quantlab.trading.application.codec import dumps, loads, register
from quantlab.trading.domain.models import InstrumentSpec, Market
from quantlab.trading.domain.validation import DomainError, identity


@dataclass(frozen=True)
class ManualResourceState:
    bindings: tuple[InstrumentBinding, ...]
    markets: tuple[tuple[str, Market], ...]
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1 or type(self.bindings) is not tuple or type(self.markets) is not tuple:
            raise DomainError('startup_workspace_incompatible', 'manual resource schema')
        if not 1 <= len(self.bindings) <= 500 or not 1 <= len(self.markets) <= 100:
            raise DomainError('validation_failed', 'bounded manual resource facts')
        if any(not isinstance(row, InstrumentBinding) or not isinstance(row.spec, InstrumentSpec) for row in self.bindings):
            raise DomainError('validation_failed', 'typed manual bindings required')
        if len({row.spec.instrument_id for row in self.bindings}) != len(self.bindings):
            raise DomainError('validation_failed', 'unique manual bindings required')
        if any(type(row) is not tuple or len(row) != 2 for row in self.markets):
            raise DomainError('validation_failed', 'typed manual alias market facts required')
        if len(dict(self.markets)) != len(self.markets):
            raise DomainError('validation_failed', 'unique masked aliases required')
        for alias, market in self.markets:
            identity(alias)
            if not isinstance(market, Market) or market not in (Market.STOCK, Market.INDEX_FUTURE):
                raise DomainError('capability_missing', 'supported explicit account market required')


register(ManualResourceState, InstrumentBinding)


class ManualResourceStore:
    """Lazy owned Ledger; construction performs no IO or provider discovery."""

    def __init__(self, bundle):
        self.bundle = bundle
        self.journal = self.state = None
        self.sequence = 0

    def retain(self, resources):
        if self.journal is None:
            self.journal = Ledger(self.bundle.launch.root / 'manual-resources-v2.sqlite', 'manual-sim-resources-v1', datetime.now(timezone.utc))
            self.bundle.journals = (*self.bundle.journals, self.journal)
            for event in self.journal.replay():
                value = loads(event.payload)
                if not isinstance(value, ManualResourceState):
                    raise DomainError('startup_workspace_incompatible', 'manual resource journal changed')
                self.state, self.sequence = value, event.sequence
        bindings = {row.spec.instrument_id: row for row in self.state.bindings} if self.state else {}
        markets = dict(self.state.markets) if self.state else {}
        for resource in resources:
            for account in resource.accounts:
                if account.alias in markets and markets[account.alias] is not account.market:
                    raise DomainError('startup_workspace_incompatible', 'masked alias market changed')
                markets[account.alias] = account.market
            for binding in resource.bindings:
                bindings[binding.spec.instrument_id] = binding
        value = ManualResourceState(tuple(bindings[key] for key in sorted(bindings)), tuple(sorted(markets.items())))
        if value != self.state:
            event = self.journal.append('manual_resources_observed', dumps(value), datetime.now(timezone.utc), expected_sequence=self.sequence)
            self.state, self.sequence = value, event.sequence
        return value
