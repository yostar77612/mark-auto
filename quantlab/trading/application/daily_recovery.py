"""Explicitly discard a proven pure daily evaluation interrupted before signals."""

from dataclasses import replace
from typing import TYPE_CHECKING

from . import automatic_state as claims
from .automatic_capacity import assert_automatic_observation
from .codec import loads
from .state import AppState
from quantlab.trading.domain.auto_cycle import evaluation_key_matches
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine


def _daily_claim_provenance(events, row) -> bool:
    previous = None
    proven = False
    for event in events:
        snapshot = loads(event.payload)
        if not isinstance(snapshot, AppState) or snapshot.version != event.sequence:
            raise DomainError('journal_failed', 'daily recovery requires full state history')
        current = next((item for item in snapshot.automatic.evaluations if item.cursor == row.cursor), None)
        prior = next((item for item in previous.automatic.evaluations if item.cursor == row.cursor), None) if previous is not None else None
        if current is not None and current.phase == 'CLAIMED' and (prior is None or prior.phase != 'CLAIMED'):
            proven = (
                event.kind == 'daily_evaluation_claimed' and current.evaluated_at == row.evaluated_at and current.order_result is None and not current.order_id
            )
        previous = snapshot
    return proven


def recover_daily_evaluations(engine: 'TradingEngine') -> None:
    """Discard only pure close work. Dispatch uncertainty and budgets stay intact."""
    with engine.lock:
        engine.assert_execution_allowed()
        if engine.configuration.environment is not Environment.BROKER_SIMULATION or engine.storage_failed or engine.state.engine_closed:
            raise DomainError('capability_missing')
        for reference in sorted(engine.gateways):
            assert_automatic_observation(engine, reference)
        if not engine.gateways or any(not row.outcome_known for row in engine.state.manual_requests):
            raise DomainError('reconciliation_required')
        events = engine.journal.replay()
        automatic = engine.state.automatic
        for row in tuple(automatic.evaluations):
            if row.cursor.interval != '1d' or row.phase != 'INTERRUPTED' or row.order_result is not None or row.order_id:
                continue
            record = next((item for item in engine.state.strategies if (item.strategy_id, item.version) == (row.cursor.strategy_id, row.cursor.version)), None)
            if record is None or record.parameters is None or record.parameters.bar_interval != '1d':
                continue
            if any(intent.cursor == row.cursor for intent in automatic.daily.intents):
                continue
            if any(evaluation_key_matches(order.key, row.cursor) for order in engine.state.orders):
                continue  # Existing canonical reports belong to normal reconciliation.
            if not _daily_claim_provenance(events, row):
                continue
            automatic = claims.complete_evaluation(automatic, row.cursor, observed=True, code='daily_signal_invalidated')
        if automatic != engine.state.automatic:
            engine._persist('daily_evaluation_discarded', replace(engine.state, automatic=automatic))
