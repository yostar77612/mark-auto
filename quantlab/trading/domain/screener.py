"""Stock screener thresholds (M6): validated, user-adjustable, Decimal for prices and ratios, integers for NT$ and lots."""

from dataclasses import dataclass, fields
from decimal import Decimal

from .validation import DomainError, decimal_value, integer

SURGE_RED, SURGE_BLACK, BREAKOUT = 'SURGE_RED', 'SURGE_BLACK', 'BREAKOUT'
CONDITIONS = (SURGE_RED, SURGE_BLACK, BREAKOUT)
LISTS = ('SURGE', 'BREAKOUT', 'DOWNLOADED')
PATTERN_FILTERS = ('ALL', 'RED', 'BLACK')

# name: (minimum, maximum). Prices and ratios are Decimal, everything else an int.
RANGES = {
    'min_price': (Decimal(1), Decimal(1000)),
    'min_volume_lots': (0, 1_000_000),
    'warmup_minutes': (0, 60),
    'list_rows': (10, 200),
    'surge_ratio': (Decimal(1), Decimal(50)),
    'red_change_pct': (Decimal(1), Decimal(10)),
    'black_change_pct': (Decimal(1), Decimal(10)),
    'near_extreme_pct': (Decimal('0.1'), Decimal(5)),
    'quiet_amount': (1_000_000, 10_000_000_000),
    'breakout_volume_multiple': (Decimal(1), Decimal(20)),
    'breakout_intraday_ratio': (Decimal(1), Decimal(20)),
    'average_days': (5, 60),
    'window_short': (20, 250),
    'window_mid': (20, 250),
    'window_long': (20, 500),
}
DECIMAL_FIELDS = ('min_price', 'surge_ratio', 'red_change_pct', 'black_change_pct', 'near_extreme_pct', 'breakout_volume_multiple', 'breakout_intraday_ratio')
FLAGS = ('download_red', 'download_black', 'download_breakout')


@dataclass(frozen=True)
class ScreenerParams:
    """Every threshold is user-adjustable (owner decision D2, 2026-11-21); defaults are the owner's."""

    min_price: Decimal = Decimal(10)
    min_volume_lots: int = 500
    warmup_minutes: int = 10
    list_rows: int = 50
    surge_ratio: Decimal = Decimal(3)
    red_change_pct: Decimal = Decimal(5)
    black_change_pct: Decimal = Decimal(5)
    near_extreme_pct: Decimal = Decimal('1.5')
    quiet_amount: int = 50_000_000
    breakout_volume_multiple: Decimal = Decimal(2)
    breakout_intraday_ratio: Decimal = Decimal(2)
    average_days: int = 20
    window_short: int = 60
    window_mid: int = 120
    window_long: int = 240
    download_red: bool = True
    download_black: bool = False
    download_breakout: bool = True

    def __post_init__(self) -> None:
        for name, (low, high) in RANGES.items():
            value = getattr(self, name)
            if name in DECIMAL_FIELDS:
                decimal_value(value, name)
            else:
                integer(value, name)
            if not low <= value <= high:
                raise DomainError('validation_failed', name + ' out of range')
        for name in FLAGS:
            if type(getattr(self, name)) is not bool:
                raise DomainError('validation_failed', name)
        if not self.window_short < self.window_mid < self.window_long:
            raise DomainError('validation_failed', 'breakout windows must increase')

    @property
    def windows(self) -> tuple[int, int, int]:
        return self.window_short, self.window_mid, self.window_long

    def as_dict(self) -> dict:
        return {field.name: str(getattr(self, field.name)) if field.name in DECIMAL_FIELDS else getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> 'ScreenerParams':
        known = {field.name for field in fields(cls)}
        return cls(**{key: (Decimal(str(value)) if key in DECIMAL_FIELDS else value) for key, value in data.items() if key in known})
