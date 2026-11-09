"""Read-only minute research for a typed TMF intraday strategy (M2-7b stage B).

The strategy record is never changed: the host already stores the result in its own receipt store, and
this command only returns a short summary. The result cannot enable the strategy.
"""

from datetime import datetime, timedelta, timezone

from quantlab.trading.application.contracts import UiCommand, UiReceipt
from quantlab.trading.domain.minute_research import MinuteResearchSettings
from quantlab.trading.domain.models import Environment, HoldingKind, Market
from quantlab.trading.domain.strategy import is_tmf
from quantlab.trading.domain.validation import DomainError

MIN_SESSIONS = 3
MAX_SESSIONS = 20
MAXIMUM_HOLD_MINUTES = 240  # the intraday cutoff closes everything earlier
BUDGET = timedelta(minutes=15)


def _summary(settings: MinuteResearchSettings, result) -> str:
    """Pipe-separated facts; the window formats them with its own catalog text."""
    values = (
        settings.first_day.isoformat(),
        settings.last_day.isoformat(),
        settings.interval,
        str(len(result.trades)),
        *(format(value.normalize(), 'f') for value in (result.net_pnl, result.costs, result.drawdown)),
        str(result.observations),
    )
    return '|'.join(values)


def _settings(spec, calendar, record, now: datetime) -> MinuteResearchSettings:
    # Only sessions inside the current contract's life: older days would need historical contract evidence.
    sessions = tuple(s for s in calendar.sessions if s.kind == 'DAY' and spec.effective_at <= s.opens_at and s.closes_at < now)[-MAX_SESSIONS:]
    if len(sessions) < MIN_SESSIONS:
        raise DomainError('calendar_missing', 'too few closed sessions for the current contract')
    return MinuteResearchSettings(
        sessions[0].trade_date,
        sessions[-1].trade_date,
        interval=record.parameters.bar_interval,
        holding_unit='MINUTES',
        minimum=0,
        maximum=MAXIMUM_HOLD_MINUTES,
    )


def run_minute_command(bundle, command: UiCommand) -> UiReceipt:
    if type(command.expected_version) is not int or type(command.target_id) is not str or not command.target_id:
        return UiReceipt(False, 'validation_failed', '')
    try:
        if bundle.launch.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('capability_missing', 'minute research needs the broker simulation context')
        with bundle.lock:
            engine, offset = bundle.engine, bundle.version_offset
            if bundle.closing or bundle.closed or bundle.control_failed or engine is None:
                raise DomainError('capability_missing', 'active research host required')
            with engine.lock:
                if command.expected_version != engine.state.version + offset:
                    raise DomainError('state_conflict', 'stale research request')
                record = engine.strategy(command.target_id)
                if (
                    record.parameters is None
                    or record.policy.kind is not HoldingKind.INTRADAY
                    or record.form.market is not Market.INDEX_FUTURE
                    or record.parameters.bar_interval not in ('1m', '5m')
                ):
                    raise DomainError('validation_failed', 'minute research is for typed TMF intraday strategies')
                spec = engine._strategy_spec(engine.catalog.resolve(record.form.instrument_id), record)
                if not is_tmf(spec):
                    raise DomainError('validation_failed', 'minute research requires a TMF contract')
                calendar = engine._strategy_calendar(record, spec.instrument_id)
                now = engine.clock.now()
                settings = _settings(spec, calendar, record, now)
        receipt = bundle.research_minutes(record, settings, calendar=calendar, deadline=datetime.now(timezone.utc) + BUDGET)
    except DomainError as error:
        return UiReceipt(False, error.code, '')
    return UiReceipt(True, 'completed', '', _summary(settings, receipt.result))
