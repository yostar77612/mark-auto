"""Futures-only data gate for entry points that can reserve OOS or other irreversible state.

`core.Bar` also represents stock signal identities (TWSE:/TPEX:), so constructing a
Bar no longer proves a TMF futures contract. Every futures research entry point
calls this before any range reservation, registry write or output directory.
"""

from .core import Dataset, ValidationError, validate_contract


def require_futures_dataset(dataset) -> None:
    """Refuse any dataset containing a non-TMF contract id (checks every distinct bar id)."""
    if not isinstance(dataset, Dataset):
        raise ValidationError('Dataset required')
    for contract_id in {bar.contract_id for bar in dataset.bars}:
        validate_contract(contract_id)
