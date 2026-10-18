"""Local-only research CLI. No imports from the legacy live trading package."""
import argparse
import sys
from pathlib import Path

from .core import canonical_json, ValidationError, content_hash
from .reporting import (synthetic_dataset, demo_config, save_dataset, load_dataset,
                        load_result, read_json, write_json, export_report, comparison_rows)


def parser():
    p = argparse.ArgumentParser(description='Offline TMF research. Live trading disabled.')
    sub = p.add_subparsers(dest='command', required=True)
    refresh = sub.add_parser('refresh', aliases=['download'], help='Explicit HTTPS download/update of recent free official TAIFEX archives')
    refresh.add_argument('--cache', type=Path, required=True)
    refresh.add_argument('--days', type=int, default=1, help='Latest published trade-date archives, 1..30; not calendar days')
    refresh.add_argument('--format', choices=('csv', 'rpt'), default='csv')
    demo = sub.add_parser('demo', help='Generate explicitly SYNTHETIC data and run all five families')
    demo.add_argument('--output', type=Path, required=True)
    demo.add_argument('--bars', type=int, default=960)
    imp = sub.add_parser('import', help='Import supported local TAIFEX file with explicit calendar')
    imp.add_argument('path', type=Path)
    imp.add_argument('--calendar', type=Path, required=True)
    imp.add_argument('--kind', required=True)
    imp.add_argument('--contract')
    imp.add_argument('--encoding')
    imp.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('backtest')
    run.add_argument('dataset', type=Path)
    run.add_argument('--family', default='trend')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--config', type=Path, help='Explicit cost/margin BacktestConfig JSON; default is labelled synthetic assumptions')
    campaign = sub.add_parser('campaign', help='Offline deterministic fixture generator; NOT a real AI integration')
    campaign.add_argument('dataset', type=Path)
    campaign.add_argument('--output', type=Path, required=True)
    campaign.add_argument('--config', type=Path)
    compare = sub.add_parser('compare')
    compare.add_argument('results', nargs='+', type=Path)
    compare.add_argument('--output', type=Path)
    return p


def config_from_json(value):
    from decimal import Decimal
    from .core import BacktestConfig, CostSpec
    def costs(item):
        return CostSpec(**{**item, 'commission_per_side': Decimal(item['commission_per_side']), 'tax_rate': Decimal(item['tax_rate'])})
    data = dict(value)
    data['costs'] = costs(data['costs'])
    for key in ('initial_cash', 'initial_margin_per_contract', 'maintenance_margin_per_contract'):
        if data.get(key) is not None:
            data[key] = Decimal(data[key])
    if 'cost_schedule' in data:
        data['cost_schedule'] = tuple(costs(c) for c in data['cost_schedule'])
    from datetime import datetime
    for key in ('margin_schedule', 'roll_events', 'settlement_events'):
        if key in data:
            rows = []
            for item in data[key]:
                row = dict(item)
                for name in ('initial_margin', 'maintenance_margin', 'price', 'settlement_fee_per_contract', 'settlement_tax_rate'):
                    if name in row:
                        row[name] = Decimal(row[name])
                for name in ('known_at', 'effective_at', 'timestamp'):
                    if name in row:
                        row[name] = datetime.fromisoformat(row[name].replace('Z', '+00:00'))
                rows.append(row)
            data[key] = tuple(rows)
    return BacktestConfig(**data)


def execute(args):
    if args.command in ('refresh', 'download'):
        from .downloads import refresh
        return refresh(args.cache, days=args.days, kind=args.format)
    if args.command == 'import':
        from .data import SessionCalendar, import_taifex
        raw = read_json(args.calendar)
        calendar = SessionCalendar(raw['sessions'], version=raw['version'])
        dataset = import_taifex(args.path, kind=args.kind, calendar=calendar, contract_id=args.contract, encoding=args.encoding)
        save_dataset(dataset, args.output)
        return {'dataset': str(args.output), 'manifest': dataset.manifest, 'quality': dataset.quality}
    if args.command == 'compare':
        result = comparison_rows([load_result(path) for path in args.results])
        if args.output:
            write_json(args.output, result)
        return result
    from .strategies import builtin_strategies
    from .backtest import run_backtest
    if args.command == 'demo':
        dataset = synthetic_dataset(args.bars)
        save_dataset(dataset, args.output / 'dataset.json')
        reports = [export_report(run_backtest(dataset, spec, demo_config()), args.output / 'reports') for spec in builtin_strategies()]
        return {'source_type': 'SYNTHETIC', 'dataset': str(args.output / 'dataset.json'), 'reports': reports,
                'live_status': 'disabled', 'real_model_status': 'not_verified'}
    dataset = load_dataset(args.dataset)
    if args.command == 'campaign':
        from .research import run_campaign, FixtureGenerator, demo_campaign_config
        config = read_json(args.config) if args.config else demo_campaign_config(dataset, demo_config())
        if isinstance(config.get('backtest_config'), dict):
            config['backtest_config'] = config_from_json(config['backtest_config'])
        return run_campaign(dataset, config=config, generator=FixtureGenerator(), output_dir=args.output)
    config = config_from_json(read_json(args.config)) if args.config else demo_config()
    candidates = [s for s in builtin_strategies() if args.family in (s.family, s.strategy_id)]
    if len(candidates) != 1:
        raise ValidationError('Unknown or ambiguous family: ' + args.family)
    return export_report(run_backtest(dataset, candidates[0], config), args.output)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output = execute(args)
        print(canonical_json(output))
        return 0
    except (ValidationError, ValueError, TypeError, KeyError, OSError, ArithmeticError) as exc:
        print(f'quantlab: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
