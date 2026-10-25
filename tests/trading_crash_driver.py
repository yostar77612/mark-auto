"""Owned-process fault fixture; the parent test must terminate this process."""

from datetime import timedelta
import json
from pathlib import Path
import sys
from threading import Event
import os

# Direct script execution starts with tests/ on sys.path, including clean CI
# hosts where the application has never been installed as an editable package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from quantlab.trading.application.events import reconcile
    from quantlab.trading.application.workflows import resume
    from quantlab.trading.domain.models import Environment, OrderPlan
    from quantlab.trading.runtime.build import create_engine

    root, phase, marker = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    engine = create_engine(root)
    reconcile(engine)
    resume(engine)
    record = next(s for s in engine.state.strategies if s.state == 'ACTIVE')
    spec = engine.catalog.resolve(record.form.instrument_id)
    quote = engine.quotes[spec.instrument_id]
    plan = OrderPlan(
        'os-kill-intent',
        record.form.account_ref,
        Environment.LOCAL,
        spec.instrument_id,
        record.strategy_id,
        record.version,
        record.form.direction,
        spec.lot_size,
        spec.unit,
        quote.ask,
        quote.ask - spec.tick_size * 10,
        False,
        engine.clock.now(),
        engine.clock.now() + timedelta(seconds=30),
        engine.state.version,
    )

    def ready() -> None:
        order = engine.state.orders[0]
        data = {
            'pid': os.getpid(),
            'phase': phase,
            'local_status': order.status.value,
            'reserved_cash': str(order.reservation.cash),
            'reserved_risk': str(order.reservation.risk),
            'remote_orders': len(engine.gateways[plan.account_ref].remote_state.orders),
            'producer_source_digest': engine.profile.source_digest,
        }
        marker.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')
        if Event().wait(60):
            raise RuntimeError('unexpected fixture signal')
        raise RuntimeError('parent failed to terminate owned crash fixture')

    if phase == 'before-submit':
        original = engine._persist

        def persist(kind, state):
            original(kind, state)
            if kind == 'order_submitting':
                ready()

        engine._persist = persist
    elif phase == 'after-accept':
        broker = engine.gateways[plan.account_ref]
        original_submit = broker.submit

        def submit(order_plan, order_id):
            original_submit(order_plan, order_id)
            engine.simulation.persist_remote()
            ready()

        broker.submit = submit
    else:
        raise ValueError('unknown fixture phase')
    engine.submit(plan, record.policy, 'os-kill-intent')
    raise RuntimeError('fixture passed the forced-kill boundary')


if __name__ == '__main__':
    main()
