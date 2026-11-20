"""Offline timing of run_backtest before and after OPT-1 P7 on the same synthetic Dataset object.

The pre-change engine is the frozen fixture tests/fixtures/backtest_pre_opt1_p7.py.txt, loaded in memory the
same way FrozenEngineEquivalenceTests load it. Measures one 5,000-bar replay on a fresh Dataset, the second
replay of the same Dataset object, and a multi-candidate pass (every builtin strategy, three rounds, on one
Dataset), the shape of campaign and walk-forward evaluation. Usage: python tools/bench_backtest_repeat.py [--repeat N]
"""

import argparse
from pathlib import Path
import statistics
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import quantlab.backtest as live  # noqa: E402
from quantlab.reporting import demo_config, synthetic_dataset  # noqa: E402
from quantlab.strategies import builtin_strategies  # noqa: E402


def frozen_engine():
    source = (ROOT / 'tests' / 'fixtures' / 'backtest_pre_opt1_p7.py.txt').read_text(encoding='utf-8')
    for old, new in (
        ('from .core import', 'from quantlab.core import'),
        ('from .strategies import', 'from quantlab.strategies import'),
        ('Path(__file__)', 'Path(_live.__file__)'),
    ):
        source = source.replace(old, new)
    module = types.ModuleType('frozen_backtest_pre_opt1_p7')
    module._live = live
    exec(compile(source, 'backtest_pre_opt1_p7.py', 'exec'), module.__dict__)  # the committed frozen fixture
    return module


def median_ms(action, repeat):
    runs = []
    for _ in range(repeat):
        started = time.perf_counter()
        action()
        runs.append((time.perf_counter() - started) * 1000)
    return statistics.median(runs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repeat', type=int, default=5)
    args = parser.parse_args(argv)
    engines = (('before', frozen_engine().run_backtest), ('after', live.run_backtest))
    strategies, config = builtin_strategies(), demo_config()
    print(f'python {sys.version.split()[0]}; repeat {args.repeat}; 5,000 synthetic bars; median ms')
    print('case | before | after')
    rows = {}
    for name, run in engines:
        shared = synthetic_dataset(5000)
        run(shared, strategies[0], config)

        def first(run=run):
            return run(synthetic_dataset(5000), strategies[0], config)  # a fresh Dataset each time

        def again(run=run, shared=shared):
            return run(shared, strategies[0], config)

        def candidates(run=run, shared=shared):
            return [run(shared, spec, config) for _ in range(3) for spec in strategies]

        build = median_ms(lambda: synthetic_dataset(5000), args.repeat)
        rows[name] = (median_ms(first, args.repeat) - build, median_ms(again, args.repeat), median_ms(candidates, args.repeat))
    labels = (
        'first replay of a fresh Dataset (dataset build excluded)',
        'repeat replay, same Dataset',
        f'{3 * len(strategies)} candidate replays, same Dataset',
    )
    for index, label in enumerate(labels):
        print(f'{label} | {rows["before"][index]:.1f} | {rows["after"][index]:.1f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
