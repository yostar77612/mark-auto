"""Market-wide snapshot rounds: batch contracts (<=500 per call), normalise rows, never expose vendor text."""

import logging
from decimal import Decimal

from quantlab.trading.domain.sector import QuoteRow
from quantlab.trading.domain.validation import DomainError
from quantlab.trading.domain.watch import WatchInstrument
from .sdk import sdk_decimal, sdk_text, sdk_time, sdk_value

logger = logging.getLogger(__name__)
BATCH = 500
_LIMITS = {'LimitUp': 'UP', 'LimitDown': 'DOWN'}


def normalise_snapshot(raw: object) -> QuoteRow | None:
    """One SDK snapshot -> QuoteRow; rows without a positive price (never traded, halted) are dropped."""
    price = sdk_decimal(sdk_value(raw, 'close'), 'snapshot price')
    if price <= 0:
        return None
    ratio = sdk_value(raw, 'volume_ratio')
    return QuoteRow(
        sdk_text(sdk_value(raw, 'code')),
        price,
        sdk_decimal(sdk_value(raw, 'change_rate'), 'snapshot change'),
        _LIMITS.get(sdk_text(sdk_value(raw, 'change_type')), ''),
        int(sdk_value(raw, 'total_volume')),
        int(sdk_value(raw, 'total_amount')),
        sdk_decimal(ratio, 'snapshot volume ratio') if ratio is not None and Decimal(str(ratio)) >= 0 else None,
        sdk_time(sdk_value(raw, 'ts')),
    )


class ShioajiSnapshotSource:
    """Snapshot rounds over the read-only market session; contract objects are resolved once and cached."""

    def __init__(self, session) -> None:
        self.session = session
        self._contracts: dict[str, object] = {}
        self._facade = None

    def _contract(self, facade, instrument: WatchInstrument):
        if facade is not self._facade:
            self._facade, self._contracts = facade, {}
        contract = self._contracts.get(instrument.code)
        if contract is None:
            contract = facade.market_contract(instrument.code)
            self._contracts[instrument.code] = contract
        return contract

    def snapshots(self, instruments: tuple[WatchInstrument, ...]) -> tuple[QuoteRow, ...]:
        facade = self.session.facade
        if not self.session.connected or facade is None:
            raise DomainError('market_data_not_connected')
        rows = []
        try:
            contracts = [self._contract(facade, instrument) for instrument in instruments]
            for start in range(0, len(contracts), BATCH):
                for raw in facade.snapshots(contracts[start : start + BATCH]):
                    row = normalise_snapshot(raw)
                    if row is not None:
                        rows.append(row)
        except Exception:
            logger.error('Shioaji snapshot round failed')
            raise DomainError('market_data_snapshot_failed') from None
        return tuple(rows)
