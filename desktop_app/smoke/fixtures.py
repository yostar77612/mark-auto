"""Offline smoke fixtures; ordered fixture/evidence behavior is preserved."""

from __future__ import annotations


class _SmokeSettingsView:
    """Validated settings snapshot for automated smoke; never writes user preferences."""

    def __init__(self, settings):
        from copy import deepcopy

        self._settings = deepcopy(settings)

    def load(self):
        from copy import deepcopy

        return deepcopy(self._settings)

    def save(self, settings):
        from copy import deepcopy

        if not isinstance(settings, dict):
            raise ValueError('Smoke preferences must be a dictionary')
        self._settings = deepcopy(settings)


def _smoke_steps():
    """Fixed offline fixtures only. No endpoints, credentials, or arbitrary commands."""
    from quantlab.core import to_dict
    from quantlab.reporting import demo_config, synthetic_dataset
    from quantlab.research import demo_campaign_config

    campaign = to_dict(demo_campaign_config(synthetic_dataset(120), demo_config()))
    campaign.update(families=['trend'], max_trials=1, max_improvements=0, max_runtime_seconds=45)
    campaign['ranking']['minimum'] = '-100000000'
    contract = 'TAIFEX:TMF:202601'
    policy = {
        'contract_id': contract,
        'risk_sessions': [
            {
                'open': '2026-01-05T00:45:00Z',
                'end': '2026-01-05T02:45:00Z',
                'trade_date': '2026-01-05',
                'session': 'day',
                'contract_id': contract,
                'source': 'explicit synthetic smoke fixture',
            }
        ],
        'margin_schedule': [{'effective_from': '2026-01-01', 'margin_per_contract': '100000', 'version': 'synthetic-assumption-v1'}],
    }
    snapshot = {'account_id': 'paper-demo', 'cash': '1000000', 'positions': {}, 'orders': {}, 'fills': {}}
    return [
        ('ui_demo', {'bars': 120}),
        ('ui_backtest', {'family': 'trend', 'parameters': {'fast': 5, 'slow': 20}, 'config': to_dict(demo_config()), 'batch': False}),
        ('ui_select', {}),  # Filled only from the preceding verified report result.
        ('ui_campaign', {'config': campaign, 'provider': {'mode': 'fixture'}}),
        ('ui_paper_reconcile', {'policy': policy, 'snapshot': snapshot}),
        ('ui_paper_replay', {'policy': policy, 'snapshot': snapshot, 'reconcile_confirmed': True, 'max_bars': 25}),
        ('ui_paper_kill', {'policy': policy}),
    ]
