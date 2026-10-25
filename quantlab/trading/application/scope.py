"""Fresh account facts before commitment; quarantine only affected exits."""

from dataclasses import replace
from typing import TYPE_CHECKING

from .reconciliation_views import differences
from .reconciliation_state import confirmed_availability
from quantlab.trading.domain.models import OrderPlan
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine


def refresh_scope(engine: 'TradingEngine', plan: OrderPlan) -> None:
    accounts = (plan.account_ref,) if plan.reduce_only else tuple(engine.gateways)
    for account in accounts:
        try:
            remote = engine.gateways[account].refresh(account)
        except Exception:
            engine._persist(
                'commit_account_query_failed',
                replace(engine.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*engine.state.issues, 'reconciliation_required'))))),
            )
            raise DomainError('reconciliation_required', 'fresh account facts unavailable') from None
        rows = differences(engine.state, remote)
        retained = tuple(row for row in engine.state.reconciliation if row.account_ref != account)
        positions = confirmed_availability(engine.state, remote)
        state = replace(engine.state, positions=positions, reconciliation=(*retained, *rows))
        if rows:
            reasons = tuple('external_position_difference' if row.kind == 'POSITION' else 'external_order_difference' for row in rows)
            state = replace(state, stopped=True, reconciled=False, issues=tuple(sorted(set((*state.issues, *reasons)))))
        if state != engine.state:
            engine._persist('commit_scope_observed', state)
        if rows and (not plan.reduce_only or any(row.instrument_id == plan.instrument_id for row in rows)):
            raise DomainError('reconciliation_required', 'this execution scope has unresolved observed differences')
