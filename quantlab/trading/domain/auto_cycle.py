"""Pure completed-bar and forced-exit timing rules; no SDK, I/O or calendar inference."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from quantlab.trading.domain.calendar import TradingSession
from quantlab.trading.domain.live_bars import LiveBar
from quantlab.trading.domain.models import HoldingKind, Market
from quantlab.trading.domain.strategy import strategy_defaults
from quantlab.trading.domain.validation import DomainError

MINUTE = timedelta(minutes=1)
RETRY_INTERVAL = timedelta(seconds=30)
RETRY_CLOSE_BUFFER = timedelta(minutes=2)
EARLY_CLOSE_EXIT_BUFFER = timedelta(minutes=10)
TAIPEI = ZoneInfo('Asia/Taipei')


@dataclass(frozen=True)
class EvaluationCursor:
    strategy_id: str
    version: int
    instrument_id: str
    interval: str
    bar_end: datetime


@dataclass(frozen=True)
class ForceExitWindow:
    due_at: datetime
    retry_cutoff: datetime
    closes_at: datetime

