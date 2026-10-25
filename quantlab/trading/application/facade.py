"""The presentation's only application command entry point."""

from dataclasses import replace
from decimal import Decimal
from time import perf_counter

from .contracts import UiAction, UiCommand, UiReceipt, UiState
from .broker_settings import BrokerSettings, check_readiness
from .engine import TradingEngine
from .events import reconcile
from .views import snapshot
from .workflows import cancel_entries, execute_day, fill_local_pending, resume, run_research, step, transfer
from .errors import ERROR_TABLE
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.validation import DomainError


class LocalFacade:
    def __init__(self, engine: TradingEngine):
        self.engine = engine

    def snapshot(self) -> UiState:
        with self.engine.lock:
            return snapshot(self.engine)

    @decimal_operation
    def execute(self, command: UiCommand) -> UiReceipt:
        started = perf_counter()
        engine = self.engine
        with engine.lock:
            try:
                if not isinstance(command, UiCommand) or not isinstance(command.action, UiAction) or type(command.expected_version) is not int:
                    raise DomainError('validation_failed', 'typed UI command required')
                if command.expected_version != engine.state.version:
                    raise DomainError('state_conflict', 'refresh before issuing another command')
                if engine.state.engine_closed and command.action is not UiAction.RECONCILE:
                    raise DomainError('state_conflict', 'engine is closed')
                reference = self._execute(command)
                return UiReceipt(True, 'completed', '', reference or '')
            except DomainError as exc:
                entry = ERROR_TABLE.get(exc.code, ERROR_TABLE['operation_failed'])
                return UiReceipt(False, exc.code, entry.explanation + ' ' + entry.action)
            except (OSError, ArithmeticError, ValueError):
                entry = ERROR_TABLE['operation_failed']
                return UiReceipt(False, 'operation_failed', entry.explanation + ' ' + entry.action)
            finally:
                engine.latencies.append(perf_counter() - started)

    def _execute(self, command: UiCommand) -> str:
        engine, action = self.engine, command.action
        if action is UiAction.CREATE_STRATEGY:
            if command.strategy is None:
                raise DomainError('validation_failed')
            return engine.create_strategy(command.strategy)
        if action is UiAction.VALIDATE:
            engine.validate_strategy(command.target_id)
        elif action is UiAction.RESEARCH:
            strategy = engine.strategy(command.target_id)
            run_research(engine, command.target_id, engine.history.get(strategy.form.instrument_id, ()))
        elif action is UiAction.DEPLOY:
            engine.deploy(command.target_id)
        elif action is UiAction.RECONCILE:
            reconcile(engine)
        elif action is UiAction.RESUME:
            resume(engine)
        elif action is UiAction.STOP_NEW:
            engine._persist('new_entries_stopped', replace(engine.state, stopped=True))
            cancel_entries(engine)
        elif action is UiAction.CANCEL_ENTRIES:
            cancel_entries(engine)
        elif action is UiAction.FLATTEN:
            if not command.target_id:
                raise DomainError('validation_failed', 'explicit managed lot required')
            result = engine.exit_lot(command.target_id, protective=True)
            if result is None:
                raise DomainError('exit_unavailable', 'no executable unreserved quantity')
            fill_local_pending(engine)
        elif action is UiAction.TRANSFER:
            transfer(engine, command.target_id, command.destination_strategy_id)
        elif action is UiAction.STEP:
            was_running = not engine.state.stopped
            step(engine, engine.history)
            if was_running:
                resume(engine)
            execute_day(engine, engine.history, allow_entries=was_running)
        elif action is UiAction.SAVE_SETTINGS:
            settings = command.settings
            if settings is None or any(type(v) is not Decimal or not v.is_finite() or v < 0 for v in (settings.stock_allocation, settings.futures_allocation)):
                raise DomainError('validation_failed', 'Decimal allocations required')
            if settings.stock_allocation + settings.futures_allocation > Decimal('100000') or settings.night_enabled:
                raise DomainError('risk_rejected', 'single budget and day-only local policy')
            from quantlab.trading.domain.risk import RiskPolicy

            RiskPolicy(trade_fraction=settings.risk_fraction, daily_fraction=settings.daily_loss_fraction)
            for ref, allocated in (
                (engine.configuration.stock_account_ref, settings.stock_allocation),
                (engine.configuration.futures_account_ref, settings.futures_allocation),
            ):
                if ref not in engine.gateways:
                    continue
                broker = engine.gateways[ref].snapshot(ref)
                reserved = sum((r.cash for r in engine.reservations() if r.account_ref == ref), Decimal('0'))
                used = broker.margin_used + reserved + max(Decimal('0'), broker.equity - broker.settled_cash)
                if allocated < used:
                    raise DomainError('risk_rejected', 'allocation cannot abandon owned commitments')
            engine._persist('settings_changed', replace(engine.state, settings=settings))
        elif action is UiAction.SWITCH_CONTEXT:
            if command.environment is not engine.configuration.environment or command.account_ref not in engine.gateways:
                raise DomainError('capability_missing', 'external account setup and evidence required')
            engine._persist('view_context_changed', replace(engine.state, account_ref=command.account_ref, environment=command.environment))
        elif action is UiAction.SAVE_BROKER_SETTINGS:
            settings = command.broker_settings
            if not isinstance(settings, BrokerSettings) or not settings.read_only or settings.execution_enabled:
                raise DomainError('capability_missing', 'broker settings remain read-only and execution disabled')
            engine._persist('broker_reference_settings_saved', replace(engine.state, broker_settings=settings, broker_readiness=None))
        elif action is UiAction.CHECK_READINESS:
            if engine.reference_inspector is None:
                raise DomainError('capability_missing', 'reference metadata inspector unavailable')
            readiness = check_readiness(engine.state.broker_settings, engine.reference_inspector, engine.clock.now())
            engine._persist('broker_metadata_readiness_checked', replace(engine.state, broker_readiness=readiness))
        elif action is UiAction.SHUTDOWN_ENGINE:
            # Distinct from flatten/cancel. Pending ownership is retained, and the
            # next startup always requires a fresh reconciliation and resume.
            engine._persist('engine_shutdown_requested', replace(engine.state, stopped=True, engine_closed=True))
        else:
            raise DomainError('validation_failed', 'unknown command')
        return ''
