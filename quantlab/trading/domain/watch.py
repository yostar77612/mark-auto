"""Watch-only identities, deliberately independent of the executable catalog."""

from dataclasses import dataclass
from enum import Enum

from .validation import DomainError, identity


class WatchKind(str, Enum):
    STOCK = 'STOCK'
    INDEX = 'INDEX'
    FUTURE = 'FUTURE'


# Watch-only continuous front-month futures; the id is TAIFEX:<code>. This never reaches an executable catalogue.
FUTURE_NAMES = {'TXFR1': '臺股期貨近月', 'MXFR1': '小型臺指期貨近月', 'TMFR1': '微型臺指期貨近月'}
# Continuous front-month single-stock futures (for example CDFR1) are history-only identities for the bulk K-line tool: the category
# marks them, the code must be a three-character product code plus R1, and they are never watched, subscribed or traded.
STOCK_FUTURE_CATEGORY = 'STKFUT'
_PRODUCT_CHARACTERS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')


def is_stock_future_code(code: str) -> bool:
    return isinstance(code, str) and len(code) == 5 and code.endswith('R1') and all(character in _PRODUCT_CHARACTERS for character in code[:3])


@dataclass(frozen=True)
class WatchInstrument:
    instrument_id: str
    kind: WatchKind
    exchange: str
    code: str
    name: str
    category: str = ''

    def __post_init__(self) -> None:
        identity(self.instrument_id)
        identity(self.code)
        prefix = {'TSE': 'TWSE', 'OTC': 'TPEX', 'INDEX': 'INDEX', 'TAIFEX': 'TAIFEX'}.get(self.exchange)
        if (
            not isinstance(self.kind, WatchKind)
            or prefix is None
            or self.instrument_id != f'{prefix}:{self.code}'
            or (self.kind is WatchKind.INDEX) != (self.exchange == 'INDEX')
            or (self.kind is WatchKind.FUTURE) != (self.exchange == 'TAIFEX')
            or self.kind is WatchKind.FUTURE
            and not (self.code in FUTURE_NAMES or self.category == STOCK_FUTURE_CATEGORY and is_stock_future_code(self.code))
            or not isinstance(self.name, str)
            or not self.name.strip()
            or len(self.name) > 200
            or not isinstance(self.category, str)
            or len(self.category) > 8
        ):
            raise DomainError('validation_failed', 'watch instrument identity')


FIXED_INDICES = (
    WatchInstrument('INDEX:IX0001', WatchKind.INDEX, 'INDEX', 'IX0001', '加權指數'),
    WatchInstrument('INDEX:IX0043', WatchKind.INDEX, 'INDEX', 'IX0043', '櫃買指數'),
)


def is_future(instrument_id: str) -> bool:
    return instrument_id.startswith('TAIFEX:')


def watch_future(code: str) -> WatchInstrument:
    return WatchInstrument(f'TAIFEX:{code}', WatchKind.FUTURE, 'TAIFEX', code, FUTURE_NAMES[code])


def stock_future(code: str, name: str) -> WatchInstrument:
    """A continuous front-month single-stock futures contract, identified for K-line history only."""
    return WatchInstrument(f'TAIFEX:{code}', WatchKind.FUTURE, 'TAIFEX', code, name, STOCK_FUTURE_CATEGORY)
