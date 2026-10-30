from pathlib import Path
from quantlab.core import ValidationError


def research_controls(paths):
    """Irreversible budget/holdout ledgers must never be rolled back with user state."""
    state = Path(paths.state)
    legacy = list((state / 'provider_budgets').glob('*'))
    legacy.extend((state / 'campaigns').glob('.holdout_registry.sqlite3*'))
    if any((path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in legacy)):
        raise ValidationError('Legacy irreversible records require migration')
    controls = Path(paths.controls)
    if controls.resolve().is_relative_to(state.resolve()):
        raise ValidationError('Irreversible records must be outside state')
    return controls
