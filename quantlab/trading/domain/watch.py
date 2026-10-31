"""Watch-only identities, deliberately independent of the executable catalog."""

from dataclasses import dataclass
from enum import Enum

from .validation import DomainError, identity


class WatchKind(str, Enum):
    STOCK = 'STOCK'
    INDEX = 'INDEX'


@dataclass(frozen=True)
class WatchInstrument:
    instrument_id: str
    kind: WatchKind
    exchange: str
    code: str
    name: str

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.code)
        prefix = {'TSE': 'TWSE', 'OTC': 'TPEX', 'INDEX': 'INDEX'}.get(self.exchange)
        if (
            not isinstance(self.kind, WatchKind)
            or prefix is None
            or self.instrument_id != f'{prefix}:{self.code}'
            or (self.kind is WatchKind.INDEX) != (self.exchange == 'INDEX')
            or not isinstance(self.name, str)
            or not self.name.strip()
            or len(self.name) > 200
        ):
            raise DomainError('validation_failed', 'watch instrument identity')


FIXED_INDICES = (
    WatchInstrument('INDEX:IX0001', WatchKind.INDEX, 'INDEX', 'IX0001', '加權指數'),
    WatchInstrument('INDEX:IX0043', WatchKind.INDEX, 'INDEX', 'IX0043', '櫃買指數'),
)
