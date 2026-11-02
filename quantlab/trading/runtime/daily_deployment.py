"""Warm only an explicit native official-daily deployment, outside writer locks."""

from dataclasses import replace

from quantlab.trading.application.codec import loads
from quantlab.trading.application.contracts import UiReceipt
from quantlab.trading.application.daily_signal_data import uses_official_daily
from quantlab.trading.application.research import ResearchResult
from quantlab.trading.domain.daily_signal_data import DailyResearchBasis
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


def prepare_daily_deployment(bundle, command):
    engine = bundle.engine
    if engine is None or not getattr(engine, 'daily_signal_cached_only', False):
        return None
    if command.environment is Environment.LIVE or bundle.launch.environment is Environment.LIVE or engine.configuration.environment is Environment.LIVE:
        return UiReceipt(False, 'production_orders_disabled', '')
    if bundle.launch.environment is Environment.LOCAL or engine.configuration.environment is Environment.LOCAL:
        return None
    if type(command.expected_version) is not int or type(command.target_id) is not str:
        return UiReceipt(False, 'validation_failed', '')
    try:
        with bundle.lock, engine.lock:
            record = engine.strategy(command.target_id)
            if not uses_official_daily(record):
                return None
            if record.state not in ('RESEARCHED', 'DISABLED') or not record.evidence_hash:
                return None
            owner, runtime, facade = bundle.sinopac_connection, bundle.automatic_runtime, bundle.facade
            manual, launch = bundle.manual_runtime, bundle.launch
            if owner is None or runtime is None:
                raise DomainError('capability_missing')
            offset, configuration = bundle.version_offset, engine.configuration
            if (
                bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or bundle.transitioning
                or engine.state.engine_closed
                or engine.storage_failed
                or bundle.engine is not engine
                or facade.engine is not engine
                or command.expected_version != engine.state.version + offset
                or command.environment is not None
                and command.environment is not bundle.launch.environment
            ):
                raise DomainError('state_conflict')
            source = engine.daily_signal_source
            if source is None:
                raise DomainError('daily_signal_source_unverified')
            result = loads(record.research_blob) if record.research_blob else None
            if not isinstance(result, ResearchResult) or not isinstance(result.daily_basis, DailyResearchBasis):
                raise DomainError('daily_signal_source_unverified')
            calendar = engine._strategy_calendar(record, record.form.instrument_id)
            with owner.lock:
                stamp, shared = runtime.owner_stamp(), owner.shared
        try:
            source.history(record.form.instrument_id, calendar, through=result.daily_basis.end, start=result.daily_basis.start)
        except DomainError:
            raise
        except Exception:
            raise DomainError('daily_signal_source_unverified', 'official deployment source preparation failed') from None
        with bundle.lock, engine.lock, owner.lock:
            if (
                bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or bundle.transitioning
                or engine.state.engine_closed
                or engine.storage_failed
                or bundle.engine is not engine
                or bundle.facade is not facade
                or facade.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.automatic_runtime is not runtime
                or bundle.manual_runtime is not manual
                or owner.shared is not shared
                or bundle.version_offset != offset
                or engine.configuration != configuration
                or bundle.launch != launch
                or bundle.launch.environment is not Environment.BROKER_SIMULATION
                or engine.daily_signal_source is not source
                or command.expected_version != engine.state.version + offset
                or engine.strategy(command.target_id) != record
                or engine._strategy_calendar(record, record.form.instrument_id) != calendar
                or runtime.owner_stamp() != stamp
            ):
                raise DomainError('state_conflict')
            return facade.execute(replace(command, expected_version=command.expected_version - offset))
    except DomainError as error:
        return UiReceipt(False, error.code, '')
