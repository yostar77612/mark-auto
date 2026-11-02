"""Queue completed market bars and bind automatic controls to current owner facts."""

from collections import deque
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import timedelta
from threading import Lock
from hashlib import sha256

from quantlab.trading.application.contracts import UiAction, UiCommand, UiReceipt
from quantlab.trading.application.codec import dumps
from quantlab.trading.domain.live_bars import LiveBar, compose_minute, finalize_minute
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.strategy import is_tmf
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.ports.manual import ManualAccountObservation
from .preflight import sinopac_preflight_facts

MAX_QUEUED_BATCHES = 4096
MAX_BATCH_BARS = 4096
AUTOMATIC_ACTIONS = frozenset((UiAction.AUTO_RESUME, UiAction.AUTO_RECONCILE))


def _facts_reason(facts):
    for key, code in (
        ('connected', 'preflight_connection'),
        ('account_ready', 'preflight_account'),
        ('permission_ready', 'preflight_permission'),
        ('realtime', 'preflight_market'),
        ('service_open', 'preflight_service'),
        ('reconciled', 'preflight_reconciliation'),
    ):
        if getattr(facts, key) is not True:
            return code
    return ''


class AutomaticRuntime:
    """Market callbacks hold only the queue lock; engine work follows terminal.poll."""

    def __init__(self, bundle):
        self.bundle = bundle
        self.queue_lock = Lock()
        self.queue = deque()
        self.overflow = False
        self.terminal = None
        self.future_stamp = None
        self.future_minutes = {}
        self.future_losses = {}

    def owner_stamp(self):
        """Bind a run to the authenticated owner; closed-market quotes are irrelevant."""
        bundle = self.bundle
        engine, owner, manual = bundle.engine, bundle.sinopac_connection, bundle.manual_runtime
        if bundle.launch.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if bundle.launch.environment is Environment.LIVE else 'capability_missing')
        if engine is None or owner is None or manual is None or manual.owner is not owner:
            raise DomainError('capability_missing')
        with engine.lock, owner.lock:
            view = owner.snapshot()
            selected = tuple(sorted(owner.selected))
            if (
                bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or bundle.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.manual_runtime is not manual
                or view.phase != 'CONNECTED'
                or view.environment is not Environment.BROKER_SIMULATION
                or not owner.query_ready
                or owner.shared is None
                or owner.shared.callback_errors
                or manual.error
                or manual.stamp != (view.generation, view.revision, selected, owner.shared)
                or any(not any(account.alias == ref and account.signed is True for account in view.accounts) for ref in selected)
            ):
                raise DomainError('state_conflict', 'automatic run owner changed or became unavailable')
            return sha256(dumps((view.environment, view.generation, view.revision, selected)).encode()).hexdigest()

    def attach_terminal(self):
        terminal = self.bundle.market_terminal
        if terminal is None or terminal is self.terminal:
            return
        old_tick, old_bars = terminal.on_tick, terminal.on_bars

        def on_tick(tick, bars):
            old_tick(tick, bars)
            self._enqueue(bars)

        def on_bars(instrument_id, bars, now, trade_date):
            old_bars(instrument_id, bars, now, trade_date)
            self._enqueue(bars)

        terminal.on_tick, terminal.on_bars = on_tick, on_bars
        self.terminal = terminal

    def _enqueue(self, bars):
        completed = tuple(bar for bar in bars if isinstance(bar, LiveBar) and bar.final and not bar.incomplete)
        if not completed:
            return
        bundle = self.bundle
        manual = bundle.manual_runtime
        batch = bundle.engine, bundle.sinopac_connection, manual.stamp if manual is not None else None, completed
        with self.queue_lock:
            if len(self.queue) >= MAX_QUEUED_BATCHES or len(completed) > MAX_BATCH_BARS:
                self.overflow = True
                self.queue.clear()
                return
            if not self.overflow:
                self.queue.append(batch)

    def handles(self, command):
        return isinstance(command, UiCommand) and command.action in AUTOMATIC_ACTIONS

    def pump_futures(self, adapter):
        """Drain only execution-consumer TMF ticks; never query or subscribe here."""
        bundle, engine, manual = self.bundle, self.bundle.engine, self.bundle.manual_runtime
        if bundle.launch.environment is not Environment.BROKER_SIMULATION or engine is None or manual is None or adapter is None:
            return
        with bundle.lock, engine.lock:
            if (
                bundle.engine is not engine
                or bundle.manual_runtime is not manual
                or manual.adapter is not adapter
                or bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or not any(row.parameters is not None for row in engine.state.strategies)
            ):
                return
            stream = adapter.tick_stream
            if stream is None or not adapter.connected or adapter.environment is not Environment.BROKER_SIMULATION:
                return
            selected = {key for group in adapter.subscriptions.values() for key in group if key in adapter.bindings and is_tmf(adapter.bindings[key].spec)}
            if not selected:
                return
            stamp = adapter, engine, manual.stamp
            if self.future_stamp is None or self.future_stamp[0] is not adapter or self.future_stamp[1] is not engine or self.future_stamp[2] != manual.stamp:
                self.future_stamp, self.future_minutes, self.future_losses = stamp, {}, {}
            self.future_minutes = {key: state for key, state in self.future_minutes.items() if key in selected}
            self.future_losses = {key: loss for key, loss in self.future_losses.items() if key in selected}
            for loss in stream.drain_tick_losses():
                if loss.instrument_id not in selected:
                    continue
                previous = self.future_losses.get(loss.instrument_id)
                first = min(previous[0], loss.first_source_at) if previous else loss.first_source_at
                last = max(previous[1], loss.last_source_at) if previous else loss.last_source_at
                self.future_losses[loss.instrument_id] = first, last
                state = self.future_minutes.get(loss.instrument_id)
                if state is not None and first < state.bar.end and last >= state.bar.start:
                    self.future_minutes[loss.instrument_id] = replace(state, bar=replace(state.bar, incomplete=True))
                with self.queue_lock:
                    self.overflow = True
                    self.queue.clear()
            for tick in stream.drain_ticks(stream.limit):
                if tick.instrument_id not in selected:
                    continue
                start = tick.source_at.replace(second=0, microsecond=0)
                loss = self.future_losses.get(tick.instrument_id)
                incomplete = loss is not None and loss[0] < start + timedelta(minutes=1) and loss[1] >= start
                update = compose_minute(self.future_minutes.get(tick.instrument_id), tick, incomplete=incomplete)
                self.future_minutes[tick.instrument_id] = update.state
                self._enqueue(update.finalized)
                if loss is not None and start > loss[1]:
                    self.future_losses.pop(tick.instrument_id)
            for key, state in tuple(self.future_minutes.items()):
                final = finalize_minute(state, now=engine.clock.now())
                if final.bar.final and not state.bar.final:
                    self.future_minutes[key] = final
                    self._enqueue((final.bar,))

    def validate_observation(self, account_ref, row):
        """Accept only the worker's current immutable cache, never query broker facts."""
        bundle = self.bundle
        owner, manual, engine = bundle.sinopac_connection, bundle.manual_runtime, bundle.engine
        if bundle.launch.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if bundle.launch.environment is Environment.LIVE else 'manual_account_observation_required')
        if owner is None or manual is None or engine is None or manual.owner is not owner:
            raise DomainError('manual_account_observation_required')
        # submit already holds engine.lock; never acquire the outer bundle lock here.
        with engine.lock, owner.lock:
            if bundle.engine is not engine or bundle.sinopac_connection is not owner or bundle.manual_runtime is not manual:
                raise DomainError('state_conflict')
            view = owner.snapshot()
            selected, shared = tuple(sorted(owner.selected)), owner.shared
            owner.preferences.check_selection(selected)
            protective = getattr(engine, 'manual_protective_observations', {}).get(account_ref) is row and row is not None
            if (
                view.phase != 'CONNECTED'
                or view.environment is not Environment.BROKER_SIMULATION
                or not owner.query_ready
                or shared is None
                or shared.callback_errors
                or bundle.closing
                or bundle.resources_closed
                or manual.error
                and (not protective or getattr(manual, 'protective_stamp', None) != manual.stamp)
            ):
                raise DomainError('manual_account_observation_required')
            if manual.stamp != (view.generation, view.revision, selected, shared) or account_ref not in selected:
                raise DomainError('state_conflict')
            account = next((account for account in view.accounts if account.alias == account_ref), None)
            if account is None or account.signed is not True:
                raise DomainError('account_not_signed' if account is not None and account.signed is False else 'account_sign_unknown')
            if (
                not isinstance(row, ManualAccountObservation)
                or row.account_ref != account_ref
                or row.environment is not Environment.BROKER_SIMULATION
                or row.source != 'SHIOAJI_SCOPED_REFRESH_HEALTHY'
                or engine.manual_observations.get(account_ref) is not row
                and not protective
                or not 0 <= (engine.clock.now() - row.as_of).total_seconds() <= 30
            ):
                raise DomainError('manual_account_observation_required')
        return True

    @contextmanager
    def submission_guard(self, account_ref, *, reduce_only=False):
        """Hold current owner epoch across the existing bounded execution call."""
        bundle = self.bundle
        engine, owner, manual = bundle.engine, bundle.sinopac_connection, bundle.manual_runtime
        if bundle.launch.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if bundle.launch.environment is Environment.LIVE else 'capability_missing')
        if engine is None or owner is None or manual is None:
            raise DomainError('capability_missing')
        with engine.lock, owner.lock:
            if (
                bundle.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.manual_runtime is not manual
                or bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
            ):
                raise DomainError('state_conflict')
            view = owner.snapshot()
            stamp = view.environment, view.generation, view.revision, tuple(sorted(owner.selected)), owner.shared
            if reduce_only:
                row = engine.manual_observations.get(account_ref) or getattr(engine, 'manual_protective_observations', {}).get(account_ref)
                self.validate_observation(account_ref, row)
            else:
                self.validate_entry(account_ref)
            current = owner.snapshot()
            if (
                bundle.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.manual_runtime is not manual
                or stamp != (current.environment, current.generation, current.revision, tuple(sorted(owner.selected)), owner.shared)
            ):
                raise DomainError('state_conflict')
            yield

    def validate_entry(self, account_ref):
        """Final cache-only admission for new risk; a prior preflight PASS is insufficient."""
        bundle = self.bundle
        engine, owner, manual = bundle.engine, bundle.sinopac_connection, bundle.manual_runtime
        if bundle.launch.environment is not Environment.BROKER_SIMULATION:
            raise DomainError('production_orders_disabled' if bundle.launch.environment is Environment.LIVE else 'capability_missing')
        if engine is None or owner is None or manual is None:
            raise DomainError('capability_missing')
        # Called by submit under engine.lock; never invert through bundle.lock.
        with engine.lock, owner.lock:
            if (
                bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or bundle.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.manual_runtime is not manual
                or manual.owner is not owner
            ):
                raise DomainError('state_conflict')
            view = owner.snapshot()
            stamp = view.environment, view.generation, view.revision, tuple(sorted(owner.selected)), owner.shared
            facts = sinopac_preflight_facts(bundle, account_ref)
            current = owner.snapshot()
            if (
                bundle.closing
                or bundle.resources_closed
                or bundle.control_failed
                or bundle.engine is not engine
                or bundle.sinopac_connection is not owner
                or bundle.manual_runtime is not manual
                or stamp != (current.environment, current.generation, current.revision, tuple(sorted(owner.selected)), owner.shared)
            ):
                raise DomainError('state_conflict')
            reason = _facts_reason(facts)
            if reason:
                raise DomainError(reason)
        return True

    def _health_reason(self, engine):
        for reference in sorted({row.form.account_ref for row in engine.state.strategies if row.parameters is not None}):
            reason = _facts_reason(sinopac_preflight_facts(self.bundle, reference))
            if reason:
                return reason
        return ''

    def execute(self, command):
        from quantlab.trading.application import automatic

        bundle = self.bundle
        if (
            not self.handles(command)
            or type(command.action) is not UiAction
            or type(command.expected_version) is not int
            or type(command.account_ref) is not str
            or type(command.manual_no_admission) is not bool
            or command.manual_no_admission
        ):
            return UiReceipt(False, 'validation_failed', '')
        if command.environment is Environment.LIVE or bundle.launch.environment is Environment.LIVE:
            return UiReceipt(False, 'production_orders_disabled', '')
        if bundle.launch.environment is Environment.LOCAL:
            return UiReceipt(False, 'capability_missing', '')
        if command.environment is not None and command.environment is not bundle.launch.environment:
            return UiReceipt(False, 'state_conflict', '')
        engine, owner, offset = bundle.engine, bundle.sinopac_connection, bundle.version_offset
        if engine is None:
            return UiReceipt(False, 'capability_missing', '')
        try:
            with bundle.lock, engine.lock, owner.lock if owner is not None else nullcontext():
                if (
                    bundle.closing
                    or bundle.resources_closed
                    or bundle.control_failed
                    or bundle.engine is not engine
                    or bundle.sinopac_connection is not owner
                    or bundle.version_offset != offset
                    or command.expected_version != engine.state.version + offset
                    or command.account_ref
                    and command.account_ref not in engine.gateways
                ):
                    raise DomainError('state_conflict')
                if command.action is UiAction.AUTO_RESUME:
                    reason = self._health_reason(engine)
                    if reason:
                        automatic.pause_automatic(engine, reason)
                        raise DomainError(reason)
                    from quantlab.trading.application.daily_execution import records

                    if records(engine):
                        from quantlab.trading.application.preflight import record_preflight

                        for reference in sorted(engine.gateways):
                            if not any(row.account_ref == reference and row.trade_date == engine.state.trading_day for row in engine.state.preflight):
                                record_preflight(engine, reference, sinopac_preflight_facts(bundle, reference))
                    automatic.resume_automatic(engine)
                else:
                    automatic.reconcile_automatic(engine)
            return UiReceipt(True, 'completed', '')
        except DomainError as error:
            return UiReceipt(False, error.code, '')

    def pump(self):
        from quantlab.trading.application import automatic

        with self.queue_lock:
            batches, overflow = tuple(self.queue), self.overflow
            self.queue.clear()
            self.overflow = False
        bundle = self.bundle
        engine, owner = bundle.engine, bundle.sinopac_connection
        if engine is None or not any(row.parameters is not None for row in engine.state.strategies):
            return
        if bundle.closing or bundle.resources_closed or bundle.control_failed or engine.state.engine_closed or engine.storage_failed:
            return
        with bundle.lock, engine.lock, owner.lock if owner is not None else nullcontext():
            if bundle.engine is not engine or bundle.sinopac_connection is not owner:
                return
            if bundle.launch.environment in (Environment.LOCAL, Environment.LIVE):
                return
            manual = bundle.manual_runtime
            stamp = manual.stamp if manual is not None else None
            if overflow or any(old_engine is not engine or old_owner is not owner or old_stamp != stamp for old_engine, old_owner, old_stamp, _ in batches):
                automatic.pause_automatic(engine, 'automatic_market_gap')
                automatic.pump_automatic(engine)
                return
            from quantlab.trading.application.daily_execution import records

            if records(engine):
                from .daily_automatic import route_daily

                if route_daily(self, engine, batches):
                    for _, _, _, bars in batches:
                        automatic.on_completed_bars(engine, bars)
                automatic.pump_automatic(engine)
                return
            try:
                reason = self._health_reason(engine)
                daily = engine.state.automatic.daily
                if not reason and daily.authorized_run and daily.owner_stamp != self.owner_stamp():
                    raise DomainError('state_conflict', 'automatic run belongs to a different authenticated owner')
            except DomainError as error:
                reason = error.code
            if reason:
                automatic.pause_automatic(engine, reason)
            if not reason and bundle.launch.environment is Environment.BROKER_SIMULATION:
                for _, _, _, bars in batches:
                    automatic.on_completed_bars(engine, bars)
            automatic.pump_automatic(engine)
