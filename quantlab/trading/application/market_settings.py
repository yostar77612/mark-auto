"""Independent market-data settings and their user-facing guidance boundary."""

from dataclasses import dataclass

from .broker_settings import _secret_reference
from .errors import ERROR_TABLE
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.validation import DomainError


def market_connection_guidance(code: str) -> str:
    """Render a known market error without exposing the private error catalogue."""
    error = ERROR_TABLE[code]
    return error.explanation + error.action


@dataclass(frozen=True)
class MarketDataSettings:
    environment: Environment = Environment.BROKER_SIMULATION
    secret_ref: str = 'MarkAuto/v2/broker/sinopac'
    enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.environment not in (Environment.BROKER_SIMULATION, Environment.LIVE)
            or not isinstance(self.environment, Environment)
            or not isinstance(self.secret_ref, str)
            or not _secret_reference(self.secret_ref, 'broker')
            or type(self.enabled) is not bool
        ):
            raise DomainError('validation_failed', 'market data settings')
