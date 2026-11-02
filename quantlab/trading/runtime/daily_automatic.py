"""Scheduled daily waiting/continuation using current authenticated server facts."""

from quantlab.trading.application import automatic, daily_execution
from quantlab.trading.domain.automatic_calendar import calendar_for_instrument
from quantlab.trading.domain.models import OrderStatus
from quantlab.trading.domain.validation import DomainError
from .preflight import sinopac_preflight_facts


def _open(engine, *, any_market=False):
    instruments = {row.form.instrument_id for row in engine.state.strategies if row.parameters is not None and row.state == 'ACTIVE'}
    instruments.update(lot.instrument_id for lot in engine.state.positions if lot.quantity)
    open_markets = []
    for instrument in instruments:
        calendar = calendar_for_instrument(engine.calendar, engine.catalog.resolve(instrument))
        session = calendar.day_session(engine.state.trading_day)
        open_markets.append(session.opens_at <= engine.clock.now() < session.closes_at)
    return bool(open_markets) and (any(open_markets) if any_market else all(open_markets))


def route_daily(runtime, engine, batches):
    """Return whether current completed minute strategies may run this pump."""
    try:
        stamp = runtime.owner_stamp()
        daily = engine.state.automatic.daily
        if daily.authorized_run and daily.owner_stamp != stamp:
            raise DomainError('state_conflict', 'saved run belongs to another authenticated owner')
        if any(order.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING) for order in engine.state.orders):
            raise DomainError('order_result_unknown')
        if any(not request.outcome_known for request in engine.state.manual_requests):
            raise DomainError('order_result_unknown')
        if not _open(engine):
            for _, _, _, bars in batches:
                daily_execution.observe_daily(engine, bars)
            observations = getattr(engine, 'manual_observations', {})
            if (
                not batches
                and set(observations) == set(engine.gateways)
                and all(0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30 for row in observations.values())
            ):
                daily_execution.observe_daily(engine, ())
            daily_execution.wait_session(engine)
            return _open(engine, any_market=True) and not engine.state.automatic.auto_paused
        try:
            facts = tuple((ref, sinopac_preflight_facts(runtime.bundle, ref)) for ref in sorted(engine.gateways))
        except DomainError as error:
            if daily.waiting_session and error.code == 'capability_missing':
                return False  # The same owner is awaiting a fresh bounded resource refresh.
            raise
        cache_ready = all(
            proof.connected is True and proof.account_ready is True and proof.permission_ready is True and proof.reconciled is True for _, proof in facts
        )
        if cache_ready:
            for _, _, _, bars in batches:
                daily_execution.observe_daily(engine, bars)
            if not batches:
                daily_execution.observe_daily(engine, ())
        elif not daily.waiting_session:
            raise DomainError('preflight_reconciliation')
        if engine.state.automatic.auto_paused:
            return False
        if not engine.state.automatic.daily.authorized_run:
            raise DomainError('daily_signal_not_authorized')
        ready = all(proof.realtime is True and proof.service_open is True for _, proof in facts) and cache_ready
        if not ready:
            if not engine.state.automatic.daily.waiting_session:
                raise DomainError(runtime._health_reason(engine) or 'preflight_market')
            return False  # Await the first complete current-day quote/observation batch.
        if engine.state.automatic.daily.waiting_session:
            daily_execution.continue_daily_session(engine, facts)
        daily_execution.dispatch_daily(engine)
        return not engine.state.automatic.auto_paused
    except DomainError as error:
        automatic.pause_automatic(engine, error.code)
        return False
