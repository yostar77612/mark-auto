"""Schedule shared market application work; no threads, SDK or transport logic."""

from dataclasses import replace
from typing import TYPE_CHECKING

from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine


def poll_market(engine: 'TradingEngine') -> None:
    """Allocate strategy subscriptions first and pass verified session facts."""
    service = engine.live_market
    if service is None:
        return
    strategies = tuple(record.form.instrument_id for record in engine.state.strategies if record.state == 'ACTIVE')
    watches = tuple(spec.instrument_id for spec in engine.catalog.instruments)
    try:
        service.allocate(strategies, watches)
        try:
            engine.calendar.session_at(engine.clock.now(), allow_night=True)
            in_session = True
        except DomainError as exc:
            if exc.code != 'session_closed':
                raise
            in_session = False
        service.poll(in_session=in_session)
    except DomainError as exc:
        # The host's existing coordinator catches typed failures; publish the
        # issue first so a failed drain/allocation cannot disappear there.
        if exc.code not in engine.state.issues:
            engine._persist('live_market_requires_attention', replace(engine.state, issues=tuple(sorted((*engine.state.issues, exc.code)))))
        raise
