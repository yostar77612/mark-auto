"""Confirmed no-send resolution from journal provenance and current reconciliation."""

from dataclasses import replace

from .automatic_capacity import assert_automatic_observation
from .automatic_state import pause
from .codec import loads
from .contracts import DailyNotSentForm
from .state import AppState
from quantlab.trading.domain.auto_cycle import evaluation_key_matches
from quantlab.trading.domain.models import Environment, Side
from quantlab.trading.domain.validation import DomainError, identity


def _same_key(key, intent):
    if not evaluation_key_matches(key, intent.cursor):
        return False
    _, separator, lot_id = key.partition(':exit:')
    return lot_id == intent.lot_id if intent.action == 'EXIT' else not separator


def _identity(intent):
    return replace(intent, phase='READY', order_id='', code='')


def _prove_unsent(engine, intent):
    """A missing current row is insufficient: inspect the complete verified history."""
    previous = claim = None
    sequence = 0
    for event in engine.journal.replay():
        sequence += 1
        snapshot = loads(event.payload)
        if (
            event.sequence != sequence
            or not isinstance(snapshot, AppState)
            or snapshot.version != sequence
            or snapshot.environment is not Environment.BROKER_SIMULATION
        ):
            raise DomainError('daily_not_sent_unproven', 'complete same-environment state history required')
        if any(_same_key(order.key, intent) for order in snapshot.orders):
            raise DomainError('daily_not_sent_unproven', 'a canonical submission was persisted, even if later removed')
        current = next((row for row in snapshot.automatic.daily.intents if row.key == intent.key), None)
        if current is not None and _identity(current) != _identity(intent):
            raise DomainError('daily_not_sent_unproven', 'the saved identity changed')
        if event.kind == 'daily_dispatch_claimed' and current is not None and current.phase == 'CLAIMED':
            prior = next((row for row in previous.automatic.daily.intents if row.key == intent.key), None) if previous is not None else None
            if (
                claim is not None
                or prior is None
                or prior.phase != 'READY'
                or not snapshot.automatic.daily.authorized_run
                or not snapshot.automatic.daily.owner_stamp
            ):
                raise DomainError('daily_not_sent_unproven', 'a single authorized READY-to-CLAIMED transition required')
            claim = snapshot
        previous = snapshot
    if claim is None or sequence != engine.state.version:
        raise DomainError('daily_not_sent_unproven', 'missing dispatch provenance or incomplete current history')
    return claim


def _expected_side(claim, intent):
    if intent.action == 'EXIT':
        lot = next((row for row in claim.positions if row.lot_id == intent.lot_id), None)
        if lot is None or (lot.account_ref, lot.instrument_id) != (intent.account_ref, intent.instrument_id):
            raise DomainError('daily_not_sent_unproven', 'original owned exit scope required')
        return Side.SELL if lot.direction is Side.BUY else Side.BUY
    record = next((row for row in claim.strategies if (row.strategy_id, row.version) == (intent.cursor.strategy_id, intent.cursor.version)), None)
    if (
        record is None
        or record.parameters is None
        or record.parameters.bar_interval != '1d'
        or record.form.account_ref != intent.account_ref
        or record.form.environment is not Environment.BROKER_SIMULATION
    ):
        raise DomainError('daily_not_sent_unproven', 'original daily strategy scope required')
    return record.form.direction


def _broker_match(engine, intent, side, broker_order):
    if broker_order.plan.instrument_id != intent.instrument_id or broker_order.plan.side is not side:
        return False
    canonical = next((row for row in engine.state.orders if row.order_id == broker_order.local_order_id), None)
    # Complete history already ruled out this dispatch key. Exact correlation
    # therefore identifies another order, including the known TMF diagnostic.
    if canonical is not None and canonical.broker_ref == broker_order.broker_order_ref and canonical.plan == broker_order.plan:
        return False
    return True


def declare_daily_not_sent(engine, form: DailyNotSentForm, *, account_ref: str = '') -> str:
    """Owner-only conclusion; no send, reservation release, retry or implicit resume."""
    with engine.lock:
        engine.assert_execution_allowed()
        if engine.configuration.environment is not Environment.BROKER_SIMULATION or engine.storage_failed or engine.state.engine_closed:
            raise DomainError('capability_missing')
        if not isinstance(form, DailyNotSentForm) or form.confirmed is not True:
            raise DomainError('daily_not_sent_confirmation_required')
        identity(form.intent_key, 'daily intent key')
        intent = next((row for row in engine.state.automatic.daily.intents if row.key == form.intent_key), None)
        if intent is None or intent.phase not in ('CLAIMED', 'UNKNOWN') or intent.order_id:
            raise DomainError('daily_not_sent_unproven', 'an unresolved daily dispatch without canonical order required')
        if account_ref and account_ref != intent.account_ref:
            raise DomainError('state_conflict', 'selected account does not own the intent')
        guard = getattr(engine, 'automatic_submission_guard', None)
        if not callable(guard):
            raise DomainError('capability_missing', 'current owner read guard required')
        claim = _prove_unsent(engine, intent)
        side = _expected_side(claim, intent)
        with guard(intent.account_ref, reduce_only=True):
            assert_automatic_observation(engine, intent.account_ref)
            if any(not row.outcome_known for row in engine.state.manual_requests):
                raise DomainError('reconciliation_required')
            observation = engine.manual_observations[intent.account_ref]
            # No yesterday price/size was saved. Any same-side instrument order
            # remains a candidate; narrower economics would invent missing facts.
            if any(_broker_match(engine, intent, side, row) for row in observation.orders):
                raise DomainError('daily_not_sent_order_found')
            engine.fence()
            settled = replace(intent, phase='KNOWN_NO_ORDER', code='daily_declared_not_sent')
            daily = replace(
                engine.state.automatic.daily, intents=tuple(settled if row.key == intent.key else row for row in engine.state.automatic.daily.intents)
            )
            automatic = pause(replace(engine.state.automatic, daily=daily), 'reconciled_waiting_resume')
            engine._persist('daily_declared_not_sent', replace(engine.state, automatic=automatic, stopped=True))
            return intent.key
