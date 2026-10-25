"""Recoverable company-action and actual two-leg contract roll orchestration."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from typing import TYPE_CHECKING

from .context import Catalog
from .lifecycle_models import CorporateActionJob, RollJob
from .state import ACTIVE, StrategyRecord, replace_order
from quantlab.trading.domain.lifecycle import CorporateAction, apply_corporate_action, plan_expiry
from quantlab.trading.domain.arithmetic import decimal_operation
from quantlab.trading.domain.models import Environment, InstrumentSpec, Market, OrderPlan, OrderStatus, Side
from quantlab.trading.domain.validation import DomainError

if TYPE_CHECKING:
    from .engine import TradingEngine

ZERO = Decimal('0')


def _issue(engine: 'TradingEngine', code: str) -> None:
    engine._persist('lifecycle_attention', replace(engine.state, stopped=True, reconciled=False, issues=tuple(sorted(set((*engine.state.issues, code))))))


def _action_job(engine: 'TradingEngine', job: CorporateActionJob, kind: str) -> None:
    others = tuple(j for j in engine.state.corporate_actions if j.job_id != job.job_id)
    engine._persist(kind, replace(engine.state, corporate_actions=(*others, job)))


def _roll_job(engine: 'TradingEngine', job: RollJob, kind: str) -> None:
    others = tuple(j for j in engine.state.rolls if j.job_id != job.job_id)
    engine._persist(kind, replace(engine.state, rolls=(*others, job)))


@decimal_operation
def schedule_corporate_action(engine: 'TradingEngine', instrument_id: str, new_spec: InstrumentSpec, action: CorporateAction) -> str:
    if engine.simulation is None or engine.state.environment is not Environment.LOCAL:
        raise DomainError('capability_missing', 'local corporate-action workflow only')
    prior = next((j for j in engine.state.corporate_actions if j.job_id == action.action_id), None)
    if prior:
        if prior.new_spec != new_spec or prior.action != action or prior.instrument_id != instrument_id:
            raise DomainError('state_conflict', 'corporate action identity conflict')
        return prior.job_id
    old_spec = engine.catalog.resolve(instrument_id)
    lots = tuple(p for p in engine.state.positions if p.instrument_id == instrument_id and p.quantity)
    if not engine.state.reconciled or not lots or len({p.account_ref for p in lots}) != 1 or any(p.origin != 'MANAGED' for p in lots):
        _issue(engine, 'reconciliation_required')
        raise DomainError('reconciliation_required', 'reconciled managed corporate action scope required')
    if any(o.status in ACTIVE and o.plan.instrument_id == instrument_id for o in engine.state.orders):
        _issue(engine, 'reconciliation_required')
        raise DomainError('reconciliation_required', 'outstanding orders need broker action reconciliation')
    results = tuple(apply_corporate_action(p, old_spec, new_spec, action, now=engine.clock.now()) for p in lots)
    after = tuple(replace(r.lot, realized_pnl=r.lot.realized_pnl + r.receivable) for r in results)
    receivable = sum((r.receivable for r in results), ZERO)
    job = CorporateActionJob(action.action_id, lots[0].account_ref, instrument_id, old_spec, new_spec, action, lots, after, receivable)
    _action_job(engine, job, 'corporate_action_prepared')
    engine.fence()
    try:
        engine.simulation.apply_corporate_action(
            job.job_id, instrument_id, new_spec, action.quantity_ratio, receivable, action.cash_payable_date, account_ref=job.account_ref
        )
        if not engine.simulation.corporate_action_applied(job.job_id, job.account_ref):
            raise DomainError('outcome_unknown')
        _confirm_action(engine, job)
    except Exception:
        # A PREPARED record is enough to recover if even this UNKNOWN write fails.
        if not engine.storage_failed:
            confirmed = any(j.job_id == job.job_id and j.status == 'APPLIED' for j in engine.state.corporate_actions)
            if not confirmed:
                _action_job(engine, replace(job, status='UNKNOWN', error='outcome_unknown'), 'corporate_action_unknown')
            _issue(engine, 'reconciliation_required')
        raise
    return job.job_id


@decimal_operation
def _confirm_action(engine: 'TradingEngine', job: CorporateActionJob) -> None:
    if any(j.job_id == job.job_id and j.status == 'APPLIED' for j in engine.state.corporate_actions):
        return
    remote = engine.gateways[job.account_ref].refresh(job.account_ref)
    expected = sum((p.quantity * (1 if p.direction is Side.BUY else -1) for p in job.after_lots), 0)
    observed = next((p.quantity for p in remote.positions if p.instrument_id == job.instrument_id), 0)
    if expected != observed:
        raise DomainError('reconciliation_required', 'corporate action broker quantity mismatch')
    factor = job.old_spec.multiplier / (job.action.quantity_ratio * job.new_spec.multiplier)
    stops = dict(engine.state.protection_stops)
    state = engine.state
    for before, after in zip(job.before_lots, job.after_lots):
        order = next(o for o in state.orders if o.order_id == before.lot_id)
        stop = (stops.get(before.lot_id, order.plan.stop_price) - job.action.cash_per_old_unit) * factor
        job.new_spec.validate_price(stop)
        stops[before.lot_id] = stop
        risk = engine.fees.loss_at_stop(job.new_spec, after.risk_entry_price or after.entry_price, stop, after.quantity, after.direction)
        state = replace_order(state, replace(order, reservation=replace(order.reservation, quantity=after.quantity, risk=risk)))
    ids = {p.lot_id for p in job.after_lots}
    positions = tuple(p for p in state.positions if p.lot_id not in ids) + job.after_lots
    overrides = tuple(s for s in state.instrument_overrides if s.instrument_id != job.instrument_id) + (job.new_spec,)
    jobs = tuple(replace(j, status='APPLIED', error='') if j.job_id == job.job_id else j for j in state.corporate_actions)
    engine._persist(
        'corporate_action_confirmed',
        replace(
            state,
            positions=positions,
            protection_stops=tuple(stops.items()),
            instrument_overrides=overrides,
            corporate_actions=jobs,
            realized_pnl=state.realized_pnl + job.receivable,
        ),
    )
    engine.catalog = Catalog(tuple(job.new_spec if s.instrument_id == job.instrument_id else s for s in engine.catalog.instruments))
    engine.quotes.pop(job.instrument_id, None)
    engine.simulation.rebuild_history(engine)


def recover_corporate_actions(engine: 'TradingEngine') -> None:
    if engine.simulation is None:
        return
    for job in tuple(engine.state.corporate_actions):
        if job.status not in ('PREPARED', 'UNKNOWN'):
            continue
        try:
            if engine.simulation.corporate_action_applied(job.job_id, job.account_ref):
                _confirm_action(engine, job)
            else:
                _issue(engine, 'reconciliation_required')
        except DomainError:
            _issue(engine, 'reconciliation_required')
            raise


def _close_plan(engine: 'TradingEngine', job: RollJob) -> OrderPlan:
    lot = job.source_lot
    quote = engine.quotes[lot.instrument_id]
    side = Side.SELL if lot.direction is Side.BUY else Side.BUY
    price = quote.bid if side is Side.SELL else quote.ask
    return OrderPlan(
        'roll-close:' + job.job_id,
        lot.account_ref,
        engine.configuration.environment,
        lot.instrument_id,
        lot.strategy_id,
        lot.strategy_version,
        side,
        lot.quantity,
        engine.catalog.resolve(lot.instrument_id).unit,
        price,
        price,
        True,
        engine.clock.now(),
        engine.clock.now() + timedelta(seconds=30),
        engine.state.version + 1,
        lot.lot_id,
    )


def _prepare_roll(engine: 'TradingEngine', lot) -> RollJob | None:
    record = engine.strategy(f'{lot.strategy_id}:{lot.strategy_version}')
    spec = engine.catalog.resolve(lot.instrument_id)
    target = engine.catalog.resolve(record.form.roll_contract_id) if record.form.roll_contract_id else None
    current_quote = engine.quotes[lot.instrument_id]
    next_quote = engine.quotes.get(target.instrument_id) if target else None
    plan = plan_expiry(
        lot,
        spec,
        target,
        engine.calendar,
        now=engine.clock.now(),
        close_price=current_quote.bid if lot.direction is Side.BUY else current_quote.ask,
        open_price=(next_quote.ask if lot.direction is Side.BUY else next_quote.bid) if next_quote else None,
        fees=engine.fees,
    )
    if plan is None:
        return None
    if plan.action != 'ROLL':
        engine.update_strategy(replace(record, state='RETIRED'), 'expiry_exit_source_retired')
        engine.exit_lot(lot.lot_id, protective=True)
        return None
    if any(o.status in ACTIVE and o.plan.instrument_id == lot.instrument_id for o in engine.state.orders):
        raise DomainError('reconciliation_required', 'roll conflicts with an active order')
    job_id = sha256(f'{lot.lot_id}:{target.instrument_id}'.encode()).hexdigest()
    job = RollJob(job_id, lot.lot_id, lot.instrument_id, target.instrument_id, lot.quantity, lot)
    engine.update_strategy(replace(record, state='RETIRED'), 'roll_source_retired')
    job = replace(job, close_plan=_close_plan(engine, job))
    _roll_job(engine, job, 'roll_close_prepared')
    return job


def _progress_close(engine: 'TradingEngine', job: RollJob) -> RollJob:
    order = next((o for o in engine.state.orders if o.key == 'roll-close:' + job.job_id), None)
    if order is None:
        if job.status != 'CLOSE_PREPARED' or not engine.state.reconciled:
            return job
        plan = _close_plan(engine, job)
        job = replace(job, close_plan=plan)
        _roll_job(engine, job, 'roll_close_revalidated')
        engine.submit(plan, job.source_lot.policy, 'roll-close:' + job.job_id)
        order = next(o for o in engine.state.orders if o.key == 'roll-close:' + job.job_id)
    if order.status is OrderStatus.FILLED:
        lot = next(p for p in engine.state.positions if p.lot_id == job.lot_id)
        if lot.quantity:
            raise DomainError('reconciliation_required', 'roll close fill did not flatten source')
        return replace(job, status='CLOSE_FILLED', close_order_id=order.order_id)
    if order.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING):
        _issue(engine, 'reconciliation_required')
        return replace(job, status='CLOSE_UNKNOWN', close_order_id=order.order_id)
    if order.status in (OrderStatus.REJECTED, OrderStatus.CANCELED):
        raise DomainError('reconciliation_required', 'roll close did not complete')
    return replace(job, status='CLOSE_SUBMITTED', close_order_id=order.order_id)


def _structured_rules(source) -> str:
    definition = source.definition
    if definition is None:
        return ''
    return json.dumps(
        {
            'schema_version': 2,
            'strategy_id': definition.strategy_id,
            'version': definition.version + 1,
            'market': definition.market.value,
            'bar_interval': definition.bar_interval,
            'direction': definition.direction,
            'holding_policy': {
                'kind': definition.policy.kind.value,
                'min_days': definition.policy.min_days,
                'max_days': definition.policy.max_days,
                'night_enabled': definition.policy.night_enabled,
                'expiry_action': definition.policy.expiry_action,
            },
            'entry': [{'field': r.field, 'operator': r.operator, 'value': str(r.value)} for r in definition.entry],
            'exit': [{'field': r.field, 'operator': r.operator, 'value': str(r.value)} for r in definition.exit],
            'cost_version': definition.cost_version,
            'risk_ref': definition.risk_ref,
        }
    )


def _research_destination(engine: 'TradingEngine', job: RollJob) -> tuple[RollJob, StrategyRecord]:
    from .workflows import run_research

    source = engine.strategy(f'{job.source_lot.strategy_id}:{job.source_lot.strategy_version}')
    form = replace(
        source.form,
        name=source.form.name[:70] + ' #roll ' + job.job_id[:8],
        parent_strategy_id=source.strategy_id,
        instrument_id=job.new_instrument_id,
        roll_contract_id='',
        draft_json=_structured_rules(source),
    )
    if job.destination_strategy_ref:
        target = engine.strategy(job.destination_strategy_ref)
        reference = job.destination_strategy_ref
    else:
        orphan = next(
            (
                s
                for s in engine.state.strategies
                if s.strategy_id == source.strategy_id
                and s.version > source.version
                and s.form.name == form.name
                and s.form.instrument_id == job.new_instrument_id
            ),
            None,
        )
        reference = f'{orphan.strategy_id}:{orphan.version}' if orphan else engine.create_strategy(form)
        target = engine.strategy(reference)
        job = replace(job, destination_strategy_ref=reference)
        _roll_job(engine, job, 'roll_destination_version_created')
    if target.state == 'DRAFT':
        engine.validate_strategy(reference)
    target = engine.strategy(reference)
    if target.state == 'RULE_VALID':
        bars = tuple(b for b in engine.history.get(job.new_instrument_id, ()) if b.available_at < engine.clock.now())
        run_research(engine, reference, bars)
    if engine.strategy(reference).state != 'ACTIVE':
        engine.deploy(reference)
    return job, engine.strategy(reference)


def _prepare_open(engine: 'TradingEngine', job: RollJob) -> RollJob:
    job, target = _research_destination(engine, job)
    quote = engine.quotes[job.new_instrument_id]
    spec = engine.catalog.resolve(job.new_instrument_id)
    side = job.source_lot.direction
    price = quote.ask if side is Side.BUY else quote.bid
    stop = price - spec.tick_size * 10 * (1 if side is Side.BUY else -1)
    plan = OrderPlan(
        'roll-open:' + job.job_id,
        job.source_lot.account_ref,
        engine.configuration.environment,
        job.new_instrument_id,
        target.strategy_id,
        target.version,
        side,
        job.quantity,
        spec.unit,
        price,
        stop,
        False,
        engine.clock.now(),
        engine.clock.now() + timedelta(seconds=30),
        engine.state.version + 1,
    )
    job = replace(job, status='OPEN_PREPARED', open_plan=plan)
    _roll_job(engine, job, 'roll_open_prepared')
    return job


def _progress_open(engine: 'TradingEngine', job: RollJob) -> RollJob:
    order = next((o for o in engine.state.orders if o.key == 'roll-open:' + job.job_id), None)
    if order is None:
        if engine.state.stopped or not engine.state.reconciled:
            return job
        job = _prepare_open(engine, job)
        engine.submit(job.open_plan, job.source_lot.policy, 'roll-open:' + job.job_id)
        order = next(o for o in engine.state.orders if o.key == 'roll-open:' + job.job_id)
    if order.filled:
        lot = next(p for p in engine.state.positions if p.lot_id == order.order_id)
        origin = job.source_lot.holding_origin
        if lot.holding_origin_trade_date != origin:
            carried = replace(lot, holding_origin_trade_date=origin)
            positions = tuple(carried if p.lot_id == lot.lot_id else p for p in engine.state.positions)
            engine._persist('roll_holding_deadline_carried', replace(engine.state, positions=positions))
    if order.status is OrderStatus.FILLED:
        return replace(job, status='COMPLETED', open_order_id=order.order_id)
    if order.status in (OrderStatus.UNKNOWN, OrderStatus.SUBMITTING):
        _issue(engine, 'reconciliation_required')
        return replace(job, status='OPEN_UNKNOWN', open_order_id=order.order_id)
    if order.status in (OrderStatus.REJECTED, OrderStatus.CANCELED):
        raise DomainError('reconciliation_required', 'roll open did not complete')
    return replace(job, status='OPEN_SUBMITTED', open_order_id=order.order_id)


@decimal_operation
def run_lifecycle(engine: 'TradingEngine') -> None:
    recover_corporate_actions(engine)
    if not engine.state.reconciled:
        return
    engine.assert_execution_allowed()
    owned = {j.lot_id for j in engine.state.rolls}
    for lot in tuple(engine.state.positions):
        if not lot.quantity or lot.lot_id in owned or engine.catalog.resolve(lot.instrument_id).market is Market.STOCK:
            continue
        try:
            _prepare_roll(engine, lot)
        except DomainError as exc:
            _issue(engine, exc.code)
    for job in tuple(engine.state.rolls):
        if job.status in ('COMPLETED', 'FROZEN'):
            continue
        try:
            if job.status.startswith('CLOSE_'):
                job = _progress_close(engine, job)
                _roll_job(engine, job, 'roll_close_observed')
            if job.status == 'CLOSE_FILLED' or job.status.startswith('OPEN_'):
                job = _progress_open(engine, job)
                _roll_job(engine, job, 'roll_open_observed')
        except DomainError as exc:
            if not engine.storage_failed:
                _roll_job(engine, replace(job, status='FROZEN', error=exc.code), 'roll_frozen')
                _issue(engine, exc.code)
