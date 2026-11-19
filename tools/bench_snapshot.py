"""Offline timing of `views.snapshot` on a LOCAL engine scaled to S strategies x O orders (OPT-1 P2).

Builds a real local engine in a temporary directory (synthetic calendar, catalog and quotes; no network,
broker or credentials), creates one filled stock entry and one open index-future entry, then clones
strategies, orders, lots and performance tracks under new identities to reach each size. Prints the
median wall time of repeated `snapshot` calls. Usage: python tools/bench_snapshot.py [--repeat N]
"""

import argparse
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.trading.application import views  # noqa: E402
from quantlab.trading.application.contracts import StrategyForm, UiAction, UiCommand  # noqa: E402
from quantlab.trading.application.facade import LocalFacade  # noqa: E402
from quantlab.trading.application.workflows import fill_local_pending, step  # noqa: E402
from quantlab.trading.domain.models import Environment, HoldingKind, Market, OrderPlan, Side  # noqa: E402
from quantlab.trading.runtime.build import create_engine  # noqa: E402

SIZES = ((10, 100), (10, 1000), (10, 5000), (50, 100), (50, 1000), (50, 5000))


def _command(facade, engine, action, **values):
    receipt = facade.execute(UiCommand(action, engine.state.version, **values))
    if not receipt.accepted:
        raise SystemExit(f'setup command {action.value} refused: {receipt.code}')
    return receipt


def _deploy(facade, engine, market):
    spec = next(s for s in engine.catalog.instruments if s.market is market)
    account = 'local-stock' if market is Market.STOCK else 'local-futures'
    form = StrategyForm(
        'bench-' + market.value,
        market,
        HoldingKind.SWING,
        3,
        5,
        Side.BUY,
        spec.instrument_id,
        account,
        Environment.LOCAL,
        Decimal('30000'),
        Decimal('0.02'),
        'BUY_AND_HOLD',
        '',
    )
    reference = _command(facade, engine, UiAction.CREATE_STRATEGY, strategy=form).reference
    for action in (UiAction.VALIDATE, UiAction.RESEARCH, UiAction.DEPLOY):
        _command(facade, engine, action, target_id=reference)
    return reference


def _submit(engine, reference, key):
    record = engine.strategy(reference)
    spec = engine.catalog.resolve(record.form.instrument_id)
    price = engine.quotes[spec.instrument_id].ask
    now = engine.clock.now()
    plan = OrderPlan(
        key,
        record.form.account_ref,
        Environment.LOCAL,
        spec.instrument_id,
        record.strategy_id,
        record.version,
        Side.BUY,
        spec.lot_size,
        spec.unit,
        price,
        price - spec.tick_size * 10,
        False,
        now,
        now + timedelta(seconds=30),
        engine.state.version,
    )
    engine.submit(plan, record.policy, key)


def base_engine(root):
    engine = create_engine(root / 'platform')
    facade = LocalFacade(engine)
    _command(facade, engine, UiAction.RECONCILE)
    _command(facade, engine, UiAction.RESUME)
    stock, future = _deploy(facade, engine, Market.STOCK), _deploy(facade, engine, Market.INDEX_FUTURE)
    _submit(engine, stock, 'stock-entry')
    fill_local_pending(engine)
    step(engine, engine.history)
    _command(facade, engine, UiAction.RESUME)
    _submit(engine, future, 'future-entry')
    return engine


def scaled_state(state, strategies, orders):
    """S strategy clones (cycling the base records) and O order clones spread round-robin over them."""
    records = [replace(state.strategies[i % len(state.strategies)], strategy_id=f'bench-s{i}') for i in range(strategies)]
    origin = {record.strategy_id: state.strategies[i % len(state.strategies)].strategy_id for i, record in enumerate(records)}
    cloned_orders = []
    for i in range(orders):
        record = records[i % strategies]
        order = state.orders[i % len(state.orders)]
        plan = replace(order.plan, strategy_id=record.strategy_id, strategy_version=record.version)
        cloned_orders.append(replace(order, order_id=f'bench-o{i}', plan=plan))
    lots = [
        replace(lot, lot_id=f'{lot.lot_id}-{record.strategy_id}', strategy_id=record.strategy_id)
        for record in records
        for lot in state.positions
        if lot.strategy_id == origin[record.strategy_id]
    ]
    tracks = [
        replace(track, strategy_id=record.strategy_id)
        for record in records
        for track in state.performance_tracks
        if track.strategy_id == origin[record.strategy_id]
    ]
    return replace(state, strategies=tuple(records), orders=tuple(cloned_orders), positions=tuple(lots), performance_tracks=tuple(tracks))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=7)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix='bench-snapshot-') as folder:
        engine = base_engine(Path(folder))
        try:
            base = engine.state
            print(f'python {sys.version.split()[0]}; repeat {args.repeat}; median ms per snapshot')
            print('strategies | orders | median_ms | min_ms')
            for strategies, orders in SIZES:
                engine.state = scaled_state(base, strategies, orders)
                views.snapshot(engine)  # warm caches and lazy imports
                runs = []
                for _ in range(args.repeat):
                    started = time.perf_counter()
                    views.snapshot(engine)
                    runs.append((time.perf_counter() - started) * 1000)
                print(f'{strategies} | {orders} | {statistics.median(runs):.1f} | {min(runs):.1f}')
            engine.state = base
        finally:
            engine.journal.close()
            engine.simulation.ledger.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
