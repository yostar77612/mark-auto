"""Pure backtest configuration decoding, independent of CLI/reporting."""


def config_from_json(value):
    # Keep operation-specific dependencies out of module startup.
    from decimal import Decimal

    # Keep operation-specific dependencies out of module startup.
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
    # Keep operation-specific dependencies out of module startup.
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
