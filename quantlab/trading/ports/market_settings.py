"""Reference-only settings shape consumed by the market SDK boundary."""

from typing import Protocol

from quantlab.trading.domain.models import Environment


class MarketSessionSettings(Protocol):
    environment: Environment
    secret_ref: str
    enabled: bool
