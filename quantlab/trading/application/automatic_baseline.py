"""Accept existing attested close evidence without broker-financial queries."""

from dataclasses import replace
from typing import TYPE_CHECKING

from .account_risk import account_net_mark
from .automatic_capacity import assert_automatic_observation
from .automatic_state import pause
from .sessions import DailyBaselineEvidence, resolve_session, synchronize_session, validate_baseline
from quantlab.trading.domain.automatic_calendar import automatic_day_calendar
from quantlab.trading.domain.models import Environment, Market
from quantlab.trading.domain.risk import AccountDailyBaseline
from quantlab.trading.domain.strategy import is_tmf
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.arithmetic import decimal_operation

if TYPE_CHECKING:
    from .engine import TradingEngine


@decimal_operation
def confirm_automatic_baseline(engine: 'TradingEngine', evidence: DailyBaselineEvidence, *, trusted_sources: frozenset[str]) -> None:
    """Trusted provider only; there is no command carrying evidence/source grants."""
    with engine.lock:
        engine.assert_execution_allowed()
        if engine.configuration.environment is not Environment.BROKER_SIMULATION or not engine.state.manual_books:
            raise DomainError('capability_missing', 'confirmed shared SIM books required')
        synchronize_session(engine)
        calendar = automatic_day_calendar(engine.calendar, tuple(spec for spec in engine.catalog.instruments if spec.market is Market.STOCK or is_tmf(spec)))
        context = resolve_session(calendar, engine.clock.now())
        validate_baseline(
            evidence,
            environment=engine.configuration.environment,
            account_refs=tuple(engine.gateways),
            calendar=calendar,
            fees=engine.fees,
            now=engine.clock.now(),
            trade_date=context.trade_date,
            trusted_sources=trusted_sources,
        )
        if engine.state.trading_day != context.trade_date:
            raise DomainError('account_daily_baseline_required', 'calendar rollback requires investigation')
        splits = evidence.account_previous_close
        if not splits and len(evidence.account_refs) == 1:
            splits = ((evidence.account_refs[0], evidence.previous_close_total_pnl),)
        if tuple(reference for reference, _ in splits) != tuple(sorted(engine.gateways)):
            raise DomainError('account_daily_baseline_required', 'exact account close attribution required')
        assert_automatic_observation(engine, evidence.account_refs[0])
        rows = engine.state.account_daily_baselines
        for reference, value in splits:
            account_net_mark(engine, reference)  # Unknown current marks cannot validate a close.
            previous = next((row for row in rows if row.account_ref == reference and row.trade_date == context.trade_date), None)
            if previous is not None and previous.previous_close_pnl != value:
                raise DomainError('state_conflict', 'same-day account baseline is immutable')
            rows = (*tuple(row for row in rows if row.account_ref != reference), AccountDailyBaseline(reference, context.trade_date, value, evidence.source_id))
        engine._persist(
            'automatic_account_closes_attested',
            replace(
                engine.state,
                account_daily_baselines=rows,
                automatic_daily_evidence=evidence,
                stopped=True,
                automatic=pause(engine.state.automatic, 'reconciled_waiting_resume'),
                issues=tuple(code for code in engine.state.issues if code != 'account_daily_baseline_required'),
            ),
        )
