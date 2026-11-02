"""Explicit historical applicability, separate from a current observation time."""

from dataclasses import dataclass
from datetime import datetime

from .models import InstrumentSpec, Market
from .validation import DomainError, aware, identity


def is_tmf_contract(spec: InstrumentSpec) -> bool:
    return (
        spec.market is Market.INDEX_FUTURE
        and spec.exchange == 'TAIFEX'
        and spec.instrument_id in (f'TMF:{spec.delivery_month}', f'TAIFEX:TMF:{spec.delivery_month}')
    )


@dataclass(frozen=True)
class HistoricalContractEvidence:
    """An independently verified specification interval; never inferred from SDK now.

    The source artifact digest and full observed specification are retained in
    research evidence. Merely knowing delivery month/expiry does not prove the
    multiplier, tick grid or listing/validity dates over a historical interval.
    """

    spec: InstrumentSpec
    sdk_code: str
    valid_from: datetime
    valid_until: datetime
    source: str
    source_digest: str

    def __post_init__(self):
        if not isinstance(self.spec, InstrumentSpec) or not is_tmf_contract(self.spec):
            raise DomainError('instrument_unresolved', 'historical TMF specification required')
        identity(self.sdk_code)
        identity(self.source)
        aware(self.valid_from)
        aware(self.valid_until)
        if (
            self.sdk_code.endswith(('R1', 'R2'))
            or self.valid_from >= self.valid_until
            or type(self.source_digest) is not str
            or len(self.source_digest) != 64
            or any(c not in '0123456789abcdef' for c in self.source_digest)
        ):
            raise DomainError('validation_failed', 'historical contract provenance or interval')

    def covers(self, spec: InstrumentSpec, start: datetime, end: datetime) -> bool:
        return self.spec == spec and self.valid_from <= start < end <= self.valid_until
